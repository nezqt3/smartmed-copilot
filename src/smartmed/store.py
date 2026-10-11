"""Local SQLite revisions. Optimistic version checks prevent lost edits."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from smartmed.migrations import migrate
from smartmed.schemas.extraction import (
    CONTRACT_VERSION,
    Extraction,
    StrictModel,
    Turn,
    validate_extraction,
)


class Draft(StrictModel):
    id: str
    version: int = Field(ge=1)
    state: Literal["requires_review", "confirmed"]
    contract_version: str
    created_at: str
    updated_at: str
    turns: list[Turn]
    document: Extraction
    model_metadata: dict
    reviewer: str | None
    acknowledged_alerts: list[str] = Field(default_factory=list)


class NotFound(Exception):
    pass


class VersionConflict(Exception):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


class DraftStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    draft_id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(draft_id, version)
                );
            """)

        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, turns: list[Turn], document: Extraction, metadata: dict, db=None) -> Draft:
        timestamp = now()
        draft = Draft(
            id=str(uuid4()),
            version=1,
            state="requires_review",
            contract_version=CONTRACT_VERSION,
            created_at=timestamp,
            updated_at=timestamp,
            turns=turns,
            document=document,
            model_metadata=metadata,
            reviewer=None,
        )

        def insert(connection):
            connection.execute(
                "INSERT INTO drafts VALUES (?, ?, ?)",
                (draft.id, draft.version, draft.model_dump_json()),
            )
            self._revision(connection, draft, "model", "generated")

        if db is None:
            with self.connect() as connection:
                insert(connection)
        else:
            insert(db)
        return draft

    @staticmethod
    def decode(payload: str) -> Draft:
        draft = Draft.model_validate(migrate(json.loads(payload)))
        draft.document = validate_extraction(draft.document.model_dump(), draft.turns)
        return draft

    def get(self, draft_id: str) -> Draft:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise NotFound
        return self.decode(row[0])

    def replace(self, draft: Draft, expected: int, actor: str, action: str) -> Draft:
        draft.contract_version = CONTRACT_VERSION
        draft.version = expected + 1
        draft.updated_at = now()
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE drafts SET version=?, payload=? WHERE id=? AND version=?",
                (draft.version, draft.model_dump_json(), draft.id, expected),
            )
            if cursor.rowcount != 1:
                raise VersionConflict
            self._revision(db, draft, actor, action)
        return draft

    def delete(self, draft_id: str, expected: int):
        with self.connect() as db:
            if db.execute("SELECT id FROM drafts WHERE id=?", (draft_id,)).fetchone() is None:
                raise NotFound
            cursor = db.execute("DELETE FROM drafts WHERE id=? AND version=?", (draft_id, expected))
            if cursor.rowcount != 1:
                raise VersionConflict
            db.execute("DELETE FROM revisions WHERE draft_id=?", (draft_id,))
            if db.execute("SELECT name FROM sqlite_master WHERE name='jobs'").fetchone():
                db.execute("DELETE FROM jobs WHERE draft_id=?", (draft_id,))

    def purge_before(self, cutoff: str) -> int:
        with self.connect() as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM drafts WHERE json_extract(payload, '$.created_at') < ?",
                    (cutoff,),
                )
            ]
            for draft_id in ids:
                db.execute("DELETE FROM revisions WHERE draft_id=?", (draft_id,))
                db.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
                if db.execute("SELECT name FROM sqlite_master WHERE name='jobs'").fetchone():
                    db.execute("DELETE FROM jobs WHERE draft_id=?", (draft_id,))
            return len(ids)

    @staticmethod
    def _revision(db, draft: Draft, actor: str, action: str):
        db.execute(
            "INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
            (draft.id, draft.version, actor, action, draft.model_dump_json()),
        )

    def history(self, draft_id: str) -> list[dict]:
        self.get(draft_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT version, actor, action, payload FROM revisions "
                "WHERE draft_id=? ORDER BY version",
                (draft_id,),
            ).fetchall()
        return [
            {
                "version": row[0],
                "actor": row[1],
                "action": row[2],
                "draft": self.decode(row[3]).model_dump(),
            }
            for row in rows
        ]

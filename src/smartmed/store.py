"""Local SQLite revisions. Optimistic version checks prevent lost edits."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from smartmed.schemas.extraction import CONTRACT_VERSION, Extraction, StrictModel, Turn


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

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def create(self, turns: list[Turn], document: Extraction, metadata: dict) -> Draft:
        timestamp = now()
        draft = Draft(
            id=str(uuid4()), version=1, state="requires_review",
            contract_version=CONTRACT_VERSION, created_at=timestamp, updated_at=timestamp,
            turns=turns, document=document, model_metadata=metadata, reviewer=None,
        )
        with self.connect() as db:
            db.execute("INSERT INTO drafts VALUES (?, ?, ?)",
                       (draft.id, draft.version, draft.model_dump_json()))
            self._revision(db, draft, "model", "generated")
        return draft

    def get(self, draft_id: str) -> Draft:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise NotFound
        return Draft.model_validate_json(row[0])

    def replace(self, draft: Draft, expected: int, actor: str, action: str) -> Draft:
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

    @staticmethod
    def _revision(db, draft: Draft, actor: str, action: str):
        db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                   (draft.id, draft.version, actor, action, draft.model_dump_json()))

    def history(self, draft_id: str) -> list[dict]:
        self.get(draft_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT version, actor, action, payload FROM revisions "
                "WHERE draft_id=? ORDER BY version", (draft_id,),
            ).fetchall()
        return [{"version": row[0], "actor": row[1], "action": row[2],
                 "draft": json.loads(row[3])} for row in rows]

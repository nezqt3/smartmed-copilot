"""Persistent FIFO jobs, one worker per local API process, no patient text in status."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from smartmed.model_client import GenerationTimeout, InvalidGeneration, ModelBusy, ModelUnavailable
from smartmed.schemas.extraction import ExtractRequest
from smartmed.segmentation import segments
from smartmed.store import DraftStore

ERROR_CODES = {
    ModelUnavailable: "model_unavailable",
    GenerationTimeout: "model_timeout",
    InvalidGeneration: "invalid_model_output",
    ModelBusy: "model_busy",
}


class QueueFull(Exception):
    pass


class JobNotFound(Exception):
    pass


class Jobs:
    def __init__(self, store: DraftStore, extractor, capacity: int, retention_days: int):
        self.store, self.extractor = store, extractor
        self.capacity, self.retention_days = capacity, retention_days
        self.wakeup = asyncio.Event()
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, actor TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                request TEXT, draft_id TEXT, error TEXT
            )""")
            # A process restart must not re-run a model call of uncertain outcome.
            db.execute(
                "UPDATE jobs SET status='failed', request=NULL, error='server_restart' "
                "WHERE status='running'"
            )
        self.worker = None
        self.janitor = None

    def status(self, job_id: str, actor: str) -> dict:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id, status, created_at, updated_at, draft_id, error "
                "FROM jobs WHERE id=? AND actor=?",
                (job_id, actor),
            ).fetchone()
        if row is None:
            raise JobNotFound
        return dict(
            zip(
                ("job_id", "status", "created_at", "updated_at", "draft_id", "error"),
                row,
                strict=True,
            )
        )

    def submit(self, request: ExtractRequest, actor: str) -> dict:
        segments(request)  # Reject an unsplittable utterance before persisting anything.
        timestamp = datetime.now(UTC).isoformat()
        job_id = str(uuid4())
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')")
            if count.fetchone()[0] >= self.capacity:
                raise QueueFull
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, 'queued', ?, ?, ?, NULL, NULL)",
                (job_id, actor, timestamp, timestamp, request.model_dump_json()),
            )
        self.wakeup.set()
        return self.status(job_id, actor)

    async def start(self):
        self.cleanup()
        self.worker = asyncio.create_task(self.run())
        self.janitor = asyncio.create_task(self.maintain())

    async def close(self):
        for task in (self.worker, self.janitor):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def cleanup(self):
        timestamp = datetime.now(UTC)
        self.store.purge_before((timestamp - timedelta(days=self.retention_days)).isoformat())
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM jobs WHERE updated_at < ? AND status IN "
                "('succeeded', 'failed', 'cancelled')",
                ((timestamp - timedelta(hours=1)).isoformat(),),
            )
            # Queued transcripts must never survive the draft retention period.
            db.execute(
                "UPDATE jobs SET status='failed', request=NULL, error='retention_expired' "
                "WHERE status='queued' AND created_at < ?",
                ((timestamp - timedelta(days=self.retention_days)).isoformat(),),
            )

    async def maintain(self):
        while True:
            await asyncio.sleep(3600)
            self.cleanup()

    def delete(self, job_id: str, actor: str):
        self.status(job_id, actor)
        with self.store.connect() as db:
            status = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if status and status[0] == "running":
                raise QueueFull
            db.execute("DELETE FROM jobs WHERE id=? AND actor=?", (job_id, actor))

    async def wait(self, job_id: str, actor: str) -> dict:
        while True:
            status = self.status(job_id, actor)
            if status["status"] not in {"queued", "running"}:
                return status
            await asyncio.sleep(0.05)

    async def run(self):
        while True:
            self.wakeup.clear()
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT id, actor, request FROM jobs WHERE status='queued' "
                    "ORDER BY created_at, id LIMIT 1"
                ).fetchone()
                if row:
                    db.execute(
                        "UPDATE jobs SET status='running', updated_at=? WHERE id=?",
                        (datetime.now(UTC).isoformat(), row[0]),
                    )
            if row is None:
                await self.wakeup.wait()
                continue
            job_id, actor, payload = row
            try:
                request = ExtractRequest.model_validate_json(payload)
                result = await self.extractor.extract(request)
                # Commit draft and job status together: no orphan draft on process failure.
                with self.store.connect() as db:
                    draft = self.store.create(
                        request.turns,
                        result.document,
                        {**result.metadata, "requested_by": actor},
                        db=db,
                    )
                    db.execute(
                        "UPDATE jobs SET status='succeeded', request=NULL, draft_id=?, "
                        "updated_at=? WHERE id=?",
                        (draft.id, draft.updated_at, job_id),
                    )
            except asyncio.CancelledError:
                self.fail(job_id, "server_restart")
                raise
            except Exception as exc:
                # Exception messages may contain patient input; status contains codes only.
                self.fail(job_id, ERROR_CODES.get(type(exc), "processing_failed"))
            finally:
                # Release the last decoded transcript while waiting for the next job.
                payload = None
                row = None
                request = result = draft = None

    def fail(self, job_id: str, code: str):
        with self.store.connect() as db:
            db.execute(
                "UPDATE jobs SET status='failed', request=NULL, error=?, updated_at=? WHERE id=?",
                (code, datetime.now(UTC).isoformat(), job_id),
            )

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from smartmed.api import create_app
from smartmed.auth import AuthStore, LoginThrottled
from smartmed.backend_settings import BackendSettings
from smartmed.jobs import JobNotFound, Jobs, QueueFull
from smartmed.medications import mentions, search
from smartmed.model_client import ExtractionResult
from smartmed.safety import report
from smartmed.schemas.extraction import FIELDS, ExtractRequest, Turn, validate_extraction
from smartmed.segmentation import merge, segments
from smartmed.store import DraftStore, NotFound


def unknown():
    return {f: {"status": "unknown", "value": None, "evidence": []} for f in FIELDS}


def request(text="你好。"):
    return ExtractRequest(turns=[Turn(turn_id=1, speaker="patient", text=text)])


class Fake:
    def __init__(self):
        self.active = self.peak = 0

    async def health(self):
        return {"model_installed": True}

    async def extract(self, req):
        self.active += 1
        self.peak = max(self.active, self.peak)
        await asyncio.sleep(0.01)
        self.active -= 1
        return ExtractionResult(validate_extraction(unknown(), req.turns), {"model": "fake"})


def test_queue_capacity_fifo_persistence_owner_and_restart(tmp_path):
    async def scenario():
        store = DraftStore(tmp_path / "drafts.db")
        fake = Fake()
        jobs = Jobs(store, fake, 2, 7)
        first = jobs.submit(request(), "pavel")
        second = jobs.submit(request(), "pavel")
        with pytest.raises(QueueFull):
            jobs.submit(request(), "pavel")
        with pytest.raises(JobNotFound):
            jobs.status(first["job_id"], "denis")
        # Reconstruct manager before starting: queued requests survive a process restart.
        jobs = Jobs(store, fake, 2, 7)
        await jobs.start()
        try:
            one = await jobs.wait(first["job_id"], "pavel")
            two = await jobs.wait(second["job_id"], "pavel")
            assert one["status"] == two["status"] == "succeeded"
            assert fake.peak == 1
            assert store.get(one["draft_id"]).created_at <= store.get(two["draft_id"]).created_at
            with store.connect() as db:
                assert db.execute("SELECT request FROM jobs").fetchall() == [(None,), (None,)]
            store.delete(one["draft_id"], 1)
            with pytest.raises(JobNotFound):
                jobs.status(first["job_id"], "pavel")
        finally:
            await jobs.close()
        interrupted = jobs.submit(request("secret。"), "pavel")
        with store.connect() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (interrupted["job_id"],))
        restarted = Jobs(store, fake, 2, 7)
        assert restarted.status(interrupted["job_id"], "pavel")["error"] == "server_restart"
        with store.connect() as db:
            assert (
                db.execute(
                    "SELECT request FROM jobs WHERE id=?", (interrupted["job_id"],)
                ).fetchone()[0]
                is None
            )

    asyncio.run(scenario())


def test_retention_purges_drafts_revisions_and_job_payloads(tmp_path):
    store = DraftStore(tmp_path / "drafts.db")
    jobs = Jobs(store, Fake(), 8, 7)
    draft = store.create(request().turns, validate_extraction(unknown(), request().turns), {})
    timestamp = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    payload = draft.model_dump()
    payload["created_at"] = timestamp
    job = jobs.submit(request("secret。"), "pavel")
    with store.connect() as db:
        db.execute("UPDATE drafts SET payload=?", (json.dumps(payload),))
        db.execute("UPDATE jobs SET created_at=?", (timestamp,))
    jobs.cleanup()
    with pytest.raises(NotFound):
        store.get(draft.id)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0
        assert (
            db.execute("SELECT request FROM jobs WHERE id=?", (job["job_id"],)).fetchone()[0]
            is None
        )


def test_segmentation_preserves_all_text_ids_and_grounding():
    original = request("你好。" * 2000)  # 6000 chars in one turn.
    batches = segments(original)
    assert len(batches) > 1
    assert "".join(t.text for batch in batches for t in batch.turns) == original.turns[0].text
    assert all(len(batch.turns[0].text) <= 1800 for batch in batches)
    with pytest.raises(ValueError, match="single_utterance_too_long"):
        segments(request("字" * 1801))
    with pytest.raises(ValidationError):
        request("字" * 8001)


def test_merge_unknown_never_overwrites_present_and_conflict_abstains():
    source = [
        Turn(turn_id=1, speaker="patient", text="咳嗽。"),
        Turn(turn_id=2, speaker="patient", text="没有咳嗽。"),
    ]
    present = unknown()
    present["咳嗽"] = {
        "status": "present",
        "value": "咳嗽",
        "evidence": [{"turn_id": 1, "quote": "咳嗽。"}],
    }
    negative = unknown()
    negative["咳嗽"] = {
        "status": "negated",
        "value": None,
        "evidence": [{"turn_id": 2, "quote": "没有咳嗽。"}],
    }
    yes = validate_extraction(present, source)
    no = validate_extraction(negative, source)
    empty = validate_extraction(unknown(), source)
    merged, conflicts = merge([yes, empty], source)
    assert merged.咳嗽.status == "present" and conflicts == []
    merged, conflicts = merge([yes, no], source)
    assert merged.咳嗽.status == "unknown" and conflicts == ["咳嗽"]
    assert report(merged, {"merge_conflicts": conflicts})["required_acknowledgements"]


def test_third_party_cannot_be_used_as_patient_evidence():
    source = [Turn(turn_id=1, speaker="third_party", text="青霉素过敏。")]
    answer = unknown()
    answer["青霉素过敏"] = {
        "status": "present",
        "value": "青霉素过敏",
        "evidence": [{"turn_id": 1, "quote": "青霉素过敏。"}],
    }
    with pytest.raises(ValidationError):
        validate_extraction(answer, source)


def test_medication_search_is_local_exact_alias_matching():
    assert search("M01AE01")[0]["id"] == "ibuprofen"
    assert mentions("notamoxicillin") == []
    assert mentions("AMOXICILLIN")[0]["family"] == "penicillin"
    assert search("does-not-exist") == []


def test_migration_preserves_facts_and_history_without_mutating_source(tmp_path):
    store = DraftStore(tmp_path / "drafts.db")
    draft = store.create(request().turns, validate_extraction(unknown(), request().turns), {})
    old = draft.model_dump()
    old.pop("acknowledged_alerts")
    old["contract_version"] = "extraction.v1"
    with store.connect() as db:
        db.execute("UPDATE drafts SET payload=?", (json.dumps(old),))
        db.execute("UPDATE revisions SET payload=?", (json.dumps(old),))
    current = store.get(draft.id)
    assert current.contract_version == "extraction.v2"
    assert current.document.model_dump() == old["document"]
    assert store.history(draft.id)[0]["draft"]["contract_version"] == "extraction.v2"
    with store.connect() as db:
        assert json.loads(db.execute("SELECT payload FROM drafts").fetchone()[0]) == old
    store.replace(current, 1, "pavel", "edited")
    assert store.get(draft.id).contract_version == "extraction.v2"


def test_login_throttling_logout_password_rotation(tmp_path):
    auth = AuthStore(tmp_path / "staff.db")
    auth.add_staff("pavel", "test-passcode-123")
    token = auth.login("pavel", "test-passcode-123")
    assert auth.resolve(token) == "pavel"
    auth.logout(token)
    assert auth.resolve(token) is None
    token = auth.login("pavel", "test-passcode-123")
    auth.add_staff("pavel", "test-passcode-456")
    assert auth.resolve(token) is None
    for _ in range(5):
        assert auth.login("pavel", "wrong") is None
    with pytest.raises(LoginThrottled):
        auth.login("pavel", "wrong")


def test_async_api_safety_acknowledgements_and_edit_reset(tmp_path):
    class MedicationFake(Fake):
        async def extract(self, req):
            answer = unknown()
            answer["已用药物"] = {
                "status": "present",
                "value": "阿莫西林",
                "evidence": [{"turn_id": 1, "quote": "我吃了阿莫西林。"}],
            }
            return ExtractionResult(validate_extraction(answer, req.turns), {})

    settings = BackendSettings(database=tmp_path / "drafts.db", auth_database=tmp_path / "staff.db")
    AuthStore(settings.auth_database).add_staff("pavel", "test-passcode-123")
    with TestClient(create_app(settings, MedicationFake())) as client:
        token = client.post(
            "/v1/auth/login",
            json={
                "staff_id": "pavel",
                "passcode": "test-passcode-123",
            },
        ).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/v1/medications?q=布洛芬").json()["items"][0]["id"] == "ibuprofen"
        queued = client.post("/v1/jobs", json=request("我吃了阿莫西林。").model_dump())
        assert queued.status_code == 202
        job_url = "/v1/jobs/" + queued.json()["job_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = client.get(job_url).json()
            if job["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert job["status"] == "succeeded"
        url = "/v1/drafts/" + job["draft_id"]
        required = client.get(url + "/safety").json()["required_acknowledgements"]
        assert required == ["penicillin_review"]
        confirmation = {"expected_version": 1, "reviewed": True}
        assert client.post(url + "/confirm", json=confirmation).status_code == 409
        confirmation["acknowledged_alerts"] = required
        assert client.post(url + "/confirm", json=confirmation).status_code == 200
        assert client.get(url + "/export").status_code == 200
        document = client.get(url).json()["document"]
        edited = client.put(url, json={"expected_version": 2, "document": document}).json()
        assert edited["acknowledged_alerts"] == []
        assert client.get(url + "/export").status_code == 409
        assert client.post("/v1/auth/logout").status_code == 204
        assert client.get(url).status_code == 401


def test_one_worker_lease_prevents_restarting_another_process(tmp_path):
    from smartmed.runtime import worker_lease

    with worker_lease(tmp_path / "drafts.db"):
        with pytest.raises(RuntimeError, match="already has an API worker"):
            with worker_lease(tmp_path / "drafts.db"):
                pass
    with worker_lease(tmp_path / "drafts.db"):
        pass


def test_local_cors_only_and_unsplittable_input_returns_clean_error(tmp_path):
    settings = BackendSettings(database=tmp_path / "drafts.db", auth_database=tmp_path / "staff.db")
    auth = AuthStore(settings.auth_database)
    auth.add_staff("pavel", "test-passcode-123")
    with TestClient(create_app(settings, Fake())) as client:
        token = client.post(
            "/v1/auth/login",
            json={
                "staff_id": "pavel",
                "passcode": "test-passcode-123",
            },
        ).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        response = client.post("/v1/jobs", json=request("敏感" * 1000).model_dump())
        assert response.status_code == 422
        assert "敏感" not in response.text
        allowed = client.options(
            "/v1/jobs",
            headers={
                "Origin": settings.frontend_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert allowed.headers["Access-Control-Allow-Origin"] == settings.frontend_origin
        denied = client.options(
            "/v1/jobs",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "Access-Control-Allow-Origin" not in denied.headers
        with settings.database.open("rb") as db:
            assert db.read(16) == b"SQLite format 3\x00"
    with pytest.raises(ValidationError):
        BackendSettings(frontend_origin="https://remote.example")


def test_segmented_model_call_keeps_literal_evidence_and_metadata(tmp_path):
    import httpx

    from smartmed.model_client import OllamaExtractor

    async def scenario():
        seen = []
        source = request("你好。" * 600 + "我咳嗽。")  # Splits within the same turn ID.

        def handler(req):
            if req.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
            payload = json.loads(req.content)
            seen.append(payload)
            answer = unknown()
            user = next(m for m in payload["messages"] if m["role"] == "user")
            text = json.loads(user["content"])["turns"][0]["text"]
            if "咳嗽" in text:
                answer["咳嗽"] = {
                    "status": "present",
                    "value": "咳嗽",
                    "evidence": [{"turn_id": 1, "quote": "我咳嗽。"}],
                }
            return httpx.Response(
                200,
                json={
                    "message": {"content": json.dumps(answer)},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 500,
                },
            )

        model = OllamaExtractor(BackendSettings(), transport=httpx.MockTransport(handler))
        try:
            result = await model.extract(source)
            assert result.document.咳嗽.value == "咳嗽"
            assert result.metadata["segment_count"] == 2
            assert result.metadata["merge_conflicts"] == []
            assert len(seen) == 2
            assert all(p["options"]["num_ctx"] == 16384 for p in seen)
        finally:
            await model.close()

    asyncio.run(scenario())


def test_unknown_contract_is_sanitized_but_can_still_be_deleted(tmp_path):
    settings = BackendSettings(database=tmp_path / "drafts.db", auth_database=tmp_path / "staff.db")
    AuthStore(settings.auth_database).add_staff("pavel", "test-passcode-123")
    store = DraftStore(settings.database)
    draft = store.create(request().turns, validate_extraction(unknown(), request().turns), {})
    payload = draft.model_dump()
    payload["contract_version"] = "future-secret-version"
    with store.connect() as db:
        db.execute("UPDATE drafts SET payload=?", (json.dumps(payload),))
    with TestClient(create_app(settings, Fake())) as client:
        token = client.post(
            "/v1/auth/login",
            json={
                "staff_id": "pavel",
                "passcode": "test-passcode-123",
            },
        ).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        url = "/v1/drafts/" + draft.id
        invalid = client.get(url)
        assert invalid.status_code == 409
        assert "future-secret-version" not in invalid.text
        assert client.delete(url + "?expected_version=1").status_code == 204
        assert client.delete(url + "?expected_version=1").status_code == 404

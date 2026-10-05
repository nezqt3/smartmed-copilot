import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from smartmed.api import create_app
from smartmed.backend_settings import BackendSettings
from smartmed.model_client import (
    ExtractionResult,
    GenerationTimeout,
    InvalidGeneration,
    ModelBusy,
    ModelUnavailable,
    OllamaExtractor,
    grounded_schema,
)
from smartmed.schemas.extraction import FIELDS, ExtractRequest, Turn, validate_extraction


def blank():
    return {name: {"status": "unknown", "value": None, "evidence": []} for name in FIELDS}


def turns():
    return [Turn(turn_id=1, speaker="doctor", text="青霉素过敏吗？"),
            Turn(turn_id=2, speaker="patient", text="咳嗽两天，没有发热。青霉素过敏情况不知道。")]


def good():
    answer = blank()
    answer["咳嗽"] = {"status": "present", "value": "咳嗽",
                      "evidence": [{"turn_id": 2, "quote": "咳嗽两天"}]}
    answer["发热"] = {"status": "negated", "value": None,
                      "evidence": [{"turn_id": 2, "quote": "没有发热"}]}
    return answer


@pytest.mark.parametrize("fault", ["fabricated", "doctor", "duration", "allergy", "no_quote",
                                 "unrelated_negation"])
def test_bad_evidence_and_known_semantic_mistakes_are_rejected(fault):
    answer = good()
    if fault == "fabricated":
        answer["咳嗽"]["evidence"][0]["quote"] = "咳嗽一个月"
    elif fault == "doctor":
        answer["青霉素过敏"] = {"status": "present", "value": "青霉素过敏",
                               "evidence": [{"turn_id": 1, "quote": "青霉素过敏吗？"}]}
    elif fault == "duration":
        answer["咳嗽"]["value"] = "两天"
    elif fault == "allergy":
        answer["青霉素过敏"] = {"status": "negated", "value": None,
                               "evidence": [{"turn_id": 2, "quote": "青霉素过敏情况不知道"}]}
    elif fault == "unrelated_negation":
        answer["已用药物"] = {"status": "negated", "value": None,
                            "evidence": [{"turn_id": 2, "quote": "没有发热"}]}
    else:
        answer["发热"]["evidence"] = []
    with pytest.raises(ValidationError):
        validate_extraction(answer, turns())


def test_explicit_negation_is_allowed_but_unknown_is_not_rewritten():
    answer = blank()
    answer["青霉素过敏"] = {"status": "negated", "value": None,
                           "evidence": [{"turn_id": 1, "quote": "我对青霉素不过敏"}]}
    source = [Turn(turn_id=1, speaker="patient", text="我对青霉素不过敏。")]
    assert validate_extraction(answer, source).青霉素过敏.status == "negated"
    assert validate_extraction(good(), turns()).青霉素过敏.status == "unknown"


def test_explicit_no_medication_has_null_value_and_literal_evidence():
    answer = blank()
    answer["已用药物"] = {"status": "negated", "value": None,
                        "evidence": [{"turn_id": 1, "quote": "我还没有吃药。"}]}
    source = [Turn(turn_id=1, speaker="patient", text="我还没有吃药。")]
    assert validate_extraction(answer, source).已用药物.status == "negated"


@pytest.mark.parametrize("bad", ["https://api.example.com", "http://192.168.1.2:11434",
                                 "http://127.0.0.1:11434/api", "http://localhost@evil.test"])
def test_external_model_endpoints_are_rejected(bad):
    with pytest.raises(ValidationError):
        BackendSettings(ollama_url=bad)


def test_duplicate_ids_and_overlong_transcripts_rejected():
    with pytest.raises(ValidationError):
        ExtractRequest(turns=[turns()[0], turns()[0]])
    with pytest.raises(ValidationError):
        ExtractRequest(turns=[Turn(turn_id=1, speaker="patient", text="字" * 2000),
                              Turn(turn_id=2, speaker="patient", text="字")])


def test_generated_quote_choices_preserve_spaces_ids_and_schema_isolation():
    from smartmed.schemas.extraction import Extraction

    schema = Extraction.model_json_schema()
    original = copy.deepcopy(schema)
    request = ExtractRequest(turns=[
        Turn(turn_id=1, speaker="doctor", text="请吃500毫克。"),
        Turn(turn_id=2, speaker="patient", text="我吃了布洛芬，一次200毫克。"),
    ])
    patched = grounded_schema(schema, request)
    assert schema == original
    variants = patched["$defs"]["Evidence"]["anyOf"]
    assert len(variants) == 1
    properties = variants[0]["properties"]
    assert properties["turn_id"]["const"] == 2
    assert "一次200毫克。" in properties["quote"]["enum"]
    assert "一次 200 毫克。" not in properties["quote"]["enum"]
    assert all(quote in request.turns[1].text for quote in properties["quote"]["enum"])


class FakeExtractor:
    error = None

    async def health(self):
        return {"model_installed": True}

    async def extract(self, request):
        if self.error:
            raise self.error
        return ExtractionResult(validate_extraction(good(), request.turns), {"model": "fake"})


def test_api_edit_confirm_export_and_revision_conflicts(tmp_path):
    app = create_app(BackendSettings(database=tmp_path / "test.sqlite3"), FakeExtractor())
    with TestClient(app) as client:
        payload = {"turns": [turn.model_dump() for turn in turns()]}
        response = client.post("/v1/drafts", json=payload)
        assert response.status_code == 201
        draft = response.json()
        url = f"/v1/drafts/{draft['id']}"
        assert client.get(url).json()["document"] == good()
        assert client.get(url + "/export").status_code == 409
        corrupt = copy.deepcopy(good())
        corrupt["咳嗽"]["evidence"][0]["quote"] = "咳嗽一个月"
        assert client.put(url, json={"expected_version": 1, "actor": "pavel",
                                     "document": corrupt}).status_code == 422
        confirmed = client.post(url + "/confirm", json={
            "expected_version": 1, "reviewer": "demo-reviewer", "reviewed": True,
        })
        assert confirmed.status_code == 200
        assert client.get(url + "/export").json()["version"] == 2
        assert client.put(url, json={"expected_version": 1, "actor": "pavel",
                                     "document": good()}).status_code == 409
        edited = client.put(url, json={"expected_version": 2, "actor": "pavel",
                                      "document": good()})
        assert edited.json()["state"] == "requires_review"
        assert edited.json()["reviewer"] is None
        assert client.get(url + "/export").status_code == 409
        revisions = client.get(url + "/history").json()
        assert [r["action"] for r in revisions] == ["generated", "confirmed", "edited"]
        assert client.get("/v1/form").json()["contract_version"] == "extraction.v1"


@pytest.mark.parametrize("error,status", [(InvalidGeneration, 502), (ModelUnavailable, 503),
                                         (ModelBusy, 503), (GenerationTimeout, 504)])
def test_api_failure_has_no_successful_draft(tmp_path, error, status):
    fake = FakeExtractor()
    fake.error = error()
    app = create_app(BackendSettings(database=tmp_path / "test.sqlite3"), fake)
    with TestClient(app) as client:
        response = client.post("/v1/drafts", json={"turns": [t.model_dump() for t in turns()]})
        assert response.status_code == status
    import sqlite3

    with sqlite3.connect(tmp_path / "test.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 0


def test_real_instructor_retries_with_context_and_native_schema(tmp_path):
    async def scenario():
        requests = []
        invalid = good()
        invalid["咳嗽"]["value"] = "两天"

        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [
                    {"name": "qwen3.5:4b", "digest": "test-digest"},
                ]})
            payload = json.loads(request.content)
            requests.append(payload)
            answer = invalid if len(requests) == 1 else good()
            return httpx.Response(200, json={
                "message": {"content": json.dumps(answer, ensure_ascii=False)},
                "done": True, "done_reason": "stop", "eval_count": 100,
            })

        model = OllamaExtractor(BackendSettings(database=tmp_path / "test.sqlite3"),
                                transport=httpx.MockTransport(handler))
        try:
            result = await model.extract(ExtractRequest(turns=turns()))
            assert result.document.咳嗽.value == "咳嗽"
            assert len(requests) == 2
            assert len(result.metadata["attempts"]) == 2
            assert requests[0]["think"] is False
            assert requests[0]["format"]["additionalProperties"] is False
            assert "两天" in json.dumps(requests[1]["messages"], ensure_ascii=False)
        finally:
            await model.close()

    asyncio.run(scenario())


def test_instructor_exhaustion_rejects_bad_output(tmp_path):
    async def scenario():
        count = 0

        def handler(request):
            nonlocal count
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
            count += 1
            invalid = good()
            invalid["发热"]["evidence"] = []
            return httpx.Response(200, json={"message": {"content": json.dumps(invalid)},
                                           "done": True, "done_reason": "stop"})

        model = OllamaExtractor(BackendSettings(database=tmp_path / "test.sqlite3"),
                                transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(InvalidGeneration):
                await model.extract(ExtractRequest(turns=turns()))
            assert count == 2
        finally:
            await model.close()

    asyncio.run(scenario())


def test_busy_request_is_rejected_and_deadline_releases_lock(tmp_path):
    async def scenario():
        entered = asyncio.Event()

        async def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
            entered.set()
            await asyncio.sleep(10)
            raise AssertionError("deadline should cancel the transport")

        model = OllamaExtractor(
            BackendSettings(database=tmp_path / "test.sqlite3", timeout_s=0.1),
            transport=httpx.MockTransport(handler),
        )
        try:
            running = asyncio.create_task(model.extract(ExtractRequest(turns=turns())))
            await entered.wait()
            with pytest.raises(ModelBusy):
                await model.extract(ExtractRequest(turns=turns()))
            with pytest.raises(GenerationTimeout):
                await running
            assert not model.lock.locked()
        finally:
            await model.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("response_type", ["http_error", "truncated", "bad_json"])
def test_transport_and_truncated_outputs_never_become_drafts(tmp_path, response_type):
    async def scenario():
        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
            if response_type == "http_error":
                return httpx.Response(500, text="upstream error")
            if response_type == "bad_json":
                return httpx.Response(200, text="broken response")
            return httpx.Response(200, json={
                "message": {"content": json.dumps(good())}, "done": True,
                "done_reason": "length",
            })

        model = OllamaExtractor(BackendSettings(database=tmp_path / "test.sqlite3"),
                                transport=httpx.MockTransport(handler))
        try:
            expected = ModelUnavailable if response_type == "http_error" else InvalidGeneration
            with pytest.raises(expected):
                await model.extract(ExtractRequest(turns=turns()))
        finally:
            await model.close()

    asyncio.run(scenario())

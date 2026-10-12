import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from smartmed.api import create_app
from smartmed.auth import AuthStore
from smartmed.backend_settings import BackendSettings
from smartmed.model_client import InvalidGeneration
from smartmed.outpatient_model import OutpatientExtractor
from smartmed.speaker_assignment import turns_from_segments


def test_segments_preserve_unpunctuated_asr_text_and_roles():
    text = "今天哪里不舒服我咳嗽两天了有没有发热没有发热"
    turns, uncertain = turns_from_segments(text, [
        {"speaker": "doctor", "text": "今天哪里不舒服", "uncertain": False},
        {"speaker": "patient", "text": "我咳嗽两天了", "uncertain": False},
        {"speaker": "doctor", "text": "有没有发热", "uncertain": False},
        {"speaker": "patient", "text": "没有发热", "uncertain": True},
    ])
    assert [turn.speaker for turn in turns] == ["doctor", "patient", "doctor", "patient"]
    assert [turn.text for turn in turns] == ["今天哪里不舒服", "我咳嗽两天了", "有没有发热", "没有发热"]
    assert "".join(turn.text for turn in turns) == text
    assert uncertain == [4]
    with pytest.raises(InvalidGeneration):
        turns_from_segments(text, [{"speaker": "patient", "text": "凭空捏造", "uncertain": False}])


def test_adjacent_same_speaker_segments_are_merged():
    turns, uncertain = turns_from_segments("我咳嗽两天晚上更重", [
        {"speaker": "patient", "text": "我咳嗽两天", "uncertain": False},
        {"speaker": "patient", "text": "晚上更重", "uncertain": True},
    ])
    assert [(turn.speaker, turn.text) for turn in turns] == [("patient", "我咳嗽两天晚上更重")]
    assert uncertain == [1]


def test_local_model_assignment_uses_segments_without_rewriting_text():
    text = "今天哪里不舒服我咳嗽两天了"

    def respond(request):
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["think"] is False
        assert payload["messages"][1]["content"] == text
        return httpx.Response(200, json={
            "done": True, "done_reason": "stop",
            "message": {"content": json.dumps({"segments": [
                {"speaker": "doctor", "text": "今天哪里不舒服", "uncertain": False},
                {"speaker": "patient", "text": "我咳嗽两天了", "uncertain": False},
            ]}, ensure_ascii=False)},
        })

    async def run():
        extractor = OutpatientExtractor(
            BackendSettings(), transport=httpx.MockTransport(respond)
        )
        extractor.health = lambda: asyncio.sleep(0, result={"ollama_available": True, "model_installed": True})
        try:
            return await extractor.assign_speakers(text)
        finally:
            await extractor.close()

    result = asyncio.run(run())
    assert result["speaker_labels"] == "inferred_from_text"
    assert [turn["text"] for turn in result["turns"]] == ["今天哪里不舒服", "我咳嗽两天了"]


def test_assignment_route_requires_staff_login(tmp_path):
    class FakeExtractor:
        async def health(self):
            return {"model_installed": True}

    class FakeAssignment:
        async def assign_speakers(self, text):
            return {"text": text, "turns": [{"turn_id": 1, "speaker": "patient", "text": text}],
                    "uncertain_turn_ids": [], "speaker_labels": "inferred_from_text"}

    settings = BackendSettings(database=tmp_path / "drafts.sqlite3", auth_database=tmp_path / "staff.sqlite3")
    AuthStore(settings.auth_database).add_staff("demo", "long-demo-passcode")
    app = create_app(settings, extractor=FakeExtractor(), outpatient_extractor=FakeAssignment())
    with TestClient(app) as client:
        assert client.post("/v1/audio/assign-speakers", json={"text": "我咳嗽"}).status_code == 401
        token = client.post("/v1/auth/login", json={"staff_id": "demo", "passcode": "long-demo-passcode"}).json()["access_token"]
        response = client.post("/v1/audio/assign-speakers", json={"text": "我咳嗽"},
                               headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["turns"][0]["text"] == "我咳嗽"

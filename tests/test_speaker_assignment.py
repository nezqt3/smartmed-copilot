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
    turns, uncertain = turns_from_segments(
        text,
        [
            {"speaker": "doctor", "text": "今天哪里不舒服", "uncertain": False},
            {"speaker": "patient", "text": "我咳嗽两天了", "uncertain": False},
            {"speaker": "doctor", "text": "有没有发热", "uncertain": False},
            {"speaker": "patient", "text": "没有发热", "uncertain": True},
        ],
    )
    assert [turn.speaker for turn in turns] == ["doctor", "patient", "doctor", "patient"]
    assert [turn.text for turn in turns] == [
        "今天哪里不舒服",
        "我咳嗽两天了",
        "有没有发热",
        "没有发热",
    ]
    assert "".join(turn.text for turn in turns) == text
    assert uncertain == [4]
    with pytest.raises(InvalidGeneration):
        turns_from_segments(text, [{"speaker": "patient", "text": "凭空捏造", "uncertain": False}])


def test_adjacent_same_speaker_segments_are_merged():
    turns, uncertain = turns_from_segments(
        "我咳嗽两天晚上更重",
        [
            {"speaker": "patient", "text": "我咳嗽两天", "uncertain": False},
            {"speaker": "patient", "text": "晚上更重", "uncertain": True},
        ],
    )
    assert [(turn.speaker, turn.text) for turn in turns] == [("patient", "我咳嗽两天晚上更重")]
    assert uncertain == [1]


def test_local_model_assignment_uses_segments_without_rewriting_text():
    text = "今天哪里不舒服我咳嗽两天了"

    def respond(request):
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["think"] is False
        assert payload["messages"][1]["content"] == text
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "segments": [
                                {
                                    "speaker": "doctor",
                                    "text": "今天哪里不舒服",
                                    "uncertain": False,
                                },
                                {"speaker": "patient", "text": "我咳嗽两天了", "uncertain": False},
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
            },
        )

    async def run():
        extractor = OutpatientExtractor(BackendSettings(), transport=httpx.MockTransport(respond))
        extractor.health = lambda: asyncio.sleep(
            0, result={"ollama_available": True, "model_installed": True}
        )
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
            return {
                "text": text,
                "turns": [{"turn_id": 1, "speaker": "patient", "text": text}],
                "uncertain_turn_ids": [],
                "speaker_labels": "inferred_from_text",
            }

    settings = BackendSettings(
        database=tmp_path / "drafts.sqlite3", auth_database=tmp_path / "staff.sqlite3"
    )
    AuthStore(settings.auth_database).add_staff("demo", "long-demo-passcode")
    app = create_app(settings, extractor=FakeExtractor(), outpatient_extractor=FakeAssignment())
    with TestClient(app) as client:
        assert client.post("/v1/audio/assign-speakers", json={"text": "我咳嗽"}).status_code == 401
        token = client.post(
            "/v1/auth/login", json={"staff_id": "demo", "passcode": "long-demo-passcode"}
        ).json()["access_token"]
        response = client.post(
            "/v1/audio/assign-speakers",
            json={"text": "我咳嗽"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["turns"][0]["text"] == "我咳嗽"


def test_long_assignment_is_lossless_and_marks_batch_boundaries():
    text = "我咳嗽。" * 400
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        batch = payload["messages"][1]["content"]
        seen.append(batch)
        assert len(batch) <= 600
        assert payload["options"]["num_thread"] == 2
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "segments": [
                                {"speaker": "patient", "text": batch, "uncertain": False},
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
            },
        )

    async def run():
        extractor = OutpatientExtractor(
            BackendSettings(),
            transport=httpx.MockTransport(respond),
        )
        extractor.health = lambda: asyncio.sleep(
            0,
            result={
                "ollama_available": True,
                "model_installed": True,
            },
        )
        try:
            return await extractor.assign_speakers(text)
        finally:
            await extractor.close()

    result = asyncio.run(run())
    assert len(seen) > 1
    assert "".join(seen) == text
    assert "".join(turn["text"] for turn in result["turns"]) == text
    assert result["uncertain_turn_ids"] == list(range(1, len(seen) + 1))


def test_batching_keeps_unpunctuated_text_and_whitespace():
    from smartmed.speaker_assignment import text_batches

    text = "我头痛" * 600 + "\n  后来好了。 "
    batches = text_batches(text)
    assert "".join(batches) == text
    assert all(0 < len(batch) <= 600 for batch in batches)


@pytest.mark.parametrize(
    "ends", [[0, "嗽"], ["我咳", "我咳"], ["我咳"], [True, "嗽"], ["我咳", "痛"]]
)
def test_invalid_boundaries_cannot_drop_or_duplicate_source(ends):
    from smartmed.speaker_assignment import segments_from_boundaries

    with pytest.raises(InvalidGeneration):
        segments_from_boundaries(
            "我咳嗽", [{"speaker": "patient", "end": end, "uncertain": False} for end in ends]
        )


def test_boundaries_preserve_temperature_and_whitespace():
    from smartmed.speaker_assignment import segments_from_boundaries

    text = "今天体温36点8摄氏度 我头痛"
    segments = segments_from_boundaries(
        text,
        [
            {"speaker": "doctor", "end": "36点8摄氏度", "uncertain": False},
            {"speaker": "patient", "end": text[-8:], "uncertain": False},
        ],
    )
    assert "".join(item["text"] for item in segments) == text
    assert segments[1]["text"] == " 我头痛"


@pytest.mark.parametrize("failure", ["timeout", "unavailable", "invalid_boundary"])
def test_assignment_failures_do_not_return_partial_turns(failure):
    from smartmed.model_client import GenerationTimeout, ModelUnavailable

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if failure == "unavailable":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "segments": [
                                {"speaker": "patient", "text": "凭空捏造", "uncertain": False},
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
            },
        )

    async def run():
        extractor = OutpatientExtractor(
            BackendSettings(),
            transport=httpx.MockTransport(respond),
        )
        extractor.health = lambda: asyncio.sleep(
            0,
            result={
                "ollama_available": True,
                "model_installed": True,
            },
        )
        expected = {
            "timeout": GenerationTimeout,
            "unavailable": ModelUnavailable,
            "invalid_boundary": InvalidGeneration,
        }[failure]
        try:
            if failure == "invalid_boundary":
                result = await extractor.assign_speakers("我咳嗽")
                assert result["turns"][0]["text"] == "我咳嗽"
                assert result["uncertain_turn_ids"] == [1]
                assert result["speaker_labels"] == "manual_required"
            else:
                with pytest.raises(expected):
                    await extractor.assign_speakers("我咳嗽")
            assert not extractor.lock.locked()
        finally:
            await extractor.close()

    asyncio.run(run())


def test_generated_whitespace_never_changes_source_temperature():
    from smartmed.speaker_assignment import source_segments

    text = "今天体温36点8摄氏度 我头痛"
    proposals = [
        {"speaker": "doctor", "text": "今天体温 36 点 8 摄氏度", "uncertain": False},
        {"speaker": "patient", "text": "我头痛", "uncertain": False},
    ]
    result = source_segments(text, proposals)
    assert "".join(item["text"] for item in result) == text
    assert result[0]["text"] == "今天体温36点8摄氏度"


def test_omitted_source_words_are_restored_and_require_role_review():
    from smartmed.speaker_assignment import source_segments

    text = "我咳嗽三天现在感觉好多了还是偶尔咳嗽"
    proposals = [
        {
            "speaker": "patient",
            "text": "我咳嗽现在感觉好多了还是偶尔咳嗽",
            "uncertain": False,
        }
    ]
    result = source_segments(text, proposals)
    assert result[0]["text"] == text
    assert result[0]["uncertain"] is True

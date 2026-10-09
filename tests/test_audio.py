import asyncio
import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from services.asr.app import Recognizer, validate_wav
from services.asr.app import create_app as create_asr_app
from smartmed.api import create_app
from smartmed.audio_client import ASRClient, ASRInvalidAudio, ASRUnavailable
from smartmed.backend_settings import BackendSettings


def wav_bytes(seconds=1, rate=16_000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\0\0" * rate * seconds * channels)
    return output.getvalue()


class FakeRecognizer:
    def ready(self):
        return True

    def transcribe(self, data):
        assert validate_wav(data) == 1
        return "我咳嗽一天"


class FakeExtractor:
    async def health(self):
        return {"model_installed": True}


class FakeASRClient:
    async def transcribe(self, data):
        assert validate_wav(data) == 1
        return {"text": "我咳嗽一天", "speaker_labels": "manual_required"}


def test_asr_requires_pcm16_mono_16khz_and_returns_unlabeled_text():
    app = create_asr_app(FakeRecognizer())
    with TestClient(app) as client:
        response = client.post(
            "/v1/transcribe", content=wav_bytes(), headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == 200
        assert response.json()["text"] == "我咳嗽一天"
        assert response.json()["speaker_labels"] == "manual_required"
        for audio in (wav_bytes(rate=8_000), wav_bytes(channels=2), b"not a wave"):
            invalid = client.post(
                "/v1/transcribe", content=audio, headers={"Content-Type": "audio/wav"}
            )
            assert invalid.status_code == 422


def test_recognizer_uses_only_prepared_local_model(tmp_path):
    class FakeModel:
        def generate(self, input):
            with open(input, "rb") as audio:
                assert audio.read(4) == b"RIFF"
            return [{"text": "没有发热"}]

    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeModel()

    seeds = []
    recognizer = Recognizer(tmp_path, model_factory=factory, seed_fn=seeds.append)
    with pytest.raises(FileNotFoundError):
        recognizer.transcribe(wav_bytes())
    (tmp_path / "config.yaml").write_text("model: Paraformer", encoding="utf-8")
    (tmp_path / "model.pt").write_bytes(b"placeholder")
    assert recognizer.transcribe(wav_bytes()) == "没有发热"
    assert recognizer.transcribe(wav_bytes()) == "没有发热"
    assert len(calls) == 1
    assert seeds == [0, 0]
    assert calls[0]["model"] == str(tmp_path)
    assert calls[0]["ncpu"] == 1
    assert calls[0]["trust_remote_code"] is False


def test_api_audio_proxy_never_creates_a_draft(tmp_path):
    app = create_app(
        BackendSettings(database=tmp_path / "drafts.sqlite3"),
        extractor=FakeExtractor(),
        asr_client=FakeASRClient(),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/audio/transcribe",
            content=wav_bytes(),
            headers={"Content-Type": "audio/wav"},
        )
        assert response.status_code == 200
        assert response.json()["speaker_labels"] == "manual_required"
        assert client.post("/v1/audio/transcribe", content=b"bad").status_code == 415


def test_asr_client_reports_invalid_audio_and_unavailable_service():
    async def scenario(status):
        client = ASRClient(
            BackendSettings(),
            transport=httpx.MockTransport(lambda request: httpx.Response(status)),
        )
        try:
            await client.transcribe(wav_bytes())
        finally:
            await client.close()

    with pytest.raises(ASRInvalidAudio):
        asyncio.run(scenario(422))
    with pytest.raises(ASRUnavailable):
        asyncio.run(scenario(503))


def test_compose_service_hosts_are_allowed_but_external_hosts_are_not():
    settings = BackendSettings(
        ollama_url="http://ollama:11434", asr_url="http://asr:8001"
    )
    assert settings.asr_url == "http://asr:8001"

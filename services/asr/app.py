"""Private local Chinese ASR service. Speaker roles are never inferred."""

import io
import os
import tempfile
import threading
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

MAX_AUDIO_BYTES = 5_000_000
MODEL_ID = "funasr/paraformer-zh"
MODEL_REVISION = "d7811ee3ac581fbcfdeb37c98c6ba674028433dc"


def validate_wav(data: bytes) -> float:
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError("WAV must be nonempty and at most 5 MB")
    try:
        with wave.open(io.BytesIO(data), "rb") as stream:
            if (
                stream.getnchannels() != 1
                or stream.getframerate() != 16_000
                or stream.getsampwidth() != 2
                or stream.getcomptype() != "NONE"
            ):
                raise ValueError("Expected mono 16 kHz PCM16 WAV")
            duration = stream.getnframes() / stream.getframerate()
            if not 0.2 <= duration <= 120:
                raise ValueError("WAV duration must be 0.2–120 seconds")
            stream.readframes(1)
            return round(duration, 3)
    except (EOFError, wave.Error) as exc:
        raise ValueError("Invalid WAV") from exc


class Recognizer:
    def __init__(self, model_dir: Path, model_factory=None, seed_fn=None):
        self.model_dir = model_dir
        self.model_factory = model_factory
        self.seed_fn = seed_fn
        self.model = None
        self.lock = threading.Lock()

    def ready(self) -> bool:
        return (self.model_dir / "config.yaml").is_file() and (
            self.model_dir / "model.pt"
        ).is_file()

    def transcribe(self, data: bytes) -> str:
        with self.lock:
            if not self.ready():
                raise FileNotFoundError("ASR model snapshot is missing")
            if self.model is None:
                if self.model_factory is None:
                    from funasr import AutoModel

                    self.model_factory = AutoModel
                if self.seed_fn is None:
                    from funasr.train_utils.set_all_random_seed import set_all_random_seed

                    self.seed_fn = set_all_random_seed
                self.model = self.model_factory(
                    model=str(self.model_dir),
                    device="cpu",
                    ncpu=1,
                    disable_update=True,
                    trust_remote_code=False,
                )
            with tempfile.NamedTemporaryFile(suffix=".wav") as temporary:
                temporary.write(data)
                temporary.flush()
                self.seed_fn(0)
                result = self.model.generate(input=temporary.name)
            if not isinstance(result, list) or not result or not isinstance(
                result[0].get("text"), str
            ):
                raise RuntimeError("Unexpected FunASR response")
            return result[0]["text"].strip()


def create_app(recognizer: Recognizer | None = None) -> FastAPI:
    recognizer = recognizer or Recognizer(
        Path(os.getenv("SMARTMED_ASR_MODEL_DIR", "/models/paraformer-zh"))
    )
    app = FastAPI(title="SmartMed local ASR", version="0.1.0")

    @app.get("/health")
    def health():
        return {
            "status": "ready" if recognizer.ready() else "model_missing",
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
        }

    @app.post("/v1/transcribe")
    async def transcribe(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "audio/wav":
            raise HTTPException(415, detail={"code": "wav_required"})
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_AUDIO_BYTES:
                raise HTTPException(413, detail={"code": "audio_too_large"})
            chunks.append(chunk)
        audio = b"".join(chunks)
        try:
            duration = validate_wav(audio)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid_wav", "message": str(exc)}) from exc
        if not recognizer.ready():
            raise HTTPException(503, detail={"code": "asr_model_missing"})
        try:
            from fastapi.concurrency import run_in_threadpool

            text = await run_in_threadpool(recognizer.transcribe, audio)
        except FileNotFoundError as exc:
            raise HTTPException(503, detail={"code": "asr_model_missing"}) from exc
        except Exception as exc:
            raise HTTPException(502, detail={"code": "asr_failed"}) from exc
        return {
            "text": text,
            "duration_s": duration,
            "sample_rate": 16_000,
            "model": MODEL_ID,
            "revision": MODEL_REVISION,
            "speaker_labels": "manual_required",
        }

    return app


app = create_app()

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, ValidationError

from smartmed.audio_client import ASRClient, ASRInvalidAudio, ASRTimeout, ASRUnavailable
from smartmed.auth import AuthStore, LoginThrottled
from smartmed.backend_settings import BackendSettings, load_backend_settings
from smartmed.jobs import JobNotFound, Jobs, QueueFull
from smartmed.medications import INDEX_VERSION, search
from smartmed.model_client import (
    GenerationTimeout,
    InvalidGeneration,
    ModelBusy,
    ModelUnavailable,
    OllamaExtractor,
)
from smartmed.outpatient_api import register_outpatient
from smartmed.outpatient_model import OutpatientExtractor
from smartmed.runtime import worker_lease
from smartmed.safety import report as safety_report
from smartmed.schemas.extraction import (
    CONTRACT_VERSION,
    FIELDS,
    MAX_INPUT_CHARS,
    Extraction,
    ExtractRequest,
    StrictModel,
    validate_extraction,
)
from smartmed.segmentation import SEGMENT_CHARS
from smartmed.store import Draft, DraftStore, NotFound, VersionConflict
from smartmed.terminology_client import (
    CodeNotFound,
    TerminologyClient,
    TerminologyTimeout,
    TerminologyUnavailable,
)


class EditRequest(StrictModel):
    expected_version: int = Field(ge=1)
    actor: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"\S")
    document: Extraction


class ConfirmRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reviewer: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"\S")
    reviewed: Literal[True]
    acknowledged_alerts: list[str] = Field(default_factory=list, max_length=20)


class LoginRequest(StrictModel):
    staff_id: str = Field(min_length=1, max_length=100)
    passcode: str = Field(min_length=1, max_length=1024)


class SpeakerAssignmentRequest(StrictModel):
    text: str = Field(min_length=1, max_length=8000)


def create_app(
    settings: BackendSettings | None = None,
    extractor=None,
    asr_client=None,
    terminology_client=None,
    outpatient_extractor=None,
) -> FastAPI:
    settings = settings or load_backend_settings()
    store = DraftStore(settings.database)
    auth = AuthStore(settings.auth_database)
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        with worker_lease(settings.database):
            app.state.extractor = extractor or OllamaExtractor(settings)
            app.state.jobs = Jobs(
                store, app.state.extractor, settings.queue_capacity, settings.retention_days
            )
            app.state.outpatient_extractor = outpatient_extractor or OutpatientExtractor(settings)
            if hasattr(app.state.extractor, "lock") and hasattr(
                app.state.outpatient_extractor, "lock"
            ):
                app.state.outpatient_extractor.lock = app.state.extractor.lock
            app.state.asr_client = asr_client or ASRClient(settings)
            app.state.terminology_client = terminology_client or TerminologyClient(settings)
            try:
                await app.state.jobs.start()
                yield
            finally:
                await app.state.jobs.close()
                if outpatient_extractor is None:
                    await app.state.outpatient_extractor.close()
                if asr_client is None:
                    await app.state.asr_client.close()
                if terminology_client is None:
                    await app.state.terminology_client.close()
                if extractor is None:
                    await app.state.extractor.close()

    app = FastAPI(title="SmartMed 本地病历草稿", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo passwords or patient text in request validation errors.
        errors = [{"loc": e["loc"], "type": e["type"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    def current_staff(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        actor = auth.resolve(credentials.credentials) if credentials else None
        if actor is None:
            raise HTTPException(
                401,
                detail={"code": "authentication_required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return actor

    register_outpatient(app, store, current_staff, settings.retention_days)

    def check_identity(asserted, actor):
        if asserted is not None and asserted != actor:
            raise HTTPException(403, detail={"code": "identity_mismatch"})

    @app.post("/v1/auth/login")
    def login(request: LoginRequest):
        try:
            token = auth.login(request.staff_id, request.passcode)
        except LoginThrottled as exc:
            raise HTTPException(
                429, detail={"code": "login_throttled"}, headers={"Retry-After": "900"}
            ) from exc
        if token is None:
            raise HTTPException(401, detail={"code": "invalid_credentials"})
        return {"access_token": token, "token_type": "bearer", "expires_in": 3600}

    @app.post("/v1/auth/logout", status_code=204)
    def logout(
        credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
        actor: str = Depends(current_staff),
    ):
        auth.logout(credentials.credentials)

    def get(draft_id: str):
        try:
            return store.get(draft_id)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "stored_contract_invalid"}) from exc
        except NotFound as exc:
            raise HTTPException(
                404,
                detail={
                    "code": "draft_not_found",
                    "message": "草稿不存在",
                },
            ) from exc

    def replace(draft, expected, actor, action):
        try:
            return store.replace(draft, expected, actor, action)
        except VersionConflict as exc:
            raise HTTPException(
                409,
                detail={
                    "code": "version_conflict",
                    "message": "版本已更新，请重新读取草稿",
                },
            ) from exc

    @app.get("/health")
    async def health():
        status = await app.state.extractor.health()
        return {"status": "ready" if status["model_installed"] else "unavailable", **status}

    @app.get("/v1/form")
    def form():
        return {
            "contract_version": CONTRACT_VERSION,
            "limits": {
                "input_characters": MAX_INPUT_CHARS,
                "turns": 160,
                "segment_characters": SEGMENT_CHARS,
            },
            "speakers": ["patient", "doctor", "third_party"],
            "fields": [{"name": name, "label": name} for name in FIELDS],
            "statuses": {"present": "明确存在", "negated": "明确否认", "unknown": "未知"},
            "schema": Extraction.model_json_schema(),
        }

    @app.get("/v1/diagnoses/catalog")
    async def diagnosis_catalog():
        try:
            return await app.state.terminology_client.catalog()
        except TerminologyTimeout as exc:
            raise HTTPException(504, detail={"code": "terminology_timeout"}) from exc
        except TerminologyUnavailable as exc:
            raise HTTPException(503, detail={"code": "terminology_unavailable"}) from exc

    @app.get("/v1/diagnoses/search")
    async def diagnosis_search(
        q: str = Query(min_length=1, max_length=80), limit: int = Query(20, ge=1, le=50)
    ):
        if not q.strip():
            raise HTTPException(422, detail={"code": "empty_query"})
        try:
            return await app.state.terminology_client.search(q, limit)
        except TerminologyTimeout as exc:
            raise HTTPException(504, detail={"code": "terminology_timeout"}) from exc
        except TerminologyUnavailable as exc:
            raise HTTPException(503, detail={"code": "terminology_unavailable"}) from exc

    @app.get("/v1/diagnoses/lookup")
    async def diagnosis_lookup(code: str = Query(min_length=1, max_length=40)):
        if not code.strip():
            raise HTTPException(422, detail={"code": "empty_code"})
        try:
            return await app.state.terminology_client.lookup(code)
        except CodeNotFound as exc:
            raise HTTPException(404, detail={"code": "code_not_in_catalog"}) from exc
        except TerminologyTimeout as exc:
            raise HTTPException(504, detail={"code": "terminology_timeout"}) from exc
        except TerminologyUnavailable as exc:
            raise HTTPException(503, detail={"code": "terminology_unavailable"}) from exc

    @app.post("/v1/audio/transcribe")
    async def transcribe(request: Request):
        if request.headers.get("content-type", "").split(";")[0] not in {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
        }:
            raise HTTPException(415, detail={"code": "wav_required"})
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 5_000_000:
                raise HTTPException(413, detail={"code": "audio_too_large"})
            chunks.append(chunk)
        try:
            return await app.state.asr_client.transcribe(b"".join(chunks))
        except ASRInvalidAudio as exc:
            raise HTTPException(422, detail={"code": "invalid_audio"}) from exc
        except ASRTimeout as exc:
            raise HTTPException(504, detail={"code": "asr_timeout"}) from exc
        except ASRUnavailable as exc:
            raise HTTPException(503, detail={"code": "asr_unavailable"}) from exc

    @app.post("/v1/audio/assign-speakers")
    async def assign_audio_speakers(
        request: SpeakerAssignmentRequest, actor: str = Depends(current_staff)
    ):
        try:
            return await app.state.outpatient_extractor.assign_speakers(request.text)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid_transcript"}) from exc
        except ModelUnavailable as exc:
            raise HTTPException(503, detail={"code": "model_unavailable"}) from exc
        except ModelBusy as exc:
            raise HTTPException(503, detail={"code": "model_busy"}) from exc
        except GenerationTimeout as exc:
            raise HTTPException(504, detail={"code": "model_timeout"}) from exc
        except InvalidGeneration as exc:
            raise HTTPException(502, detail={"code": "invalid_speaker_assignment"}) from exc

    def submit_job(request, actor):

        try:
            return app.state.jobs.submit(request, actor)
        except QueueFull as exc:
            raise HTTPException(
                503, detail={"code": "queue_full"}, headers={"Retry-After": "5"}
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                422,
                detail={
                    "code": "single_utterance_too_long",
                    "max_segment_characters": SEGMENT_CHARS,
                },
            ) from exc

    @app.post("/v1/jobs", status_code=202)
    async def enqueue(request: ExtractRequest, actor: str = Depends(current_staff)):
        return submit_job(request, actor)

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str, actor: str = Depends(current_staff)):
        try:
            return app.state.jobs.status(job_id, actor)
        except JobNotFound as exc:
            raise HTTPException(404, detail={"code": "job_not_found"}) from exc

    @app.delete("/v1/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, actor: str = Depends(current_staff)):
        try:
            app.state.jobs.delete(job_id, actor)
        except JobNotFound as exc:
            raise HTTPException(404, detail={"code": "job_not_found"}) from exc
        except QueueFull as exc:
            raise HTTPException(409, detail={"code": "job_running"}) from exc

    @app.post("/v1/drafts", response_model=Draft, status_code=201)
    async def generate(request: ExtractRequest, actor: str = Depends(current_staff)):
        # Backwards-compatible blocking route uses the same single-worker queue.
        job = submit_job(request, actor)
        status = await app.state.jobs.wait(job["job_id"], actor)
        app.state.jobs.delete(job["job_id"], actor)
        if status["status"] != "succeeded":
            code = status["error"]
            http_status = {
                "model_unavailable": 503,
                "model_busy": 503,
                "model_timeout": 504,
                "invalid_model_output": 502,
            }.get(code, 502)
            raise HTTPException(http_status, detail={"code": code})
        return get(status["draft_id"])

    @app.get("/v1/medications")
    def medications(
        q: Annotated[str, Query(max_length=100)] = "", actor: str = Depends(current_staff)
    ):
        return {"index_version": INDEX_VERSION, "items": search(q)}

    @app.get("/v1/drafts/{draft_id}/safety")
    def safety(draft_id: str, actor: str = Depends(current_staff)):
        draft = get(draft_id)
        return safety_report(draft.document, draft.model_metadata)

    @app.get("/v1/drafts/{draft_id}", response_model=Draft)
    def read(draft_id: str, actor: str = Depends(current_staff)):
        return get(draft_id)

    @app.put("/v1/drafts/{draft_id}", response_model=Draft)
    def edit(draft_id: str, request: EditRequest, actor: str = Depends(current_staff)):
        check_identity(request.actor, actor)
        draft = get(draft_id)
        if draft.version != request.expected_version:
            raise HTTPException(409, detail={"code": "version_conflict"})
        try:
            draft.document = validate_extraction(request.document.model_dump(), draft.turns)
        except ValidationError as exc:
            # Do not include Pydantic's input/context: those contain clinical text.
            errors = [
                {"loc": error["loc"], "msg": error["msg"]}
                for error in exc.errors(include_context=False, include_input=False)
            ]
            raise HTTPException(422, detail={"code": "invalid_evidence", "errors": errors}) from exc
        draft.state = "requires_review"
        draft.reviewer = None
        draft.acknowledged_alerts = []
        return replace(draft, request.expected_version, actor, "edited")

    @app.post("/v1/drafts/{draft_id}/confirm", response_model=Draft)
    def confirm(draft_id: str, request: ConfirmRequest, actor: str = Depends(current_staff)):
        check_identity(request.reviewer, actor)
        draft = get(draft_id)
        required = safety_report(draft.document, draft.model_metadata)["required_acknowledgements"]
        if not set(required).issubset(request.acknowledged_alerts):
            raise HTTPException(
                409,
                detail={
                    "code": "safety_acknowledgement_required",
                    "required_acknowledgements": required,
                },
            )
        draft.acknowledged_alerts = sorted(set(request.acknowledged_alerts))
        draft.state = "confirmed"
        draft.reviewer = actor
        return replace(draft, request.expected_version, actor, "confirmed")

    @app.get("/v1/drafts/{draft_id}/history")
    def history(draft_id: str, actor: str = Depends(current_staff)):
        get(draft_id)
        try:
            return store.history(draft_id)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": "stored_contract_invalid"}) from exc

    @app.get("/v1/drafts/{draft_id}/export", response_model=Draft)
    def export(draft_id: str, actor: str = Depends(current_staff)):
        draft = get(draft_id)
        required = safety_report(draft.document, draft.model_metadata)["required_acknowledgements"]
        if draft.state != "confirmed" or not set(required).issubset(draft.acknowledged_alerts):
            raise HTTPException(
                409,
                detail={
                    "code": "review_required",
                    "message": "导出前请人工核对并确认",
                },
            )
        return draft

    @app.delete("/v1/drafts/{draft_id}", status_code=204)
    def delete(
        draft_id: str,
        expected_version: Annotated[int, Query(ge=1)],
        actor: str = Depends(current_staff),
    ):
        try:
            store.delete(draft_id, expected_version)
        except NotFound as exc:
            raise HTTPException(404, detail={"code": "draft_not_found"}) from exc
        except VersionConflict as exc:
            raise HTTPException(409, detail={"code": "version_conflict"}) from exc

    return app

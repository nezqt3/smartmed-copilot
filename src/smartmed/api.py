from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import Field, ValidationError

from smartmed.audio_client import ASRClient, ASRInvalidAudio, ASRTimeout, ASRUnavailable
from smartmed.backend_settings import BackendSettings, load_backend_settings
from smartmed.model_client import (
    GenerationTimeout,
    InvalidGeneration,
    ModelBusy,
    ModelUnavailable,
    OllamaExtractor,
)
from smartmed.schemas.extraction import (
    CONTRACT_VERSION,
    FIELDS,
    Extraction,
    ExtractRequest,
    StrictModel,
    validate_extraction,
)
from smartmed.store import Draft, DraftStore, NotFound, VersionConflict
from smartmed.terminology_client import (
    CodeNotFound,
    TerminologyClient,
    TerminologyTimeout,
    TerminologyUnavailable,
)


class EditRequest(StrictModel):
    expected_version: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=100, pattern=r"\S")
    document: Extraction


class ConfirmRequest(StrictModel):
    expected_version: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=100, pattern=r"\S")
    reviewed: Literal[True]


def create_app(settings: BackendSettings | None = None, extractor=None, asr_client=None,
               terminology_client=None) -> FastAPI:
    settings = settings or load_backend_settings()
    store = DraftStore(settings.database)

    @asynccontextmanager
    async def lifespan(app):
        app.state.extractor = extractor or OllamaExtractor(settings)
        app.state.asr_client = asr_client or ASRClient(settings)
        app.state.terminology_client = terminology_client or TerminologyClient(settings)
        try:
            yield
        finally:
            if extractor is None:
                await app.state.extractor.close()
            if asr_client is None:
                await app.state.asr_client.close()
            if terminology_client is None:
                await app.state.terminology_client.close()

    app = FastAPI(title="SmartMed 本地病历草稿", version="0.1.0", lifespan=lifespan)

    def get(draft_id: str):
        try:
            return store.get(draft_id)
        except NotFound as exc:
            raise HTTPException(404, detail={
                "code": "draft_not_found", "message": "草稿不存在",
            }) from exc

    def replace(draft, expected, actor, action):
        try:
            return store.replace(draft, expected, actor, action)
        except VersionConflict as exc:
            raise HTTPException(409, detail={
                "code": "version_conflict", "message": "版本已更新，请重新读取草稿",
            }) from exc

    @app.get("/health")
    async def health():
        status = await app.state.extractor.health()
        return {"status": "ready" if status["model_installed"] else "unavailable", **status}

    @app.get("/v1/form")
    def form():
        return {
            "contract_version": CONTRACT_VERSION,
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
    async def diagnosis_search(q: str = Query(min_length=1, max_length=80),
                               limit: int = Query(20, ge=1, le=50)):
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
            "audio/wav", "audio/x-wav", "audio/wave",
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

    @app.post("/v1/drafts", response_model=Draft, status_code=201)
    async def generate(request: ExtractRequest):
        try:
            result = await app.state.extractor.extract(request)
        except ModelBusy as exc:
            raise HTTPException(503, detail={
                "code": "model_busy", "message": "模型正在处理其他请求，请稍后重试",
            }, headers={"Retry-After": "5"}) from exc
        except GenerationTimeout as exc:
            raise HTTPException(504, detail={
                "code": "model_timeout", "message": "生成超时，未保存草稿",
            }) from exc
        except ModelUnavailable as exc:
            raise HTTPException(503, detail={
                "code": "model_unavailable", "message": "本地Ollama或模型不可用",
            }) from exc
        except InvalidGeneration as exc:
            raise HTTPException(502, detail={
                "code": "invalid_model_output",
                "message": "模型输出未通过验证，未保存草稿；请重试或人工录入",
            }) from exc
        return store.create(request.turns, result.document, result.metadata)

    @app.get("/v1/drafts/{draft_id}", response_model=Draft)
    def read(draft_id: str):
        return get(draft_id)

    @app.put("/v1/drafts/{draft_id}", response_model=Draft)
    def edit(draft_id: str, request: EditRequest):
        draft = get(draft_id)
        if draft.version != request.expected_version:
            raise HTTPException(409, detail={"code": "version_conflict"})
        try:
            draft.document = validate_extraction(request.document.model_dump(), draft.turns)
        except ValidationError as exc:
            # Do not include Pydantic's input/context: those contain clinical text.
            errors = [{"loc": error["loc"], "msg": error["msg"]}
                      for error in exc.errors(include_context=False, include_input=False)]
            raise HTTPException(422, detail={"code": "invalid_evidence", "errors": errors}) from exc
        draft.state = "requires_review"
        draft.reviewer = None
        return replace(draft, request.expected_version, request.actor, "edited")

    @app.post("/v1/drafts/{draft_id}/confirm", response_model=Draft)
    def confirm(draft_id: str, request: ConfirmRequest):
        draft = get(draft_id)
        draft.state = "confirmed"
        draft.reviewer = request.reviewer
        return replace(draft, request.expected_version, request.reviewer, "confirmed")

    @app.get("/v1/drafts/{draft_id}/history")
    def history(draft_id: str):
        get(draft_id)
        return store.history(draft_id)

    @app.get("/v1/drafts/{draft_id}/export", response_model=Draft)
    def export(draft_id: str):
        draft = get(draft_id)
        if draft.state != "confirmed":
            raise HTTPException(409, detail={
                "code": "review_required", "message": "导出前请人工核对并确认",
            })
        return draft

    return app

"""Authenticated versioned outpatient drafts, revisions, review and printable export."""

import html
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import Field, ValidationError

from smartmed.model_client import GenerationTimeout, InvalidGeneration, ModelBusy, ModelUnavailable
from smartmed.schemas.extraction import StrictModel, Turn
from smartmed.schemas.outpatient import (
    SECTIONS,
    VERSION,
    Encounter,
    OutpatientDocument,
    OutpatientRequest,
    Patient,
    validate_document,
)


def timestamp():
    return datetime.now(UTC).isoformat()


class OutpatientDraft(StrictModel):
    id: str
    contract_version: Literal["outpatient.v1"] = VERSION
    version: int = Field(ge=1)
    state: Literal["requires_review", "confirmed"] = "requires_review"
    created_at: str
    updated_at: str
    patient: Patient
    encounter: Encounter
    turns: list[Turn]
    transcript_reviewed_by: str
    document: OutpatientDocument
    model_metadata: dict
    reviewer: str | None = None
    reviewed_at: str | None = None


class Edit(StrictModel):
    expected_version: int = Field(ge=1)
    patient: Patient
    encounter: Encounter
    document: OutpatientDocument


class Confirm(StrictModel):
    expected_version: int = Field(ge=1)
    reviewed: Literal[True]
    reviewed_sections: list[str] = Field(min_length=9, max_length=9)
    patient_encounter_reviewed: Literal[True]


def printable(draft: OutpatientDraft) -> str:
    esc = lambda value: html.escape(str("未记录" if value is None or value == "" else value))  # noqa: E731
    def shown(value):
        text = str(value).replace("T", " ") if value else None
        return text[:16] if text else None

    visited_at = shown(draft.encounter.visited_at)
    labels = {
        "present": "明确陈述",
        "negated": "明确否认",
        "uncertain": "尚不确定",
        "patient": "患者",
        "doctor": "医生",
        "third_party": "家属/其他",
        "clinician": "医生手动补充",
        "unknown": "未知",
        "male": "男",
        "female": "女",
        "other": "其他",
        "initial": "初诊",
        "follow_up": "复诊",
    }
    sections = []
    for key, label in SECTIONS.items():
        section = getattr(draft.document, key)
        items = "".join(
            f"<li>{esc(item.text)} <small>（{esc(labels[item.assertion])}；"
            f"{esc(labels[item.reported_by])}）</small></li>"
            for item in section.items
        )
        content = "<ul>" + items + "</ul>" if items else "<p>未记录 / 未知</p>"
        sections.append(f"<section><h2>{label}</h2>{content}</section>")
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>门诊病历 — {esc(draft.patient.name)}</title>
<style>body{{font:16px/1.6 sans-serif;max-width:900px;margin:32px auto;padding:20px}}
h1{{text-align:center}}h2{{font-size:18px;border-bottom:1px solid #bbb}}
section{{break-inside:avoid}}small{{color:#555}}@media print{{button{{display:none}}}}</style>
<h1>门诊病历（SmartMed 演示）</h1>
<p>姓名：{esc(draft.patient.name)}　患者编号：{esc(draft.patient.patient_id)}　
性别：{esc(labels[draft.patient.sex])}　年龄：{esc(draft.patient.age)}</p>
<p>科室：{esc(draft.encounter.department)}　就诊时间：{esc(visited_at)}　
类型：{esc(labels[draft.encounter.visit_type])}</p>
{"".join(sections)}
<p>审核医师：{esc(draft.reviewer)}　审核时间：{esc(draft.reviewed_at)}</p>
<small>记录ID：{esc(draft.id)}　版本：{draft.version} / {VERSION}。
此为经用户审核的演示记录，不是电子签名或医院处方。</small></html>"""


def register_outpatient(app, store, current_staff, retention_days):
    staff_dependency = Depends(current_staff)
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS outpatient_drafts (
            id TEXT PRIMARY KEY, version INTEGER NOT NULL, created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outpatient_revisions (
            draft_id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL,
            action TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(draft_id, version)
        );""")

    def purge():
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with store.connect() as db:
            db.execute(
                "DELETE FROM outpatient_revisions WHERE draft_id IN "
                "(SELECT id FROM outpatient_drafts WHERE created_at<?)",
                (cutoff,),
            )
            db.execute("DELETE FROM outpatient_drafts WHERE created_at<?", (cutoff,))

    def load(draft_id):
        purge()
        with store.connect() as db:
            row = db.execute(
                "SELECT payload FROM outpatient_drafts WHERE id=?", (draft_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, detail={"code": "draft_not_found"})
        try:
            draft = OutpatientDraft.model_validate_json(row[0])
            draft.document = validate_document(draft.document.model_dump(), draft.turns)
            return draft
        except (ValueError, ValidationError) as exc:
            raise HTTPException(409, detail={"code": "stored_contract_invalid"}) from exc

    def write(draft, expected, actor, action):
        draft.updated_at = timestamp()
        with store.connect() as db:
            if expected is None:
                db.execute(
                    "INSERT INTO outpatient_drafts VALUES (?, ?, ?, ?)",
                    (draft.id, draft.version, draft.created_at, draft.model_dump_json()),
                )
            else:
                draft.version = expected + 1
                changed = db.execute(
                    "UPDATE outpatient_drafts SET version=?, payload=? WHERE id=? AND version=?",
                    (draft.version, draft.model_dump_json(), draft.id, expected),
                ).rowcount
                if not changed:
                    raise HTTPException(409, detail={"code": "version_conflict"})
            db.execute(
                "INSERT INTO outpatient_revisions VALUES (?, ?, ?, ?, ?)",
                (draft.id, draft.version, actor, action, draft.model_dump_json()),
            )
        return draft

    def version(draft, expected):
        if draft.version != expected:
            raise HTTPException(409, detail={"code": "version_conflict"})

    def exportable(draft):
        if draft.state != "confirmed" or not draft.reviewer or not draft.reviewed_at:
            raise HTTPException(409, detail={"code": "review_required"})
        for key in SECTIONS:
            section = getattr(draft.document, key)
            if not section.reviewed or any(not i.reviewed for i in section.items):
                raise HTTPException(409, detail={"code": "section_review_required"})

    @app.get("/v1/outpatient/form")
    def form(actor=staff_dependency):
        return {
            "contract_version": VERSION,
            "sections": SECTIONS,
            "schema": OutpatientDocument.model_json_schema(),
            "max_input_characters": 8000,
        }

    @app.post("/v1/outpatient/drafts", response_model=OutpatientDraft, status_code=201)
    async def generate(request: OutpatientRequest, actor=staff_dependency):
        purge()
        try:
            result = await app.state.outpatient_extractor.extract(request)
            document = validate_document(
                result.document.model_dump(), request.turns, generated=True
            )
        except (ModelUnavailable, GenerationTimeout, InvalidGeneration, ModelBusy) as exc:
            codes = {
                ModelUnavailable: (503, "model_unavailable"),
                GenerationTimeout: (504, "model_timeout"),
                InvalidGeneration: (502, "invalid_model_output"),
                ModelBusy: (503, "model_busy"),
            }
            status, code = codes[type(exc)]
            raise HTTPException(status, detail={"code": code}) from exc
        except ValidationError as exc:
            raise HTTPException(502, detail={"code": "invalid_model_output"}) from exc
        draft = OutpatientDraft(
            id=str(uuid4()),
            version=1,
            created_at=timestamp(),
            updated_at=timestamp(),
            patient=request.patient,
            encounter=request.encounter,
            turns=request.turns,
            transcript_reviewed_by=actor,
            document=document,
            model_metadata=result.metadata,
        )
        return write(draft, None, actor, "generated")

    @app.get("/v1/outpatient/drafts/{draft_id}", response_model=OutpatientDraft)
    def get(draft_id: str, actor=staff_dependency):
        return load(draft_id)

    @app.put("/v1/outpatient/drafts/{draft_id}", response_model=OutpatientDraft)
    def edit(draft_id: str, request: Edit, actor=staff_dependency):
        draft = load(draft_id)
        version(draft, request.expected_version)
        try:
            draft.document = validate_document(request.document.model_dump(), draft.turns)
        except ValidationError as exc:
            raise HTTPException(422, detail={"code": "invalid_evidence"}) from exc
        # Any edit resets all review. A client cannot preserve/forge checks on changed content.
        for key in SECTIONS:
            section = getattr(draft.document, key)
            section.reviewed = False
            for item in section.items:
                item.reviewed = False
        draft.patient, draft.encounter = request.patient, request.encounter
        draft.state, draft.reviewer, draft.reviewed_at = "requires_review", None, None
        return write(draft, request.expected_version, actor, "edited")

    @app.post("/v1/outpatient/drafts/{draft_id}/confirm", response_model=OutpatientDraft)
    def confirm(draft_id: str, request: Confirm, actor=staff_dependency):
        draft = load(draft_id)
        version(draft, request.expected_version)
        if set(request.reviewed_sections) != set(SECTIONS):
            raise HTTPException(422, detail={"code": "all_sections_review_required"})
        if any(getattr(draft.document, key).status == "conflict" for key in SECTIONS):
            raise HTTPException(409, detail={"code": "resolve_conflicts_before_review"})
        # Server records the clinician's explicit confirmation of all sections of this version.
        for key in SECTIONS:
            section = getattr(draft.document, key)
            section.reviewed = True
            for item in section.items:
                item.reviewed = True
        draft.state, draft.reviewer, draft.reviewed_at = "confirmed", actor, timestamp()
        return write(draft, request.expected_version, actor, "confirmed")

    @app.get("/v1/outpatient/drafts/{draft_id}/export", response_model=OutpatientDraft)
    def export(draft_id: str, actor=staff_dependency):
        draft = load(draft_id)
        exportable(draft)
        return draft

    @app.get("/v1/outpatient/drafts/{draft_id}/print", response_class=HTMLResponse)
    def print_record(draft_id: str, actor=staff_dependency):
        draft = load(draft_id)
        exportable(draft)
        return HTMLResponse(printable(draft), headers={"Cache-Control": "no-store"})

    @app.get("/v1/outpatient/drafts/{draft_id}/history")
    def history(draft_id: str, actor=staff_dependency):
        load(draft_id)
        with store.connect() as db:
            rows = db.execute(
                "SELECT version, actor, action FROM outpatient_revisions "
                "WHERE draft_id=? ORDER BY version",
                (draft_id,),
            ).fetchall()
        return [{"version": r[0], "actor": r[1], "action": r[2]} for r in rows]

    @app.delete("/v1/outpatient/drafts/{draft_id}", status_code=204)
    def delete(draft_id: str, expected_version: int, actor=staff_dependency):
        draft = load(draft_id)
        version(draft, expected_version)
        with store.connect() as db:
            changed = db.execute(
                "DELETE FROM outpatient_drafts WHERE id=? AND version=?",
                (draft_id, expected_version),
            ).rowcount
            if not changed:
                raise HTTPException(409, detail={"code": "version_conflict"})
            db.execute("DELETE FROM outpatient_revisions WHERE draft_id=?", (draft_id,))

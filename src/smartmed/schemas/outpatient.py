"""SmartMed outpatient.v1: a project contract, not an official hospital interface."""

import re
from typing import Literal

from pydantic import Field, ValidationInfo, model_validator

from smartmed.schemas.extraction import Evidence, ExtractRequest, StrictModel, Turn

VERSION = "outpatient.v1"
SECTIONS = {
    "chief_complaint": "主诉",
    "present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "medication_history": "用药史",
    "physical_examination": "体格检查",
    "investigations": "辅助检查",
    "assessment": "初步诊断",
    "plan": "治疗处理意见",
}
DOCTOR_SECTIONS = {"physical_examination", "assessment", "plan"}
HISTORY_SECTIONS = {
    "chief_complaint",
    "present_illness",
    "past_history",
    "allergy_history",
    "medication_history",
}


class ClinicalItem(StrictModel):
    text: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    assertion: Literal["present", "negated", "uncertain"]
    origin: Literal["transcript", "manual"]
    reported_by: Literal["patient", "doctor", "third_party", "clinician"]
    evidence: list[Evidence] = Field(max_length=8)
    reviewed: bool


class Section(StrictModel):
    status: Literal["documented", "unknown", "conflict"]
    items: list[ClinicalItem] = Field(max_length=24)
    reviewed: bool

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "unknown") != (not self.items):
            raise ValueError("unknown requires no items; documented/conflict require items")
        return self


class OutpatientDocument(StrictModel):
    chief_complaint: Section
    present_illness: Section
    past_history: Section
    allergy_history: Section
    medication_history: Section
    physical_examination: Section
    investigations: Section
    assessment: Section
    plan: Section

    @model_validator(mode="after")
    def grounded(self, info: ValidationInfo):
        if not info.context:
            return self
        turns = {t.turn_id: t for t in info.context["turns"]}
        generated = info.context.get("generated", False)
        for name in SECTIONS:
            section = getattr(self, name)
            if generated and section.reviewed:
                raise ValueError("Model cannot claim clinician review")
            for item in section.items:
                if generated and (item.origin != "transcript" or item.reviewed):
                    raise ValueError("Model cannot create manual facts or clinician review")
                if item.origin == "manual":
                    if item.evidence or item.reported_by != "clinician":
                        raise ValueError(
                            "Manual facts require clinician origin and no invented quotes"
                        )
                    continue
                if not item.evidence or item.reported_by == "clinician":
                    raise ValueError("Transcript facts require a speaker and citations")
                for evidence in item.evidence:
                    turn = turns.get(evidence.turn_id)
                    if (
                        not turn
                        or turn.speaker != item.reported_by
                        or evidence.quote not in turn.text
                    ):
                        raise ValueError("Citation must match the original turn and its speaker")
                    if name in HISTORY_SECTIONS and turn.speaker == "doctor":
                        raise ValueError("History sections require patient/third-party facts")
                    if name in DOCTOR_SECTIONS and turn.speaker != "doctor":
                        raise ValueError(
                            "Examination, assessment and plan require doctor statements"
                        )
                if (
                    name == "assessment"
                    and re.search(
                        r"可能|考虑|怀疑|疑似|尚未确诊|待排",
                        item.text,
                    )
                    and item.assertion != "uncertain"
                ):
                    raise ValueError("Tentative doctor assessment must remain uncertain")
                if name in DOCTOR_SECTIONS and re.search(r"[？?]|吗[。！!]?$", item.text):
                    raise ValueError("A doctor question is not a finding, diagnosis or order")
                if not any(item.text in e.quote for e in item.evidence):
                    raise ValueError("Fact text must be copied from a cited span")
        return self


def validate_document(payload: dict, turns: list[Turn], *, generated=False) -> OutpatientDocument:
    return OutpatientDocument.model_validate(
        payload,
        context={"turns": turns, "generated": generated},
    )


class Patient(StrictModel):
    patient_id: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=100)
    sex: Literal["male", "female", "other", "unknown"] = "unknown"
    age: int | None = Field(default=None, ge=0, le=130)


class Encounter(StrictModel):
    department: str | None = Field(default=None, max_length=100)
    visit_type: Literal["initial", "follow_up", "unknown"] = "unknown"
    visited_at: str | None = Field(default=None, max_length=40)


class OutpatientRequest(ExtractRequest):
    transcript_reviewed: Literal[True]
    patient: Patient = Field(default_factory=Patient)
    encounter: Encounter = Field(default_factory=Encounter)

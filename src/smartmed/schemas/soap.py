from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

ICD10_CODE_PATTERN = r"^[A-Z][0-9]{2}(\.[0-9]{1,3})?$"
ICD11_CODE_PATTERN = r"^[A-Z][0-9A-Z]{2,6}(\.[0-9A-Z]{1,4})?$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    mild = "mild"
    moderate = "moderate"
    severe = "severe"


class Route(StrEnum):
    oral = "oral"
    sublingual = "sublingual"
    topical = "topical"
    inhaled = "inhaled"
    intravenous = "intravenous"
    intramuscular = "intramuscular"
    subcutaneous = "subcutaneous"
    rectal = "rectal"
    unknown = "unknown"


class DoseUnit(StrEnum):
    mg = "mg"
    mcg = "mcg"
    g = "g"
    ml = "ml"
    iu = "iu"
    piece = "piece"


class DoseForm(StrEnum):
    tablet = "tablet"
    capsule = "capsule"
    solution = "solution"
    suspension = "suspension"
    injection = "injection"
    ointment = "ointment"
    drops = "drops"
    inhaler = "inhaler"
    patch = "patch"
    unknown = "unknown"


class Frequency(StrEnum):
    once_daily = "once_daily"
    twice_daily = "twice_daily"
    three_times_daily = "three_times_daily"
    four_times_daily = "four_times_daily"
    every_other_day = "every_other_day"
    weekly = "weekly"
    nightly = "nightly"
    as_needed = "as_needed"
    single_dose = "single_dose"
    unknown = "unknown"


class Specificity(StrEnum):
    definite = "definite"
    suspected = "suspected"
    symptom_only = "symptom_only"


class LabUnit(StrEnum):
    mmol_per_l = "mmol/L"
    g_per_l = "g/L"
    umol_per_l = "umol/L"
    u_per_l = "U/L"
    percent = "percent"
    x10e9_per_l = "x10e9/L"
    g_per_l_hba1c = "g/mol"
    mg_per_dl = "mg/dL"
    unknown = "unknown"


class Citation(Strict):
    field: str
    utterance_ids: list[str] = Field(default_factory=list)
    quote: str | None = None


class Vitals(Strict):
    height_cm: float | None = Field(default=None, ge=20, le=250)
    weight_kg: float | None = Field(default=None, ge=1, le=400)
    temperature_c: float | None = Field(default=None, ge=25, le=45)
    systolic_bp: int | None = Field(default=None, ge=40, le=300)
    diastolic_bp: int | None = Field(default=None, ge=20, le=200)
    heart_rate: int | None = Field(default=None, ge=20, le=260)
    respiratory_rate: int | None = Field(default=None, ge=4, le=80)
    spo2_percent: float | None = Field(default=None, ge=40, le=100)


class Symptom(Strict):
    name: str
    onset_days: int | None = Field(default=None, ge=0, le=36500)
    severity: Severity | None = None
    aggravating: list[str] = Field(default_factory=list)
    relieving: list[str] = Field(default_factory=list)
    continuous: bool | None = None


class Subjective(Strict):
    chief_complaint: str | None = None
    present_illness: str | None = None
    symptoms: list[Symptom] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    medication_adherence: str | None = None


class ExamFinding(Strict):
    site: str
    finding: str
    severity: Severity | None = None
    abnormal: bool | None = None


class LabResult(Strict):
    name: str
    value: float | None = None
    unit: LabUnit | None = None
    text: str | None = None
    collected_at: str | None = None


class Objective(Strict):
    vitals: Vitals = Field(default_factory=Vitals)
    findings: list[ExamFinding] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)


class Diagnosis(Strict):
    title: str
    icd10_code: str | None = Field(default=None, pattern=ICD10_CODE_PATTERN)
    icd11_code: str | None = Field(default=None, pattern=ICD11_CODE_PATTERN)
    specificity: Specificity = Specificity.suspected
    episode_index: int | None = Field(default=None, ge=0, le=20)


class Assessment(Strict):
    summary: str | None = None
    diagnoses: list[Diagnosis] = Field(default_factory=list)


class Medication(Strict):
    trade_name: str | None = None
    ingredient: str
    dose_value: float | None = Field(default=None, gt=0, le=100000)
    dose_unit: DoseUnit | None = None
    dose_form: DoseForm | None = None
    route: Route | None = None
    frequency: Frequency | None = None
    duration_days: int | None = Field(default=None, ge=0, le=3650)
    instruction: str | None = None


class Allergy(Strict):
    substance: str
    reaction: str | None = None
    severity: Severity | None = None


class PlanItem(Strict):
    text: str
    category: str | None = None
    code: str | None = None


class Plan(Strict):
    items: list[PlanItem] = Field(default_factory=list)
    follow_up_days: int | None = Field(default=None, ge=0, le=3650)
    safety_notes: str | None = None


class EncounterRecord(Strict):
    subjective: Subjective = Field(default_factory=Subjective)
    objective: Objective = Field(default_factory=Objective)
    assessment: Assessment = Field(default_factory=Assessment)
    plan: Plan = Field(default_factory=Plan)
    medications: list[Medication] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    abstained_fields: list[str] = Field(default_factory=list)

    def cited_fields(self) -> set[str]:
        return {
            citation.field
            for citation in self.citations
            if citation.utterance_ids or citation.quote
        }

    def uncited_populated_fields(self) -> set[str]:
        return populated_field_paths(self) - self.cited_fields() - {"citations", "abstained_fields"}


def populated_field_paths(record: EncounterRecord) -> set[str]:
    paths: set[str] = set()
    _absorb(record.model_dump(mode="json"), "", paths)
    return paths


def _absorb(value: object, path: str, out: set[str]) -> None:
    if not _has_content(value):
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _absorb(child, f"{path}.{key}" if path else str(key), out)
        return
    if isinstance(value, list):
        if _is_scalar_seq(value):
            out.add(path)
        else:
            for index, child in enumerate(value):
                _absorb(child, f"{path}[{index}]", out)
        return
    out.add(path)


def _is_scalar_seq(values: list) -> bool:
    return all(not isinstance(item, (dict, list)) for item in values)


def _has_content(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, dict):
        return any(_has_content(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_content(child) for child in value)
    return True

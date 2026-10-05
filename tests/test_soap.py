import pytest
from pydantic import ValidationError

from smartmed.schemas.soap import (
    Allergy,
    Assessment,
    Citation,
    Diagnosis,
    EncounterRecord,
    Frequency,
    Medication,
    Objective,
    Plan,
    Subjective,
    Symptom,
    Vitals,
    populated_field_paths,
)


def minimal_record() -> EncounterRecord:
    return EncounterRecord(
        subjective=Subjective(
            chief_complaint="咳嗽伴低热五天",
            symptoms=[Symptom(name="咳嗽", onset_days=5, severity="moderate")],
        ),
        objective=Objective(vitals=Vitals(temperature_c=37.8, heart_rate=88)),
        assessment=Assessment(
            diagnoses=[
                Diagnosis(title="急性支气管炎", icd10_code="J20.900", specificity="definite")
            ],
        ),
        plan=Plan(follow_up_days=7),
        medications=[
            Medication(
                trade_name="阿莫西林胶囊",
                ingredient="amoxicillin",
                dose_value=500,
                dose_unit="mg",
                frequency=Frequency.three_times_daily,
                duration_days=7,
            )
        ],
        allergies=[Allergy(substance="青霉素", reaction="皮疹", severity="severe")],
        citations=[
            Citation(field="subjective.chief_complaint", utterance_ids=["u3"], quote="咳嗽五天了"),
        ],
    )


def test_full_record_round_trips():
    record = minimal_record()
    again = EncounterRecord.model_validate_json(record.model_dump_json())
    assert again == record


def test_empty_record_is_representable():
    record = EncounterRecord()
    assert record.subjective.chief_complaint is None
    assert record.objective.vitals.spo2_percent is None
    assert record.medications == []
    assert populated_field_paths(record) == set()


def test_abstention_keeps_field_null_and_marks_it():
    record = minimal_record()
    record.assessment.diagnoses[0].icd10_code = None
    record.abstained_fields.append("assessment.diagnoses[0].icd10_code")
    assert "assessment.diagnoses[0].icd10_code" not in populated_field_paths(record)
    assert "assessment.diagnoses[0].title" in populated_field_paths(record)


def test_uncited_populated_fields_flags_missing_grounding():
    record = minimal_record()
    uncited = record.uncited_populated_fields()
    assert "subjective.chief_complaint" not in uncited
    assert "medications[0].ingredient" in uncited
    assert "allergies[0].substance" in uncited


@pytest.mark.parametrize("code", ["J20.900", "I10", "E11.9", "Z00.01", "A01.00"])
def test_icd10_pattern_accepts_clinical_revision_forms(code):
    Diagnosis(title="x", icd10_code=code)


@pytest.mark.parametrize("code", ["j20.900", "J200", "J20.9000", "J2.0", "J20-900"])
def test_icd10_pattern_rejects_malformed(code):
    with pytest.raises(ValidationError):
        Diagnosis(title="x", icd10_code=code)


def test_controlled_enums_reject_free_text():
    with pytest.raises(ValidationError):
        Medication(ingredient="metformin", dose_unit="pillows")
    with pytest.raises(ValidationError):
        Symptom(name="头晕", severity="very bad")
    with pytest.raises(ValidationError):
        Medication(ingredient="metformin", frequency="3/day")


def test_numeric_bounds_reject_implausible_vitals():
    with pytest.raises(ValidationError):
        Vitals(temperature_c=99.0)
    with pytest.raises(ValidationError):
        Vitals(weight_kg=-3)
    with pytest.raises(ValidationError):
        Medication(ingredient="insulin", dose_value=0)


def test_extra_keys_are_rejected():
    payload = minimal_record().model_dump(mode="json")
    payload["doctor_signature"] = "auto"
    with pytest.raises(ValidationError):
        EncounterRecord.model_validate(payload)

import json

from jsonschema import Draft202012Validator

from smartmed.schemas import repair_instructions, strict_json_schema, validate_payload
from smartmed.schemas.json_schema import grammar_text


def walk(node, path=""):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}/{index}")


def test_schema_is_draft_2020_12_and_self_contained():
    schema = strict_json_schema()
    Draft202012Validator.check_schema(schema)
    assert "$ref" not in grammar_text()
    assert "$defs" not in schema


def test_every_object_is_closed_and_complete():
    schema = strict_json_schema()
    objects = [node for _, node in walk(schema) if "properties" in node]
    assert len(objects) >= 12
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


def test_optional_fields_are_nullable_not_absent():
    schema = strict_json_schema()
    complaint = schema["properties"]["subjective"]["properties"]["chief_complaint"]
    types = {branch["type"] for branch in complaint["anyOf"]}
    assert types == {"string", "null"}
    units = set(
        schema["properties"]["medications"]["items"]["properties"]["dose_unit"]["anyOf"][0]["enum"]
    )
    assert {"mg", "mcg", "g", "ml", "iu", "piece"} <= units


def test_grammar_text_is_stable_json():
    first = json.loads(grammar_text())
    second = json.loads(grammar_text())
    assert first == second


def test_valid_payload_has_no_errors():
    payload = {
        "subjective": {
            "chief_complaint": "头晕一周",
            "symptoms": [{"name": "头晕", "onset_days": 7}],
        },
        "citations": [{"field": "subjective.chief_complaint", "utterance_ids": ["u1"]}],
    }
    record, errors = validate_payload(payload)
    assert errors == []
    assert record is not None
    assert record.subjective.symptoms[0].onset_days == 7


def test_broken_payload_reports_paths_for_one_repair():
    payload = {
        "assessment": {
            "diagnoses": [{"title": "肺炎", "icd10_code": "J18.9", "specificity": "maybe"}]
        },
        "objective": {"vitals": {"temperature_c": 400}},
        "plan": {"follow_up_days": -1},
    }
    record, errors = validate_payload(payload)
    assert record is None
    text = repair_instructions(errors)
    assert "assessment.diagnoses[0].specificity" in text
    assert "objective.vitals.temperature_c" in text
    assert "plan.follow_up_days" in text

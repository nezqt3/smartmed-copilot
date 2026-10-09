import json

import pytest

from smartmed.annotation_review import compare, prepare
from smartmed.schemas.extraction import FIELDS, ExtractRequest, validate_extraction


def blank_annotation():
    return {field: {"status": "unknown", "value": None, "evidence": []} for field in FIELDS}


def test_short_allergy_answer_requires_adjacent_specific_question():
    answer = blank_annotation()
    answer["青霉素过敏"] = {
        "status": "negated",
        "value": None,
        "evidence": [{"turn_id": 2, "quote": "不过敏"}],
    }
    turns = ExtractRequest.model_validate(
        {"turns": [
            {"turn_id": 1, "speaker": "doctor", "text": "对青霉素过敏吗？"},
            {"turn_id": 2, "speaker": "patient", "text": "不过敏。"},
        ]}
    ).turns
    validate_extraction(answer, turns)
    turns[0].text = "对布洛芬过敏吗？"
    with pytest.raises(ValueError, match="青霉素过敏"):
        validate_extraction(answer, turns)
    turns[0].text = "对青霉素和布洛芬过敏吗？"
    with pytest.raises(ValueError, match="青霉素过敏"):
        validate_extraction(answer, turns)


def test_two_reviewers_generate_explicit_disagreement(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps([{
            "id": "c1",
            "turns": [{"turn_id": 1, "speaker": "patient", "text": "我咳嗽。"}],
            "gold": blank_annotation(),
        }], ensure_ascii=False),
        encoding="utf-8",
    )
    directory = tmp_path / "reviews"
    prepare(source, directory)
    first = directory / "review_A.json"
    second = directory / "review_B.json"
    a = json.loads(first.read_text(encoding="utf-8"))
    b = json.loads(second.read_text(encoding="utf-8"))
    assert "gold" not in a["cases"][0]
    a["reviewer"], b["reviewer"] = "Reviewer A", "Reviewer B"
    a["cases"][0]["annotation"] = blank_annotation()
    b["cases"][0]["annotation"] = blank_annotation()
    b["cases"][0]["annotation"]["咳嗽"] = {
        "status": "present",
        "value": "咳嗽",
        "evidence": [{"turn_id": 1, "quote": "咳嗽"}],
    }
    first.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    second.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "differences.json"
    compare(source, first, second, output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["exact_agreement"] == 5
    assert report["differences"][0]["field"] == "咳嗽"
    assert report["differences"][0]["resolution"] is None
    assert report["state"] == "awaiting_adjudication"

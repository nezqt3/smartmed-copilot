import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from smartmed.backend_settings import BackendSettings
from smartmed.outpatient_compact import CompactDocument, expand, spans
from smartmed.outpatient_model import OutpatientExtractor
from smartmed.schemas.outpatient import OutpatientRequest


def request():
    return OutpatientRequest(
        transcript_reviewed=True,
        patient={"name": "Secret patient name"},
        turns=[
            {"turn_id": 7, "speaker": "patient", "text": "咳嗽五天。没有发热。"},
            {"turn_id": 9, "speaker": "doctor", "text": "考虑呼吸道感染。建议复诊。"},
            {"turn_id": 12, "speaker": "patient", "text": "以前说没有过敏。青霉素后出过皮疹。"},
        ],
    )


def test_expansion_preserves_sources_unknown_and_conflict():
    req = request()
    data = {
        "f": [[0, 0, "p"], [1, 1, "n"], [7, 2, "u"], [8, 3, "p"], [3, 4, "n"], [3, 5, "p"]],
        "c": [3],
    }
    compact = CompactDocument.model_validate_json(json.dumps(data), context={"request": req})
    doc = expand(compact.model_dump(), req)
    assert doc.present_illness.items[0].assertion == "negated"
    assert doc.assessment.items[0].reported_by == "doctor"
    assert doc.assessment.items[0].evidence[0].turn_id == 9
    assert doc.allergy_history.status == "conflict"
    assert doc.medication_history.status == "unknown"
    assert not doc.plan.reviewed
    assert all(
        span["text"] in next(t.text for t in req.turns if t.turn_id == span["turn_id"])
        for span in spans(req)
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"f": [[7, 0, "p"]], "c": []},  # patient cannot supply a doctor diagnosis
        {"f": [[0, 2, "p"]], "c": []},  # doctor cannot supply patient history
        {"f": [[7, 2, "p"]], "c": []},  # tentative assessment cannot become definite
        {"f": [[0, 999, "p"]], "c": []},
        {"f": [[0, -1, "p"]], "c": []},
        {"f": [[0, 0, "p"], [0, 0, "n"]], "c": []},
        {"f": [], "c": [3]},
        {"f": [], "c": [], "reviewed": True},
    ],
)
def test_compact_rejects_ungrounded_or_unsafe_output(payload):
    with pytest.raises((ValidationError, ValueError)):
        CompactDocument.model_validate_json(json.dumps(payload), context={"request": request()})


def test_compact_instructor_path_and_phase_timings():
    def transport(req):
        if req.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3.5:4b", "digest": "fixture"}]}
            )
        payload = json.loads(req.content)
        assert set(payload["format"]["properties"]) == {*(f"s{i}" for i in range(9)), "c"}
        assert "Secret patient name" not in json.dumps(payload["messages"])
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {**{f"s{i}": [[2, "u"]] if i == 7 else [] for i in range(9)}, "c": []}
                    )
                },
                "load_duration": 10,
                "prompt_eval_duration": 20,
                "eval_duration": 30,
            },
        )

    async def run():
        ex = OutpatientExtractor(
            BackendSettings(outpatient_format="spans", outpatient_plan_audit=False),
            transport=httpx.MockTransport(transport),
        )
        try:
            result = await ex.extract(request())
            assert result.document.assessment.items[0].text == "考虑呼吸道感染。"
            assert result.metadata["attempts"][0]["eval_duration_ns"] == 30
            assert result.metadata["generation_format"] == "spans"
        finally:
            await ex.close()

    asyncio.run(run())


def test_schema_prevents_wrong_speakers_and_doctor_questions():
    from smartmed.outpatient_compact import GroupedDocument, grounded_schema

    req = request()
    schema = grounded_schema(GroupedDocument.model_json_schema(), req)
    assert set(schema["properties"]["s0"]["items"]["prefixItems"][0]["enum"]) == {0, 1, 4, 5}
    assert set(schema["properties"]["s7"]["items"]["prefixItems"][0]["enum"]) == {2, 3}
    for section in range(9):
        assert schema["properties"][f"s{section}"]["items"]["maxItems"] == 2


def test_cannot_remove_uncertainty_from_pneumonia_assessment():
    from smartmed.outpatient_compact import GroupedDocument

    req = OutpatientRequest(
        transcript_reviewed=True,
        turns=[{"turn_id": 1, "speaker": "doctor", "text": "肺炎还不能排除。"}],
    )
    payload = {**{f"s{i}": [[0, "p"]] if i == 7 else [] for i in range(9)}, "c": []}
    with pytest.raises(ValidationError):
        GroupedDocument.model_validate_json(json.dumps(payload), context={"request": req})


def test_separate_plan_pass_restores_original_doctor_statement():
    from smartmed.outpatient_compact import GroupedDocument, PlanSelection

    calls = []

    def transport(req):
        if req.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3.5:4b", "digest": "fixture"}]}
            )
        payload = json.loads(req.content)
        fields = set(payload["format"]["properties"])
        calls.append(fields)
        if fields == {"s8", "c"}:
            content = {"s8": [[3, "p"]], "c": []}
            assert "Secret patient name" not in json.dumps(payload["messages"])
            assert "咳嗽五天" not in payload["messages"][1]["content"]
        else:
            content = {**{f"s{i}": [[2, "u"]] if i == 7 else [] for i in range(9)}, "c": []}
        return httpx.Response(
            200,
            json={"done": True, "done_reason": "stop", "message": {"content": json.dumps(content)}},
        )

    async def run():
        ex = OutpatientExtractor(BackendSettings(), transport=httpx.MockTransport(transport))
        try:
            result = await ex.extract(request())
            assert result.document.plan.items[0].text == "建议复诊。"
            assert [a["stage"] for a in result.metadata["attempts"]] == ["extraction", "plan_check"]
            assert result.document.assessment.items[0].assertion == "uncertain"
            assert not result.document.plan.reviewed
        finally:
            await ex.close()

    asyncio.run(run())
    assert len(calls) == 2
    assert set(GroupedDocument.model_fields) != set(PlanSelection.model_fields)


def test_plan_pass_cannot_drop_existing_fact_or_clear_conflict():
    from smartmed.outpatient_compact import merge_plan

    req = request()
    first = expand({"s8": [[3, "p"]], "c": [8]}, req).plan
    second = expand({"s8": [], "c": []}, req).plan
    result = merge_plan(first, second)
    assert result.status == "conflict"
    assert result.items[0].text == "建议复诊。"
    first = expand({"s8": [[3, "p"]], "c": []}, req).plan
    second = expand({"s8": [[3, "n"]], "c": []}, req).plan
    result = merge_plan(first, second)
    assert result.status == "conflict"
    assert len(result.items) == 2

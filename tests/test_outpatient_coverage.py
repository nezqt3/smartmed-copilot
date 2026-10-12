"""Regression guards for the audio_dev_01 read-through: known outpatient-coverage gaps.

These assert the deterministic extraction/plan layer only, so a real model can no longer
silently drop the plan, the visit reason, or the negative-temperature fact.
"""

import asyncio
import json

import httpx

from smartmed.backend_settings import BackendSettings
from smartmed.outpatient_compact import (
    GroupedDocument,
    ensure_coverage,
    expand,
    grounded_schema,
    merge_plan,
    remove_repeated_selections,
    spans,
)
from smartmed.outpatient_model import OutpatientExtractor
from smartmed.schemas.outpatient import OutpatientRequest

TURNS = [
    (1, "doctor", "你好，今天哪里不舒服？请从最早出现的症状说起。"),
    (2, "patient", "我从三天前开始咳嗽，起初只是偶尔咳，现在晚上也会咳。"),
    (3, "doctor", "这三天有没有发热？您量过体温吗？"),
    (4, "patient", "没有发热。"),
    (5, "patient", "昨天晚上量过体温，数字我现在记不清。"),
    (6, "doctor", "咳嗽的时候有没有痰？白天和晚上有什么区别？"),
    (7, "patient", "有一点痰，白天不太明显，躺下以后咳得更多。"),
    (8, "doctor", "在来这里之前，您已经吃过什么药吗？"),
    (9, "patient", "昨天吃了布洛芬一次，包装上写的是二百毫克。"),
    (10, "doctor", "您知道自己有没有青霉素过敏吗？"),
    (11, "patient", "青霉素过敏情况我不清楚，以前没有专门检查过。"),
    (12, "doctor", "我会先记录您说的情况，药盒如果还在请带来核对。"),
    (13, "patient", "好的，我回家找一下药盒；今天主要是想确认咳嗽的原因。"),
]


def request():
    return OutpatientRequest(
        transcript_reviewed=True,
        turns=[
            {"turn_id": turn_id, "speaker": speaker, "text": text}
            for turn_id, speaker, text in TURNS
        ],
    )


def source_index(fragment, speaker=None):
    for span in spans(request()):
        if fragment in span["text"] and (speaker is None or span["speaker"] == speaker):
            return span["i"]
    raise AssertionError(f"no span contains {fragment!r} from {speaker}")


def allowed(section):
    schema = grounded_schema(GroupedDocument.model_json_schema(), request())
    field = schema["properties"][f"s{section}"]
    if field.get("maxItems") == 0:
        return set()
    return set(field["items"]["prefixItems"][0]["enum"])


def test_doctor_followup_instruction_is_eligible_for_plan():
    assert source_index("请带来核对", "doctor") in allowed(8)


def test_visit_reason_is_eligible_for_chief_complaint():
    assert source_index("想确认咳嗽的原因", "patient") in allowed(0)


def test_negative_temperature_and_uncertain_recall_are_eligible():
    assert source_index("没有发热", "patient") in allowed(1)
    assert source_index("记不清", "patient") in allowed(1)


def test_unpunctuated_fever_and_unknown_number_have_separate_assertions():
    req = OutpatientRequest(
        transcript_reviewed=True,
        turns=[{"turn_id": 1, "speaker": "patient",
                "text": "没有发热昨天晚上量过体温数字我现在记不清"}],
    )
    empty = expand({"c": []}, req)
    result = ensure_coverage(empty, req)
    assert any("没有发热" in item.text and item.assertion == "negated"
               for item in result.present_illness.items)
    assert any("记不清" in item.text and item.assertion == "uncertain"
               for item in result.present_illness.items)


def test_doctor_statement_cannot_leak_into_present_illness():
    instruction = source_index("请带来核对", "doctor")
    symptom = source_index("三天前开始咳嗽", "patient")
    assert instruction not in allowed(1)
    assert symptom in allowed(0)
    assert symptom in allowed(1)


def test_plan_merge_restores_instruction_the_main_pass_missed():
    req = request()
    instruction = source_index("请带来核对", "doctor")
    empty_plan = expand({**{f"s{i}": [] for i in range(9)}, "c": []}, req).plan
    recovered = expand({"s8": [[instruction, "p"]], "c": []}, req).plan
    merged = merge_plan(empty_plan, recovered)
    assert merged.status == "documented"
    assert any("请带来核对" in item.text for item in merged.items)


def test_identical_model_selections_do_not_invalidate_the_plan():
    source = source_index("请带来核对", "doctor")
    normalized, changes = remove_repeated_selections(
        {"s8": [[source, "p"], [source, "p"]], "c": []}
    )
    assert normalized["s8"] == [[source, "p"]]
    assert changes == [{"section": "s8", "source_span": source}]


def test_unpunctuated_doctor_question_is_excluded_from_plan_enum():
    req = OutpatientRequest(
        transcript_reviewed=True,
        turns=[
            {"turn_id": 1, "speaker": "doctor", "text": "你好今天哪里不舒服"},
            {"turn_id": 2, "speaker": "doctor", "text": "我会先记录您说的情况请带来核对"},
        ],
    )
    source = spans(req)
    question = next(span["i"] for span in source if "哪里" in span["text"])
    instruction = next(span["i"] for span in source if "请带来核对" in span["text"])
    field = grounded_schema(GroupedDocument.model_json_schema(), req)["properties"]["s8"]
    plan_enum = set(field["items"]["prefixItems"][0]["enum"])
    assert question not in plan_enum
    assert instruction in plan_enum


def test_full_pipeline_produces_non_empty_plan_for_audio_dev_01():
    req = request()
    symptom = source_index("三天前开始咳嗽", "patient")
    negated = source_index("没有发热", "patient")

    def respond(rq):
        if rq.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3.5:4b", "digest": "fixture"}]}
            )
        fields = set(json.loads(rq.content)["format"]["properties"])
        if fields == {"s8", "c"}:
            content = {"s8": [], "c": []}
        else:
            content = {f"s{i}": [] for i in range(9)}
            content["s0"] = [[symptom, "p"]]
            content["s1"] = [[symptom, "p"], [negated, "u"]]
            content["c"] = []
        return httpx.Response(
            200,
            json={"done": True, "done_reason": "stop", "message": {"content": json.dumps(content)}},
        )

    async def run():
        ex = OutpatientExtractor(BackendSettings(), transport=httpx.MockTransport(respond))
        try:
            result = await ex.extract(req)
            assert result.document.plan.status == "documented"
            assert any("请带来核对" in item.text for item in result.document.plan.items)
            complaint = {item.text for item in result.document.chief_complaint.items}
            history = {item.text for item in result.document.present_illness.items}
            assert any("想确认咳嗽的原因" in text for text in complaint)
            assert not complaint & history
            assert any("没有发热" in item.text and item.assertion == "negated"
                       for item in result.document.present_illness.items)
            assert any("记不清" in item.text and item.assertion == "uncertain"
                       for item in result.document.present_illness.items)
        finally:
            await ex.close()

    asyncio.run(run())

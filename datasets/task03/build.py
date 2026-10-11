"""Explicit assistant-authored synthetic candidates; never human annotation."""

import hashlib
import json
from pathlib import Path

from smartmed.schemas.extraction import FIELDS

ROOT = Path(__file__).resolve().parent
# Field indices follow FIELDS. Strings are present values, None denotes explicit negation.
# Unlisted fields are unknown. No inference of doses or physician recommendations.
SPECS = [
    (
        "我发热，伴有干咳，症状持续四天。我对青霉素过敏，已经服用了布洛芬，每次200毫克。",
        {0: "发热", 1: "干咳", 2: "四天", 3: "对青霉素过敏", 4: "布洛芬", 5: "200毫克"},
    ),
    ("我没有发热，也没有咳嗽，还没有用药。", {0: None, 1: None, 4: None}),
    ("我咳嗽持续五天，没有发热。", {0: None, 1: "咳嗽", 2: "五天"}),
    (
        "我对青霉素不过敏。昨天已经吃了对乙酰氨基酚，一次500毫克。",
        {3: None, 4: "对乙酰氨基酚", 5: "500毫克"},
    ),
    ("我只有鼻塞，尚不清楚是否发热。", {}),
    ("我买了阿莫西林，准备晚上再吃，现在没有用药。", {4: None}),
    ("我发热两天，药的名字和剂量都记不清。", {0: "发热", 2: "两天"}),
    ("我没有咳嗽，发热持续三天。", {0: "发热", 1: None, 2: "三天"}),
    ("我已经服用了头孢氨苄，剂量是250毫克，但不清楚青霉素过敏史。", {4: "头孢氨苄", 5: "250毫克"}),
    ("我咳嗽一周，吃过布洛芬，剂量忘了。", {1: "咳嗽", 2: "一周", 4: "布洛芬"}),
    ("我从未使用过青霉素，不知道自己是否过敏。", {}),
    ("阿莫西林是医生建议的，我尚未服用，目前没有服用任何药物。", {4: None}),
    ("我已经吃了布洛芬和对乙酰氨基酚，但记不清各自用了多少。", {4: "布洛芬和对乙酰氨基酚"}),
    ("我说不清是否发热，也不确定有没有咳嗽。", {}),
    ("我已经吃了阿莫西林两粒，每粒多少毫克不清楚。", {4: "阿莫西林", 5: "两粒"}),
    ("我今天没有吃药，但昨天吃了布洛芬200毫克。", {4: "布洛芬", 5: "200毫克"}),
    ("我喝了300毫升水，排队号码是18，已经服用了布洛芬，但剂量忘了。", {4: "布洛芬"}),
    ("我对青霉素过敏。我没有用药。", {3: "对青霉素过敏", 4: None}),
    ("我发热，不是三天，刚才说错了，发热持续六天。", {0: "发热", 2: "六天"}),
    ("我一会儿说咳嗽两天，一会儿说五天，实在记不清开始时间。", {1: "咳嗽"}),
    (
        "我从前天开始干咳，持续两天，已服用头孢氨苄500毫克。",
        {1: "干咳", 2: "两天", 4: "头孢氨苄", 5: "500毫克"},
    ),
    ("我没有发热，只是干咳持续八天，没吃药。", {0: None, 1: "干咳", 2: "八天", 4: None}),
    (
        "我对青霉素没有过敏，已服用了对乙酰氨基酚250毫克。",
        {3: None, 4: "对乙酰氨基酚", 5: "250毫克"},
    ),
    ("我只是来问药价，目前没有用任何药物。", {4: None}),
    ("我发热十天，还没有服用任何药物。", {0: "发热", 2: "十天", 4: None}),
    (
        "我咳嗽持续九天，对青霉素过敏，但未使用任何药物。",
        {1: "咳嗽", 2: "九天", 3: "对青霉素过敏", 4: None},
    ),
    ("我吃过头孢氨苄一粒，具体规格忘记了。", {4: "头孢氨苄", 5: "一粒"}),
    ("我没有咳嗽，是否发热不知道，青霉素是否过敏也不知道。", {1: None}),
    (
        "我曾经对青霉素过敏，昨天已经吃了阿莫西林250毫克。",
        {3: "对青霉素过敏", 4: "阿莫西林", 5: "250毫克"},
    ),
    ("我出现发热和咳嗽，两个症状都持续七天。", {0: "发热", 1: "咳嗽", 2: "七天"}),
    ("我没用过青霉素，但是不清楚是否过敏；已经服用了布洛芬400毫克。", {4: "布洛芬", 5: "400毫克"}),
    ("我想明天服用头孢氨苄，今天没有吃任何药。", {4: None}),
    ("我吃了布洛芬，盒子上写每片200毫克，但忘了吃了几片。", {4: "布洛芬"}),
    ("我觉得咳嗽可能是两周，也可能是三周，无法确认。", {1: "咳嗽"}),
    ("我没有发热，也没吃药，不知道青霉素过敏情况。", {0: None, 4: None}),
    (
        "我刚才说服用了阿莫西林，那是说错了，实际已经服用的是布洛芬100毫克。",
        {4: "布洛芬", 5: "100毫克"},
    ),
    (
        "医生说通常用500毫克，我实际服用的对乙酰氨基酚只有250毫克。",
        {4: "对乙酰氨基酚", 5: "250毫克"},
    ),
    (
        "我没有咳嗽，发热持续十二小时，已经服用布洛芬一片。",
        {0: "发热", 1: None, 2: "十二小时", 4: "布洛芬", 5: "一片"},
    ),
    ("我已经服用对乙酰氨基酚和头孢氨苄，具体每种药的剂量不清楚。", {4: "对乙酰氨基酚和头孢氨苄"}),
    (
        "我没有发热，只有咳嗽，咳嗽持续十四天，尚未服用任何药物。",
        {0: None, 1: "咳嗽", 2: "十四天", 4: None},
    ),
]


def build():
    rows = []
    for index, (text, specified) in enumerate(SPECS, 1):
        turns = [{"turn_id": 1, "speaker": "patient", "text": text}]
        # A family member's medical history must not become the patient's history.
        if index == 14:
            turns.insert(
                0,
                {
                    "turn_id": 2,
                    "speaker": "third_party",
                    "text": "我是他的哥哥，我对青霉素过敏，已经吃了阿莫西林500毫克。",
                },
            )
        gold = {f: {"status": "unknown", "value": None, "evidence": []} for f in FIELDS}
        for field_index, value in specified.items():
            gold[FIELDS[field_index]] = {
                "status": "negated" if value is None else "present",
                "value": value,
                "evidence": [{"turn_id": 1, "quote": text}],
            }
        rows.append(
            {
                "id": f"task03_{index:02d}",
                "dialogue_group_id": f"task03_dialogue_{index:02d}",
                "split": "development" if index <= 20 else "heldout_candidate",
                "source_id": "smartmed_synthetic_task03_v1",
                "source_record_id": f"synthetic_{index:02d}",
                "source_version": "task03.candidate.v1",
                "human_reviewed": False,
                "clinical_reviewed": False,
                "turns": turns,
                "gold": gold,
            }
        )
    for split in ("development", "heldout_candidate"):
        path = ROOT / f"{split}.json"
        path.write_text(
            json.dumps([r for r in rows if r["split"] == split], ensure_ascii=False, indent=2)
            + "\n"
        )
    manifest = {
        "dataset_version": "task03.candidate.v1",
        "created_on": "2026-10-09",
        "contract_version": "extraction.v2",
        "state": "candidate_pending_two_human_reviews",
        "model_evaluated": False,
        "clinically_validated": False,
        "files": {
            s + ".json": {
                "cases": 20,
                "sha256": hashlib.sha256((ROOT / (s + ".json")).read_bytes()).hexdigest(),
            }
            for s in ("development", "heldout_candidate")
        },
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    build()

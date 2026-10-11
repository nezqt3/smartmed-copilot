"""Local synthetic smoke benchmark; not a clinical accuracy evaluation."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from smartmed.backend_settings import BackendSettings
from smartmed.outpatient_model import OutpatientExtractor
from smartmed.schemas.outpatient import OutpatientRequest

ROOT = Path(__file__).resolve().parents[2]
CHECKS = [
    ("chief_complaint", "咳嗽", None),
    ("present_illness", "37.8", "present"),
    ("present_illness", "不确定是不是血", "uncertain"),
    ("present_illness", "先是喉咙痛", "present"),
    ("past_history", "高血压", None),
    ("past_history", "没有做过手术", None),
    ("medication_history", "氨氯地平5毫克", None),
    ("medication_history", "不记得一粒多少毫克", "uncertain"),
    ("medication_history", "名字忘了", "uncertain"),
    ("medication_history", "量也没看清", "uncertain"),
    ("allergy_history", "皮疹", None),
    ("physical_examination", "146/88", None),
    ("physical_examination", "97%", None),
    ("physical_examination", "未闻及明显湿啰音", None),
    ("investigations", "白细胞不高", "present"),
    ("assessment", "肺炎还不能排除", "uncertain"),
    ("plan", "不要再自行服用阿莫西林", None),
    ("plan", "胸部X线", None),
    ("plan", "先不决定静脉输液", None),
    ("plan", "呼吸困难", None),
    ("plan", "最迟两天", None),
]


def assess(document):
    results = {}
    for section, text, assertion in CHECKS:
        results[f"{section}:{text}"] = any(
            text in item["text"] and (assertion is None or item["assertion"] == assertion)
            for item in document[section]["items"]
        )
    results["allergy_conflict"] = document["allergy_history"]["status"] == "conflict"
    results["no_relative_asthma"] = not any(
        "我自己有哮喘" in item["text"]
        for section in ("past_history", "present_illness")
        for item in document[section]["items"]
    )
    results["no_requested_azithromycin_as_taken"] = not any(
        "阿奇霉素" in item["text"] for item in document["medication_history"]["items"]
    )
    return results


async def main(args):
    req = OutpatientRequest.model_validate(json.loads((ROOT / args.input).read_text()))
    ex = OutpatientExtractor(
        BackendSettings(
            model=args.model,
            outpatient_plan_audit=args.plan_audit,
            outpatient_format=args.format,
            context_tokens=args.context,
            repair_attempts=args.retries,
            outpatient_timeout_s=240,
        )
    )
    raws = []

    async def capture(response):
        if response.request.url.path == "/api/chat":
            await response.aread()
            raws.append(response.json())

    ex.http.event_hooks = {"response": [capture]}
    started = time.monotonic()
    out = {
        "variant": args.format,
        "model": args.model,
        "context": args.context,
        "input": args.input,
        "turns": len(req.turns),
        "input_characters": sum(len(t.text) for t in req.turns),
    }
    try:
        result = await ex.extract(req)
        out.update(valid=True, document=result.document.model_dump(), metadata=result.metadata)
        if "realistic" in args.input:
            out["checks"] = assess(out["document"])
    except Exception as error:
        out.update(valid=False, error=type(error).__name__)
    finally:
        await ex.close()
    out["wall_s"] = round(time.monotonic() - started, 3)
    out["raw"] = raws
    for raw in raws:
        raw.pop("context", None)
    path = ROOT / "experiments/03_outpatient_latency" / (args.name + ".json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in out.items() if k not in ("document", "raw")}, ensure_ascii=False
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-audit", action="store_true")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--format", choices=["full", "spans"], default="spans")
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--input", default="examples/outpatient_realistic_synthetic_zh.json")
    parser.add_argument("--name", required=True)
    asyncio.run(main(parser.parse_args()))

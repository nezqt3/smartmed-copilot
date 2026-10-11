"""Blind annotation templates and agreement checks; never fabricate human reviews."""

import argparse
import json
from pathlib import Path

from smartmed.schemas.extraction import FIELDS, Turn, validate_extraction

ROOT = Path(__file__).resolve().parent


def template(cases):
    return [
        {
            "id": c["id"],
            "turns": c["turns"],
            "reviewer": "",
            "reviewed_on": "",
            "document": {field: None for field in FIELDS},
        }
        for c in cases
    ]


def agreement(left, right, cases):
    expected = {c["id"]: c for c in cases}
    maps = [{c["id"]: c for c in rows} for rows in (left, right)]
    if any(
        len(rows) != len(mapping) or set(mapping) != set(expected)
        for rows, mapping in zip((left, right), maps, strict=True)
    ):
        raise ValueError("Each annotator must submit each case exactly once")
    matching_status = matching_value = total = 0
    disagreements = []
    for case_id, case in expected.items():
        entries = [mapping[case_id] for mapping in maps]
        for entry in entries:
            if not entry["reviewer"].strip() or not entry["reviewed_on"].strip():
                raise ValueError("Reviewer and review date must be filled in")
            if entry["turns"] != case["turns"]:
                raise ValueError("Do not alter the original transcript")
            validate_extraction(entry["document"], [Turn(**t) for t in case["turns"]])
        for field in FIELDS:
            a, b = (e["document"][field] for e in entries)
            status_match = a["status"] == b["status"]
            value_match = status_match and a["value"] == b["value"]
            matching_status += status_match
            matching_value += value_match
            total += 1
            if a != b:
                disagreements.append({"id": case_id, "field": field, "left": a, "right": b})
    return {
        "kind": "annotation_agreement",
        "cases": len(cases),
        "fields": total,
        "status_agreement": matching_status / total if total else None,
        "status_value_agreement": matching_value / total if total else None,
        "disagreements": disagreements,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=ROOT / "cases_frozen.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--template", type=Path)
    mode.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if args.template:
        args.template.write_text(json.dumps(template(cases), ensure_ascii=False, indent=2) + "\n")
    else:
        if args.output is None:
            parser.error("--compare requires --output")
        result = agreement(*(json.loads(p.read_text()) for p in args.compare), cases)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

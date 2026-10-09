"""Prepare blind annotation sheets and compare two completed human reviews."""

import argparse
import json
from collections import Counter
from pathlib import Path

from smartmed.schemas.extraction import (
    CONTRACT_VERSION,
    FIELDS,
    ExtractRequest,
    validate_extraction,
)

SPEC_VERSION = "annotation.v1"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(source: Path, output_dir: Path):
    cases = read_json(source)
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Case IDs must be unique")
    for case in cases:
        ExtractRequest.model_validate({"turns": case["turns"]})
    rows = [
        {
            "id": case["id"],
            "turns": case["turns"],
            "annotation": {
                field: {"status": None, "value": None, "evidence": []} for field in FIELDS
            },
        }
        for case in cases
    ]
    for reviewer in ("A", "B"):
        path = output_dir / f"review_{reviewer}.json"
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
        write_json(
            path,
            {
                "spec_version": SPEC_VERSION,
                "contract_version": CONTRACT_VERSION,
                "reviewer": "",
                "cases": rows,
            },
        )


def checked_review(path: Path, expected_ids: set[str]):
    data = read_json(path)
    if data.get("spec_version") != SPEC_VERSION or data.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"{path}: wrong specification or contract version")
    if not isinstance(data.get("reviewer"), str) or not data["reviewer"].strip():
        raise ValueError(f"{path}: reviewer name is required")
    rows = data.get("cases")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: cases must be a list")
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected_ids:
        raise ValueError(f"{path}: missing, extra or duplicate case IDs")
    by_id = {}
    for row in rows:
        try:
            turns = ExtractRequest.model_validate({"turns": row["turns"]}).turns
            annotation = validate_extraction(row["annotation"], turns)
        except Exception as exc:
            raise ValueError(f"{path}: invalid annotation for {row['id']}: {exc}") from exc
        by_id[row["id"]] = (row["turns"], annotation.model_dump(mode="json"))
    return data["reviewer"].strip(), by_id


def compare(source: Path, first: Path, second: Path, output: Path):
    cases = read_json(source)
    source_by_id = {case["id"]: case["turns"] for case in cases}
    if len(source_by_id) != len(cases):
        raise ValueError("Source contains duplicate case IDs")
    name_a, review_a = checked_review(first, set(source_by_id))
    name_b, review_b = checked_review(second, set(source_by_id))
    if name_a == name_b:
        raise ValueError("Two distinct reviewers are required")
    differences = []
    status_pairs = Counter()
    for case in cases:
        case_id = case["id"]
        turns_a, fields_a = review_a[case_id]
        turns_b, fields_b = review_b[case_id]
        if turns_a != source_by_id[case_id] or turns_b != source_by_id[case_id]:
            raise ValueError(f"{case_id}: source turns were changed")
        for field in FIELDS:
            a, b = fields_a[field], fields_b[field]
            status_pairs[(a["status"], b["status"])] += 1
            if a != b:
                differences.append(
                    {
                        "case_id": case_id,
                        "field": field,
                        "review_A": a,
                        "review_B": b,
                        "resolution": None,
                        "adjudicator": None,
                        "reason": None,
                    }
                )
    write_json(
        output,
        {
            "spec_version": SPEC_VERSION,
            "reviewers": [name_a, name_b],
            "case_count": len(cases),
            "field_count": len(cases) * len(FIELDS),
            "exact_agreement": len(cases) * len(FIELDS) - len(differences),
            "status_pairs": [
                {"A": a, "B": b, "count": n}
                for (a, b), n in sorted(status_pairs.items())
            ],
            "differences": differences,
            "state": "awaiting_adjudication" if differences else "agreed_pending_final_review",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "compare"))
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("experiments/02_model_comparison/cases_test.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first", type=Path)
    parser.add_argument("--second", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source, args.output)
    else:
        if args.first is None or args.second is None:
            parser.error("compare requires --first and --second")
        compare(args.source, args.first, args.second, args.output)


if __name__ == "__main__":
    main()

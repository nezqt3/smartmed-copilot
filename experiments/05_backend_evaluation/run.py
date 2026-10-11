"""Measure the production API on frozen synthetic data; never a clinical benchmark."""

import argparse
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from smartmed.api import create_app
from smartmed.auth import AuthStore
from smartmed.backend_settings import BackendSettings
from smartmed.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from smartmed.schemas.extraction import FIELDS

ROOT = Path(__file__).resolve().parent


def metrics(records, cases):
    exact = correct = positive = nonpositive = false_positive = false_negative = 0
    grounded = populated = 0
    corrections = []
    for record, case in zip(records, cases, strict=True):
        answer = record.get("document", {})
        source = {t["turn_id"]: t for t in case["turns"]}
        edits = 0
        for field in FIELDS:
            gold = case["gold"][field]
            fact = answer.get(field, {})
            match = (fact.get("status"), fact.get("value")) == (gold["status"], gold["value"])
            exact += match
            correct += fact.get("status") == gold["status"]
            edits += not match
            positive += gold["status"] == "present"
            nonpositive += gold["status"] != "present"
            false_positive += gold["status"] != "present" and fact.get("status") == "present"
            false_negative += gold["status"] == "present" and fact.get("status") != "present"
            if fact.get("status") in {"present", "negated"}:
                populated += 1
                evidence = fact.get("evidence", [])
                valid = bool(evidence) and all(
                    e["turn_id"] in source
                    and source[e["turn_id"]]["speaker"] == "patient"
                    and e["quote"] in source[e["turn_id"]]["text"]
                    for e in evidence
                )
                if fact["status"] == "present":
                    valid = valid and any(fact["value"] in e["quote"] for e in evidence)
                grounded += valid
        if answer:
            corrections.append(edits)
    fields = len(cases) * len(FIELDS)
    return {
        "cases": len(cases),
        "successful_cases": len(corrections),
        "field_count": fields,
        "status_accuracy": correct / fields if fields else None,
        "exact_status_value": exact / fields if fields else None,
        "grounded_populated_fields": grounded,
        "populated_fields": populated,
        "grounding_rate": grounded / populated if populated else None,
        "false_positive_fields": false_positive,
        "nonpositive_gold_fields": nonpositive,
        "false_positive_rate": false_positive / nonpositive if nonpositive else None,
        "false_negative_fields": false_negative,
        "positive_gold_fields": positive,
        "false_negative_rate": false_negative / positive if positive else None,
        "simulated_field_corrections_mean": sum(corrections) / len(corrections)
        if corrections
        else None,
        "workflow_passes": sum(r.get("workflow_passed", False) for r in records),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["qwen3.5:4b"])
    parser.add_argument("--cases", type=Path, default=ROOT / "cases_frozen.json")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    raw = args.cases.read_bytes()
    cases = json.loads(raw)
    if args.limit:
        cases = cases[: args.limit]
    out = ROOT / "results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    summary = {
        "kind": "production_backend_synthetic_regression",
        "human_reviewed": False,
        "clinical_validation": False,
        "prompt_version": PROMPT_VERSION,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "source_sha256": {
            str(p.relative_to(ROOT.parents[1])): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT.parents[1] / "src/smartmed").rglob("*.py"))
        },
        "models": {},
        "complete": False,
    }
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2))
    for model in args.models:
        folder = out / model.replace(":", "_").replace("/", "_")
        folder.mkdir()
        settings = BackendSettings(
            model=model,
            database=folder / "drafts.db",
            auth_database=folder / "staff.db",
            timeout_s=120,
        )
        password = secrets.token_urlsafe(24)
        AuthStore(settings.auth_database).add_staff("synthetic-evaluation", password)
        records = []
        with TestClient(create_app(settings)) as client:
            token = client.post(
                "/v1/auth/login",
                json={
                    "staff_id": "synthetic-evaluation",
                    "passcode": password,
                },
            ).json()["access_token"]
            client.headers["Authorization"] = "Bearer " + token
            for case in cases:
                start = time.monotonic()
                response = client.post("/v1/drafts", json={"turns": case["turns"]})
                record = {
                    "id": case["id"],
                    "http_status": response.status_code,
                    "elapsed_s": round(time.monotonic() - start, 3),
                }
                if response.status_code == 201:
                    draft = response.json()
                    url = "/v1/drafts/" + draft["id"]
                    record["document"] = draft["document"]
                    record["model_metadata"] = draft["model_metadata"]
                    blocked = client.get(url + "/export").status_code == 409
                    # Apply frozen references as a simulated edit, NOT a physician review.
                    edited = client.put(url, json={"expected_version": 1, "document": case["gold"]})
                    safety = client.get(url + "/safety").json()
                    confirmed = client.post(
                        url + "/confirm",
                        json={
                            "expected_version": 2,
                            "reviewed": True,
                            "acknowledged_alerts": safety["required_acknowledgements"],
                        },
                    )
                    exported = client.get(url + "/export")
                    history = client.get(url + "/history").json()
                    deleted = client.delete(url + "?expected_version=3")
                    record["workflow_passed"] = (
                        blocked
                        and edited.status_code == confirmed.status_code == 200
                        and exported.status_code == 200
                        and deleted.status_code == 204
                        and client.get(url).status_code == 404
                        and [h["action"] for h in history] == ["generated", "edited", "confirmed"]
                    )
                else:
                    record["error"] = response.json()
                records.append(record)
                (folder / "records.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2)
                )
                print(model, case["id"], record["http_status"], record["elapsed_s"], flush=True)
        summary["models"][model] = metrics(records, cases)
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    summary["complete"] = True
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Saved:", out, flush=True)


if __name__ == "__main__":
    main()

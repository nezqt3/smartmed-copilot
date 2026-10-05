"""Real API regression smoke on old cases. NOT a new independent benchmark."""

import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from smartmed.api import create_app
from smartmed.backend_settings import BackendSettings
from smartmed.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from smartmed.schemas.extraction import Extraction

ROOT = Path(__file__).resolve().parents[2]
out = Path(__file__).parent / "results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
out.mkdir(parents=True)
source = out / "source"
source.mkdir()
for name in ("api.py", "model_client.py", "prompt.py", "backend_settings.py",
             "schemas/extraction.py"):
    target = source / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "src/smartmed" / name, target)
(out / "schema.json").write_text(json.dumps(Extraction.model_json_schema(),
                                            ensure_ascii=False, indent=2))
(out / "prompt.txt").write_text(SYSTEM_PROMPT)
cases = json.loads((ROOT / "experiments/02_model_comparison/cases_test.json").read_text())
selected = [case for case in cases if case["id"] in {
    "test_01_negation", "test_04_unknown", "test_12_doctor_only",
    "test_16_family", "test_32_unrelated_allergy",
}]
if len(selected) != 5:
    raise RuntimeError(f"Wrong case IDs: {[case['id'] for case in selected]}")
report = {"kind": "regression_smoke_not_independent_benchmark",
          "prompt_version": PROMPT_VERSION, "cases": []}
settings = BackendSettings(database=out / "smoke.sqlite3")
with TestClient(create_app(settings)) as client:
    for case in selected:
        started = time.monotonic()
        response = client.post("/v1/drafts", json={"turns": case["turns"]})
        item = {"id": case["id"], "http_status": response.status_code,
                "elapsed_s": round(time.monotonic() - started, 3), "body": response.json()}
        if response.status_code == 201:
            draft = item["body"]
            item["differences"] = [
                {"field": name, "key": key, "expected": expected[key],
                 "actual": draft["document"][name][key]}
                for name, expected in case["gold"].items()
                for key in ("status", "value")
                if expected[key] != draft["document"][name][key]
            ]
            draft_url = f"/v1/drafts/{draft['id']}"
            item["export_before_review"] = client.get(draft_url + "/export").status_code
            # This is a synthetic automated workflow check, not a doctor's approval.
            confirmation = client.post(draft_url + "/confirm", json={
                "expected_version": draft["version"],
                "reviewer": "automated-synthetic-smoke", "reviewed": True,
            })
            item["confirmation_status"] = confirmation.status_code
            item["export_after_review"] = client.get(draft_url + "/export").status_code
        report["cases"].append(item)
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(case["id"], response.status_code, item["elapsed_s"],
              "differences=", len(item.get("differences", [])), flush=True)
report["complete"] = True
(out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print("Saved:", out / "report.json", flush=True)
sys.exit(0 if all(case["http_status"] == 201 for case in report["cases"]) else 1)

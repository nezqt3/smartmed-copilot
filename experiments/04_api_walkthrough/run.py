"""Real HTTP walkthrough using synthetic data; prints and saves every response."""
import copy
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
output = Path(__file__).parent / "results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
output.mkdir(parents=True)
events = []
started = time.perf_counter()


def call(client, method, path, expected, payload=None):
    before = time.perf_counter()
    response = client.request(method, path, json=payload)
    event = {
        "step": len(events) + 1,
        "method": method,
        "path": path,
        "request": payload,
        "http_status": response.status_code,
        "elapsed_s": round(time.perf_counter() - before, 4),
        "response": response.json(),
    }
    events.append(event)
    print(json.dumps(event, ensure_ascii=False, indent=2), flush=True)
    (output / "trace.json").write_text(json.dumps(events, ensure_ascii=False, indent=2))
    assert response.status_code == expected, (path, response.status_code, expected)
    return event["response"]


with httpx.Client(base_url="http://127.0.0.1:8000", timeout=100, trust_env=False) as client:
    call(client, "GET", "/health", 200)
    call(client, "GET", "/v1/form", 200)
    encounter = json.loads((ROOT / "examples/encounter_zh.json").read_text())
    draft = call(client, "POST", "/v1/drafts", 201, encounter)
    path = f"/v1/drafts/{draft['id']}"
    call(client, "GET", path, 200)
    call(client, "GET", path + "/export", 409)

    invalid = copy.deepcopy(draft["document"])
    invalid["已用药物剂量"]["value"] = "999毫克"
    call(client, "PUT", path, 422, {
        "expected_version": draft["version"], "actor": "demo-developer",
        "document": invalid,
    })

    # A genuine edit of evidence granularity; the facts and original wording stay intact.
    edited = copy.deepcopy(draft["document"])
    edited["咳嗽"]["evidence"] = [{"turn_id": 2, "quote": "我咳嗽两天了"}]
    draft = call(client, "PUT", path, 200, {
        "expected_version": draft["version"], "actor": "demo-developer",
        "document": edited,
    })
    call(client, "POST", path + "/confirm", 409, {
        "expected_version": 1, "reviewer": "demo-developer", "reviewed": True,
    })
    draft = call(client, "POST", path + "/confirm", 200, {
        "expected_version": draft["version"], "reviewer": "demo-developer",
        "reviewed": True,
    })
    call(client, "GET", path + "/export", 200)

    edited = copy.deepcopy(draft["document"])
    edited["咳嗽"]["evidence"] = [{"turn_id": 2, "quote": "我咳嗽两天了，没有发热。"}]
    draft = call(client, "PUT", path, 200, {
        "expected_version": draft["version"], "actor": "demo-developer",
        "document": edited,
    })
    call(client, "GET", path + "/export", 409)
    draft = call(client, "POST", path + "/confirm", 200, {
        "expected_version": draft["version"], "reviewer": "demo-developer",
        "reviewed": True,
    })
    history = call(client, "GET", path + "/history", 200)
    exported = call(client, "GET", path + "/export", 200)
    (output / "export.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2))

summary = {
    "total_s": round(time.perf_counter() - started, 4),
    "steps": len(events), "draft_id": draft["id"],
    "final_version": draft["version"], "history_versions": len(history),
    "generation": draft["model_metadata"],
    "output_dir": str(output),
}
(output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)

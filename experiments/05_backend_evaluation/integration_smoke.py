"""Real queue + 8000-character request smoke; synthetic text only."""

import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from smartmed.api import create_app
from smartmed.auth import AuthStore
from smartmed.backend_settings import BackendSettings

ROOT = Path(__file__).resolve().parent


def main():
    out = ROOT / "results" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_integration")
    out.mkdir(parents=True)
    settings = BackendSettings(
        database=out / "drafts.db", auth_database=out / "staff.db", queue_capacity=2, timeout_s=120
    )
    password = secrets.token_urlsafe(24)
    AuthStore(settings.auth_database).add_staff("synthetic-smoke", password)
    patient = "我咳嗽两天，没有发热。"
    size = 8000 - len(patient)
    doctor = "请继续。" * (size // 4) + "好" * (size % 4)
    long_input = {
        "turns": [
            {"turn_id": 1, "speaker": "doctor", "text": doctor},
            {"turn_id": 2, "speaker": "patient", "text": patient},
        ]
    }
    assert sum(len(t["text"]) for t in long_input["turns"]) == 8000
    report = {
        "kind": "synthetic_integration_smoke",
        "clinical_validation": False,
        "input_characters": 8000,
        "jobs": [],
        "complete": False,
    }
    with TestClient(create_app(settings)) as client:
        token = client.post(
            "/v1/auth/login",
            json={
                "staff_id": "synthetic-smoke",
                "passcode": password,
            },
        ).json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        start = time.monotonic()
        first = client.post("/v1/jobs", json=long_input)
        second = client.post(
            "/v1/jobs",
            json={
                "turns": [
                    {"turn_id": 1, "speaker": "patient", "text": "我没有吃药。"},
                ]
            },
        )
        report["queue_submit_statuses"] = [first.status_code, second.status_code]
        assert first.status_code == second.status_code == 202
        third = client.post("/v1/jobs", json=long_input)
        report["overflow_status"] = third.status_code
        assert third.status_code == 503
        for index, response in enumerate((first, second)):
            deadline = time.monotonic() + 660
            url = "/v1/jobs/" + response.json()["job_id"]
            while time.monotonic() < deadline:
                job = client.get(url).json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.5)
            assert job["status"] == "succeeded", job
            draft_url = "/v1/drafts/" + job["draft_id"]
            draft = client.get(draft_url).json()
            if index == 0:
                assert draft["document"]["咳嗽"]["status"] == "present"
                assert draft["document"]["发热"]["status"] == "negated"
                assert draft["model_metadata"]["segment_count"] > 1
            blocked = client.get(draft_url + "/export").status_code
            required = client.get(draft_url + "/safety").json()["required_acknowledgements"]
            confirmed = client.post(
                draft_url + "/confirm",
                json={
                    "expected_version": 1,
                    "reviewed": True,
                    "acknowledged_alerts": required,
                },
            )
            exported = client.get(draft_url + "/export")
            deleted = client.delete(draft_url + "?expected_version=2")
            passed = blocked == 409 and confirmed.status_code == exported.status_code == 200
            passed = (
                passed and deleted.status_code == 204 and client.get(draft_url).status_code == 404
            )
            assert passed
            report["jobs"].append(
                {
                    "status": job["status"],
                    "workflow_passed": passed,
                    "document": draft["document"],
                    "model_metadata": draft["model_metadata"],
                }
            )
        report["elapsed_s"] = round(time.monotonic() - start, 3)
        report["complete"] = True
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("Saved:", out / "report.json", flush=True)


if __name__ == "__main__":
    main()

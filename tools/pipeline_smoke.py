"""Exercise production routes with local models and an isolated synthetic database."""

import argparse
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from smartmed.api import create_app
from smartmed.auth import AuthStore
from smartmed.backend_settings import load_backend_settings

SYNTHETIC_TEXT = (
    "今天哪里不舒服我咳嗽两天了还有咽痛有没有发热没有发热"
    "以前有什么疾病我有高血压药物过敏情况呢青霉素过敏情况我不知道"
    "今天测量体温36点8摄氏度建议多饮水休息三天后复诊"
)


def checked(response, expected):
    if response.status_code != expected:
        raise RuntimeError(f"{response.request.url.path}: HTTP {response.status_code}")
    return response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="Synthetic WAV, mono PCM16 16 kHz")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="smartmed-smoke-") as directory:
        settings = load_backend_settings().model_copy(update={
            "database": Path(directory) / "drafts.sqlite3",
            "auth_database": Path(directory) / "staff.sqlite3",
        })
        passcode = secrets.token_urlsafe(24)
        AuthStore(settings.auth_database).add_staff("synthetic_smoke", passcode)
        with TestClient(create_app(settings)) as client:
            login = checked(client.post("/v1/auth/login", json={
                "staff_id": "synthetic_smoke", "passcode": passcode,
            }), 200)
            client.headers["Authorization"] = f"Bearer {login['access_token']}"
            text = SYNTHETIC_TEXT
            if args.audio:
                text = checked(client.post(
                    "/v1/audio/transcribe", content=args.audio.read_bytes(),
                    headers={"Content-Type": "audio/wav"},
                ), 200)["text"]
                print("ASR passed", flush=True)
            assigned = checked(client.post("/v1/audio/assign-speakers", json={"text": text}), 200)
            assert "".join(turn["text"] for turn in assigned["turns"]) == text.strip()
            print(f"Lossless speaker assignment: {len(assigned['turns'])} turns", flush=True)
            # Synthetic smoke data only: this flag simulates the UI review step.
            draft = checked(client.post("/v1/outpatient/drafts", json={
                "turns": assigned["turns"], "transcript_reviewed": True,
            }), 201)
            saved = checked(client.get(f"/v1/outpatient/drafts/{draft['id']}"), 200)
            assert saved["document"] == draft["document"]
            print("Extraction, grounding validation and draft persistence passed", flush=True)


if __name__ == "__main__":
    main()

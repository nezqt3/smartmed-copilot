"""Check provenance, split, hashes, WAV format and transcript shape."""

import hashlib
import json
import wave
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate() -> list[str]:
    cases = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    errors = []
    ids = [case["id"] for case in cases]
    if len(cases) != 6 or len(ids) != len(set(ids)):
        errors.append("Expected six unique cases")
    if Counter(case["split"] for case in cases) != {"dev": 3, "test": 3}:
        errors.append("Expected three dev and three test cases")
    for case in cases:
        path = ROOT / case["audio_path"]
        if not path.is_file():
            errors.append(f"{case['id']}: WAV missing")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
            errors.append(f"{case['id']}: checksum mismatch")
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                1, 2, 16_000,
            ):
                errors.append(f"{case['id']}: expected mono 16 kHz PCM16")
            if not 60 <= duration <= 120:
                errors.append(f"{case['id']}: duration {duration:.1f}s outside 1–2 min")
        if not case["turns"] or any(
            turn["speaker"] not in {"doctor", "patient"} or not turn["text"].strip()
            for turn in case["turns"]
        ):
            errors.append(f"{case['id']}: bad transcript")
        if case["source_type"] != "synthetic_macos_tts_not_clinically_reviewed":
            errors.append(f"{case['id']}: provenance is missing")
    return errors


if __name__ == "__main__":
    failures = validate()
    if failures:
        raise SystemExit("\n".join(failures))
    print("Six audio cases validated")

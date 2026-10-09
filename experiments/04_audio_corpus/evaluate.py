"""Measure ASR transcription on synthetic clips; no clinical quality claim."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent


def normalized(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)).lower()


def edit_distance(reference: str, predicted: str) -> int:
    previous = list(range(len(predicted) + 1))
    for index, expected in enumerate(reference, 1):
        current = [index]
        for column, actual in enumerate(predicted, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


def evaluate(base_url: str, output: Path):
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "api"}:
        raise ValueError("Only the local API or Compose API service is allowed")
    cases = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    local_opener = build_opener(ProxyHandler({}))
    rows = []
    for case in cases:
        audio = (ROOT / case["audio_path"]).read_bytes()
        request = Request(
            base_url.rstrip("/") + "/v1/audio/transcribe",
            data=audio,
            headers={"Content-Type": "audio/wav"},
            method="POST",
        )
        started = time.monotonic()
        with local_opener.open(request, timeout=240) as response:
            result = json.load(response)
        elapsed = round(time.monotonic() - started, 3)
        reference = normalized("".join(turn["text"] for turn in case["turns"]))
        hypothesis = normalized(result["text"])
        rows.append({
            "id": case["id"],
            "split": case["split"],
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "reference_type": case["transcript_status"],
            "reference": reference,
            "hypothesis": hypothesis,
            "character_error_rate": round(
                edit_distance(reference, hypothesis) / len(reference), 4
            ),
            "elapsed_s": elapsed,
            "audio_duration_s": case["duration_s"],
            "model": result.get("model"),
            "revision": result.get("revision"),
        })
        print(f"{case['id']}: CER={rows[-1]['character_error_rate']:.3f}, {elapsed}s")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"cases": rows, "synthetic_tts_only": True}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "asr.json")
    args = parser.parse_args()
    evaluate(args.base_url, args.output)


if __name__ == "__main__":
    main()

"""Download one pinned model snapshot before starting the offline ASR service."""

import hashlib
import os
from pathlib import Path

from huggingface_hub import snapshot_download

from services.asr.app import MODEL_ID, MODEL_REVISION

MODEL_SHA256 = "5bba782a5e9196166233b9ab12ba04cadff9ef9212b4ff6153ed9290ff679025"


def verified_snapshot(model_dir: Path) -> bool:
    model = model_dir / "model.pt"
    if not (model_dir / "config.yaml").is_file() or not model.is_file():
        return False
    digest = hashlib.sha256()
    with model.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == MODEL_SHA256


def main():
    model_dir = Path(os.getenv("SMARTMED_ASR_MODEL_DIR", "/models/paraformer-zh"))
    model_dir.mkdir(parents=True, exist_ok=True)
    if not verified_snapshot(model_dir):
        snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=model_dir)
    if not verified_snapshot(model_dir):
        raise RuntimeError("Incomplete or corrupted ASR model snapshot")
    print(f"ASR model ready: {MODEL_ID}@{MODEL_REVISION}")


if __name__ == "__main__":
    main()

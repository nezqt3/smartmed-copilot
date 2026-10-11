import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("task03_check", ROOT / "tools/task03_check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def updated_dataset(tmp_path, mutation):
    root = tmp_path / "task03"
    shutil.copytree(ROOT / "datasets/task03", root)
    path = root / "heldout_candidate.json"
    cases = json.loads(path.read_text())
    mutation(cases, root)
    path.write_text(json.dumps(cases, ensure_ascii=False) + "\n")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][path.name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    return root


def test_rejects_variant_group_crossing_splits_even_with_distinct_text(tmp_path):
    def mutation(cases, root):
        development = json.loads((root / "development.json").read_text())
        cases[0]["dialogue_group_id"] = development[0]["dialogue_group_id"]

    with pytest.raises(ValueError, match="leakage"):
        checker.check(updated_dataset(tmp_path, mutation))


def test_rejects_gold_citing_physician_instead_of_patient(tmp_path):
    def mutation(cases, root):
        cases[0]["turns"][0]["speaker"] = "doctor"

    with pytest.raises(ValueError, match="证据"):
        checker.check(updated_dataset(tmp_path, mutation))


def test_rejects_unversioned_corpus_edit(tmp_path):
    root = tmp_path / "task03"
    shutil.copytree(ROOT / "datasets/task03", root)
    path = root / "heldout_candidate.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        checker.check(root)

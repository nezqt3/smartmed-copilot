import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "experiments/05_backend_evaluation"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_metrics_do_not_hide_failed_cases_or_make_empty_grounding_perfect():
    evaluator = module("run")
    cases = json.loads((ROOT / "cases_frozen.json").read_text())[:2]
    records = [{"document": c["gold"], "workflow_passed": True} for c in cases]
    full = evaluator.metrics(records, cases)
    assert full["exact_status_value"] == full["grounding_rate"] == 1
    assert full["simulated_field_corrections_mean"] == 0
    failed = evaluator.metrics([{}, {}], cases)
    assert failed["successful_cases"] == 0
    assert failed["exact_status_value"] == 0
    assert failed["grounding_rate"] is None
    assert failed["false_negative_rate"] == 1
    assert failed["simulated_field_corrections_mean"] is None


def test_blind_annotation_templates_and_disagreement_validation():
    annotations = module("annotations")
    cases = json.loads((ROOT / "cases_frozen.json").read_text())[:1]
    blind = annotations.template(cases)
    assert "gold" not in blind[0]
    assert all(v is None for v in blind[0]["document"].values())
    with pytest.raises(ValueError):
        annotations.agreement(blind, blind, cases)
    left = copy.deepcopy(blind)
    left[0].update(
        reviewer="synthetic-test-annotator", reviewed_on="2026-10-06", document=cases[0]["gold"]
    )
    result = annotations.agreement(left, left, cases)
    assert result["status_agreement"] == 1 and result["disagreements"] == []
    with pytest.raises(ValueError):
        annotations.agreement(left + left, left, cases)

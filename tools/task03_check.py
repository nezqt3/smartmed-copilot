"""Task 03 corpus integrity and fixture API checks, not model/human evaluation."""

import hashlib
import json
import secrets
import tempfile
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from smartmed.api import create_app
from smartmed.auth import AuthStore
from smartmed.backend_settings import BackendSettings
from smartmed.model_client import ExtractionResult
from smartmed.schemas.extraction import FIELDS, ExtractRequest, validate_extraction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets/task03"
REVIEW_NOTES = {
    "task03_11": "Никогда не применял пенициллин: аллергия unknown, не negated.",
    "task03_12": "Рекомендация не означает приём; пациент явно отрицает любой приём.",
    "task03_13": "Два препарата есть, связь дозы с каждым неизвестна: доза unknown.",
    "task03_14": "Сведения брата исключены; сомнения пациента означают unknown.",
    "task03_15": "Фактически приняты две капсулы; не угадывать миллиграммы.",
    "task03_16": "Отрицание сегодня не отменяет фактический приём вчера.",
    "task03_17": "Вода и номер очереди не являются дозой; доза unknown.",
    "task03_18": "Аллергия present, отсутствие приёма negated, доза unknown.",
    "task03_19": "Явное исправление трёх дней на шесть: использовать шесть.",
    "task03_20": "Неразрешённые два/пять дней: длительность unknown, кашель present.",
}


def read(path):
    return json.loads(path.read_text())


def fingerprint(turns):
    return hashlib.sha256(
        json.dumps(turns, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def check(root=DATA):
    manifest = read(root / "manifest.json")
    sources = {s["id"]: s for s in read(root / "sources.json")["sources"]}
    seen_ids, groups, transcripts = set(), {}, {}
    rows = []
    for filename, entry in manifest["files"].items():
        path = root / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{filename}: checksum differs; create a new dataset version")
        cases = read(path)
        if len(cases) != entry["cases"]:
            raise ValueError("Case count differs from manifest")
        split = filename.removesuffix(".json")
        for case in cases:
            if case["id"] in seen_ids:
                raise ValueError("Duplicate case ID")
            seen_ids.add(case["id"])
            if case["split"] != split:
                raise ValueError("Wrong split label")
            source = sources[case["source_id"]]
            if source["version"] != case["source_version"] or not case["source_record_id"]:
                raise ValueError("Source provenance missing or inconsistent")
            if source["kind"] != "synthetic_assistant_authored" and not source.get(
                "conditions_verified"
            ):
                raise ValueError("External source conditions not verified")
            for key, mapping in (
                (case["dialogue_group_id"], groups),
                (fingerprint(case["turns"]), transcripts),
            ):
                if key in mapping and mapping[key] != split:
                    raise ValueError("Dialogue/variant leakage between splits")
                mapping[key] = split
            request = ExtractRequest.model_validate({"turns": case["turns"]})
            validate_extraction(case["gold"], request.turns)
            rows.append(case)
    previous = set()
    for p in [
        ROOT / "experiments/01_baseline/cases.json",
        ROOT / "experiments/02_model_comparison/cases_test.json",
        ROOT / "experiments/05_backend_evaluation/cases_frozen.json",
    ]:
        for c in read(p):
            if "turns" in c:
                previous.add(fingerprint(c["turns"]))
    repeated = [c["id"] for c in rows if fingerprint(c["turns"]) in previous]
    if repeated:
        raise ValueError(f"Transcripts already used in earlier experiments: {repeated}")
    return rows


class FixtureExtractor:
    def __init__(self, cases):
        self.by_text = {fingerprint(c["turns"]): c for c in cases}

    async def health(self):
        return {"model_installed": True}

    async def extract(self, request):
        case = self.by_text[fingerprint([t.model_dump() for t in request.turns])]
        return ExtractionResult(
            validate_extraction(case["gold"], request.turns), {"model": "fixture_no_llm"}
        )


def api_checks(cases):
    results = []
    with tempfile.TemporaryDirectory(prefix="smartmed-task03-") as temp:
        settings = BackendSettings(
            database=Path(temp) / "drafts.db", auth_database=Path(temp) / "staff.db"
        )
        passcode = secrets.token_urlsafe(24)
        AuthStore(settings.auth_database).add_staff("fixture-review", passcode)
        with TestClient(create_app(settings, FixtureExtractor(cases))) as client:
            token = client.post(
                "/v1/auth/login", json={"staff_id": "fixture-review", "passcode": passcode}
            ).json()["access_token"]
            client.headers["Authorization"] = "Bearer " + token
            for case in cases:
                created = client.post("/v1/drafts", json={"turns": case["turns"]})
                if created.status_code != 201:
                    raise ValueError(f"{case['id']}: create returned {created.status_code}")
                draft = created.json()
                url = "/v1/drafts/" + draft["id"]
                loaded = client.get(url)
                edited = client.put(
                    url, json={"expected_version": draft["version"], "document": case["gold"]}
                )
                if loaded.status_code != 200 or edited.status_code != 200:
                    raise ValueError(f"{case['id']}: read/edit failed")
                if (
                    loaded.json()["document"] != case["gold"]
                    or edited.json()["document"] != case["gold"]
                ):
                    raise ValueError("Stored fields/evidence differ from original")
                results.append(
                    {
                        "id": case["id"],
                        "create": 201,
                        "read": 200,
                        "edit": 200,
                        "exact_fields_and_quotes_preserved": True,
                        "note_ru": REVIEW_NOTES[case["id"]],
                    }
                )
    return results


def main():
    cases = check()
    selected = [c for c in cases if c["id"] in REVIEW_NOTES]
    report = {
        "checked_on": "2026-10-09",
        "kind": "assistant_structural_and_fixture_review",
        "reviewer": "Codex assistant, not Pavel or independent human annotator",
        "human_cross_review_complete": False,
        "clinical_review_complete": False,
        "model_evaluation_performed": False,
        "total_cases": len(cases),
        "split_counts": dict(Counter(c["split"] for c in cases)),
        "validated_fields": len(cases) * len(FIELDS),
        "status_counts": dict(Counter(f["status"] for c in cases for f in c["gold"].values())),
        "cross_split_ids_groups_and_exact_transcript_overlap": 0,
        "exact_overlap_with_previous_experiment_transcripts": 0,
        "manifest": read(DATA / "manifest.json"),
        "selected_api_checks": api_checks(selected),
    }
    out = ROOT / "docs/task03-check-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": len(cases),
                "selected_api_passed": len(report["selected_api_checks"]),
                "report": str(out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

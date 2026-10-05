"""Run local candidates sequentially; score a frozen synthetic suite without an LLM judge."""
import hashlib
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "01_baseline"))
from run import FIELDS, STATUSES, api

MODELS = ("qwen2.5:3b", "qwen3:4b-instruct", "qwen3.5:4b", "qwen2.5:7b")

def percentile(values, fraction):
    return sorted(values)[max(0, __import__('math').ceil(len(values) * fraction) - 1)] if values else None

def score(run, gold):
    confusion = {a: {b: 0 for b in (*STATUSES, "invalid")} for a in STATUSES}
    total = correct = valid = exact = unsupported = missing = failed = 0
    details = []
    by_id = {c["id"]: c for c in gold}
    for record in run["cases"]:
        ref = by_id[record["id"]]["gold"]
        answer = record.get("answer", {})
        answer = answer if isinstance(answer, dict) else {}
        failed += int("error" in record)
        valid += int("error" not in record and not record.get("validation_errors"))
        for field in FIELDS:
            item = answer.get(field, {})
            item = item if isinstance(item, dict) else {}
            expected, actual = ref[field]["status"], item.get("status")
            actual = actual if actual in STATUSES else "invalid"
            confusion[expected][actual] += 1
            total += 1
            correct += int(expected == actual)
            exact += int(expected == actual and ref[field]["value"] == item.get("value"))
            unsupported += int(expected != "present" and actual == "present")
            missing += int(expected == "present" and actual != "present")
        details.append({"id": record["id"], "error": record.get("error"),
                        "validation_errors": record.get("validation_errors", []),
                        "differences": record.get("differences", [])})
    f1 = {}
    for status in STATUSES:
        tp = confusion[status][status]
        fp = sum(confusion[other][status] for other in STATUSES if other != status)
        fn = sum(confusion[status][other] for other in (*STATUSES,"invalid") if other != status)
        f1[status] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0
    return {"cases": len(run["cases"]), "failed_requests": failed,
            "valid_cases": valid, "status_correct": correct, "field_count": total,
            "status_accuracy": correct / total, "status_macro_f1": statistics.mean(f1.values()),
            "f1_by_status": f1, "exact_status_value": exact / total,
            "unsupported_positive_fields": unsupported, "missed_positive_fields": missing,
            "confusion": confusion, "details": details}

def invoke(model, dataset, folder, label, keep_alive="5m"):
    command = [sys.executable, str(ROOT.parent / "01_baseline" / "run.py"),
               "--model", model, "--cases", str(dataset), "--thinking", "off",
               "--keep-alive", keep_alive]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    lines = []
    for line in process.stdout:
        print(f"[{model} {label}] {line.rstrip()}", flush=True)
        lines.append(line)
    process.wait()
    saved = next((line.removeprefix("Saved: ").strip() for line in lines if line.startswith("Saved: ")), None)
    if saved is None:
        raise RuntimeError(f"No result for {model}: {''.join(lines)[-2000:]}")
    run = json.loads(Path(saved).read_text())
    (folder / f"{model.replace(':','_')}_{label}.json").write_text(json.dumps(run, ensure_ascii=False, indent=2))
    return run

def unload():
    for loaded in api("ps").get("models", []):
        api("generate", {"model": loaded["name"], "keep_alive": 0, "stream": False})

def report(folder, summary):
    lines = ["# Local Qwen comparison", "", "Synthetic assistant-authored Chinese cases; no clinical or native-speaker review.",
             "Model selection suite, not an independent final clinical test. Exact value boundaries can differ without a factual error.",
             "All candidates: same prompt/schema, temperature=0, seed=42, num_ctx=4096, num_predict=1400, think=false.",
             "Quality runs may overlap downloads; their wall times are not used to rank speed. Dedicated timing starts only after all downloads finish.", "",
             "| Model | Cases | Valid cases | Status accuracy | Macro F1 | Exact status+value | Unsupported positives | Missed positives |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for model, row in summary["models"].items():
        s = row["quality"]
        lines.append(f"| {model} | {s['cases']} | {s['valid_cases']} | {s['status_accuracy']:.1%} | {s['status_macro_f1']:.3f} | {s['exact_status_value']:.1%} | {s['unsupported_positive_fields']} | {s['missed_positive_fields']} |")
    lines += ["", "Detailed raw answers, references, errors and timing: adjacent JSON files.",
              "Timing uses 5 fixed cases repeated 3 times, excludes the first request as warm-up. P95 on 14 requests is exploratory.",
              "Ollama reported allocation is not measured peak RAM, and latency excludes ASR and the product API.", ""]
    for model, row in summary["models"].items():
        if "timing" in row:
            lines.append(f"- {model}: {json.dumps(row['timing'])}")
    (folder / "REPORT.md").write_text("\n".join(lines) + "\n")
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

def main():
    dataset = ROOT / "cases_test.json"
    raw = dataset.read_bytes()
    gold = json.loads(raw)
    folder = ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True)
    (folder / "cases_test.json").write_bytes(raw)
    summary = {"dataset_sha256": hashlib.sha256(raw).hexdigest(), "models": {}, "complete": False}
    (ROOT / "LATEST_RESULT.txt").write_text(str(folder) + "\n")
    pending = list(MODELS)
    deadline = time.monotonic() + 7200
    while pending:
        installed = {m["name"] for m in api("tags")["models"]}
        ready = next((m for m in pending if m in installed), None)
        if ready:
            unload()
            run = invoke(ready, dataset, folder, "quality")
            summary["models"][ready] = {"quality": score(run, gold)}
            pending.remove(ready)
            unload()
            report(folder, summary)
        else:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Downloads still pending: {pending}")
            print(f"Waiting for installed models: {pending}", flush=True)
            time.sleep(30)
    # No downloads remain; identical repeated cases measure latency independently of corpus mix.
    timing_cases = []
    for repeat in range(3):
        for index in (0, 6, 16, 26, 32):
            case = dict(gold[index])
            case["id"] += f"_repeat{repeat}"
            timing_cases.append(case)
    timing_path = folder / "cases_timing.json"
    timing_path.write_text(json.dumps(timing_cases, ensure_ascii=False, indent=2))
    for model in MODELS:
        unload()
        run = invoke(model, timing_path, folder, "timing")
        successful = [c for c in run["cases"][1:] if "error" not in c]
        values = [c["wall_seconds"] for c in successful]
        allocations = [m.get("size", 0) for c in run["cases"] for m in c.get("loaded_models") or []]
        summary["models"][model]["timing"] = {
            "warm_successful_requests": len(values), "warm_median_seconds": statistics.median(values) if values else None,
            "warm_p95_seconds": percentile(values, .95), "first_request_seconds": run["cases"][0]["wall_seconds"],
            "max_ollama_reported_allocation_bytes": max(allocations, default=0),
            "failed_requests": sum("error" in c for c in run["cases"])}
        report(folder, summary)
    unload()
    summary["complete"] = True
    report(folder, summary)
    print(f"COMPLETE: {folder / 'REPORT.md'}", flush=True)

if __name__ == "__main__":
    main()

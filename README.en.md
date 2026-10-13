# SmartMed Ambient EHR Copilot

<video src="video/smartmed-business-flow-zh.mp4" controls width="100%"></video>

> Новая панель: **outpatient.v1**, девять разделов китайской амбулаторной записи,
> несколько фактов в разделе, источники, ручные правки, проверка врачом и печать/сохранение PDF.
> Запуск: API как ниже, `cd apps/panel && npm ci && npm run dev`; http://127.0.0.1:5173.
> [Актуальный контракт](docs/outpatient-contract.md). Старый шестиполевый сценарий описан ниже
> и доступен через переключатель панели. ASR и роли ещё требуют подключения.


[Русский](README.md) | **English** | [中文](README.zh-CN.md)

Local Chinese outpatient text prototype: dialogue → six grounded facts → draft → human review → JSON.
Structure and literal citations do not guarantee medical correctness. All evaluation cases are synthetic,
not physician-reviewed or clinically validated. The physician UI, ASR, diagnoses and full SOAP remain integration work.

## Setup (macOS / Linux, Python 3.11+, running Ollama)

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ollama pull qwen3.5:4b
.venv/bin/python -m smartmed.auth pavel
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

The staff command prompts for a hidden passcode of at least 12 characters. No cloud API key is required.
Run one worker per database; an exclusive file lock prevents competing workers.
In [Swagger](http://127.0.0.1:8000/docs), log in with `staff_id` and `passcode`, then Authorize with the token.
Tokens expire after one hour; logout revokes them. Five unsuccessful login attempts lock the staff ID for 15 minutes.

## API

```text
POST   /v1/auth/login
POST   /v1/auth/logout
GET    /health
GET    /v1/form
GET    /v1/medications?q=布洛芬
POST   /v1/jobs                         → 202 + job_id
GET    /v1/jobs/{job_id}
DELETE /v1/jobs/{job_id}
POST   /v1/drafts                       → 201 (blocking compatibility route)
GET    /v1/drafts/{id}
PUT    /v1/drafts/{id}
GET    /v1/drafts/{id}/safety
POST   /v1/drafts/{id}/confirm
GET    /v1/drafts/{id}/history
GET    /v1/drafts/{id}/export
DELETE /v1/drafts/{id}?expected_version=N
```

Use async jobs for the UI. Poll once per second; on success fetch the `draft_id`, on failure display its error code.
The queue persists waiting jobs across restarts. Interrupted running jobs fail with `server_restart`.
Capacity is 8 active jobs; overflow returns 503 with Retry-After. Running jobs cannot be deleted (409).
Deleting a completed job leaves the draft intact. Drafts are shared by local staff; job status is creator-only.
All draft, medication and job routes require bearer authentication. Actor/reviewer come from the token.
Optional body identities must match. Passwords and token hashes live in a separate staff database.

Edits require `expected_version` and `document`; conflicts return 409. Query `/safety` before confirmation;
confirm with `reviewed: true`, `expected_version` and `acknowledged_alerts`. Missing required acknowledgements
return 409. Edits reset confirmation and acknowledgements. Export requires confirmation and preserves
reported facts; it is not prescribing authorization.
CORS permits `http://127.0.0.1:5173`; change `SMARTMED_BACKEND_FRONTEND_ORIGIN` to another loopback origin.

## Extraction and safety

Fields: fever, cough, symptom duration, penicillin allergy, medications taken, actual dosage.
States are `present`, `negated`, `unknown`. Speakers: patient, doctor, third_party; only patient evidence is allowed.
Maximum input: 8000 characters and 160 turns. Sentence-aware segments are at most 1800 characters;
a single longer sentence is rejected without truncation. All text and turn IDs are preserved.
Unknown segments cannot erase facts; differing statuses/values abstain with a required review alert.
Cross-segment corrections and references still need manual interpretation.

Ollama is loopback-only, temperature=0, seed=42, think=false, context 16384. Native quote choices and
runtime grounding remain enforced. Metadata records model digest, prompt hash, parameters and segment results.
A failed segment creates no partial draft. Concrete migration v1 → v2 preserves facts and adds third-party support
and acknowledgement fields; unknown/corrupt stored contracts return 409.
The narrow cough regex needs evaluation on real speech; explicit allergy/medication negation guards remain strict.

The offline demonstration index contains 5 ingredients and WHO ATC sources. It is not a Chinese product registry.
It offers no doses, substitutions or full interaction checks. Review alerts include unknown allergy/dose,
unindexed medication, dose without medication, penicillin use with unresolved allergy and segment conflicts.
See [sources and rule limits](docs/safety-and-medications.md).

## Retention and verification

Database files have 0600 permissions. Synthetic drafts expire 7 days after creation, swept at startup and hourly;
configure `SMARTMED_BACKEND_RETENTION_DAYS` (1–365). Purging deletes revisions and related jobs.
Job input is cleared on completion/failure; completed statuses expire after an hour. SQLite secure_delete is enabled.
Backups, exports, ASR audio and experiment traces need separate cleanup; this is not a legal compliance claim.

```sh
.venv/bin/ruff check src tests experiments/03_backend_smoke/run.py experiments/04_api_walkthrough/run.py experiments/05_backend_evaluation
.venv/bin/pytest tests experiments/02_model_comparison/test_scoring.py experiments/01_baseline/test_checks.py
.venv/bin/python experiments/05_backend_evaluation/run.py --models qwen3.5:4b qwen2.5:3b
```

CI needs no model service. [Measured results](docs/backend-evaluation.md) separate the historical 40-case,
four-model experiment from the current production API regression. Corrections are simulated against frozen
references, not measured clinician edits. New cases are frozen before evaluation but not human-reviewed.
[Integration contract](docs/backend-contract.md), [annotation guide](docs/annotation-guide.md) and
[Denis handoff](docs/denis-message.md) describe the remaining joint integration and human review work.

## Панель врача / Doctor panel / 医生面板

`cd apps/panel && npm ci && npm run dev` — http://127.0.0.1:5173.
Сервисы ASR и диагнозов: [infra/README.md](infra/README.md).

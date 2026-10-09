# SmartMed Ambient EHR Copilot

[Русский](README.md) | **English** | [中文](README.zh-CN.md)

A local assistant for drafting Chinese outpatient clinical documentation.
The prototype implements: text dialogue → six structured facts with source quotes →
validation → draft → manual confirmation → JSON export. A separate local ASR service
transcribes WAV audio; its text and speaker roles require manual review before extraction.
A separate offline diagnosis catalog searches a pinned 2019 source with an official 2020 addendum. The complete 2022 edition is not yet available; full SOAP notes, use of current codes in records, and medication checks are future work.

## Docker quick start

```sh
docker compose up --build -d
curl http://127.0.0.1:8000/health
```

The first run downloads local models. See [infrastructure instructions](infra/README.md) for
independent service rebuilds and development mode.

## Run without Docker

Requires Python 3.11+ and an installed, running Ollama service. Model weights are downloaded separately.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ollama pull qwen3.5:4b
.venv/bin/pytest
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000
```

This starts the draft API. Audio and diagnosis search also need their separate Compose services.

## API

Open [Swagger](http://127.0.0.1:8000/docs) after startup. The full contract is available at `GET /openapi.json`; the form description is at `GET /v1/form`.

```text
GET  /health
GET  /v1/form
POST /v1/audio/transcribe
GET  /v1/diagnoses/catalog
GET  /v1/diagnoses/search?q=...
GET  /v1/diagnoses/lookup?code=...
POST /v1/drafts
GET  /v1/drafts/{id}
PUT  /v1/drafts/{id}
POST /v1/drafts/{id}/confirm
GET  /v1/drafts/{id}/history
GET  /v1/drafts/{id}/export
```

## Extraction and validation

Qwen3.5 4B runs locally through Ollama; no external model APIs are used.
Instructor/Pydantic validate six fields: fever, cough, symptom duration, penicillin allergy,
medications already taken and dosage. Statuses are `present`, `negated` and `unknown`.
Facts include verbatim patient quotes. One retry is allowed after a validation failure.

SQLite stores drafts and revision history. Editing resets confirmation; export requires
confirmation. Structure and quote checks do not guarantee medical correctness.
Test cases are synthetic; no clinical validation has been performed.

## Repository structure

- `src/smartmed/` — API, model client, schemas and storage.
- `tests/` — backend and schema tests.
- `examples/encounter_zh.json` — sample Chinese dialogue.
- `experiments/01_baseline/` — introductory baseline.
- `experiments/02_model_comparison/` — local model comparison.
- `experiments/03_backend_smoke/` — generation regression checks.
- `experiments/04_api_walkthrough/` — complete HTTP walkthrough.
- `experiments/04_audio_corpus/` — six synthetic Chinese WAV clips and provenance.
- `infra/` and `services/asr/` — separate API, ASR and Ollama services.
- `docs/` — three project proposals in RU / EN / ZH (DOCX).
- `tools/` — document generator.
- `archive/` — previous materials.

## Project proposals

[Русский](docs/SmartMed_Ambient_EHR_Copilot_RU.docx) · [English](docs/SmartMed_Ambient_EHR_Copilot_EN.docx) · [中文](docs/SmartMed_Ambient_EHR_Copilot_ZH.docx)

## Walkthrough

With the API running, execute the command below to repeat the full walkthrough. It creates a synthetic draft in the local database. Results are stored locally and excluded from Git.

```sh
.venv/bin/python experiments/04_api_walkthrough/run.py
```

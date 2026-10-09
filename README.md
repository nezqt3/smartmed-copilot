# SmartMed Ambient EHR Copilot

**Русский** | [English](README.en.md) | [中文](README.zh-CN.md)

Локальный ассистент подготовки амбулаторной записи на китайском языке.
Реализован прототип: текстовый диалог → шесть структурированных фактов с цитатами →
проверка → черновик → ручное подтверждение → экспорт JSON. Для WAV добавлен отдельный
локальный ASR: его текст необходимо исправить и вручную разделить по ролям перед извлечением.
Поиск кодов диагнозов работает отдельно по справочнику 2019 года с официальным дополнением 2020 года. Полная сводная редакция 2022 года пока недоступна; применение актуальной редакции кодов в записи, полный SOAP и проверка назначений — следующие этапы.

## Быстрый запуск в Docker

```sh
docker compose up --build -d
curl http://127.0.0.1:8000/health
```

Первый запуск загружает локальные веса. Подробности, отдельная пересборка сервисов и режим
разработки — в [инструкции по инфраструктуре](infra/README.md).

## Запуск без Docker

Нужны Python 3.11+, установленная и запущенная Ollama. Веса модели скачиваются отдельно.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ollama pull qwen3.5:4b
.venv/bin/pytest
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000
```

Этот способ запускает API черновиков. Для аудио и поиска диагнозов поднимите отдельные ASR и terminology через Compose.

## API

После запуска открой [Swagger](http://127.0.0.1:8000/docs). Полный контракт доступен через `GET /openapi.json`, описание формы — через `GET /v1/form`.

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

## Извлечение и проверки

Qwen3.5 4B работает локально через Ollama; внешние API моделей не используются.
Instructor/Pydantic проверяют шесть полей: температура, кашель, длительность симптомов,
аллергия на пенициллин, принятые лекарства и доза. Статусы: `present`, `negated`, `unknown`.
Факты подкрепляются исходными цитатами пациента. При ошибке допускается одна повторная попытка.

SQLite хранит черновики и историю версий. Редактирование сбрасывает подтверждение;
экспорт доступен после подтверждения. Проверки структуры и цитат не гарантируют медицинскую
правильность. Тестовые случаи синтетические; клиническая проверка не проводилась.

## Структура

- `src/smartmed/` — код API, модели, схем и хранения.
- `tests/` — тесты бэкенда и схем.
- `examples/encounter_zh.json` — готовый китайский диалог.
- `experiments/01_baseline/` — учебный baseline.
- `experiments/02_model_comparison/` — сравнение локальных моделей.
- `experiments/03_backend_smoke/` — регрессии генерации.
- `experiments/04_api_walkthrough/` — полный HTTP-сценарий.
- `experiments/04_audio_corpus/` — шесть синтетических китайских WAV и манифест.
- [`infra/`](infra/README.md) — Docker Compose и отдельные образы API/ASR/справочника.
- [`resources/diagnoses/`](resources/diagnoses/README.md) — источник кодов, редакция и ограничения.
- `docs/` — три описания проекта RU / EN / ZH в DOCX.
- [`docs/annotation_spec_ru.md`](docs/annotation_spec_ru.md) — правила шести полей и порядок независимой разметки.
- `tools/` — генератор документов.
- `archive/` — предыдущие материалы.

## Документы проекта

[Русский](docs/SmartMed_Ambient_EHR_Copilot_RU.docx) · [English](docs/SmartMed_Ambient_EHR_Copilot_EN.docx) · [中文](docs/SmartMed_Ambient_EHR_Copilot_ZH.docx)

## Прогоны

При работающем API полный сценарий можно повторить командой ниже. Он создаёт синтетический черновик в локальной базе. Результаты сохраняются локально и исключены из Git.

```sh
.venv/bin/python experiments/04_api_walkthrough/run.py
```

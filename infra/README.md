# Локальная инфраструктура

`compose.yaml` поднимает независимо собираемые сервисы:

| Сервис | Назначение | Доступ |
|---|---|---|
| `api` | Черновики, проверка фактов и входной аудио API | `127.0.0.1:8000` |
| `asr` | Локальное распознавание WAV через FunASR | Только сеть Compose |
| `ollama` | Локальная Qwen для шести полей | Только сеть Compose |
| `asr-model-init` | Однократная загрузка закреплённого Paraformer | Завершается |
| `ollama-model-init` | Загрузка `qwen3.5:4b` в том Ollama | Завершается |
| `corpus-check` | Проверка шести WAV и манифеста | Запускается вручную |

Тома `api-data`, `asr-models` и `ollama-data` независимы. Пересборка кода одного сервиса не удаляет данные и веса другого. API принимает соединения только на `127.0.0.1`; модели не публикуют порты на хосте.

## Первый запуск

Из корня репозитория:

```sh
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/form
```

Если `8000` занят другим проектом, задайте `SMARTMED_API_PORT=8002` для `docker compose up -d` и обращайтесь к `127.0.0.1:8002`. Контейнерные адреса `api:8000`, `asr:8001` и `ollama:11434` при этом не меняются.

Первый запуск скачивает крупные образы, около 0.9 ГБ весов Paraformer и несколько гигабайт весов Qwen; предусмотрите примерно 8 ГБ свободного места сверх существующего Docker-кэша. Последующие запуски используют тома. Загрузчики завершаются с кодом 0, после чего стартует API. Для диагностики: `docker compose logs asr-model-init ollama-model-init asr api`. На Mac отдельно измерьте производительность контейнерной Ollama; при необходимости её можно запустить нативно и перенастроить только сервис API.

Аудиозапрос:

```sh
curl --fail-with-body -H 'Content-Type: audio/wav' \
  --data-binary @experiments/04_audio_corpus/clips/audio_dev_01.wav \
  http://127.0.0.1:8000/v1/audio/transcribe
```

Ответ содержит сплошной текст и `speaker_labels: manual_required`. После прослушивания исправьте текст и разбейте его на реплики `doctor`/`patient`; только затем отправляйте `POST /v1/drafts`. Сервис не угадывает роли и не создаёт черновик из сырого ASR. Допустим только моно PCM16 WAV 16 кГц длительностью 0.2–120 секунд и размером до 5 МБ.

## Параллельная разработка

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
docker compose build api
docker compose up -d --no-deps api
docker compose build asr
docker compose up -d --no-deps asr
docker compose run --rm corpus-check
docker compose run --rm audio-eval
```

`compose.dev.yaml` монтирует `src/` только в API, а `services/` только в ASR и включает перезагрузку кода. Отдельные Dockerfile находятся в `infra/docker/`. Код экспериментов, архив и локальные данные не входят в контекст образов.

ASR использует локальный снимок [FunASR Paraformer-zh](https://huggingface.co/funasr/paraformer-zh) с зафиксированным commit SHA. После загрузки `asr` работает с `HF_HUB_OFFLINE=1` и локальным путём модели; `disable_update=True` сам по себе не делает клиент полностью офлайн. Проверка реплик и китайского медицинского смысла остаётся за человеком.

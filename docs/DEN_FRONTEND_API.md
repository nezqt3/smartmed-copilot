# Дену: запись, форма и контракт SmartMed API

Версия от 5 октября 2026. Описывает реализованный API, а не будущие функции.

## Что подключаем

```text
Запись микрофона → ASR → текстовые реплики doctor/patient
→ POST /v1/drafts → форма + исходные цитаты
→ PUT (правки) → POST confirm → GET export
```

Бэкенд сейчас принимает только текст. Нет ручки загрузки аудио, ASR, определения говорящего,
WebSocket/SSE, полного SOAP или PDF-экспорта. Разделение на doctor/patient должно происходить
до вызова API. Если определение говорящих не готово, в демо нужно явно назначать/проверять роли,
а не отправлять весь разговор как речь пациента. Интерфейс продукта и разговор — китайские.

## Адрес и запуск

Репозиторий: https://github.com/nezqt3/smartmed-copilot

На машине с Python 3.11+, установленной Ollama и достаточной памятью:

```sh
git clone git@github.com:nezqt3/smartmed-copilot.git
cd smartmed-copilot
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
ollama pull qwen3.5:4b
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000
```

Ollama должна быть запущена отдельно (приложение или `ollama serve`). Веса не хранятся в Git.
API_BASE = `http://127.0.0.1:8000`. Swagger: `/docs`, машиночитаемый контракт: `/openapi.json`.
Копия OpenAPI текущего кода лежит рядом: `smartmed.openapi.json`.

На компьютере Дена localhost означает компьютер Дена, а не Павла. Для доступа к серверу Павла
нужна отдельная настройка сетевого адреса; текущий запуск слушает только loopback.
CORS middleware пока нет. Для локального фронта удобно настроить dev-proxy `/api` →
`http://127.0.0.1:8000` с удалением префикса `/api`; браузер обращается к своему origin.
Это рекомендация по настройке фронта, готового proxy в репозитории пока нет.

## Ручки

| Метод | Путь | Успешный ответ |
|---|---|---|
| GET | `/health` | 200: доступность Ollama, модели, busy |
| GET | `/v1/form` | 200: поля, статусы, JSON Schema, contract_version |
| POST | `/v1/drafts` | 201: новый Draft |
| GET | `/v1/drafts/{id}` | 200: Draft |
| PUT | `/v1/drafts/{id}` | 200: новая версия Draft |
| POST | `/v1/drafts/{id}/confirm` | 200: подтверждённая новая версия |
| GET | `/v1/drafts/{id}/history` | 200: массив `{version, actor, action, draft}` |
| GET | `/v1/drafts/{id}/export` | 200: подтверждённый Draft, JSON |

Все POST/PUT: `Content-Type: application/json`. Обязательны точные имена ключей.

## Генерация: полный пример запроса

`POST /v1/drafts`

```json
{
  "turns": [
    {"turn_id": 1, "speaker": "doctor", "text": "哪里不舒服？有发热吗？"},
    {"turn_id": 2, "speaker": "patient", "text": "我咳嗽两天了，没有发热。"},
    {"turn_id": 3, "speaker": "doctor", "text": "青霉素过敏吗？吃过什么药？"},
    {"turn_id": 4, "speaker": "patient", "text": "青霉素过敏情况我不知道。我昨天吃了布洛芬，一次200毫克。"}
  ]
}
```

`turn_id`: уникальное целое >=1; роли только `doctor`/`patient`; порядок реплик сохраняем.
От 1 до 40 реплик, непустой текст, максимум 2000 символов суммарно. Длинный разговор
не обрезаем молча. Стратегия длинных приёмов ещё не реализована.
Повторный POST создаёт другой черновик: идемпотентности нет.

## Типы ответа для TypeScript

```ts
type Turn = { turn_id: number; speaker: 'doctor' | 'patient'; text: string };
type Evidence = { turn_id: number; quote: string };
type Fact =
  | { status: 'present'; value: string; evidence: Evidence[] }
  | { status: 'negated'; value: null; evidence: Evidence[] }
  | { status: 'unknown'; value: null; evidence: [] };
type FieldName = '发热' | '咳嗽' | '症状持续时间' | '青霉素过敏' | '已用药物' | '已用药物剂量';
type Extraction = Record<FieldName, Fact>;
type Draft = {
  id: string;
  version: number;
  state: 'requires_review' | 'confirmed';
  contract_version: string;
  created_at: string;
  updated_at: string;
  turns: Turn[];
  document: Extraction;
  model_metadata: Record<string, unknown>;
  reviewer: string | null;
};
```

Значение `present` — непустой буквальный фрагмент цитаты; для `present` и `negated`
нужна минимум одна цитата (максимум восемь). `unknown` имеет `null` и пустой массив.
Цитата — непрерывный оригинальный фрагмент указанной реплики пациента, не перевод.
Не переписываем и не нормализуем пробелы. Бэкенд проверяет это и несколько узких смысловых правил.

## Пример document из реального прогона

Это полный объект шести полей внутри ответа Draft; конкретные цитаты при новом вызове могут отличаться.

```json
{
  "发热": {"status": "negated", "value": null, "evidence": [{"turn_id": 2, "quote": "没有发热。"}]},
  "咳嗽": {"status": "present", "value": "咳嗽", "evidence": [{"turn_id": 2, "quote": "我咳嗽两天了，没有发热。"}]},
  "症状持续时间": {"status": "present", "value": "两天", "evidence": [{"turn_id": 2, "quote": "我咳嗽两天了，没有发热。"}]},
  "青霉素过敏": {"status": "unknown", "value": null, "evidence": []},
  "已用药物": {"status": "present", "value": "布洛芬", "evidence": [{"turn_id": 4, "quote": "我昨天吃了布洛芬，"}]},
  "已用药物剂量": {"status": "present", "value": "200毫克", "evidence": [{"turn_id": 4, "quote": "一次200毫克。"}]}
}
```

## Правки и подтверждение: реальные тела запросов

Сохраняем последнюю полученную версию Draft. PUT отправляет ВСЕ шесть полей, не PATCH.

```ts
// draft — последний объект с сервера; editedDocument — все шесть полей формы.
const editBody = {
  expected_version: draft.version,
  actor: 'demo-user',
  document: editedDocument,
};
// PUT /v1/drafts/{id}, JSON.stringify(editBody)

const confirmBody = {
  expected_version: draft.version,
  reviewer: 'demo-user',
  reviewed: true,
};
// POST /v1/drafts/{id}/confirm, JSON.stringify(confirmBody)
```

После каждого успешного PUT/confirm заменяем локальный Draft ответом сервера: версия выросла.
После PUT всегда `requires_review`, reviewer сброшен. Редактирование подтверждённого документа
снова требует подтверждения. Произвольный новый факт без исходного доказательства API не примет.
Отдельного свободного редактора медицинской карты пока нет.

Confirm вызываем только после явного действия пользователя. Это подтверждение в интерфейсе,
не электронная подпись: actor/reviewer пока обычные строки, авторизации и проверки личности нет.
Export отдаёт весь Draft (включая диалог и метаданные), а не только document и не PDF.

## Ошибки и состояние интерфейса

| HTTP / code | Действие фронта |
|---|---|
| 404 `draft_not_found` | Черновик не найден |
| 409 `version_conflict` | Загрузить свежий Draft, предложить сверить изменения; не затирать автоматически |
| 409 `review_required` | Экспорт недоступен до подтверждения |
| 422 | Показать ошибку входа или `invalid_evidence`; правка не сохранена |
| 502 `invalid_model_output` | Ответ модели не прошёл проверку; новый черновик не сохранён |
| 503 `model_busy` | Модель занята; есть Retry-After: 5 |
| 503 `model_unavailable` | Ollama или нужная модель недоступна |
| 504 `model_timeout` | Генерация не завершилась, новый черновик не сохранён |

Ошибки API обычно имеют `detail: {code, message?}`; при стандартной проверке FastAPI
422 имеет `detail` как массив ошибок. Код должен поддерживать обе формы.

Генерация не стримится. Показываем загрузку, блокируем повторный submit.
Бюджет сервера 90 секунд; клиенту дать, например, 100 секунд. Последний синтетический прогон:
генерация 14,04 с, весь сценарий из 15 запросов 14,12 с. Это один замер, не SLA.
Повтор после обрыва связи может создать дубликат: отмена браузерного запроса не гарантирует
отмену операции на сервере.

В форме выводим китайское название, статус, значение и цитаты с переходом к исходной реплике.
`unknown` означает «неизвестно», не «нет». Не добавляем отсутствующие диагнозы и назначения.

## Проверка подключения без фронта

```sh
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/form
curl --fail-with-body http://127.0.0.1:8000/v1/drafts \
  -H 'Content-Type: application/json' --data-binary @examples/encounter_zh.json
.venv/bin/python experiments/04_api_walkthrough/run.py
```

Последний скрипт выполняет генерацию, чтение, корректную/некорректную правку, конфликт версий,
подтверждение, сброс подтверждения, историю и экспорт. Создаёт синтетический черновик в базе.
Полные запросы/ответы и время сохраняются локально в experiments/04_api_walkthrough/results/.

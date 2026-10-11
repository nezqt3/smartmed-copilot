Новый амбулаторный API: [outpatient.v1](outpatient-contract.md). Ниже сохранён контракт шестиполевого API.

# Контракт интеграции бэкенда — 6 октября 2026

База URL: `http://127.0.0.1:8000`. CORS по умолчанию: `http://127.0.0.1:5173`.
Настроить другой локальный origin: `SMARTMED_BACKEND_FRONTEND_ORIGIN=http://localhost:5173`.
Это API текстового первого этапа, не SOAP и не ASR-сервис.

## Вход

`POST /v1/auth/login`:
```json
{"staff_id":"pavel","passcode":"<пароль сотрудника>"}
```
Ответ: `access_token`, `token_type: bearer`, `expires_in: 3600`.
К защищённым запросам прикладывать `Authorization: Bearer <token>`.
Токен хранить в памяти интерфейса, не помещать в URL, логи и экспорт.
401 → повторный вход; 429 → временная блокировка входа.
`POST /v1/auth/logout` с текущим token → 204.

## Схема и ввод

`GET /v1/form` возвращает `contract_version: extraction.v2`, `fields`, `statuses`, `schema`, `limits`, `speakers`.
Интерфейс строит карточки по `fields`. patient=пациент, doctor=врач, third_party=родственник/другой человек.
У ASR неопределённого говорящего сначала должен установить пользователь; не обозначать его автоматически пациентом.

`POST /v1/jobs`:
```json
{"turns":[
  {"turn_id":1,"speaker":"doctor","text":"咳嗽多久了？"},
  {"turn_id":2,"speaker":"patient","text":"咳嗽两天，没有发热。"}
]}
```
Ответ 202: `job_id`, `status`, `created_at`, `updated_at`, `draft_id`, `error`.
Опрос `GET /v1/jobs/{job_id}` раз в секунду. `queued`/`running` → ожидание;
`succeeded` → `GET /v1/drafts/{draft_id}`; `failed` → показать `error` и предложить повторную подачу.
503 `queue_full` → соблюдать Retry-After; не создавать дубликаты автоматически.
422 `single_utterance_too_long` → предложить добавить границы предложений, не обрезать текст.
Суммарно ≤8000 символов, ≤160 реплик, отдельное предложение ≤1800 символов.
`DELETE /v1/jobs/{job_id}` → 204; выполняемое задание → 409 `job_running`.
Совместимый `POST /v1/drafts` принимает тот же ввод и ждёт 201; для интерфейса использовать очередь.

## Черновик и цитаты

`GET /v1/drafts/{id}` возвращает `id`, `version`, `state`, `contract_version`, даты,
`turns`, `document`, `model_metadata`, `reviewer`, `acknowledged_alerts`.
Факт `present`: value — исходный текст, evidence непустой.
Факт `negated`: value=null, evidence непустой.
Факт `unknown`: value=null, evidence=[].
При клике на поле найти исходную реплику по `turn_id` и выделить буквальный `quote`.
Использовать textContent / экранирование; разговор не является HTML.

`PUT /v1/drafts/{id}`:
```json
{"expected_version":1,"document":{"<все шесть полей>":"<факты по схеме>"}}
```
Это схематический пример: настоящий document должен содержать шесть объектов из `/v1/form`.
Не передавать actor. Ответ возвращает новую версию, `requires_review`, reviewer=null и пустые acknowledgement.
409 `version_conflict` → перечитать и предложить повторно применить правки; не перезаписывать автоматически.
422 `invalid_evidence` → правки не сохранены, нужно исправить цитаты/статусы.

## Предупреждения и подтверждение

`GET /v1/drafts/{id}/safety`: `ruleset_version`, `index_version`, `alerts`, `medications`,
`required_acknowledgements`. Каждый alert содержит `code`, `field`, `message`,
`requires_acknowledgement`, `source_url`. Показывать предупреждения рядом с карточками.
Индекс лекарств: `GET /v1/medications?q=阿莫西林`; пустой q возвращает все 5 ингредиентов.
Справочник не назначает и не пересчитывает дозы.

`POST /v1/drafts/{id}/confirm`:
```json
{"expected_version":2,"reviewed":true,"acknowledged_alerts":["penicillin_review"]}
```
Передавать только действительно просмотренные обязательные коды текущего отчёта.
Не передавать reviewer. Без обязательных кодов → 409 `safety_acknowledgement_required`.
`reviewed` — утверждение врача о фактической проверке, интерфейс не должен отправлять его автоматически.
В случае смены версии между safety и confirm API не сохранит подтверждение (409).

## Экспорт и удаление

`GET /v1/drafts/{id}/export` → JSON только после подтверждения; иначе 409 `review_required`.
`GET /v1/drafts/{id}/history` → версии, авторы, действия, снимки черновика.
`DELETE /v1/drafts/{id}?expected_version=N` → 204, удаляет черновик и всю историю;
устаревшая версия → 409. Хранение по умолчанию 7 дней, очистка при старте и ежечасно.
Не считать удаление из API удалением скачанных JSON/аудио/резервных копий.

## Что подключает Денис

Панель врача, подсветку цитат, импорт текстовых turns из локального ASR, определение говорящих,
справочник диагнозов и демонстрацию общего приложения. Проверка бэкенда не проверяет эти компоненты.

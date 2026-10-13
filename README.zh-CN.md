# SmartMed Ambient EHR Copilot

<video src="video/smartmed-business-flow-zh.mp4" controls width="100%"></video>

> Новая панель: **outpatient.v1**, девять разделов китайской амбулаторной записи,
> несколько фактов в разделе, источники, ручные правки, проверка врачом и печать/сохранение PDF.
> Запуск: API как ниже, `cd apps/panel && npm ci && npm run dev`; http://127.0.0.1:5173.
> [Актуальный контракт](docs/outpatient-contract.md). Старый шестиполевый сценарий описан ниже
> и доступен через переключатель панели. ASR и роли ещё требуют подключения.


[Русский](README.md) | [English](README.en.md) | **中文**

本地中文门诊文本原型：对话 → 六个带患者原文证据的事实 → 草稿 → 人工复核 → JSON导出。
结构和原文检查不能保证医学正确。评估数据为合成样例，未经医生复核或临床验证。
医生界面、语音识别、诊断和完整SOAP仍需集成。

## 安装与启动（macOS / Linux，Python 3.11+，Ollama已运行）

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ollama pull qwen3.5:4b
.venv/bin/python -m smartmed.auth pavel
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

员工创建命令会隐藏输入密码（至少12字符），无需外部API密钥。
每个数据库只允许运行一个API进程，文件锁防止冲突。
在[Swagger](http://127.0.0.1:8000/docs)用 `staff_id` 和 `passcode` 登录，然后在Authorize中填入token。
Token有效期1小时，退出使其失效；连续5次未成功的登录尝试使该ID锁定15分钟。

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

界面使用异步任务，每秒查询一次状态；成功后按 `draft_id` 获取草稿，失败则展示错误码。
等待中的任务重启后继续，重启中断的执行任务标记为 `server_restart`，不自动重做。
容量为8个未完成任务，满时返回503和Retry-After。正在运行的任务不能删除（409）。
删除已完成任务不删除草稿。员工共享本地草稿，任务状态仅创建者可见。
草稿、任务和药品接口均需Bearer认证。操作者由token确定，正文可选身份必须与其一致。
凭据单独存储，密码及token均不以明文保存。

编辑需 `expected_version` 和 `document`，版本冲突返回409。
确认前查询 `/safety`；提交 `reviewed: true`、`expected_version` 及 `acknowledged_alerts`。
缺少必要的警告确认返回409；修改会清空确认状态及警告确认列表。
人工确认后才能导出；导出的是已报告事实，不是处方授权。
CORS只允许 `http://127.0.0.1:5173`，可用 `SMARTMED_BACKEND_FRONTEND_ORIGIN` 设置其他本机origin。

## 提取与安全

六个字段：发热、咳嗽、症状持续时间、青霉素过敏、已用药物、已用药物剂量。
状态为 `present`、`negated`、`unknown`；发言角色为patient、doctor、third_party，只能引用患者。
最多8000字符、160条发言；按句分段，每段最多1800字符。
单句超过1800字符时拒绝，不截断。保留全部字符和发言ID，合并后重新验证完整原文。
未知片段不覆盖有证据事实；冲突状态或不同值变为未知并要求复核。
跨段更正及指代仍需人工解释。

Ollama仅允许本机地址，temperature=0、seed=42、think=false、上下文16384。
生成中的证据选择约束与运行时原文验证保留；记录模型digest、prompt哈希、参数及分段元数据。
任何片段失败不保存部分草稿。具体v1 → v2迁移不改变医学事实，支持第三方角色及警告确认。
未知或损坏的存储版本返回409。咳嗽正则是有限合成样例的启发式；过敏和用药明确否认检查保持严格。

离线演示索引包含5种成分，附WHO ATC来源，不是中国药品注册数据库。
不提供剂量、替代药或完整相互作用判断。警告覆盖过敏或剂量未知、药物不在索引、
剂量无药物、青霉素类药物与未排除的过敏及分段冲突。参见[规则和来源](docs/safety-and-medications.md)。

## 保存与验证

数据库权限0600，合成草稿创建后保存7天，启动及每小时清理；
`SMARTMED_BACKEND_RETENTION_DAYS` 可设置1–365天。清理包含历史及关联任务。
任务成功或失败立即清除输入文本，已完成任务状态保留1小时，SQLite secure_delete已启用。
备份、导出、音频及实验结果需单独清理；这不是法律合规声明。

```sh
.venv/bin/ruff check src tests experiments/03_backend_smoke/run.py experiments/04_api_walkthrough/run.py experiments/05_backend_evaluation
.venv/bin/pytest tests experiments/02_model_comparison/test_scoring.py experiments/01_baseline/test_checks.py
.venv/bin/python experiments/05_backend_evaluation/run.py --models qwen3.5:4b qwen2.5:3b
```

CI无需Ollama。[实测结果](docs/backend-evaluation.md)区分历史40例四模型比较与当前API回归。
修改次数按固定参考模拟，不是医生实际修改；新样例运行前已固定，但未人工复核。
[集成合同](docs/backend-contract.md)、[标注规则](docs/annotation-guide.md)及
[交接消息](docs/denis-message.md)说明仍需联合集成和人工检查的部分。

## Панель врача / Doctor panel / 医生面板

`cd apps/panel && npm ci && npm run dev` — http://127.0.0.1:5173.
Сервисы ASR и диагнозов: [infra/README.md](infra/README.md).

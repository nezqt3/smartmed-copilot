# SmartMed Ambient EHR Copilot

[Русский](README.md) | [English](README.en.md) | **中文**

用于中文门诊病历草稿整理的本地助手。
当前已实现文本原型：对话 → 六个带原文证据的结构化字段 → 验证 → 草稿 → 人工确认 → JSON导出。
完整SOAP病历、语音识别、ICD编码映射和用药检查属于后续开发内容。

## 安装与启动

需要Python 3.11及以上版本，以及已安装并运行的Ollama服务。模型权重需单独下载。

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
ollama pull qwen3.5:4b
.venv/bin/pytest
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000
```

## API

启动后打开[Swagger](http://127.0.0.1:8000/docs)。完整接口定义通过`GET /openapi.json`获取，表单定义通过`GET /v1/form`获取。

```text
GET  /health
GET  /v1/form
POST /v1/drafts
GET  /v1/drafts/{id}
PUT  /v1/drafts/{id}
POST /v1/drafts/{id}/confirm
GET  /v1/drafts/{id}/history
GET  /v1/drafts/{id}/export
```

## 信息提取与验证

Qwen3.5 4B通过Ollama在本地运行，不调用外部模型API。
Instructor/Pydantic验证六个字段：发热、咳嗽、症状持续时间、青霉素过敏、已用药物、已用药物剂量。
状态为`present`（明确存在）、`negated`（明确否认）、`unknown`（未知）。
事实附有患者原文证据；验证失败后最多重试一次。

SQLite保存草稿及版本历史。修改后需重新确认，确认后方可导出。
结构和原文证据检查不能保证医学内容正确。测试样例为合成数据，尚未开展临床验证。

## 目录结构

- `src/smartmed/` — API、模型调用、数据结构与存储代码.
- `tests/` — 后端与数据结构测试.
- `examples/encounter_zh.json` — 中文对话示例.
- `experiments/01_baseline/` — 入门基线实验.
- `experiments/02_model_comparison/` — 本地模型比较.
- `experiments/03_backend_smoke/` — 生成回归检查.
- `experiments/04_api_walkthrough/` — 完整HTTP流程演示.
- `docs/` — 俄语、英语、中文三份项目方案（DOCX）.
- `tools/` — 文档生成器.
- `archive/` — 历史资料.

## 项目方案

[Русский](docs/SmartMed_Ambient_EHR_Copilot_RU.docx) · [English](docs/SmartMed_Ambient_EHR_Copilot_EN.docx) · [中文](docs/SmartMed_Ambient_EHR_Copilot_ZH.docx)

## 流程演示

API运行后，可执行以下命令重复完整流程。该脚本会在本地数据库创建一个合成案例草稿。结果保存在本地，不提交至Git。

```sh
.venv/bin/python experiments/04_api_walkthrough/run.py
```

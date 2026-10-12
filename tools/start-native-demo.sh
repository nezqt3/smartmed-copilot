#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

command -v ollama >/dev/null 2>&1 || { echo 'Установи нативную Ollama для GPU/Metal.' >&2; exit 1; }
[ -x .venv/bin/python ] || { echo 'Создай .venv и установи проект: pip install -e ".[dev]"' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Запусти Docker Desktop для ASR и справочника.' >&2; exit 1; }
curl --fail --silent --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null || {
  echo 'Запусти приложение Ollama или ollama serve.' >&2; exit 1;
}
ollama show qwen3.5:4b >/dev/null 2>&1 || ollama pull qwen3.5:4b
# Avoid running a second, CPU-only Qwen inside the Docker VM.
docker compose stop ollama ollama-model-init
# Finish the first model download before starting the bounded health wait.
docker compose -f compose.yaml -f compose.native.yaml up --build --no-deps \
  --exit-code-from asr-model-init asr-model-init
docker compose -f compose.yaml -f compose.native.yaml up --build -d \
  --wait --wait-timeout 180 asr terminology

export SMARTMED_BACKEND_OLLAMA_URL=http://127.0.0.1:11434
export SMARTMED_BACKEND_ASR_URL=http://127.0.0.1:18001
export SMARTMED_BACKEND_TERMINOLOGY_URL=http://127.0.0.1:18002
export SMARTMED_BACKEND_CPU_THREADS=${SMARTMED_BACKEND_CPU_THREADS:-2}
export SMARTMED_BACKEND_CONTEXT_TOKENS=${SMARTMED_BACKEND_CONTEXT_TOKENS:-8192}
staff_count=$(.venv/bin/python -c "from smartmed.auth import AuthStore; from pathlib import Path; import sqlite3; AuthStore(Path('data/staff.sqlite3')); d=sqlite3.connect('data/staff.sqlite3'); print(d.execute('select count(*) from staff').fetchone()[0])")
if [ "$staff_count" -eq 0 ]; then
  .venv/bin/python -m smartmed.auth demo_frontend
fi
cleanup() {
  if [ -n "${api_pid:-}" ]; then kill "$api_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
.venv/bin/uvicorn smartmed.api:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 &
api_pid=$!
ready=0
for attempt in $(seq 1 60); do
  kill -0 "$api_pid" 2>/dev/null || { echo 'API завершился. Проверь ошибку выше.' >&2; exit 1; }
  if curl --fail --silent --max-time 3 http://127.0.0.1:8000/health | grep -q '"status":"ready"'; then
    ready=1; break
  fi
  sleep 1
done
[ "$ready" -eq 1 ] || { echo 'Модель/API не готовы.' >&2; exit 1; }
echo 'Панель: http://127.0.0.1:5173. Ctrl+C завершает API и панель.'
cd apps/panel
[ -d node_modules ] || npm ci
npm run dev -- --strictPort

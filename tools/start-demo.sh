#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ "$(uname -s)" = "Darwin" ]; then
  exec sh tools/start-native-demo.sh
fi

if ! docker info >/dev/null 2>&1; then
  echo 'Docker не запущен. Открой Docker Desktop и повтори команду.' >&2
  exit 1
fi

docker compose up --build -d

echo 'Ожидаю готовности API и локальных моделей…'
ready=0
for attempt in $(seq 1 300); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8000/health | grep -q '"status":"ready"'; then
    ready=1
    break
  fi
  sleep 2
done

if [ "$ready" -ne 1 ]; then
  echo 'Сервисы не стали готовы за 10 минут. Проверь: docker compose ps и docker compose logs api asr ollama-model-init' >&2
  exit 1
fi

staff_count=$(docker compose exec -T api python -c "import sqlite3; d=sqlite3.connect('/app/data/staff.sqlite3'); print(d.execute('select count(*) from staff').fetchone()[0])")
if [ "$staff_count" -eq 0 ]; then
  echo 'Создай первого сотрудника для входа. Пароль от 12 символов, ввод скрыт.'
  docker compose exec api python -m smartmed.auth demo_frontend --database /app/data/staff.sqlite3
  echo 'Логин: demo_frontend'
else
  echo 'Учётная запись уже есть. Войди с её логином и паролем.'
fi

echo 'Панель: http://127.0.0.1:8080'
echo 'Остановить: docker compose down'

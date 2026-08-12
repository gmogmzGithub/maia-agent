#!/usr/bin/env bash
# Start the complete Stage 0 local topology and verify it.
#
#   1. one local PostgreSQL instance          (docker compose)
#   2. schema migrations                      (alembic upgrade head)
#   3. one pinned Hermes Runtime process      (hermes serve + product plugin)
#   4. one Product application process        (FastAPI + background loop)
#
# Nothing else runs. Logs land in var/log/.
#
# This script is the local operator entry point. It starts dependencies in the
# order the product needs them: database first, schema second, Hermes Runtime
# third, Product app last. That keeps failures obvious in logs and avoids a
# Product worker trying to process messages before the database or Hermes are
# reachable.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .env ]; then
  echo "error: .env is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

mkdir -p var/log var/run

echo "==> 1/4 PostgreSQL"
# PostgreSQL is the product system of record: Inbox, Outbox, appointments,
# properties, and Hermes session bindings all live there. Wait until pg_isready
# succeeds before applying migrations.
docker compose up -d db
until docker compose exec -T db pg_isready -U realestate -d realestate >/dev/null 2>&1; do
  sleep 1
done
echo "    ready"

echo "==> 2/4 Migrations"
# Run migrations before either runtime process can write new state.
"$REPO_ROOT/.venv/bin/alembic" upgrade head

echo "==> 3/4 Hermes Runtime"
# Reuse an already-running local Hermes if present; otherwise start the pinned
# runtime with this repo's HERMES_HOME and plugin env through hermes-serve.sh.
if curl -fsS "http://127.0.0.1:${HERMES_PORT:-9119}/api/health" >/dev/null 2>&1; then
  echo "    already running"
else
  nohup scripts/hermes-serve.sh > var/log/hermes.log 2>&1 &
  echo $! > var/run/hermes.pid
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${HERMES_PORT:-9119}/api/health" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  echo "    started (pid $(cat var/run/hermes.pid), log var/log/hermes.log)"
fi

APP_URL="http://${APP_HOST:-127.0.0.1}:${APP_PORT:-8080}"
# /health answers 503 when a dependency is degraded, which still means the
# application is up — poll for any HTTP response, not for a 2xx.
app_answers() { curl -s -o /dev/null "$APP_URL/health"; }

echo "==> 4/4 Product application"
# The Product process is last because its background loop may immediately poll
# Inbox rows and call Hermes. Starting it only after the DB and Hermes are up
# makes local failures much easier to reason about.
if app_answers; then
  echo "    already running"
else
  nohup scripts/run-app.sh > var/log/app.log 2>&1 &
  echo $! > var/run/app.pid
  for _ in $(seq 1 30); do
    app_answers && break
    sleep 1
  done
  echo "    started (pid $(cat var/run/app.pid), log var/log/app.log)"
fi

echo
echo "==> Health"
curl -s "$APP_URL/health" | "$REPO_ROOT/.venv/bin/python" -m json.tool

#!/usr/bin/env bash
# Start the pinned upstream Hermes Runtime with the standalone product plugin.
#
# Hermes runs from an unmodified checkout in its own virtualenv, against a
# repo-local HERMES_HOME so the developer's personal ~/.hermes is untouched.
#
# This is intentionally only Hermes. It does not start PostgreSQL or FastAPI;
# scripts/up.sh is the full topology command. Keeping this small makes it easy
# to restart just the agent runtime after changing roles/*/SOUL.md or Hermes
# config.
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

if [ -z "${HERMES_DASHBOARD_SESSION_TOKEN:-}" ]; then
  echo "error: HERMES_DASHBOARD_SESSION_TOKEN is empty in .env." >&2
  exit 1
fi

# This is the crucial isolation switch. Without it, Hermes would use ~/.hermes
# and would not see this project's generated sales/admin Role profiles.
export HERMES_HOME="${HERMES_HOME:-$REPO_ROOT/hermes-home}"
# The plugin runs inside the Hermes process, so these values must be exported
# into this process environment. The plugin never receives database or Calendar
# credentials; it only gets its own token and the Product API URL.
export REALESTATE_PLUGIN_API_TOKEN
export REALESTATE_BACKEND_URL

# HERMES_PORT is optional for local port conflicts. .env.example documents the
# normal value; the fallback keeps older .env files runnable.
PORT="${HERMES_PORT:-9119}"
HOST="${HERMES_HOST:-127.0.0.1}"
echo "Hermes serve on $HOST:$PORT (HERMES_HOME=$HERMES_HOME)"
exec "$REPO_ROOT/.venv-hermes/bin/hermes" serve --host "$HOST" --port "$PORT"

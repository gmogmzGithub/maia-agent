#!/usr/bin/env bash
# Start the one local Product application process: FastAPI plus the in-process
# background loop (ADR-0007).
#
# This script exists separately from hermes-serve.sh because the Product app and
# Hermes are different processes. The Product app owns PostgreSQL, business
# authority, Meta/Telegram/Calendar clients, and the worker loop; Hermes owns
# model conversation and tool calling.
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

# Always run uvicorn from the Product virtualenv. That keeps Product
# dependencies separate from the Hermes Runtime virtualenv.
# APP_HOST / APP_PORT may be omitted in older .env files; these fallbacks mirror
# .env.example and make local boot deterministic.
exec "$REPO_ROOT/.venv/bin/uvicorn" realestate.app:app \
  --host "${APP_HOST:-127.0.0.1}" \
  --port "${APP_PORT:-8080}"

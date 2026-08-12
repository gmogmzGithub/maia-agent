#!/usr/bin/env bash
# Stop the Stage 0 local topology started by scripts/up.sh.
#
# This script exists so shutdown is symmetric with startup: one command stops
# the Product process, the Hermes Runtime process, and the local PostgreSQL
# container without deleting the database volume.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

stop() {
  local name="$1" pattern="$2" pidfile="var/run/$1.pid"
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(cat "$pidfile")"
    # run-app.sh / hermes-serve.sh exec their child, so the recorded pid is the
    # real process; kill any descendants first in case that ever changes.
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    rm -f "$pidfile"
  fi
  # Backstop: a process started outside up.sh has no pid file. The pattern is
  # intentionally narrow so this does not kill unrelated Python or Hermes work.
  if pkill -f "$pattern" 2>/dev/null; then
    echo "stopped $name"
  fi
}

stop app 'uvicorn realestate.app:app'
stop hermes 'hermes serve --host 127.0.0.1'

# Compose down stops PostgreSQL but preserves the named volume. Do not add -v
# unless the intent is to delete the local product database.
docker compose down

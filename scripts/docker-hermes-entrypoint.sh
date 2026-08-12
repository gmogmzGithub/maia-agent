#!/usr/bin/env bash
set -euo pipefail

cd /opt/realestate
mkdir -p "${HERMES_HOME}/profiles"

# The shared generator uses the repository-relative hermes-home path for local
# development. In the image that path is a link to the durable Compose volume.
if [ -e hermes-home ] && [ ! -L hermes-home ]; then
  echo "error: /opt/realestate/hermes-home exists but is not the Hermes state volume" >&2
  exit 1
fi
ln -sfn "${HERMES_HOME}" hermes-home

# Profile config is derived from runtime environment values and role sources.
# This works with Compose env_file values and does not require copying secrets
# or the developer's local Hermes databases into the image.
./scripts/apply-models.sh

exec hermes serve --host "${HERMES_HOST:-0.0.0.0}" --port "${HERMES_PORT:-9119}"

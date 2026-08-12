#!/usr/bin/env bash
# Prepare the Stage 0 developer machine from a clean checkout.
#
# Creates two isolated virtual environments:
#   .venv          the Product application (Python 3.12, P-031)
#   .venv-hermes   the pinned upstream Hermes Runtime, installed from an
#                  UNMODIFIED checkout, plus this repo's standalone plugin
#
# This script exists because the Product process and the Hermes Runtime are two
# different processes with different dependency needs. Keeping two virtualenvs
# makes that boundary obvious:
#
#   .venv/bin/uvicorn          runs the FastAPI Product application
#   .venv-hermes/bin/hermes    runs upstream Hermes plus this repo's plugin
#
# It also generates .env with fresh local secrets on first run and never
# overwrites it. Existing .env files may contain real tokens, so updating
# defaults belongs in .env.example and an explicit local .env edit, not in a
# destructive rewrite here.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# Read the existing local configuration before resolving the Hermes checkout.
# This lets a server or another workstation pin a different checkout without
# putting a machine-specific path into the script itself.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
# Default to the sibling Hermes checkout used during development.
HERMES_CHECKOUT="${HERMES_CHECKOUT:-$HOME/workspace/repos/hermes-agent}"

if [ ! -d "$HERMES_CHECKOUT" ]; then
  echo "error: Hermes checkout not found at $HERMES_CHECKOUT" >&2
  echo "       Set HERMES_CHECKOUT to its location." >&2
  exit 1
fi

echo "==> Product virtualenv (.venv, Python 3.12)"
# Install the Product app editable so code changes under src/ are picked up by
# the next run without rebuilding a wheel.
uv venv --python 3.12 .venv
VIRTUAL_ENV="$REPO_ROOT/.venv" uv pip install -e ".[dev]" --quiet

echo "==> Hermes virtualenv (.venv-hermes) from $HERMES_CHECKOUT"
uv venv --python 3.12 .venv-hermes
# --no-deps for the checkout itself would skip the runtime; install normally.
# Editable install means .venv-hermes/bin/hermes executes the code from
# HERMES_CHECKOUT. That gives us an inspectable local Hermes runtime without
# copying Hermes into this repository.
VIRTUAL_ENV="$REPO_ROOT/.venv-hermes" uv pip install -e "$HERMES_CHECKOUT" --quiet
echo "==> Standalone product plugin into the Hermes virtualenv"
# The plugin is product code, but it must be installed into the Hermes env so
# Hermes discovers the realestate toolset through its normal plugin mechanism.
VIRTUAL_ENV="$REPO_ROOT/.venv-hermes" uv pip install -e ./plugin --quiet

if [ ! -f .env ]; then
  echo "==> Generating .env with fresh local secrets"
  # These are local shared secrets between the two local processes. They are not
  # stable credentials and must not be committed.
  HERMES_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  PLUGIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  DEVELOPER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  sed \
    -e "s|^HERMES_DASHBOARD_SESSION_TOKEN=.*|HERMES_DASHBOARD_SESSION_TOKEN=$HERMES_TOKEN|" \
    -e "s|^PLUGIN_API_TOKEN=.*|PLUGIN_API_TOKEN=$PLUGIN_TOKEN|" \
    -e "s|^REALESTATE_PLUGIN_API_TOKEN=.*|REALESTATE_PLUGIN_API_TOKEN=$PLUGIN_TOKEN|" \
    -e "s|^DEVELOPER_BASIC_PASSWORD=.*|DEVELOPER_BASIC_PASSWORD=$DEVELOPER_PASSWORD|" \
    .env.example > .env
  chmod 600 .env
else
  echo "==> .env already exists; leaving it untouched"
fi

echo "==> Hermes profile at $REPO_ROOT/hermes-home"
mkdir -p hermes-home
# Enable only the product plugin. Hermes plugins are opt-in; this file is the
# repo-local profile so the developer's personal ~/.hermes stays untouched.
# scripts/hermes-serve.sh points HERMES_HOME here at runtime.
write_profile_config() {
  cat > "$1" <<'YAML'
# Repo-local Hermes profile for the Stage 0 product runtime.
# Hermes core is unmodified; this only enables the standalone product plugin.
plugins:
  enabled:
    - realestate
YAML
}
[ -f hermes-home/config.yaml ] || write_profile_config hermes-home/config.yaml

# One Hermes profile per conversational Role (ADR-0001). Each profile's SOUL.md
# is that Role's byte-stable guide, so the two role surfaces stay separate and
# independently cacheable inside one runtime. Model choice comes from .env.
# apply-models.sh materializes roles/* into hermes-home/profiles/*.
echo "==> Role profiles and models"
./scripts/apply-models.sh

echo
echo "Bootstrap complete."
echo "  next: scripts/up.sh"

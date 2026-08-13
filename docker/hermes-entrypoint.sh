#!/usr/bin/env bash
set -euo pipefail

: "${HERMES_DASHBOARD_SESSION_TOKEN:?HERMES_DASHBOARD_SESSION_TOKEN is required}"
: "${REALESTATE_PLUGIN_API_TOKEN:?REALESTATE_PLUGIN_API_TOKEN is required}"
: "${MODEL_PROVIDER:?MODEL_PROVIDER is required}"
: "${SALES_MODEL:?SALES_MODEL is required}"
: "${ADMIN_MODEL:?ADMIN_MODEL is required}"

readonly MAIA_ROLES_ROOT="${MAIA_ROLES_ROOT:-/opt/maia/roles}"

mkdir -p "$HERMES_HOME/profiles/sales" "$HERMES_HOME/profiles/admin"

write_profile() {
  local role="$1" model="$2"
  cat > "$HERMES_HOME/profiles/$role/config.yaml" <<YAML
model:
  default: "$model"
  provider: "$MODEL_PROVIDER"
plugins:
  enabled:
    - realestate
# Product-created sessions must see Maia's small, fixed tool surface directly.
# Hermes's generic progressive-disclosure default otherwise hides plugin tools
# behind tool_search, which lets a model answer without consulting Product.
tools:
  tool_search: false
platform_toolsets:
  product:
    - realestate
YAML
  cp "$MAIA_ROLES_ROOT/$role/SOUL.md" "$HERMES_HOME/profiles/$role/SOUL.md"
}

cat > "$HERMES_HOME/config.yaml" <<YAML
model:
  default: "$ADMIN_MODEL"
  provider: "$MODEL_PROVIDER"
plugins:
  enabled:
    - realestate
tools:
  tool_search: false
platform_toolsets:
  product:
    - realestate
YAML

write_profile sales "$SALES_MODEL"
write_profile admin "$ADMIN_MODEL"

exec hermes serve --host 127.0.0.1 --port 9119

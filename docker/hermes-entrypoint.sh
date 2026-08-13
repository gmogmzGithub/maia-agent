#!/usr/bin/env bash
set -euo pipefail

: "${HERMES_DASHBOARD_SESSION_TOKEN:?HERMES_DASHBOARD_SESSION_TOKEN is required}"
: "${REALESTATE_PLUGIN_API_TOKEN:?REALESTATE_PLUGIN_API_TOKEN is required}"
: "${MODEL_PROVIDER:?MODEL_PROVIDER is required}"
: "${SALES_MODEL:?SALES_MODEL is required}"
: "${ADMIN_MODEL:?ADMIN_MODEL is required}"

readonly MAIA_ROLES_ROOT="${MAIA_ROLES_ROOT:-/opt/maia/roles}"

mkdir -p "$HERMES_HOME/profiles/sales" "$HERMES_HOME/profiles/admin"

# Every config Maia writes — root and per-profile — has the same shape, so the
# shape is spelled once here. Only the model differs.
#
# tool_search is off because Product-created sessions must see Maia's small,
# fixed tool surface directly. Hermes's generic progressive-disclosure default
# otherwise hides plugin tools behind tool_search, which lets a model answer
# without consulting Product.
write_config() {
  local path="$1" model="$2"
  cat > "$path" <<YAML
model:
  default: "$model"
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
}

write_profile() {
  local role="$1" model="$2"
  write_config "$HERMES_HOME/profiles/$role/config.yaml" "$model"
  cp "$MAIA_ROLES_ROOT/$role/SOUL.md" "$HERMES_HOME/profiles/$role/SOUL.md"
}

write_config "$HERMES_HOME/config.yaml" "$ADMIN_MODEL"
write_profile sales "$SALES_MODEL"
write_profile admin "$ADMIN_MODEL"

exec hermes serve --host 127.0.0.1 --port 9119

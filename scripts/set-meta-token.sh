#!/usr/bin/env bash
# Refresh the Meta access token in .env.
#
# Stage 0 runs on the WhatsApp *test* number, whose tokens are the 24-hour ones
# minted by "Generate new token" on the app's API Setup page. A permanent System
# User token belongs to the production-number path, which is blocked on S-016
# (the legal owner of the WhatsApp assets). Until then, this is the refresh:
#
#   ./scripts/set-meta-token.sh 'EAA...'
#
# This exists because bootstrap.sh intentionally never overwrites .env after
# first creation. Re-running bootstrap to refresh a 24-hour Meta token would risk
# changing unrelated local secrets, so this script updates only META_ACCESS_TOKEN
# and then validates the pasted token with Meta's debug_token endpoint.
#
# Prints the token's type and expiry so a stale paste is obvious immediately.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "usage: scripts/set-meta-token.sh '<access token>'" >&2
  exit 1
fi

python3 - "$TOKEN" <<'PY'
import pathlib, re, sys
token = sys.argv[1].strip()
p = pathlib.Path(".env")
# Replace only the token line. The rest of .env may contain local generated
# secrets and operator edits that must survive token refreshes.
p.write_text(re.sub(r"^META_ACCESS_TOKEN=.*$", f"META_ACCESS_TOKEN={token}", p.read_text(), flags=re.M))
p.chmod(0o600)
print("stored in .env")
PY

python3 - "$TOKEN" <<'PY'
import json, subprocess, sys
from datetime import datetime, timezone

token = sys.argv[1].strip()
# Use the token to introspect itself; this catches bad copies before a live
# WhatsApp test fails later in the worker.
url = f"https://graph.facebook.com/v25.0/debug_token?input_token={token}"
raw = subprocess.run(
    ["curl", "-s", url, "-H", f"Authorization: Bearer {token}"],
    capture_output=True, text=True,
).stdout
try:
    data = json.loads(raw)["data"]
except Exception:
    print(f"could not introspect the token: {raw[:200]}")
    raise SystemExit(1)

if not data.get("is_valid"):
    print("REJECTED: Meta says this token is not valid.")
    raise SystemExit(1)

expires = data.get("expires_at")
if expires in (0, None):
    print("valid, expires: NEVER")
else:
    when = datetime.fromtimestamp(expires, tz=timezone.utc)
    hours = (when - datetime.now(timezone.utc)).total_seconds() / 3600
    print(f"valid, expires: {when.isoformat()} ({hours:.1f}h from now)")
    if hours < 1:
        print("WARNING: under an hour left — generate a fresh one before a long test.")
PY

echo "Restart the app to pick it up:  pkill -f 'uvicorn realestate.app' && ./scripts/up.sh"

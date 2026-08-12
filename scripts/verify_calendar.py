"""Check that the Google Calendar service account can actually see the calendar.

Run this after the setup in Downloads/checkpoint-3-requirements.md Part B1. It
proves the two things that go wrong most often — the key is valid, and the
calendar was actually shared with the service account — before any product code
depends on them.

    ./.venv/bin/python scripts/verify_calendar.py

Reads GOOGLE_CALENDAR_CREDENTIALS (path to the JSON key) and GOOGLE_CALENDAR_ID
from .env.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from realestate.channels.google.calendar import SCOPES  # noqa: E402
from realestate.config import Settings  # noqa: E402


def main() -> int:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        sys.exit("error: .env is missing. Run scripts/bootstrap.sh first.")

    # The application's own settings model, so this verifies the values the
    # product will actually read. The env file is named explicitly: the model's
    # default is CWD-relative, and this script must work from any directory.
    settings = Settings(_env_file=env_file)
    key_path = settings.google_calendar_credentials.strip()
    calendar_id = settings.google_calendar_id.strip()

    if not key_path or not calendar_id:
        print("Not configured yet. Add to .env:")
        print("  GOOGLE_CALENDAR_CREDENTIALS=/path/to/service-account.json")
        print("  GOOGLE_CALENDAR_ID=you@gmail.com")
        return 1

    key_file = Path(key_path).expanduser()
    if not key_file.is_file():
        print(f"FAIL  key file not found: {key_file}")
        return 1

    try:
        key = json.loads(key_file.read_text())
    except ValueError:
        print(f"FAIL  {key_file} is not valid JSON")
        return 1

    client_email = key.get("client_email")
    if key.get("type") != "service_account" or not client_email:
        print("FAIL  that JSON is not a service-account key")
        print("      (Credentials -> Create credentials -> Service account -> JSON key)")
        return 1

    print(f"key file    OK    service account: {client_email}")

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        # calendar.py imports the Google SDK lazily, so importing SCOPES above
        # succeeds even when the SDK is absent. Say so usefully rather than
        # dying on a traceback.
        print("FAIL  the Google client libraries are not installed.")
        print("      Run scripts/bootstrap.sh, or:")
        print("      VIRTUAL_ENV=.venv uv pip install google-api-python-client google-auth")
        return 1

    # The product's scopes, not a second copy: a scope change there must change
    # what this verifies.
    credentials = service_account.Credentials.from_service_account_file(
        str(key_file), scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    # 1. Can the service account see the calendar at all?
    try:
        calendar = service.calendars().get(calendarId=calendar_id).execute()
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        print(f"FAIL  cannot read calendar {calendar_id}")
        print(f"      {exc}")
        print()
        print("      Almost always this means the calendar was not shared with")
        print(f"      {client_email}.")
        print("      Google Calendar -> that calendar -> Settings and sharing ->")
        print("      Share with specific people -> add it as 'Make changes to events'.")
        return 1

    print(f"calendar    OK    {calendar.get('summary')} ({calendar.get('timeZone')})")

    # 2. Can it read busy time? This is what availability will depend on.
    now = datetime.now(tz=UTC)
    busy = (
        service.freebusy()
        .query(
            body={
                "timeMin": now.isoformat(),
                "timeMax": (now + timedelta(days=14)).isoformat(),
                "items": [{"id": calendar_id}],
            }
        )
        .execute()
    )
    periods = busy["calendars"][calendar_id].get("busy", [])
    print(f"free/busy   OK    {len(periods)} busy period(s) in the next 14 days")

    # 3. Can it write? Create and immediately delete a probe event.
    probe = {
        "summary": "[verificación] borrar si aparece",
        "start": {"dateTime": (now + timedelta(days=400)).isoformat()},
        "end": {"dateTime": (now + timedelta(days=400, hours=1)).isoformat()},
    }
    try:
        created = service.events().insert(calendarId=calendar_id, body=probe).execute()
        service.events().delete(calendarId=calendar_id, eventId=created["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        print("FAIL  can read but cannot write.")
        print(f"      {exc}")
        print("      The share permission is probably 'See all event details'")
        print("      rather than 'Make changes to events'.")
        return 1

    print("write       OK    created and deleted a probe event")
    print()
    print("Ready for Checkpoint 3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

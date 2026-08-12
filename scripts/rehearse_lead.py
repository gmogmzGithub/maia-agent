"""Drive one Lead conversation through the running application's webhook.

A rehearsal harness, not a test double: the payload is signed with the real app
secret and every layer behind the webhook is the real one — Inbox, worker,
Hermes, the product tools, Google Calendar, the Outbox, and the Broker's
Telegram notifications. Only the inbound leg is synthesised.

Its purpose is to exercise the Sales guide and the appointment path before a
person spends a live WhatsApp session on it. Use a number that is not a real
WhatsApp user so the outbound leg fails loudly instead of messaging someone:

    ./.venv/bin/python scripts/rehearse_lead.py --wa-id 5215550000001 \
        "hola, me interesa Casa Roble" "el viernes por la tarde"

Each argument is one Lead message, sent and then waited on until the
application releases a reply.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from realestate.channels.whatsapp.signature import compute_signature  # noqa: E402
from realestate.config import get_settings  # noqa: E402
from realestate.db.engine import Database  # noqa: E402
from realestate.db.models import OutboxMessage  # noqa: E402
from tests.fixtures import webhooks  # noqa: E402


async def released(database: Database, seen: set[str]) -> list[OutboxMessage]:
    from sqlalchemy import select

    async with database.session_scope() as session:
        rows = (
            (await session.execute(select(OutboxMessage).order_by(OutboxMessage.created_at)))
            .scalars()
            .all()
        )
        return [r for r in rows if str(r.id) not in seen]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("messages", nargs="+")
    parser.add_argument("--wa-id", default="5215550000001")
    parser.add_argument("--name", default="Rehearsal")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    settings = get_settings()
    url = "http://127.0.0.1:8080/webhooks/whatsapp"
    database = Database(settings.database_url)
    seen: set[str] = set()
    for row in await released(database, set()):
        seen.add(str(row.id))

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for index, text in enumerate(args.messages):
                payload = webhooks.text_message(
                    wamid=f"rehearsal.{int(time.time())}.{index}",
                    body=text,
                    from_wa_id=args.wa_id,
                    profile_name=args.name,
                )
                body = json.dumps(payload).encode("utf-8")
                response = await client.post(
                    url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": compute_signature(
                            settings.meta_app_secret, body
                        ),
                    },
                )
                print(f"\n> {text}   [webhook {response.status_code}]")

                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline:
                    new = await released(database, seen)
                    if new:
                        for row in new:
                            seen.add(str(row.id))
                            print(f"\n< [{row.kind} / {row.status}] {row.body}")
                        break
                    await asyncio.sleep(1.0)
                else:
                    print("\n< (no reply within the timeout)")
                    return 1
    finally:
        await database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

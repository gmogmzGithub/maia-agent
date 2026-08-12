"""Exercise the Administrative Role locally, without Telegram (Checkpoint 4).

The Telegram transport is covered by tests; this drives the same Administrative
session the worker would, so the natural-language behaviour can be checked
before a bot token exists.

    ./.venv/bin/python scripts/admin_session.py --new "desactiva Casa Roble"
    ./.venv/bin/python scripts/admin_session.py "y actívala de nuevo"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from realestate.config import get_settings  # noqa: E402
from realestate.db.engine import Database  # noqa: E402
from realestate.db.models import AgentRole, AgentSession  # noqa: E402
from realestate.hermes import HermesClient  # noqa: E402
from realestate.hermes.sessions import (  # noqa: E402
    RoleSession,
    bind_channel_session,
    submit_prompt,
)

CHANNEL_KEY = "local:admin-exercise"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--new", action="store_true", help="start a fresh session")
    args = parser.parse_args()

    settings = get_settings()
    client = HermesClient.from_settings(settings)
    health = await client.check_health()
    if not health.ok:
        print(f"Hermes is not usable [{health.status.value}]: {health.detail}")
        await client.aclose()
        return 1

    database = Database(settings.database_url)
    try:
        async with database.session_scope() as db:
            existing = (
                await db.execute(
                    select(AgentSession).where(AgentSession.channel_key == CHANNEL_KEY)
                )
            ).scalar_one_or_none()
            if args.new and existing is not None:
                await db.delete(existing)
                await db.commit()
                existing = None
            session = RoleSession(
                gateway_session_id="",
                hermes_session_id=existing.hermes_session_id if existing else "",
                role=AgentRole.ADMINISTRATIVE,
            )

        text = " ".join(args.prompt).strip()
        if not text:
            return 0

        async def bind(hermes_session_id: str) -> None:
            async with database.session_scope() as db:
                await bind_channel_session(
                    db,
                    role=AgentRole.ADMINISTRATIVE,
                    channel_key=CHANNEL_KEY,
                    hermes_session_id=hermes_session_id,
                )

        print(f"\n> {text}")
        turn = await submit_prompt(
            client, session, text, profile=settings.admin_profile, on_attached=bind
        )
        print(f"\n{turn.text}\n")
        print(f"[tools observed: {', '.join(turn.tools_used) or 'none'}]")
    finally:
        await client.aclose()
        await database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

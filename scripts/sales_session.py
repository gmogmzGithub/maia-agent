"""Exercise one persistent Hermes Sales session locally (Checkpoint 1).

This is the pre-WhatsApp harness the implementation plan asks for: it creates a
Sales Role session against the pinned runtime, binds it to the Sales Role in
PostgreSQL, and sends prompts to it. Checkpoint 2 replaces this caller with the
durable Inbox worker; the JSON-RPC and binding contracts it uses do not change.

    ./.venv/bin/python scripts/sales_session.py --new "hola, cuánto cuesta Casa Roble?"
    ./.venv/bin/python scripts/sales_session.py "y cuántos baños tiene?"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from realestate.config import get_settings  # noqa: E402
from realestate.db.engine import Database  # noqa: E402
from realestate.db.models import AgentRole  # noqa: E402
from realestate.hermes import HermesClient  # noqa: E402
from realestate.hermes.sessions import (  # noqa: E402
    RoleSession,
    bind_role_session,
    find_role_session,
    submit_prompt,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="*", help="text to send to the Sales Role")
    parser.add_argument(
        "--new", action="store_true", help="create a fresh Sales session first"
    )
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
            session = None if args.new else await find_role_session(db, AgentRole.SALES)
            if session is None:
                # Bound lazily: the durable session id only exists once a turn
                # has actually run (see hermes/sessions.py::_attach).
                session = RoleSession(
                    gateway_session_id="",
                    hermes_session_id="",
                    role=AgentRole.SALES,
                )

        text = " ".join(args.prompt).strip()
        if not text:
            return 0

        print(f"\n> {text}")

        async def bind(hermes_session_id: str) -> None:
            # The plugin resolves Role from this binding, so it must exist
            # before the model can reach for a tool.
            async with database.session_scope() as db:
                await bind_role_session(
                    db, role=AgentRole.SALES, hermes_session_id=hermes_session_id
                )
            print(f"[bound Sales session {hermes_session_id}]")

        turn = await submit_prompt(
            client, session, text, profile=settings.sales_profile, on_attached=bind
        )
        print(f"\n{turn.text}\n")
        if turn.tools_used:
            print(f"[tools observed: {', '.join(turn.tools_used)}]")
    finally:
        await client.aclose()
        await database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

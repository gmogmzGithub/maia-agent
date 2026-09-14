"""The website worker completes durable turns outside the request path."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from realestate.db.engine import Database
from realestate.domain.public.website_conversation import (
    WebsiteCommand,
    WebsiteConversation,
    WebsiteReply,
    WebsiteTurn,
)
from realestate.worker.website import WebsiteConversationWorker
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import product_actor, provision, reset

pytestmark = requires_postgres
MOMENT = datetime(2026, 9, 13, 20, 0, tzinfo=UTC)


class FixedResponder:
    async def respond(self, turn: WebsiteTurn) -> WebsiteReply:
        return WebsiteReply("Encontré propiedades públicas.", "website-hermes-1")


@pytest.fixture
async def database() -> Database:
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await session.commit()
        await reset(session, members=True)
        await provision(session)
    yield database
    await database.dispose()


async def test_worker_completes_a_queued_turn_and_leaves_no_pending_work(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        module = WebsiteConversation(session, await product_actor(session), FixedResponder())
        accepted = await module.enqueue(
            WebsiteCommand(
                message="Enséñame propiedades en Zapopan",
                command_key=f"website-worker-{uuid.uuid4()}",
            ),
            at=MOMENT,
        )
        await session.commit()

    worker = WebsiteConversationWorker(
        database,
        object(),
        "website",
        responder=FixedResponder(),
    )
    assert await worker.tick() is True
    assert await worker.tick() is False

    async with database.session_scope() as session:
        progress = await WebsiteConversation(
            session, await product_actor(session), FixedResponder()
        ).progress(accepted.turn_id, accepted.conversation_token)

    assert progress.status == "Complete"
    assert progress.result is not None
    assert progress.result["reply"] == "Encontré propiedades públicas."


async def test_closing_a_conversation_cancels_its_queued_turn(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        module = WebsiteConversation(
            session, await product_actor(session), FixedResponder()
        )
        accepted = await module.enqueue(
            WebsiteCommand(
                message="Enséñame propiedades",
                command_key=f"website-worker-close-{uuid.uuid4()}",
            ),
            at=MOMENT,
        )
        assert await module.close(
            accepted.conversation_token,
            at=MOMENT,
            delete_content=False,
        )
        await session.commit()

    worker = WebsiteConversationWorker(
        database,
        object(),
        "website",
        responder=FixedResponder(),
    )
    assert await worker.tick() is False

    async with database.session_scope() as session:
        progress = await WebsiteConversation(
            session, await product_actor(session), FixedResponder()
        ).progress(accepted.turn_id, accepted.conversation_token)

    assert progress.status == "Failed"
    assert progress.error_message == "La conversación terminó antes de responder."

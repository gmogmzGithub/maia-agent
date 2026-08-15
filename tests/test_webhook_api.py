"""The Meta webhook endpoint: authentication, durability, idempotency.

The exit-condition property under test is that *every inbound message survives
in PostgreSQL* and *a duplicate Meta webhook creates neither duplicate
processing nor a duplicate reply*.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, func, select

from realestate.api.webhooks import WEBHOOK_PATH
from realestate.app import create_app
from realestate.channels.whatsapp.signature import SIGNATURE_HEADER, compute_signature
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    Conversation,
    DeliveryStatus,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    OutboxMessage,
)
from realestate.domain.properties import ArtifactStore
from tests.conftest import DATABASE_URL, env, requires_postgres
from tests.fixtures import webhooks

pytestmark = requires_postgres

SECRET = env("META_APP_SECRET")


@pytest.fixture
async def wired(tmp_path: Path):
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await session.execute(delete(DeliveryStatus))
        await session.execute(delete(OutboxMessage))
        await session.execute(delete(InboxMessage))
        await session.execute(delete(Conversation))
        await session.execute(delete(LeadEngagementCycle))
        await session.execute(delete(Lead))
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app
    await database.dispose()


async def post(client, body: dict, *, secret: str | None = None):
    return await webhooks.post_signed(
        client, WEBHOOK_PATH, body, SECRET if secret is None else secret
    )


async def count(app, model) -> int:
    async with app.state.database.session_scope() as session:
        return (await session.execute(select(func.count(model.id)))).scalar_one()


# --- Verification handshake --------------------------------------------------


async def test_the_handshake_echoes_the_challenge_for_the_right_token(wired) -> None:
    client, _ = wired

    response = await client.get(
        WEBHOOK_PATH,
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1158201444",
            "hub.verify_token": env("META_VERIFY_TOKEN"),
        },
    )

    assert response.status_code == 200
    assert response.text == "1158201444"


async def test_the_handshake_rejects_a_wrong_token(wired) -> None:
    client, _ = wired

    response = await client.get(
        WEBHOOK_PATH,
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "1158201444",
            "hub.verify_token": "wrong",
        },
    )

    assert response.status_code == 403
    assert "1158201444" not in response.text


# --- Payload authentication --------------------------------------------------


async def test_an_unsigned_payload_is_rejected_and_persists_nothing(wired) -> None:
    client, app = wired
    body = webhooks.text_message(wamid="wamid.UNSIGNED", body="hola")

    response = await client.post(WEBHOOK_PATH, content=webhooks.encode(body))

    assert response.status_code == 403
    assert await count(app, InboxMessage) == 0


async def test_a_forged_signature_is_rejected_and_persists_nothing(wired) -> None:
    client, app = wired
    body = webhooks.text_message(wamid="wamid.FORGED", body="hola")

    response = await post(client, body, secret="not-the-app-secret")

    assert response.status_code == 403
    assert response.json()["result"] == "invalid_signature"
    assert await count(app, InboxMessage) == 0


# --- Durable acceptance ------------------------------------------------------


async def test_an_authenticated_message_is_persisted_before_acknowledgement(
    wired,
) -> None:
    client, app = wired

    response = await post(
        client, webhooks.text_message(wamid="wamid.A1", body="hola, informes?")
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    async with app.state.database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()

    assert message.wamid == "wamid.A1"
    assert message.text == "hola, informes?"
    assert message.status == InboxStatus.PENDING.value
    assert message.from_wa_id == webhooks.LEAD_WA_ID


async def test_the_complete_meta_object_is_retained(wired) -> None:
    # V-001: the referral payload must survive untouched for inspection, and no
    # Property is derived from it (P-049).
    client, app = wired

    await post(
        client,
        webhooks.text_message(
            wamid="wamid.REF", body="hola", referral=webhooks.SAMPLE_REFERRAL
        ),
    )

    async with app.state.database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()
        conversation = (await session.execute(select(Conversation))).scalar_one()

    assert message.raw_message["referral"] == webhooks.SAMPLE_REFERRAL
    assert message.raw_message["text"]["body"] == "hola"
    # No Property was guessed from the advertisement reference.
    assert conversation.property_uuid is None


async def test_a_lead_cycle_and_conversation_are_created_once(wired) -> None:
    client, app = wired

    await post(client, webhooks.text_message(wamid="wamid.B1", body="primero"))
    await post(client, webhooks.text_message(wamid="wamid.B2", body="segundo"))

    assert await count(app, Lead) == 1
    assert await count(app, LeadEngagementCycle) == 1
    assert await count(app, Conversation) == 1
    assert await count(app, InboxMessage) == 2


async def test_the_engagement_deadline_does_not_move_on_a_later_message(wired) -> None:
    # P-004: activity inside the cycle does not reset the fixed 30-day window.
    client, app = wired
    await post(client, webhooks.text_message(wamid="wamid.C1", body="uno"))
    async with app.state.database.session_scope() as session:
        first = (await session.execute(select(LeadEngagementCycle))).scalar_one()
        original_deadline = first.expires_at

    await post(client, webhooks.text_message(wamid="wamid.C2", body="dos"))

    async with app.state.database.session_scope() as session:
        cycle = (await session.execute(select(LeadEngagementCycle))).scalar_one()

    assert cycle.expires_at == original_deadline


# --- Idempotency -------------------------------------------------------------


async def test_a_duplicate_webhook_creates_no_second_record(wired) -> None:
    client, app = wired
    body = webhooks.text_message(wamid="wamid.DUP", body="hola")

    first = await post(client, body)
    second = await post(client, body)

    assert first.json()["accepted"] == 1
    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1
    assert await count(app, InboxMessage) == 1
    assert await count(app, Lead) == 1
    assert await count(app, Conversation) == 1


async def test_a_duplicate_does_not_reset_message_state(wired) -> None:
    client, app = wired
    body = webhooks.text_message(wamid="wamid.DUP2", body="hola")
    await post(client, body)

    async with app.state.database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()
        message.status = InboxStatus.PROCESSED.value
        await session.commit()

    await post(client, body)

    async with app.state.database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()

    # A replayed webhook must not drag completed work back into the queue.
    assert message.status == InboxStatus.PROCESSED.value


# --- Delivery statuses -------------------------------------------------------


async def test_a_delivery_status_is_persisted_as_product_state(wired) -> None:
    client, app = wired

    response = await post(
        client, webhooks.status_update(provider_message_id="wamid.OUT1", status="delivered")
    )

    assert response.json()["statuses"] == 1
    async with app.state.database.session_scope() as session:
        record = (await session.execute(select(DeliveryStatus))).scalar_one()

    assert record.provider_message_id == "wamid.OUT1"
    assert record.status == "delivered"


async def test_a_delivery_status_is_linked_to_its_outbox_row(wired) -> None:
    client, app = wired
    await post(client, webhooks.text_message(wamid="wamid.D1", body="hola"))

    async with app.state.database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        session.add(
            OutboxMessage(
                conversation_id=conversation.id,
                idempotency_key=f"reply:{uuid.uuid4()}",
                to_wa_id=webhooks.LEAD_WA_ID,
                kind="AgentReply",
                body="respuesta",
                covered_inbox_ids=[],
                status="Sent",
                provider_message_id="wamid.OUTBOUND",
            )
        )
        await session.commit()

    await post(
        client,
        webhooks.status_update(provider_message_id="wamid.OUTBOUND", status="read"),
    )

    async with app.state.database.session_scope() as session:
        record = (await session.execute(select(DeliveryStatus))).scalar_one()
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()

    assert record.outbox_id == outbox.id


async def test_a_repeated_delivery_status_is_absorbed(wired) -> None:
    client, app = wired
    body = webhooks.status_update(provider_message_id="wamid.OUT2", status="sent")

    await post(client, body)
    await post(client, body)

    assert await count(app, DeliveryStatus) == 1


# --- A signed body that is not JSON -----------------------------------------


async def test_a_correctly_signed_body_that_is_not_json_is_a_400(wired) -> None:
    """Authentic but unparseable. A 500 would make Meta retry it forever, and a
    200 would acknowledge something that was never stored."""
    client, app = wired
    raw = b"this is authentic, and it is not JSON"

    response = await client.post(
        WEBHOOK_PATH,
        content=raw,
        headers={
            SIGNATURE_HEADER: compute_signature(SECRET, raw),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"result": "invalid_json"}
    assert await count(app, InboxMessage) == 0


async def test_an_unsigned_non_json_body_is_rejected_before_it_is_parsed(wired) -> None:
    client, app = wired

    response = await client.post(
        WEBHOOK_PATH, content=b"garbage", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 403
    assert response.json() == {"result": "invalid_signature"}
    assert await count(app, InboxMessage) == 0

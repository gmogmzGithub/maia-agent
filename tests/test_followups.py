"""Deterministic WhatsApp-only Lead follow-ups."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from realestate.db.engine import Database
from realestate.db.models import (
    Conversation,
    Lead,
    LeadEngagementCycle,
    LeadFollowUp,
    LeadFollowUpStatus,
    OutboxMessage,
)
from realestate.domain.followups import CADENCE_DAYS, LeadFollowUpService
from tests.conftest import DATABASE_URL, requires_postgres

pytestmark = requires_postgres

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        for model in (
            LeadFollowUp,
            OutboxMessage,
            Conversation,
            LeadEngagementCycle,
            Lead,
        ):
            await session.execute(delete(model))
        await session.commit()
    yield db
    await db.dispose()


async def cycle(
    database: Database,
    *,
    wa_id: str = "5215551230000",
    started_at: datetime = NOW,
    opt_out: bool = False,
) -> None:
    async with database.session_scope() as session:
        lead = Lead(wa_id=wa_id, follow_up_opt_out=opt_out)
        session.add(lead)
        await session.flush()
        row = LeadEngagementCycle(
            lead_id=lead.id,
            started_at=started_at,
            expires_at=started_at + timedelta(days=30),
        )
        session.add(row)
        await session.flush()
        session.add(
            Conversation(
                lead_id=lead.id,
                cycle_id=row.id,
                phone_number_id="123456",
            )
        )
        await session.commit()


async def enqueue(database: Database, now: datetime = NOW, limit: int = 20) -> int:
    async with database.session_scope() as session:
        return await LeadFollowUpService(session).enqueue_due(now=now, limit=limit)


async def followups(database: Database) -> list[LeadFollowUp]:
    async with database.session_scope() as session:
        return list(
            (
                await session.execute(
                    select(LeadFollowUp).order_by(LeadFollowUp.day_number)
                )
            )
            .scalars()
            .all()
        )


async def outbox(database: Database) -> list[OutboxMessage]:
    async with database.session_scope() as session:
        return list(
            (
                await session.execute(
                    select(OutboxMessage).order_by(OutboxMessage.created_at)
                )
            )
            .scalars()
            .all()
        )


async def test_the_whatsapp_cadence_is_santiagos_normalized_days() -> None:
    assert CADENCE_DAYS == (1, 5, 7, 14, 18, 22, 26, 28)


async def test_day_one_enqueues_one_whatsapp_followup(database) -> None:
    await cycle(database)

    assert await enqueue(database) == 1

    rows = await followups(database)
    messages = await outbox(database)
    assert [row.day_number for row in rows] == [1]
    assert rows[0].status == LeadFollowUpStatus.ENQUEUED.value
    assert rows[0].outbox_id == messages[0].id
    assert messages[0].kind == "LeadFollowUp"
    assert messages[0].to_wa_id == "5215551230000"
    assert "horario" in messages[0].body


async def test_repeating_the_tick_does_not_duplicate_the_same_day(database) -> None:
    await cycle(database)

    assert await enqueue(database) == 1
    assert await enqueue(database) == 0

    assert len(await followups(database)) == 1
    assert len(await outbox(database)) == 1


async def test_si_two_and_day_twenty_two_are_normalized_to_single_days(
    database,
) -> None:
    await cycle(database, started_at=NOW - timedelta(days=21))

    assert await enqueue(database) == 6

    assert [row.day_number for row in await followups(database)] == [
        1,
        5,
        7,
        14,
        18,
        22,
    ]


async def test_future_days_are_not_enqueued_early(database) -> None:
    await cycle(database, started_at=NOW - timedelta(days=3))

    assert await enqueue(database) == 1

    assert [row.day_number for row in await followups(database)] == [1]


async def test_follow_up_opt_out_suppresses_the_cadence(database) -> None:
    await cycle(database, opt_out=True)

    assert await enqueue(database) == 0
    assert await followups(database) == []
    assert await outbox(database) == []


async def test_a_skipped_backfill_row_prevents_catchup_delivery(database) -> None:
    await cycle(database, started_at=NOW - timedelta(days=6))
    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        session.add(
            LeadFollowUp(
                cycle_id=conversation.cycle_id,
                conversation_id=conversation.id,
                day_number=1,
                channel="WhatsApp",
                due_at=NOW - timedelta(days=6),
                status=LeadFollowUpStatus.SKIPPED.value,
            )
        )
        await session.commit()

    assert await enqueue(database) == 2

    rows = await followups(database)
    assert [(row.day_number, row.status) for row in rows] == [
        (1, LeadFollowUpStatus.SKIPPED.value),
        (5, LeadFollowUpStatus.ENQUEUED.value),
        (7, LeadFollowUpStatus.ENQUEUED.value),
    ]

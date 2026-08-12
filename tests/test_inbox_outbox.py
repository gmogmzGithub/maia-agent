"""Inbox claiming, retries, recovery, and Outbox delivery classification.

These cover the durability properties Checkpoint 2 rests on and Checkpoint 5
will lean on: FIFO per Conversation, one active group per Conversation, fenced
leases, bounded retries, and the three-way send outcome.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.db.engine import Database
from realestate.db.models import (
    Conversation,
    InboxGroup,
    InboxGroupStatus,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.inbox import MAX_ATTEMPTS, InboxService
from realestate.domain.outbox import OutboxKind, OutboxService
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import webhooks

pytestmark = requires_postgres


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await session.execute(delete(OutboxMessage))
        await session.execute(delete(InboxMessage))
        await session.execute(delete(InboxGroup))
        await session.execute(delete(Conversation))
        await session.execute(delete(LeadEngagementCycle))
        await session.execute(delete(Lead))
        await session.commit()
    yield db
    await db.dispose()


def inbound(wamid: str, body: str, *, seconds_ago: int = 0):
    payload = webhooks.text_message(
        wamid=wamid,
        body=body,
        timestamp=int(datetime.now(tz=UTC).timestamp()) - seconds_ago,
    )
    return parse_webhook(payload).messages[0]


async def accept_all(database, *messages) -> None:
    async with database.session_scope() as session:
        service = InboxService(session)
        for message in messages:
            await service.accept(message)


async def age_out_collection_window(database) -> None:
    """Backdate persistence so the two-second collection window has elapsed."""
    async with database.session_scope() as session:
        for row in (await session.execute(select(InboxMessage))).scalars():
            row.persisted_at = datetime.now(tz=UTC) - timedelta(seconds=10)
        await session.commit()


# --- Collection window and grouping ------------------------------------------


async def test_a_conversation_is_not_claimable_inside_the_collection_window(
    database,
) -> None:
    await accept_all(database, inbound("w1", "hola"))

    async with database.session_scope() as session:
        assert await InboxService(session).claimable_conversations(3) == []


async def test_rapid_fragments_are_claimed_as_one_group(database) -> None:
    await accept_all(
        database,
        inbound("w1", "hola", seconds_ago=3),
        inbound("w2", "me interesa Casa Roble", seconds_ago=2),
        inbound("w3", "cuánto cuesta?", seconds_ago=1),
    )
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        conversation_id = (await service.claimable_conversations(3))[0]
        group = await service.claim(conversation_id)

    assert group is not None
    assert len(group.messages) == 3
    # Arrival order is preserved, and every source record survives separately.
    assert group.combined_text() == "hola\nme interesa Casa Roble\ncuánto cuesta?"
    assert len(group.inbox_ids) == 3


async def test_claiming_marks_messages_processing_and_counts_an_attempt(
    database,
) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        conversation_id = (await service.claimable_conversations(3))[0]
        await service.claim(conversation_id)

    async with database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()

    assert message.status == InboxStatus.PROCESSING.value
    assert message.attempts == 1
    assert message.group_id is not None


# --- One active group per Conversation ---------------------------------------


async def test_a_second_claim_on_the_same_conversation_is_refused(database) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session_a:
        first = await InboxService(session_a).claim(
            (await InboxService(session_a).claimable_conversations(3))[0]
        )
        assert first is not None

        async with database.session_scope() as session_b:
            second = await InboxService(session_b).claim(first.conversation_id)

    assert second is None, "the database must enforce one active lane per Conversation"


async def test_a_claimed_conversation_is_no_longer_listed(database) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        conversation_id = (await service.claimable_conversations(3))[0]
        await service.claim(conversation_id)
        assert await service.claimable_conversations(3) == []


async def test_separate_conversations_proceed_independently(database) -> None:
    await accept_all(
        database,
        inbound("w1", "hola"),
        inbound("w2", "hola", seconds_ago=1),
    )
    # A second Lead writes from a different number.
    other = parse_webhook(
        webhooks.text_message(wamid="w3", body="hola", from_wa_id="5213311112222")
    ).messages[0]
    await accept_all(database, other)
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        claimable = await InboxService(session).claimable_conversations(3)

    assert len(claimable) == 2


# --- Settlement --------------------------------------------------------------


async def test_settling_marks_every_message_processed(database) -> None:
    await accept_all(database, inbound("w1", "hola"), inbound("w2", "otra"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        group = await service.claim((await service.claimable_conversations(3))[0])
        assert group is not None
        assert await service.settle(group)

    async with database.session_scope() as session:
        statuses = {
            row.status for row in (await session.execute(select(InboxMessage))).scalars()
        }
        group_row = (await session.execute(select(InboxGroup))).scalar_one()

    assert statuses == {InboxStatus.PROCESSED.value}
    assert group_row.status == InboxGroupStatus.SETTLED.value


async def test_unadopted_messages_are_detected_before_release(database) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        group = await service.claim((await service.claimable_conversations(3))[0])
        assert group is not None
        assert not await service.unadopted_exists(group)

        # A fragment lands while the turn is still running.
        await service.accept(inbound("w2", "perdón, me refería a otra cosa"))

        assert await service.unadopted_exists(group)


async def test_adoption_joins_a_late_message_to_the_active_group(database) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        group = await service.claim((await service.claimable_conversations(3))[0])
        assert group is not None

        await service.accept(inbound("w2", "corrección"))
        late = await service.peek_pending(group)
        await service.adopt(group, late)

        assert not await service.unadopted_exists(group)
        assert len(group.inbox_ids) == 2


# --- Fencing and retries ------------------------------------------------------


async def test_an_expired_owner_cannot_settle_recovered_work(database) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        group = await service.claim((await service.claimable_conversations(3))[0])
        assert group is not None
        # The lease expires and recovery reclaims the work.
        row = (await session.execute(select(InboxGroup))).scalar_one()
        row.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await session.commit()
        assert await service.recover_expired_claims() == 1

        # The former owner comes back and tries to finish.
        assert not await service.settle(group)
        assert not await service.renew_lease(group)

    async with database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()

    assert message.status == InboxStatus.PENDING.value
    assert message.attempts == 1


async def test_a_failed_attempt_returns_the_message_with_backoff(database) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        service = InboxService(session)
        group = await service.claim((await service.claimable_conversations(3))[0])
        assert group is not None
        assert not service.is_exhausted(group)
        await service.fail(group)

    async with database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()

    assert message.status == InboxStatus.PENDING.value
    assert message.attempts == 1
    assert message.next_attempt_at is not None
    assert message.group_id is None


async def test_three_attempts_exhaust_and_the_message_is_kept_as_failed(
    database,
) -> None:
    await accept_all(database, inbound("w1", "hola"))
    await age_out_collection_window(database)

    for attempt in range(MAX_ATTEMPTS):
        async with database.session_scope() as session:
            service = InboxService(session)
            # Clear the backoff so the test does not have to wait it out.
            for row in (await session.execute(select(InboxMessage))).scalars():
                row.next_attempt_at = None
                row.persisted_at = datetime.now(tz=UTC) - timedelta(seconds=10)
            await session.commit()

            conversations = await service.claimable_conversations(3)
            assert conversations, f"attempt {attempt + 1} should be claimable"
            group = await service.claim(conversations[0])
            assert group is not None
            exhausted = service.is_exhausted(group)
            await service.fail(group)

    assert exhausted

    async with database.session_scope() as session:
        message = (await session.execute(select(InboxMessage))).scalar_one()
        service = InboxService(session)
        # The lane is released: a permanently failing item cannot block it.
        assert await service.claimable_conversations(3) == []

    # Durably stored, never deleted (ADR-0005).
    assert message.status == InboxStatus.FAILED.value
    assert message.attempts == MAX_ATTEMPTS


# --- Outbox -------------------------------------------------------------------


@pytest.fixture
async def conversation(database):
    await accept_all(database, inbound("w1", "hola"))
    async with database.session_scope() as session:
        yield (await session.execute(select(Conversation))).scalar_one()


async def test_enqueue_is_idempotent_on_its_key(database, conversation) -> None:
    async with database.session_scope() as session:
        outbox = OutboxService(session)
        first = await outbox.enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:group-1",
            covered_inbox_ids=[],
        )
        second = await outbox.enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta duplicada",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:group-1",
            covered_inbox_ids=[],
        )

    assert first.created
    assert not second.created
    assert first.outbox_id == second.outbox_id

    async with database.session_scope() as session:
        rows = (await session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].body == "respuesta"


async def test_a_released_reply_records_every_covered_inbox_id(
    database, conversation
) -> None:
    covered = [uuid.uuid4(), uuid.uuid4()]

    async with database.session_scope() as session:
        await OutboxService(session).enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="una respuesta coherente",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:group-2",
            covered_inbox_ids=covered,
        )

    async with database.session_scope() as session:
        row = (await session.execute(select(OutboxMessage))).scalar_one()

    assert row.covered_inbox_ids == [str(i) for i in covered]


@pytest.mark.parametrize(
    ("result", "expected_status", "retried"),
    [
        (SendResult(SendOutcome.SENT, provider_message_id="wamid.X"), OutboxStatus.SENT, False),
        (SendResult(SendOutcome.UNKNOWN, detail="timeout"), OutboxStatus.DELIVERY_UNKNOWN, False),
        (SendResult(SendOutcome.FAILED_PERMANENT, detail="401"), OutboxStatus.FAILED, False),
        (SendResult(SendOutcome.FAILED_RETRYABLE, detail="503"), OutboxStatus.PENDING, True),
    ],
)
async def test_each_send_outcome_maps_to_its_status(
    database, conversation, result, expected_status, retried
) -> None:
    async with database.session_scope() as session:
        outbox = OutboxService(session)
        await outbox.enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key=f"reply:{uuid.uuid4()}",
            covered_inbox_ids=[],
        )
        row = (await outbox.claim_due())[0]
        await outbox.record_result(row, result)

    async with database.session_scope() as session:
        stored = (await session.execute(select(OutboxMessage))).scalar_one()

    assert stored.status == expected_status.value
    assert (stored.next_attempt_at is not None) == retried


async def test_an_ambiguous_send_is_never_replayed(database, conversation) -> None:
    # P-036: prefer a missing reply over a duplicate visible one.
    async with database.session_scope() as session:
        outbox = OutboxService(session)
        await outbox.enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:ambiguous",
            covered_inbox_ids=[],
        )
        row = (await outbox.claim_due())[0]
        await outbox.record_result(row, SendResult(SendOutcome.UNKNOWN, detail="timeout"))

        assert await outbox.claim_due() == []


async def test_a_retryable_failure_stops_after_three_attempts(
    database, conversation
) -> None:
    async with database.session_scope() as session:
        outbox = OutboxService(session)
        await outbox.enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:retries",
            covered_inbox_ids=[],
        )
        for _ in range(MAX_ATTEMPTS):
            rows = await outbox.claim_due()
            assert rows, "should still be due"
            row = rows[0]
            row.next_attempt_at = None  # skip the backoff in the test
            await outbox.record_result(
                row, SendResult(SendOutcome.FAILED_RETRYABLE, detail="503")
            )
            async with database.session_scope() as peek:
                fresh = (await peek.execute(select(OutboxMessage))).scalar_one()
                if fresh.status == OutboxStatus.PENDING.value:
                    fresh.next_attempt_at = None
                    await peek.commit()

    async with database.session_scope() as session:
        stored = (await session.execute(select(OutboxMessage))).scalar_one()

    assert stored.status == OutboxStatus.FAILED.value
    assert stored.attempts == MAX_ATTEMPTS
    # Content and coverage are preserved for the Developer to inspect.
    assert stored.body == "respuesta"
    assert stored.last_error is not None


async def test_a_retry_after_header_overrides_the_fixed_delay(
    database, conversation
) -> None:
    async with database.session_scope() as session:
        outbox = OutboxService(session)
        await outbox.enqueue(
            conversation=conversation,
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:retry-after",
            covered_inbox_ids=[],
        )
        row = (await outbox.claim_due())[0]
        before = datetime.now(tz=UTC)
        await outbox.record_result(
            row,
            SendResult(
                SendOutcome.FAILED_RETRYABLE, detail="429", retry_after_seconds=120
            ),
        )

    async with database.session_scope() as session:
        stored = (await session.execute(select(OutboxMessage))).scalar_one()

    assert stored.next_attempt_at > before + timedelta(seconds=100)


async def test_a_restart_quarantines_an_abandoned_send_instead_of_replaying_it(
    database, conversation
) -> None:
    async with database.session_scope() as session:
        outbox = OutboxService(session)
        await outbox.enqueue(
            conversation=await session.merge(conversation),
            to_wa_id=webhooks.LEAD_WA_ID,
            body="respuesta",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key="reply:crashed-send",
            covered_inbox_ids=[],
        )
        claimed = await outbox.claim_due()
        assert claimed[0].status == OutboxStatus.SENDING.value

    async with database.session_scope() as session:
        restarted = OutboxService(session)
        assert await restarted.recover_abandoned_sends() == 1
        assert await restarted.claim_due() == []
        row = (
            await session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.idempotency_key == "reply:crashed-send"
                )
            )
        ).scalar_one()
    assert row.status == OutboxStatus.DELIVERY_UNKNOWN.value
    assert "result was unknown" in row.last_error


# --- Races and lost leases ----------------------------------------------------


async def test_two_concurrent_deliveries_of_one_wamid_resolve_to_one_row(
    database,
) -> None:
    """Meta retries aggressively. The unique constraint is the arbiter, and the
    loser re-resolves to the winner rather than failing the request."""
    # The Lead already exists, so the only row two concurrent deliveries can
    # collide on is the message itself — which is the race being asserted.
    await accept_all(database, inbound("w-race-first", "hola"))
    message = inbound("w-race", "hola de nuevo")

    async def accept_once():  # noqa: ANN202
        async with database.session_scope() as session:
            return await InboxService(session).accept(message)

    first, second = await asyncio.gather(accept_once(), accept_once())

    assert first.inbox_id == second.inbox_id
    # One of them persisted it; the other re-resolved to that same row.
    assert {first.duplicate, second.duplicate} == {False, True}
    async with database.session_scope() as session:
        rows = (await session.execute(select(InboxMessage))).scalars().all()
    assert sorted(row.wamid for row in rows) == ["w-race", "w-race-first"]


async def test_a_changed_whatsapp_profile_name_is_adopted(database) -> None:
    """The Model has no other way to learn it, so a stale one would be repeated
    for the rest of the cycle."""
    await accept_all(database, inbound("w-name-1", "hola"))

    renamed = parse_webhook(
        webhooks.text_message(wamid="w-name-2", body="otra vez", profile_name="Memo")
    ).messages[0]
    await accept_all(database, renamed)

    async with database.session_scope() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
    assert lead.profile_name == "Memo"


async def test_an_absent_profile_name_does_not_erase_the_known_one(database) -> None:
    await accept_all(database, inbound("w-name-1", "hola"))

    anonymous = parse_webhook(
        webhooks.text_message(wamid="w-name-3", body="otra vez", profile_name="")
    ).messages[0]
    await accept_all(database, anonymous)

    async with database.session_scope() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
    assert lead.profile_name == "Cliente Demo"


async def test_claiming_a_conversation_with_nothing_pending_yields_no_group(
    database,
) -> None:
    """Between the candidate query and the claim, another worker can drain the
    lane. Opening an empty group would settle a turn that answered nothing."""
    await accept_all(database, inbound("w-empty", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        conversation_id = (await session.execute(select(Conversation))).scalar_one().id
        group = await InboxService(session).claim(conversation_id)
        assert group is not None
        assert await InboxService(session).settle(group)

    async with database.session_scope() as session:
        assert await InboxService(session).claim(conversation_id) is None


async def test_adopting_nothing_is_a_no_op(database) -> None:
    await accept_all(database, inbound("w-adopt", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        conversation_id = (await session.execute(select(Conversation))).scalar_one().id
        inbox = InboxService(session)
        group = await inbox.claim(conversation_id)
        assert group is not None
        before = list(group.messages)

        await inbox.adopt(group, [])

        assert group.messages == before


async def test_the_lease_can_be_extended_while_the_claim_is_still_held(
    database,
) -> None:
    await accept_all(database, inbound("w-lease", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        conversation_id = (await session.execute(select(Conversation))).scalar_one().id
        inbox = InboxService(session)
        group = await inbox.claim(conversation_id)
        assert group is not None
        row = await session.get(InboxGroup, group.group_id)
        assert row is not None
        before = row.lease_expires_at

        assert await inbox.renew_lease(group) is True

        await session.refresh(row)
        assert row.lease_expires_at >= before


async def test_a_lost_lease_can_neither_renew_nor_settle_nor_fail(database) -> None:
    """Recovery already owns the work; this worker must not touch it (P-038)."""
    await accept_all(database, inbound("w-lost", "hola"))
    await age_out_collection_window(database)

    async with database.session_scope() as session:
        conversation_id = (await session.execute(select(Conversation))).scalar_one().id
        group = await InboxService(session).claim(conversation_id)
        assert group is not None

    # The lease expires and recovery reassigns the group.
    async with database.session_scope() as session:
        row = await session.get(InboxGroup, group.group_id)
        assert row is not None
        row.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await session.commit()
    async with database.session_scope() as session:
        assert await InboxService(session).recover_expired_claims() == 1

    async with database.session_scope() as session:
        inbox = InboxService(session)
        assert await inbox.renew_lease(group) is False
        assert await inbox.settle(group) is False
        assert await inbox.fail(group) is False


async def test_recovery_with_nothing_expired_reports_nothing(database) -> None:
    async with database.session_scope() as session:
        assert await InboxService(session).recover_expired_claims() == 0


# --- Outbox idempotency race ---------------------------------------------------


def _commit_a_competing_outbox_row(conversation_id, key: str) -> None:
    """Insert an Outbox row on a separate connection, synchronously.

    Used from inside ``Session.add`` — after ``enqueue`` has done its
    pre-check and before it commits — so the collision the ``IntegrityError``
    branch exists for actually happens. A concurrent pair races either way and
    would leave that branch untested on most runs.
    """
    import psycopg

    dsn = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO outbox_messages
                (id, conversation_id, idempotency_key, to_wa_id, kind, body,
                 covered_inbox_ids, status, attempts)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, '[]'::jsonb, %s, 0)
            """,
            (
                str(conversation_id),
                key,
                "5215550000001",
                OutboxKind.AGENT_REPLY,
                "hola",
                OutboxStatus.PENDING.value,
            ),
        )


async def test_a_reply_that_collides_at_insert_time_returns_the_winners_row(
    database,
) -> None:
    """One reply per Inbox group, whatever happens upstream.

    The pre-check is advisory; the unique index is the guarantee. When the two
    disagree the loser must report the winner's row rather than raise — the
    Worker is mid-settlement and a raise there would strand the Inbox group.
    """
    await accept_all(database, inbound("w-outbox-race", "hola"))
    key = "reply:same-group"

    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        original_add = session.add

        def add_after_another_worker_won(instance) -> None:  # noqa: ANN001
            session.add = original_add  # only the first insert races
            _commit_a_competing_outbox_row(conversation.id, key)
            original_add(instance)

        session.add = add_after_another_worker_won
        result = await OutboxService(session).enqueue(
            conversation=conversation,
            to_wa_id="5215550000001",
            body="hola",
            kind=OutboxKind.AGENT_REPLY,
            idempotency_key=key,
            covered_inbox_ids=[],
        )

    assert not result.created
    async with database.session_scope() as session:
        rows = (await session.execute(select(OutboxMessage))).scalars().all()
    assert [row.id for row in rows] == [result.outbox_id]

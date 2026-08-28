"""Exactly one authority answers a Contact (ADR-0029).

Two races and one gate.

**Maia against a human.** A human taking over mid-turn wins: the Lead worker
re-reads the handling mode under a lock at settlement and withholds the draft.
The group is *settled* rather than failed, because retrying would eventually
tell the Contact that something went wrong when the product worked exactly as
designed.

**Human against human.** Two Advisors pressing *Atender* resolve to one holder,
and the loser is told who has it. An Administrator may move handling explicitly;
an Advisor may not take it from a colleague.

**The gate still applies to a person.** A human reply from the CRM goes out on
the Organization's own channel and through the same Outbound Eligibility Gate as
everything else: suppression is a fact about the Contact, and Meta's 24-hour
window is a platform constraint. Neither becomes negotiable because somebody
typed the message.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    ConversationHandlingState,
    HandlingMode,
    InboxGroupStatus,
    InboxMessage,
    InboxStatus,
    OutboxMessage,
    SuppressionRecord,
)
from realestate.domain.commercial.actors import NotAuthorized, NotFound
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.handling import (
    ConversationHandling,
    HumanReply,
    NotHandling,
    ReleaseHandling,
    ReplyRecorded,
    TakeHandling,
)
from realestate.domain.inbox import InboxService
from realestate.domain.outbound import DenialReason, Purpose
from tests.conftest import DATABASE_URL, age_pending_inbox, requires_postgres
from tests.fixtures import visits
from tests.fixtures.stubs import SCHEDULE, StubWhatsApp

pytestmark = requires_postgres


@pytest.fixture
async def operation(tmp_path: Path):
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await visits.reset(session)
        built = await visits.build(session, tmp_path / "artifacts")
        await session.commit()
    yield database, built
    await database.dispose()


def key(name: str) -> str:
    return f"{name}:{uuid.uuid4().hex}"


async def assigned_inbound(session, built, **kwargs):  # noqa: ANN001, ANN202
    """Create inbound work and attach its deterministic Responsible Advisor."""
    from realestate.domain.commercial.identity import CommercialIdentity
    from realestate.domain.commercial.opportunities import OpportunityManagement

    conversation = await visits.inbound(session, **kwargs)
    contact_id = await CommercialIdentity(session).contact_for_lead(
        conversation.lead_id
    )
    assert contact_id is not None
    opportunity = await OpportunityManagement(session).open_demand_for_contact(
        contact_id
    )
    assert opportunity is not None
    await Assignment(session).assign(built.admin, opportunity.id)
    return conversation


# -- The default and the transitions --------------------------------------


async def test_a_conversation_with_no_row_is_maias(operation) -> None:
    """An absent row means Maia, so no backfill can be wrong."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-default", body="Hola, busco casa"
        )
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        may = await ConversationHandling(session).maia_may_reply(conversation.id)

    assert snapshot.mode is HandlingMode.MAIA
    assert snapshot.holder_member_id is None
    assert may


async def test_an_advisor_takes_a_conversation_and_maia_stops(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-take", body="Hola, busco casa"
        )
        await session.commit()

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    assert snapshot.mode is HandlingMode.HUMAN
    assert snapshot.holder_member_id == built.advisor_id
    assert not snapshot.maia_may_reply
    assert snapshot.held_by(built.advisor)

    async with database.session_scope() as session:
        assert not await ConversationHandling(session).maia_may_reply(conversation.id)
        actions = [
            row.action
            for row in await session.scalars(
                select(AuditEvent).where(AuditEvent.subject_type == "Conversation")
            )
        ]
    assert "TakeConversationHandling" in actions


async def test_product_cannot_take_a_conversation(operation) -> None:
    """Maia does not "take" a conversation; being the default is not a claim."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-product", body="Hola"
        )
        with pytest.raises(NotAuthorized):
            await ConversationHandling(session).take(
                built.product,
                TakeHandling(
                    conversation_id=conversation.id, command_key=key("take")
                ),
            )


async def test_another_advisor_cannot_reach_the_conversation(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-race", body="Hola"
        )
        await session.commit()

    async with database.session_scope() as session:
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await ConversationHandling(session).take(
                built.second_advisor,
                TakeHandling(
                    conversation_id=conversation.id, command_key=key("take")
                ),
            )

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
    assert snapshot.holder_member_id == built.advisor_id


async def test_two_advisors_taking_concurrently_produce_one_holder(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-race2", body="Hola"
        )
        await session.commit()

    winners: list[uuid.UUID] = []
    refused = 0
    async with database.session_scope() as first:
        async with database.session_scope() as second:
            snapshot = await ConversationHandling(first).take(
                built.advisor,
                TakeHandling(
                    conversation_id=conversation.id, command_key=key("take")
                ),
            )
            await first.commit()
            winners.append(snapshot.holder_member_id)  # type: ignore[arg-type]
            try:
                await ConversationHandling(second).take(
                    built.second_advisor,
                    TakeHandling(
                        conversation_id=conversation.id, command_key=key("take")
                    ),
                )
                await second.commit()
            except NotFound:
                refused += 1

    assert winners == [built.advisor_id]
    assert refused == 1
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(ConversationHandlingState).where(
                    ConversationHandlingState.conversation_id == conversation.id
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].holder_member_id == built.advisor_id


async def test_an_administrator_may_move_handling_explicitly(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-admin", body="Hola"
        )
        await session.commit()
    async with database.session_scope() as session:
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()
    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).take(
            built.admin,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    assert snapshot.holder_member_id == built.admin_id
    assert snapshot.reason == "AdminReassigned"


async def test_only_the_holder_or_an_administrator_releases(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-release", body="Hola"
        )
        await session.commit()
    async with database.session_scope() as session:
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await ConversationHandling(session).release(
                built.second_advisor,
                ReleaseHandling(
                    conversation_id=conversation.id, command_key=key("release")
                ),
            )

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).release(
            built.advisor,
            ReleaseHandling(
                conversation_id=conversation.id, command_key=key("release")
            ),
        )
        await session.commit()

    assert snapshot.mode is HandlingMode.MAIA
    assert snapshot.maia_may_reply


async def test_releasing_into_awaiting_contact_keeps_maia_silent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-wait", body="Hola"
        )
        await session.commit()
    async with database.session_scope() as session:
        handling = ConversationHandling(session)
        await handling.take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        snapshot = await handling.release(
            built.advisor,
            ReleaseHandling(
                conversation_id=conversation.id,
                command_key=key("release"),
                to_mode=HandlingMode.AWAITING_CONTACT,
            ),
        )
        await session.commit()

    assert snapshot.mode is HandlingMode.AWAITING_CONTACT
    assert not snapshot.maia_may_reply


async def test_the_contact_writing_again_ends_the_wait(operation) -> None:
    """AwaitingContact means "nobody acts until they answer", so their answer
    ends it — while Human and AdminReview are deliberately untouched."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-wait2", body="Hola"
        )
        handling = ConversationHandling(session)
        await handling.take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await handling.release(
            built.advisor,
            ReleaseHandling(
                conversation_id=conversation.id,
                command_key=key("release"),
                to_mode=HandlingMode.AWAITING_CONTACT,
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        await assigned_inbound(
            session, built, wamid="w-wait3", body="Sigo interesado"
        )
        snapshot = await ConversationHandling(session).snapshot(conversation.id)

    assert snapshot.mode is HandlingMode.MAIA
    assert snapshot.reason == "ContactWroteAgain"


async def test_an_inbound_message_never_takes_a_conversation_from_a_human(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-hold", body="Hola"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        await assigned_inbound(
            session, built, wamid="w-hold2", body="¿Hay novedades?"
        )
        snapshot = await ConversationHandling(session).snapshot(conversation.id)

    assert snapshot.mode is HandlingMode.HUMAN
    assert snapshot.holder_member_id == built.advisor_id


# -- The Maia-versus-human race -------------------------------------------


async def test_a_human_held_conversation_is_not_claimable_by_maia(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-claim", body="Hola"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()
    await age_pending_inbox(database)

    async with database.session_scope() as session:
        claimable = await InboxService(session).claimable_conversations(5)

    assert conversation.id not in claimable


async def test_a_human_arriving_mid_turn_wins_and_the_draft_is_withheld(
    operation,
) -> None:
    """The race the settlement re-check exists for.

    Hermes is scripted to take over on behalf of the Advisor while it is
    "composing", so the draft is finished exactly when a human holds the
    conversation. The Contact must get one answer, from the human.
    """
    database, built = operation
    from realestate.worker.whatsapp import WhatsAppWorker

    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-midturn", body="Quiero información"
        )
        await session.commit()
    await age_pending_inbox(database)

    async def scripted_turn(hermes, role_session, prompt, **kwargs):  # noqa: ANN001, ANN202
        if not role_session.hermes_session_id:
            await kwargs["on_attached"]("session-midturn")
        async with database.session_scope() as other:
            await ConversationHandling(other).take(
                built.advisor,
                TakeHandling(
                    conversation_id=conversation.id, command_key=key("take")
                ),
            )
            await other.commit()

        class Turn:
            text = "Claro, te comparto la información…"

        return Turn()

    whatsapp = StubWhatsApp()
    worker = WhatsAppWorker(
        database=database,
        hermes=object(),  # type: ignore[arg-type]
        whatsapp=whatsapp,  # type: ignore[arg-type]
        sales_profile="sales",
        schedule=SCHEDULE,
    )
    import realestate.worker.whatsapp as worker_module

    original = worker_module.run_turn
    worker_module.run_turn = scripted_turn  # type: ignore[assignment]
    try:
        await worker.tick()
    finally:
        worker_module.run_turn = original  # type: ignore[assignment]

    assert whatsapp.sent == []
    async with database.session_scope() as session:
        outbox = list(await session.scalars(select(OutboxMessage)))
        groups = list(
            await session.scalars(
                select(InboxMessage.status).where(
                    InboxMessage.conversation_id == conversation.id
                )
            )
        )
        actions = [
            row.action
            for row in await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "WithholdMaiaReplyForHuman"
                )
            )
        ]

    # Nothing was staged, so nothing can be delivered later either.
    assert outbox == []
    assert actions == ["WithholdMaiaReplyForHuman"]
    # Settled, not failed: retrying would end in a processing-failure notice
    # announcing a fault where the product behaved correctly.
    assert set(groups) == {InboxStatus.PROCESSED.value}


# -- The human reply ------------------------------------------------------


async def test_a_human_reply_goes_out_through_the_gate(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-reply", body="¿Me puedes ayudar?"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        recorded = await ConversationHandling(session).reply(
            built.advisor,
            HumanReply(
                conversation_id=conversation.id,
                body="Claro que sí, con gusto te apoyo.",
                command_key=key("reply"),
            ),
        )
        await session.commit()

    assert recorded.queued
    async with database.session_scope() as session:
        row = await session.get(OutboxMessage, recorded.outbox_id)
        actions = [
            event.action
            for event in await session.scalars(
                select(AuditEvent).where(AuditEvent.action == "SendHumanReply")
            )
        ]

    assert row is not None
    # The Organization's own channel, labelled as a human reply rather than
    # Maia's, so the metric and the thread both stay honest.
    assert row.kind == Purpose.HUMAN_REPLY.value
    assert row.body == "Claro que sí, con gusto te apoyo."
    assert actions == ["SendHumanReply"]


async def test_an_advisor_who_does_not_hold_it_cannot_reply(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-nohold", body="Hola"
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotHandling):
            await ConversationHandling(session).reply(
                built.advisor,
                HumanReply(
                    conversation_id=conversation.id,
                    body="Hola, soy el asesor.",
                    command_key=key("reply"),
                ),
            )


async def test_a_reply_waits_for_a_concurrent_authority_transfer(operation) -> None:
    """A transfer that holds the authority row wins before a stale reply checks it."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-reply-transfer", body="¿Me ayudan?"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async def stale_reply() -> ReplyRecorded:
        async with database.session_scope() as reply_session:
            recorded = await ConversationHandling(reply_session).reply(
                built.advisor,
                HumanReply(
                    conversation_id=conversation.id,
                    body="Yo sigo atendiendo.",
                    command_key=key("reply"),
                ),
            )
            await reply_session.commit()
            return recorded

    async with database.session_scope() as transfer_session:
        await ConversationHandling(transfer_session).take(
            built.admin,
            TakeHandling(
                conversation_id=conversation.id,
                command_key=key("admin-transfer"),
            ),
        )
        reply_task = asyncio.create_task(stale_reply())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(reply_task), timeout=0.2)
        await transfer_session.commit()

    with pytest.raises(NotHandling):
        await reply_task

    async with database.session_scope() as session:
        staged = list(
            await session.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.conversation_id == conversation.id
                )
            )
        )
    assert staged == []


async def test_a_suppressed_contact_may_still_be_answered_by_a_human(
    operation,
) -> None:
    """Suppression stops *outreach*, and answering is not outreach (ADR-0045).

    Worth pinning down because the intuitive expectation is the opposite. A
    Contact who wrote "no me contacten" and then wrote again with a question has
    not been gagged: refusing to answer them would leave a person mid-sentence.
    What suppression blocks is Product reaching out on its own, which is asserted
    in tests/test_outbound_eligibility.py.
    """
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-supp", body="Hola"
        )
        session.add(
            SuppressionRecord(
                lead_id=conversation.lead_id,
                channel="WhatsApp",
                reason="ExplicitOptOut",
            )
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        recorded = await ConversationHandling(session).reply(
            built.advisor,
            HumanReply(
                conversation_id=conversation.id,
                body="Le llamo en un momento.",
                command_key=key("reply"),
            ),
        )
        await session.commit()

    assert recorded.queued
    async with database.session_scope() as session:
        staged = list(await session.scalars(select(OutboxMessage)))
        suppression = await session.scalar(
            select(SuppressionRecord).where(
                SuppressionRecord.lead_id == conversation.lead_id
            )
        )
    assert [row.kind for row in staged] == [Purpose.HUMAN_REPLY.value]
    # The suppression is untouched: the next business-initiated message is still
    # refused.
    assert suppression is not None and suppression.revoked_at is None


async def test_a_closed_service_window_refuses_the_human_reply(operation) -> None:
    """Meta's 24-hour rule is a platform constraint, not a product preference."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-window", body="Hola"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        # Age every inbound message past the window.
        for row in await session.scalars(
            select(InboxMessage).where(
                InboxMessage.conversation_id == conversation.id
            )
        ):
            row.sent_at = row.sent_at - timedelta(hours=30)
            row.persisted_at = row.persisted_at - timedelta(hours=30)
        await session.commit()

    async with database.session_scope() as session:
        recorded = await ConversationHandling(session).reply(
            built.advisor,
            HumanReply(
                conversation_id=conversation.id,
                body="Hola, ¿sigues interesado?",
                command_key=key("reply"),
            ),
        )
        await session.commit()

    assert not recorded.queued
    assert recorded.denied_reason == DenialReason.SERVICE_WINDOW_CLOSED.value
    async with database.session_scope() as session:
        assert list(await session.scalars(select(OutboxMessage))) == []


async def test_an_empty_human_reply_is_refused(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-empty", body="Hola"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized):
            await ConversationHandling(session).reply(
                built.advisor,
                HumanReply(
                    conversation_id=conversation.id,
                    body="   ",
                    command_key=key("reply"),
                ),
            )


async def test_taking_the_same_conversation_twice_with_one_key_replays(
    operation,
) -> None:
    database, built = operation
    command_key = key("take")
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-replay", body="Hola"
        )
        await session.commit()

    async with database.session_scope() as session:
        first = await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=command_key),
        )
        await session.commit()
    async with database.session_scope() as session:
        second = await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=command_key),
        )
        await session.commit()

    assert first.version == second.version


# -- Reads the Inbox page depends on --------------------------------------


async def test_handling_rows_for_a_whole_page_come_in_one_query(operation) -> None:
    """The Inbox shows who is answering on every line; asking per row would be a
    query per line."""
    database, built = operation
    async with database.session_scope() as session:
        first = await assigned_inbound(
            session, built, wamid="w-page1", body="Hola"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=first.id, command_key=key("take")),
        )
        await session.commit()
    async with database.session_scope() as session:
        second = await assigned_inbound(
            session,
            built,
            wamid="w-page2",
            body="Hola",
            from_wa_id="5213311112222",
        )
        await session.commit()

    async with database.session_scope() as session:
        handling = ConversationHandling(session)
        rows = await handling.modes_for([first.id, second.id])
        empty = await handling.modes_for([])

    # Only the Conversation somebody took has a row; an absent row means Maia.
    assert set(rows) == {first.id}
    assert rows[first.id].mode == HandlingMode.HUMAN.value
    assert empty == {}


async def test_note_inbound_on_a_conversation_with_no_row_does_nothing(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-noop", body="Hola"
        )
        assert (
            await ConversationHandling(session).note_inbound(
                built.product, conversation
            )
            is None
        )


async def test_an_administrator_may_reply_on_a_conversation_a_human_holds(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-adminreply", body="¿Me ayudan?"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        recorded = await ConversationHandling(session).reply(
            built.admin,
            HumanReply(
                conversation_id=conversation.id,
                body="Te contacto yo directamente.",
                command_key=key("reply"),
            ),
        )
        await session.commit()

    assert recorded.queued


async def test_an_unknown_conversation_reads_as_absent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import NotFound

        with pytest.raises(NotFound):
            await ConversationHandling(session).take(
                built.advisor,
                TakeHandling(conversation_id=uuid.uuid4(), command_key=key("take")),
            )


async def test_releasing_into_a_human_mode_is_refused(operation) -> None:
    """``release`` hands authority back; taking it is what ``take`` is for."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-badmode", body="Hola"
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized):
            await ConversationHandling(session).release(
                built.advisor,
                ReleaseHandling(
                    conversation_id=conversation.id,
                    command_key=key("release"),
                    to_mode=HandlingMode.HUMAN,
                ),
            )


async def test_releasing_a_conversation_maia_already_holds_changes_nothing(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-already", body="Hola"
        )
        await session.commit()

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).release(
            built.advisor,
            ReleaseHandling(
                conversation_id=conversation.id, command_key=key("release")
            ),
        )
        await session.commit()

    assert snapshot.mode is HandlingMode.MAIA


async def test_every_handling_label_has_spanish(operation) -> None:
    from realestate.domain.commercial.handling import MODE_LABELS, REASON_LABELS

    assert set(MODE_LABELS) == {mode.value for mode in HandlingMode}
    for label in (*MODE_LABELS.values(), *REASON_LABELS.values()):
        assert label and label[0].isupper()


async def test_a_snapshot_reads_its_own_labels(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-labels", body="Hola"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        snapshot = await ConversationHandling(session).snapshot(conversation.id)

    assert snapshot.mode_label == "Atiende una persona"
    assert snapshot.reason_label == "Una persona tomó la conversación"
    assert snapshot.holder_name == built.advisor.display_name


async def test_a_reply_after_product_already_wrote_answers_the_last_message(
    operation,
) -> None:
    """With nothing new since Product wrote, the Contact's most recent message is
    still what a human is answering — and the gate decides whether the window is
    open, not the caller."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await assigned_inbound(
            session, built, wamid="w-after-out", body="¿Me ayudan?"
        )
        await ConversationHandling(session).take(
            built.advisor,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        first = await ConversationHandling(session).reply(
            built.advisor,
            HumanReply(
                conversation_id=conversation.id,
                body="Claro.",
                command_key=key("reply"),
            ),
        )
        await session.commit()
    assert first.queued

    async with database.session_scope() as session:
        second = await ConversationHandling(session).reply(
            built.advisor,
            HumanReply(
                conversation_id=conversation.id,
                body="Te marco en un momento.",
                command_key=key("reply"),
            ),
        )
        await session.commit()

    assert second.queued
    async with database.session_scope() as session:
        staged = [
            row.body
            for row in await session.scalars(
                select(OutboxMessage).order_by(OutboxMessage.created_at)
            )
        ]
    assert staged == ["Claro.", "Te marco en un momento."]


async def test_a_conversation_with_no_inbound_message_cannot_be_answered(
    operation,
) -> None:
    """No message to answer means no reactive evidence, so the gate refuses."""
    database, built = operation
    from tests.fixtures import commercial as fixtures

    async with database.session_scope() as session:
        lead = await fixtures.make_lead(session, "5213300001111")
        conversation = await fixtures.make_conversation(session, lead)
        await ConversationHandling(session).take(
            built.admin,
            TakeHandling(conversation_id=conversation.id, command_key=key("take")),
        )
        await session.commit()

    async with database.session_scope() as session:
        recorded = await ConversationHandling(session).reply(
            built.admin,
            HumanReply(
                conversation_id=conversation.id,
                body="Hola, soy el asesor.",
                command_key=key("reply"),
            ),
        )
        await session.commit()

    assert not recorded.queued
    assert recorded.denied_reason == DenialReason.MISSING_REACTIVE_TRIGGER.value


def test_the_mid_turn_marker_names_the_processing_state() -> None:
    """Shared so the CRM warning and the worker agree about "Maia is mid-turn"."""
    from realestate.domain.commercial.handling import unused_group_states

    assert unused_group_states() == (InboxGroupStatus.PROCESSING.value,)

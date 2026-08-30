"""The Outbound Eligibility Gate (ADR-0045).

These are behaviour tests: they assert what does and does not reach a Contact,
and what evidence Product keeps about the choice. They deliberately do not
assert the shape of the rule code, so the rules can be reordered or rewritten
without rewriting the suite.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    ConsentCategory,
    ConsentRecord,
    ConsentState,
    Conversation,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    OutboundDecision,
    OutboundInitiation,
    OutboundOutcome,
    OutboxMessage,
    SuppressionRecord,
)
from realestate.domain.inbox import InboxService
from realestate.domain.outbound import (
    APPROVED_TEMPLATES,
    ApprovedTemplate,
    DeliveryDenied,
    DenialReason,
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
    Queued,
    TemplateDelivery,
    detect_opt_out,
)
from realestate.domain.text import fold_phrase
from realestate.domain.outbox import OutboxKind
from realestate.channels.whatsapp.payload import InboundMessage
from tests.conftest import (
    DATABASE_URL,
    larevia_organization_id,
    requires_postgres,
)
from tests.fixtures import commercial

pytestmark = requires_postgres

NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)
WA_ID = "5215559990000"


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        for model in (
            AuditEvent,
            OutboundDecision,
            SuppressionRecord,
            ConsentRecord,
            OutboxMessage,
            InboxMessage,
            Conversation,
            LeadEngagementCycle,
            Lead,
        ):
            await session.execute(delete(model))
        await session.commit()
    yield db
    await db.dispose()


async def seed(
    database: Database,
    *,
    last_inbound: datetime | None = NOW - timedelta(minutes=5),
    last_outbound: datetime | None = None,
) -> tuple:
    """One Lead with one Conversation, and the message history that matters."""
    async with database.session_scope() as session:
        organization_id = await larevia_organization_id(session)
        lead = Lead(organization_id=organization_id, wa_id=WA_ID)
        session.add(lead)
        await session.flush()
        cycle = LeadEngagementCycle(
            organization_id=lead.organization_id,
            lead_id=lead.id,
            started_at=NOW - timedelta(days=2),
            expires_at=NOW + timedelta(days=28),
        )
        session.add(cycle)
        await session.flush()
        conversation = Conversation(
            organization_id=organization_id,
            lead_id=lead.id,
            cycle_id=cycle.id,
            phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
        )
        session.add(conversation)
        await session.flush()
        if last_inbound is not None:
            session.add(
                InboxMessage(
                    organization_id=conversation.organization_id,
                    conversation_id=conversation.id,
                    wamid=f"wamid.{last_inbound.timestamp()}",
                    from_wa_id=WA_ID,
                    message_type="text",
                    text="Hola",
                    sent_at=last_inbound,
                    persisted_at=last_inbound,
                    raw_message={},
                    status=InboxStatus.PROCESSED.value,
                )
            )
        if last_outbound is not None:
            session.add(
                OutboxMessage(
                    organization_id=conversation.organization_id,
                    conversation_id=conversation.id,
                    idempotency_key=f"seed:{last_outbound.timestamp()}",
                    to_wa_id=WA_ID,
                    kind=OutboxKind.AGENT_REPLY,
                    body="Con gusto.",
                    covered_inbox_ids=[],
                    created_at=last_outbound,
                )
            )
        await session.commit()
        return lead.id, conversation.id


def intent(conversation, **overrides) -> OutboundIntent:
    values = dict(
        conversation=conversation,
        body="Hola de nuevo.",
        purpose=Purpose.AGENT_REPLY,
        initiation=OutboundInitiation.REACTIVE,
        idempotency_key="test-intent",
        requested_at=NOW,
    )
    values.update(overrides)
    return OutboundIntent(**values)


async def ask(database: Database, conversation_id, **overrides):
    async with database.session_scope() as session:
        conversation = await session.get(Conversation, conversation_id)
        initiation = overrides.get("initiation", OutboundInitiation.REACTIVE)
        if (
            initiation is OutboundInitiation.REACTIVE
            and "trigger_inbox_ids" not in overrides
        ):
            trigger = await session.scalar(
                select(InboxMessage.id)
                .where(InboxMessage.conversation_id == conversation_id)
                .order_by(InboxMessage.persisted_at.desc())
                .limit(1)
            )
            overrides["trigger_inbox_ids"] = (
                (trigger,) if trigger is not None else ()
            )
        outcome = await OutboundMessaging(session).request(
            intent(conversation, **overrides)
        )
        await session.commit()
        return outcome


async def decisions(database: Database) -> list[OutboundDecision]:
    async with database.session_scope() as session:
        return list(
            (
                await session.execute(
                    select(OutboundDecision).order_by(OutboundDecision.decided_at)
                )
            )
            .scalars()
            .all()
        )


async def outbox(database: Database) -> list[OutboxMessage]:
    """Only what the gate produced: seeded history uses a ``seed:`` key."""
    async with database.session_scope() as session:
        return list(
            (
                await session.execute(
                    select(OutboxMessage)
                    .where(~OutboxMessage.idempotency_key.startswith("seed:"))
                    .order_by(OutboxMessage.created_at)
                )
            )
            .scalars()
            .all()
        )


# -- Reactive replies ------------------------------------------------------


async def test_a_reply_inside_the_service_window_is_queued(database) -> None:
    _, conversation_id = await seed(database)

    outcome = await ask(database, conversation_id)

    assert isinstance(outcome, Queued)
    messages = await outbox(database)
    assert [m.body for m in messages] == ["Hola de nuevo."]
    recorded = await decisions(database)
    assert [(d.outcome, d.initiation) for d in recorded] == [
        (OutboundOutcome.QUEUED.value, OutboundInitiation.REACTIVE.value)
    ]
    assert recorded[0].outbox_id == messages[0].id


async def test_a_reply_after_the_window_closed_fails_closed(database) -> None:
    """A draft that sat in the queue too long must not become a rejected send."""
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=25))

    outcome = await ask(database, conversation_id)

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.SERVICE_WINDOW_CLOSED
    assert await outbox(database) == []


async def test_free_form_is_refused_at_the_exact_window_boundary(database) -> None:
    _, conversation_id = await seed(
        database, last_inbound=NOW - timedelta(hours=24)
    )

    outcome = await ask(database, conversation_id)

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.SERVICE_WINDOW_CLOSED


async def test_a_contact_who_never_wrote_has_no_window(database) -> None:
    _, conversation_id = await seed(database, last_inbound=None)

    outcome = await ask(database, conversation_id)

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.MISSING_REACTIVE_TRIGGER


async def test_a_reactive_message_without_trigger_evidence_is_refused(database) -> None:
    _, conversation_id = await seed(database)

    outcome = await ask(database, conversation_id, trigger_inbox_ids=())

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.MISSING_REACTIVE_TRIGGER


async def test_trigger_messages_from_another_conversation_are_refused(
    database,
) -> None:
    """A caller cannot borrow somebody else's messages to look reactive."""
    _, first = await seed(database)
    async with database.session_scope() as session:
        organization_id = await larevia_organization_id(session)
        lead = Lead(organization_id=organization_id, wa_id="5215558880000")
        session.add(lead)
        await session.flush()
        cycle = LeadEngagementCycle(
            organization_id=organization_id,
            lead_id=lead.id,
            started_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
        session.add(cycle)
        await session.flush()
        other = Conversation(
            organization_id=organization_id,
            lead_id=lead.id,
            cycle_id=cycle.id,
            phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
        )
        session.add(other)
        await session.flush()
        stranger = InboxMessage(
            organization_id=other.organization_id,
            conversation_id=other.id,
            wamid="wamid.stranger",
            from_wa_id="5215558880000",
            message_type="text",
            text="Hola",
            sent_at=NOW,
            persisted_at=NOW,
            raw_message={},
        )
        session.add(stranger)
        await session.commit()
        stranger_id = stranger.id

    outcome = await ask(database, first, trigger_inbox_ids=(stranger_id,))

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.UNTRUSTED_TRIGGER
    assert await outbox(database) == []


# -- Business-initiated messages -------------------------------------------


async def test_a_utility_notice_inside_the_window_needs_no_consent(database) -> None:
    """Telling somebody what happened to their own booking is not marketing."""
    _, conversation_id = await seed(database)

    outcome = await ask(
        database,
        conversation_id,
        purpose=Purpose.APPOINTMENT_RESOLUTION,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
    )

    assert isinstance(outcome, Queued)


async def test_marketing_without_a_consent_record_is_denied(
    database, monkeypatch
) -> None:
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)
    _, conversation_id = await seed(
        database,
        last_inbound=NOW - timedelta(hours=4),
        last_outbound=NOW - timedelta(hours=3),
    )

    outcome = await ask(
        database,
        conversation_id,
        purpose=Purpose.LEAD_FOLLOW_UP,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.MARKETING_CONSENT_MISSING
    assert await outbox(database) == []


async def test_a_revoked_consent_does_not_count_as_permission(
    database, monkeypatch
) -> None:
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)
    lead_id, conversation_id = await seed(
        database,
        last_inbound=NOW - timedelta(hours=4),
        last_outbound=NOW - timedelta(hours=3),
    )
    async with database.session_scope() as session:
        session.add(
            ConsentRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="Test",
                recorded_at=NOW - timedelta(days=2),
            )
        )
        session.add(
            ConsentRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.REVOKED.value,
                source="Test",
                recorded_at=NOW - timedelta(days=1),
            )
        )
        await session.commit()

    outcome = await ask(
        database,
        conversation_id,
        purpose=Purpose.LEAD_FOLLOW_UP,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.MARKETING_CONSENT_MISSING


async def test_a_suppressed_contact_receives_nothing_proactive(database) -> None:
    lead_id, conversation_id = await seed(database)
    async with database.session_scope() as session:
        session.add(
            SuppressionRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id, reason="ExplicitOptOut", evidence="baja"
            )
        )
        await session.commit()

    outcome = await ask(
        database,
        conversation_id,
        purpose=Purpose.APPOINTMENT_RESOLUTION,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.SUPPRESSED


async def test_a_suppressed_contact_can_still_be_answered(database) -> None:
    """Suppression stops outreach; it does not gag Product mid-conversation."""
    lead_id, conversation_id = await seed(database)
    async with database.session_scope() as session:
        session.add(
            SuppressionRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id, reason="ExplicitOptOut", evidence="baja"
            )
        )
        await session.commit()

    outcome = await ask(database, conversation_id)

    assert isinstance(outcome, Queued)


async def test_a_reply_from_the_contact_stops_the_generic_follow_up(
    database, monkeypatch
) -> None:
    """ADR-0021: any reply ends the sequence, consent or no consent."""
    lead_id, conversation_id = await seed(
        database,
        last_outbound=NOW - timedelta(hours=3),
        last_inbound=NOW - timedelta(hours=1),
    )
    async with database.session_scope() as session:
        session.add(
            ConsentRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="Test",
            )
        )
        await session.commit()
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)
    monkeypatch.setitem(
        APPROVED_TEMPLATES,
        "t1",
        ApprovedTemplate(ConsentCategory.MARKETING, "es_MX"),
    )

    outcome = await ask(
        database,
        conversation_id,
        purpose=Purpose.LEAD_FOLLOW_UP,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
        template_id="t1",
        template_category=ConsentCategory.MARKETING,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.CONTACT_REPLIED
    assert await outbox(database) == []


async def test_a_follow_up_proceeds_once_nothing_is_owed(database, monkeypatch) -> None:
    """The allow path exists: consent, an approved template, and no reply owed."""
    lead_id, conversation_id = await seed(
        database,
        last_inbound=NOW - timedelta(hours=4),
        last_outbound=NOW - timedelta(hours=3),
    )
    async with database.session_scope() as session:
        session.add(
            ConsentRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="Test",
            )
        )
        await session.commit()
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)
    monkeypatch.setitem(
        APPROVED_TEMPLATES,
        "t1",
        ApprovedTemplate(ConsentCategory.MARKETING, "es_MX"),
    )

    outcome = await ask(
        database,
        conversation_id,
        purpose=Purpose.LEAD_FOLLOW_UP,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
        template_id="t1",
        template_category=ConsentCategory.MARKETING,
    )

    assert isinstance(outcome, Queued)
    assert len(await outbox(database)) == 1


# -- Templates -------------------------------------------------------------


async def test_the_approved_template_registry_starts_empty() -> None:
    """Product must never invent a template Meta has not approved."""
    assert APPROVED_TEMPLATES == {}


async def test_an_unregistered_template_does_not_open_the_window(database) -> None:
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=30))

    outcome = await ask(
        database,
        conversation_id,
        template_id="invented_template",
        template_category=ConsentCategory.SERVICE,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.TEMPLATE_NOT_APPROVED
    assert await outbox(database) == []


async def test_a_template_approved_for_another_category_is_refused(
    database, monkeypatch
) -> None:
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=30))
    monkeypatch.setitem(
        APPROVED_TEMPLATES,
        "t1",
        ApprovedTemplate(ConsentCategory.UTILITY, "es_MX"),
    )

    outcome = await ask(
        database,
        conversation_id,
        template_id="t1",
        template_category=ConsentCategory.SERVICE,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.TEMPLATE_CATEGORY_MISMATCH


async def test_an_approved_template_carries_a_message_past_the_window(
    database, monkeypatch
) -> None:
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=30))
    monkeypatch.setitem(
        APPROVED_TEMPLATES,
        "t1",
        ApprovedTemplate(ConsentCategory.SERVICE, "es_MX"),
    )

    outcome = await ask(
        database,
        conversation_id,
        template_id="t1",
        template_category=ConsentCategory.SERVICE,
    )

    assert isinstance(outcome, Queued)
    recorded = await decisions(database)
    assert recorded[0].template_id == "t1"
    assert recorded[0].template_category == ConsentCategory.SERVICE.value

    async with database.session_scope() as session:
        message = await session.get(OutboxMessage, outcome.outbox_id)
        assert message is not None
        delivery = await OutboundMessaging(session).prepare_delivery(message, now=NOW)
        assert delivery == TemplateDelivery(WA_ID, "t1", "es_MX")
        await session.rollback()


async def test_template_identifier_and_category_must_arrive_together(database) -> None:
    _, conversation_id = await seed(database)

    outcome = await ask(database, conversation_id, template_id="t1")

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.TEMPLATE_METADATA_INCOMPLETE


# -- Idempotency, concurrency, recovery ------------------------------------


async def test_repeating_an_allowed_intent_reuses_the_same_outbox_row(
    database,
) -> None:
    _, conversation_id = await seed(database)

    first = await ask(database, conversation_id)
    second = await ask(database, conversation_id)

    assert isinstance(first, Queued) and isinstance(second, Queued)
    assert first.outbox_id == second.outbox_id
    assert first.created and not second.created
    assert len(await outbox(database)) == 1


async def test_only_one_of_two_racing_intents_creates_the_message(database) -> None:
    """Two workers, one key. The partial unique index is the arbiter."""
    _, conversation_id = await seed(database)

    async def attempt() -> bool:
        async with database.session_scope() as session:
            conversation = await session.get(Conversation, conversation_id)
            trigger = await session.scalar(
                select(InboxMessage.id).where(
                    InboxMessage.conversation_id == conversation_id
                )
            )
            assert trigger is not None
            outcome = await OutboundMessaging(session).request(
                intent(conversation, trigger_inbox_ids=(trigger,))
            )
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                return False
            return isinstance(outcome, Queued)

    results = await asyncio.gather(attempt(), attempt(), attempt())

    assert results == [True, True, True]
    assert len(await outbox(database)) == 1
    queued = [
        d for d in await decisions(database) if d.outcome == OutboundOutcome.QUEUED.value
    ]
    assert len(queued) == 1


async def test_a_denied_intent_may_be_recorded_more_than_once(database) -> None:
    """Refusing the same thing twice is history, not a constraint violation."""
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=30))

    await ask(database, conversation_id)
    await ask(database, conversation_id)

    recorded = await decisions(database)
    assert len(recorded) == 2
    assert {d.outcome for d in recorded} == {OutboundOutcome.DENIED.value}


async def test_an_interrupted_transaction_leaves_neither_half(database) -> None:
    """Recovery: a crash between staging and commit must lose the whole thing."""
    _, conversation_id = await seed(database)

    async with database.session_scope() as session:
        conversation = await session.get(Conversation, conversation_id)
        trigger = await session.scalar(
            select(InboxMessage.id).where(
                InboxMessage.conversation_id == conversation_id
            )
        )
        assert trigger is not None
        outcome = await OutboundMessaging(session).request(
            intent(conversation, trigger_inbox_ids=(trigger,))
        )
        assert isinstance(outcome, Queued)
        await session.rollback()

    assert await outbox(database) == []
    assert await decisions(database) == []


async def test_a_free_form_row_is_rechecked_after_waiting_in_the_queue(
    database,
) -> None:
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=1))
    queued = await ask(database, conversation_id)
    assert isinstance(queued, Queued)

    async with database.session_scope() as session:
        message = await session.get(OutboxMessage, queued.outbox_id)
        assert message is not None
        delivery = await OutboundMessaging(session).prepare_delivery(
            message, now=NOW + timedelta(hours=24)
        )

    assert isinstance(delivery, DeliveryDenied)
    assert delivery.reason is DenialReason.SERVICE_WINDOW_CLOSED
    messages = await outbox(database)
    assert messages[0].status == "Failed"


async def test_a_legacy_row_without_gate_evidence_is_quarantined(database) -> None:
    _, conversation_id = await seed(database)
    async with database.session_scope() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        legacy = OutboxMessage(
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            idempotency_key="legacy:pending",
            to_wa_id=WA_ID,
            kind=OutboxKind.AGENT_REPLY,
            body="No debe salir.",
            covered_inbox_ids=[],
        )
        session.add(legacy)
        await session.commit()
        delivery = await OutboundMessaging(session).prepare_delivery(legacy, now=NOW)

    assert isinstance(delivery, DeliveryDenied)
    assert delivery.reason is DenialReason.ELIGIBILITY_EVIDENCE_MISSING
    assert legacy.status == "Failed"


async def test_a_reply_that_arrives_after_queueing_stops_delivery(
    database, monkeypatch
) -> None:
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)
    monkeypatch.setitem(
        APPROVED_TEMPLATES,
        "t1",
        ApprovedTemplate(ConsentCategory.MARKETING, "es_MX"),
    )
    lead_id, conversation_id = await seed(
        database,
        last_inbound=NOW - timedelta(hours=4),
        last_outbound=NOW - timedelta(hours=3),
    )
    async with database.session_scope() as session:
        session.add(
            ConsentRecord(
                organization_id=await larevia_organization_id(session),
                lead_id=lead_id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.GRANTED.value,
                source="Test",
            )
        )
        await session.commit()
    queued = await ask(
        database,
        conversation_id,
        purpose=Purpose.LEAD_FOLLOW_UP,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
        template_id="t1",
        template_category=ConsentCategory.MARKETING,
    )
    assert isinstance(queued, Queued)

    async with database.session_scope() as session:
        await InboxService(session).accept(
            InboundMessage(
                wamid="wamid.after-queue",
                from_wa_id=WA_ID,
                phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
                message_type="text",
                text="Sigo interesado",
                sent_at=NOW + timedelta(minutes=1),
                raw={},
                profile_name=None,
            )
        )
    async with database.session_scope() as session:
        message = await session.get(OutboxMessage, queued.outbox_id)
        assert message is not None
        delivery = await OutboundMessaging(session).prepare_delivery(message)

    assert isinstance(delivery, DeliveryDenied)
    assert delivery.reason is DenialReason.CONTACT_REPLIED


async def test_an_opt_out_racing_a_request_cannot_leave_deliverable_work(
    database,
) -> None:
    _, conversation_id = await seed(database)

    async def request_notice():
        return await ask(
            database,
            conversation_id,
            purpose=Purpose.APPOINTMENT_RESOLUTION,
            initiation=OutboundInitiation.BUSINESS_INITIATED,
        )

    async def opt_out() -> None:
        async with database.session_scope() as session:
            await InboxService(session).accept(
                InboundMessage(
                    wamid="wamid.racing-optout",
                    from_wa_id=WA_ID,
                    phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
                    message_type="text",
                    text="baja",
                    sent_at=NOW + timedelta(minutes=1),
                    raw={},
                    profile_name=None,
                )
            )

    request_result, _ = await asyncio.gather(request_notice(), opt_out())
    if isinstance(request_result, Queued):
        async with database.session_scope() as session:
            message = await session.get(OutboxMessage, request_result.outbox_id)
            assert message is not None
            delivery = await OutboundMessaging(session).prepare_delivery(message)
        assert isinstance(delivery, DeliveryDenied)
        assert delivery.reason is DenialReason.SUPPRESSED
    else:
        assert request_result.reason is DenialReason.SUPPRESSED


async def test_a_denied_decision_never_stages_a_message(database) -> None:
    _, conversation_id = await seed(database, last_inbound=NOW - timedelta(hours=30))

    await ask(database, conversation_id)

    assert await outbox(database) == []
    assert (await decisions(database))[0].outbox_id is None


# -- Explicit opt-out ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["BAJA", "Baja.", "  stop  ", "Ya no me escriban", "no quiero más mensajes"],
)
def test_an_unambiguous_opt_out_is_recognised(text: str) -> None:
    assert detect_opt_out(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "No me contactes por teléfono, mejor por aquí",
        "¿Me das de baja el precio?",
        "Hola, quiero información",
        "stop mirando esa propiedad",
        "",
        None,
    ],
)
def test_ordinary_messages_are_not_treated_as_opt_outs(text) -> None:
    assert detect_opt_out(text) is None


def test_normalisation_folds_case_accents_and_punctuation() -> None:
    assert fold_phrase("  ¡NO ME CONTÁCTES!  ") == "no me contactes"


async def test_accepting_an_opt_out_message_suppresses_the_contact(database) -> None:
    """The production path: it happens as the message is stored, not later."""
    async with database.session_scope() as session:
        accepted = await InboxService(session).accept(
            InboundMessage(
                wamid="wamid.optout",
                from_wa_id=WA_ID,
                phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
                message_type="text",
                text="Ya no me escriban",
                sent_at=NOW,
                raw={},
                profile_name=None,
            )
        )

    async with database.session_scope() as session:
        suppression = (
            await session.execute(select(SuppressionRecord))
        ).scalar_one()
        consent = (await session.execute(select(ConsentRecord))).scalar_one()
        audit = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "RecordExplicitOptOut")
            )
        ).scalar_one()

    assert suppression.lead_id == accepted.lead_id
    assert suppression.reason == "ExplicitOptOut"
    assert suppression.source_inbox_id == accepted.inbox_id
    assert consent.state == ConsentState.REVOKED.value
    assert consent.category == ConsentCategory.MARKETING.value
    assert audit.details["phrase"] == "ya no me escriban"


async def test_recording_the_same_opt_out_twice_keeps_one_active_record(
    database,
) -> None:
    for index in range(2):
        async with database.session_scope() as session:
            await InboxService(session).accept(
                InboundMessage(
                    wamid=f"wamid.optout.{index}",
                    from_wa_id=WA_ID,
                    phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
                    message_type="text",
                    text="baja",
                    sent_at=NOW + timedelta(seconds=index),
                    raw={},
                    profile_name=None,
                )
            )

    async with database.session_scope() as session:
        active = list(
            (
                await session.execute(
                    select(SuppressionRecord).where(
                        SuppressionRecord.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(active) == 1


async def test_an_opt_out_immediately_blocks_the_next_proactive_message(
    database,
) -> None:
    async with database.session_scope() as session:
        accepted = await InboxService(session).accept(
            InboundMessage(
                wamid="wamid.optout.blocking",
                from_wa_id=WA_ID,
                phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
                message_type="text",
                text="baja",
                sent_at=NOW,
                raw={},
                profile_name=None,
            )
        )

    outcome = await ask(
        database,
        accepted.conversation_id,
        purpose=Purpose.APPOINTMENT_NEEDS_REVIEW,
        initiation=OutboundInitiation.BUSINESS_INITIATED,
    )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.SUPPRESSED


# -- The Product/Hermes boundary -------------------------------------------


def test_no_product_code_reaches_the_outbox_without_a_decision() -> None:
    """The gate is only a gate if nothing walks around it.

    Asserted structurally rather than behaviourally: a future caller that
    reintroduced a direct enqueue would still pass every behaviour test above
    while silently sending unauthorised messages.

    Matched on the import rather than on call text, so a comment or a docstring
    mentioning the method cannot fail this, and so the check survives the calls
    being reformatted across lines.
    """
    from tests.conftest import REPO_ROOT

    importers = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src").rglob("*.py")
        if path.name not in {"outbox.py", "outbound.py"}
        and "OutboxService" in ast_imported_names(path)
    )

    # Claiming, draining and reconciling rows that already exist is fine — both
    # of these do only that. Bringing a new one into being is what must go
    # through the gate, and neither of them can: staging is not exported.
    assert importers == [
        "src/realestate/api/webhooks.py",
        "src/realestate/worker/whatsapp.py",
    ]


def ast_imported_names(path) -> set[str]:  # noqa: ANN001
    """Every name a module imports, without importing the module."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def test_hermes_is_given_no_tool_that_touches_consent_or_suppression() -> None:
    """Hermes composes wording. It cannot grant, revoke, or bypass permission."""
    from tests.conftest import REPO_ROOT

    surfaces = [
        REPO_ROOT / "src/realestate/api/plugin.py",
        *(REPO_ROOT / "plugin").rglob("*.py"),
    ]
    forbidden = {
        "ConsentRecord",
        "SuppressionRecord",
        "OutboundMessaging",
        "OutboundIntent",
        "record_explicit_opt_out",
        "APPROVED_TEMPLATES",
    }
    for path in surfaces:
        assert not forbidden & ast_imported_names(path), path


def test_every_outbox_kind_has_an_explicit_gate_purpose() -> None:
    """Adding a sender without classifying it must fail this contract."""
    kinds = {
        value
        for name, value in vars(OutboxKind).items()
        if name.isupper() and isinstance(value, str)
    }

    assert {purpose.value for purpose in Purpose} == kinds

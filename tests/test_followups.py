"""The unanswered-inquiry follow-up policy (ADR-0021, ADR-0045).

The cadence is a named, versioned hypothesis, and every attempt it produces is
subject to the Outbound Eligibility Gate. Both halves are tested here: which
days the policy proposes, and what actually happens to those proposals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest
from sqlalchemy import delete, select

from realestate.db.engine import Database
from realestate.db.models import (
    ConsentCategory,
    ConsentRecord,
    ConsentState,
    Conversation,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    LeadFollowUp,
    LeadFollowUpStatus,
    OutboundDecision,
    OutboundOutcome,
    OutboxMessage,
    SuppressionRecord,
)
from realestate.domain.followups import (
    CADENCE_DAYS,
    FOLLOW_UP_POLICY_ID,
    FOLLOW_UP_POLICY_VERSION,
    LeadFollowUpService,
    due_at,
    followup_message,
    followup_template_id,
)
from realestate.domain.outbound import (
    APPROVED_TEMPLATES,
    ApprovedTemplate,
    DenialReason,
)
from realestate.worker.followups import LeadFollowUpWorker
from tests.conftest import (
    DATABASE_URL,
    larevia_organization_id,
    requires_postgres,
)
from tests.fixtures import commercial

pytestmark = requires_postgres

NOW = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)
WA_ID = "5215551230000"


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        for model in (
            LeadFollowUp,
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


async def cycle(
    database: Database,
    *,
    wa_id: str = WA_ID,
    started_at: datetime = NOW,
    opt_out: bool = False,
    marketing_consent: bool = False,
    inbound_at: datetime | None = None,
    outbound_at: datetime | None = None,
) -> None:
    """One engagement cycle, plus whatever history the case needs."""
    async with database.session_scope() as session:
        organization_id = await larevia_organization_id(session)
        lead = Lead(
            organization_id=organization_id,
            wa_id=wa_id,
            follow_up_opt_out=opt_out,
        )
        session.add(lead)
        await session.flush()
        row = LeadEngagementCycle(
            organization_id=lead.organization_id,
            lead_id=lead.id,
            started_at=started_at,
            expires_at=started_at + timedelta(days=30),
        )
        session.add(row)
        await session.flush()
        conversation = Conversation(
            organization_id=organization_id,
            lead_id=lead.id,
            cycle_id=row.id,
            phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
        )
        session.add(conversation)
        await session.flush()
        if marketing_consent:
            session.add(
                ConsentRecord(
                    organization_id=lead.organization_id,
                    lead_id=lead.id,
                    category=ConsentCategory.MARKETING.value,
                    state=ConsentState.GRANTED.value,
                    source="Test",
                )
            )
        if inbound_at is not None:
            session.add(
                InboxMessage(
                    organization_id=conversation.organization_id,
                    conversation_id=conversation.id,
                    wamid=f"wamid.{wa_id}.{inbound_at.timestamp()}",
                    from_wa_id=wa_id,
                    message_type="text",
                    text="Hola",
                    sent_at=inbound_at,
                    persisted_at=inbound_at,
                    raw_message={},
                    status=InboxStatus.PROCESSED.value,
                )
            )
        if outbound_at is not None:
            session.add(
                OutboxMessage(
                    organization_id=conversation.organization_id,
                    conversation_id=conversation.id,
                    idempotency_key=f"seed:{wa_id}:{outbound_at.timestamp()}",
                    to_wa_id=wa_id,
                    kind="AgentReply",
                    body="Con gusto.",
                    covered_inbox_ids=[],
                    created_at=outbound_at,
                )
            )
        await session.commit()


async def permitted_cycle(database: Database, *, started: datetime) -> None:
    """A cycle the gate would allow: consent on file, and we answered last.

    Spelled once so the one test that deliberately inverts the inbound/outbound
    order reads as different instead of needing a diff to spot.
    """
    await cycle(
        database,
        started_at=started,
        marketing_consent=True,
        inbound_at=started,
        outbound_at=started + timedelta(minutes=1),
    )


async def run(database: Database, now: datetime = NOW, limit: int = 20):
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
    """Only follow-up messages: seeded conversation history is not one."""
    async with database.session_scope() as session:
        return list(
            (
                await session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.kind == "LeadFollowUp")
                    .order_by(OutboxMessage.created_at)
                )
            )
            .scalars()
            .all()
        )


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


def allow_templates(monkeypatch) -> None:
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)
    for day in CADENCE_DAYS:
        monkeypatch.setitem(
            APPROVED_TEMPLATES,
            followup_template_id(day),
            ApprovedTemplate(ConsentCategory.MARKETING, "es_MX"),
        )


# -- The policy is a versioned hypothesis ----------------------------------


def test_the_cadence_is_the_conservative_pilot_hypothesis() -> None:
    assert CADENCE_DAYS == (1, 3, 7, 14, 28)
    assert (FOLLOW_UP_POLICY_ID, FOLLOW_UP_POLICY_VERSION) == (
        "unanswered-inquiry",
        2,
    )


def test_day_one_is_the_day_after_the_inquiry_not_its_own_instant() -> None:
    """v1 put day 1 on the cycle start, competing with the immediate answer."""
    started = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    # Detached on purpose: ``due_at`` is arithmetic over a row's own timestamps
    # and never reaches the database, so neither the Lead nor the Organization
    # has to exist for it.
    row = LeadEngagementCycle(
        lead_id=None,
        organization_id=None,
        started_at=started,
        expires_at=started + timedelta(days=30),
    )
    assert due_at(row, 1) == started + timedelta(days=1)
    assert due_at(row, 28) == started + timedelta(days=28)


def test_every_cadence_day_has_its_own_message_and_template() -> None:
    bodies = {day: followup_message(day) for day in CADENCE_DAYS}
    assert len(set(bodies.values())) == len(CADENCE_DAYS)
    templates = {followup_template_id(day) for day in CADENCE_DAYS}
    assert len(templates) == len(CADENCE_DAYS)
    assert all(str(FOLLOW_UP_POLICY_VERSION) in t for t in templates)


@pytest.mark.parametrize("day", [0, 5, 18, 22, 26])
def test_days_outside_the_current_policy_are_rejected(day: int) -> None:
    with pytest.raises(ValueError):
        followup_message(day)
    with pytest.raises(ValueError):
        followup_template_id(day)


# -- The policy is inoperative without consent and templates ---------------


async def test_a_due_follow_up_is_blocked_while_commercial_state_is_missing(
    database,
) -> None:
    """The live default: nothing goes out, and the refusal is on the record."""
    await cycle(database, started_at=NOW - timedelta(days=1))

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 1)
    assert await outbox(database) == []
    rows = await followups(database)
    assert [(r.day_number, r.status) for r in rows] == [
        (1, LeadFollowUpStatus.BLOCKED.value)
    ]
    assert rows[0].outbox_id is None
    recorded = await decisions(database)
    assert recorded[0].outcome == OutboundOutcome.DENIED.value
    assert recorded[0].reason == DenialReason.FOLLOW_UP_POLICY_INACTIVE.value
    assert rows[0].decision_id == recorded[0].id


async def test_consent_alone_is_not_enough_without_an_approved_template(
    database, monkeypatch
) -> None:
    """Day 1 is already past the 24-hour window, so a template is structural."""
    await permitted_cycle(database, started=NOW - timedelta(days=1))
    monkeypatch.setattr("realestate.domain.outbound.FOLLOW_UP_POLICY_ACTIVATED", True)

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 1)
    assert await outbox(database) == []
    assert (await decisions(database))[0].reason == (
        DenialReason.TEMPLATE_NOT_APPROVED.value
    )


async def test_a_blocked_attempt_records_its_policy_version(database) -> None:
    await cycle(database, started_at=NOW - timedelta(days=1))

    await run(database)

    row = (await followups(database))[0]
    assert (row.policy_id, row.policy_version) == (
        FOLLOW_UP_POLICY_ID,
        FOLLOW_UP_POLICY_VERSION,
    )


async def test_a_blocked_day_is_not_retried_on_the_next_tick(database) -> None:
    await cycle(database, started_at=NOW - timedelta(days=1))

    first = await run(database)
    second = await run(database)

    assert (first.enqueued, first.blocked) == (0, 1)
    assert (second.enqueued, second.blocked) == (0, 0)
    assert len(await followups(database)) == 1
    assert len(await decisions(database)) == 1


# -- What the policy proposes ----------------------------------------------


async def test_the_policy_proposes_every_elapsed_day_once(
    database, monkeypatch
) -> None:
    allow_templates(monkeypatch)
    await permitted_cycle(database, started=NOW - timedelta(days=15))

    result = await run(database)

    assert result.enqueued == 4
    assert [r.day_number for r in await followups(database)] == [1, 3, 7, 14]
    assert len(await outbox(database)) == 4


async def test_future_days_are_not_enqueued_early(database, monkeypatch) -> None:
    allow_templates(monkeypatch)
    await permitted_cycle(database, started=NOW - timedelta(days=4))

    result = await run(database)

    assert [r.day_number for r in await followups(database)] == [1, 3]
    assert result.enqueued == 2


async def test_repeating_the_tick_does_not_duplicate_a_day(
    database, monkeypatch
) -> None:
    allow_templates(monkeypatch)
    await permitted_cycle(database, started=NOW - timedelta(days=1))

    assert (await run(database)).enqueued == 1
    assert (await run(database)).enqueued == 0

    assert len(await followups(database)) == 1
    assert len(await outbox(database)) == 1


# -- What stops the sequence -----------------------------------------------


async def test_a_reply_from_the_contact_stops_the_sequence(
    database, monkeypatch
) -> None:
    """ADR-0021. The Contact wrote after we did, so we owe an answer, not this."""
    allow_templates(monkeypatch)
    started = NOW - timedelta(days=8)
    await cycle(
        database,
        started_at=started,
        marketing_consent=True,
        outbound_at=started + timedelta(minutes=1),
        inbound_at=started + timedelta(days=2),
    )

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 3)
    assert await outbox(database) == []
    assert {d.reason for d in await decisions(database)} == {
        DenialReason.CONTACT_REPLIED.value
    }


async def test_an_explicit_opt_out_stops_the_sequence(database, monkeypatch) -> None:
    allow_templates(monkeypatch)
    started = NOW - timedelta(days=4)
    await permitted_cycle(database, started=started)
    async with database.session_scope() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
        session.add(
            SuppressionRecord(
                organization_id=lead.organization_id,
                lead_id=lead.id,
                reason="ExplicitOptOut",
                evidence="baja",
            )
        )
        await session.commit()

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 2)
    assert await outbox(database) == []
    assert {d.reason for d in await decisions(database)} == {
        DenialReason.SUPPRESSED.value
    }


async def test_the_legacy_opt_out_flag_is_still_honoured(database) -> None:
    """Superseded by SuppressionRecord, but an existing opt-out still counts."""
    await cycle(database, started_at=NOW - timedelta(days=1), opt_out=True)

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 0)
    assert await followups(database) == []
    assert await decisions(database) == []


async def test_a_skipped_backfill_row_prevents_catchup_delivery(
    database, monkeypatch
) -> None:
    allow_templates(monkeypatch)
    started = NOW - timedelta(days=4)
    await permitted_cycle(database, started=started)
    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        session.add(
            LeadFollowUp(
                organization_id=conversation.organization_id,
                cycle_id=conversation.cycle_id,
                conversation_id=conversation.id,
                day_number=1,
                channel="WhatsApp",
                policy_id=FOLLOW_UP_POLICY_ID,
                policy_version=FOLLOW_UP_POLICY_VERSION,
                due_at=started + timedelta(days=1),
                status=LeadFollowUpStatus.SKIPPED.value,
            )
        )
        await session.commit()

    result = await run(database)

    assert result.enqueued == 1
    assert [(r.day_number, r.status) for r in await followups(database)] == [
        (1, LeadFollowUpStatus.SKIPPED.value),
        (3, LeadFollowUpStatus.ENQUEUED.value),
    ]


# -- Atomicity -------------------------------------------------------------


async def test_the_attempt_and_its_decision_and_message_land_together(
    database, monkeypatch
) -> None:
    allow_templates(monkeypatch)
    await permitted_cycle(database, started=NOW - timedelta(days=1))

    await run(database)

    row = (await followups(database))[0]
    message = (await outbox(database))[0]
    decision = (await decisions(database))[0]
    assert row.outbox_id == message.id
    assert row.decision_id == decision.id
    assert decision.outbox_id == message.id
    assert row.status == LeadFollowUpStatus.ENQUEUED.value


async def test_a_missing_conversation_produces_nothing_at_all(database) -> None:
    """Recovery: a deleted Conversation must not leave a half-written attempt."""
    await cycle(database, started_at=NOW - timedelta(days=1))
    async with database.session_scope() as session:
        await session.execute(delete(Conversation))
        await session.commit()

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 0)
    assert await followups(database) == []
    assert await decisions(database) == []


async def test_a_tracking_row_failure_rolls_back_decision_and_outbox(
    database, monkeypatch
) -> None:
    """The caller's final write is inside the same transaction as the gate."""
    allow_templates(monkeypatch)
    await permitted_cycle(database, started=NOW - timedelta(days=1))

    original = LeadFollowUpService._row

    def broken_row(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        row = original(*args, **kwargs)
        row.decision_id = uuid.uuid4()
        return row

    monkeypatch.setattr(LeadFollowUpService, "_row", staticmethod(broken_row))

    result = await run(database)

    assert (result.enqueued, result.blocked) == (0, 0)
    assert await followups(database) == []
    assert await outbox(database) == []
    assert await decisions(database) == []


# -- The worker ------------------------------------------------------------
#
# ``tick`` deliberately takes no clock: it is the scheduled entry point and
# reads the real one. These cases therefore place the cycle relative to now
# rather than to the fixed NOW the policy tests use.


def _worker_log(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "realestate.worker.followups"
    ]


async def test_the_worker_reports_blocked_attempts_without_treating_them_as_errors(
    database, caplog
) -> None:
    """A refused follow-up is the policy working, not a fault to alert on."""
    import logging

    await cycle(database, started_at=datetime.now(tz=UTC) - timedelta(days=2))

    with caplog.at_level(logging.DEBUG):
        await LeadFollowUpWorker(database).tick()

    worker_records = [
        r for r in caplog.records if r.name == "realestate.worker.followups"
    ]
    assert [r.levelno for r in worker_records] == [logging.INFO]
    assert "refused" in worker_records[0].getMessage()
    assert [r.status for r in await followups(database)] == [
        LeadFollowUpStatus.BLOCKED.value
    ]


async def test_the_worker_reports_what_it_enqueued(
    database, caplog, monkeypatch
) -> None:
    import logging

    allow_templates(monkeypatch)
    started = datetime.now(tz=UTC) - timedelta(days=2)
    await permitted_cycle(database, started=started)

    with caplog.at_level(logging.DEBUG):
        await LeadFollowUpWorker(database).tick()

    assert any("Enqueued 1" in message for message in _worker_log(caplog))
    assert len(await outbox(database)) == 1


async def test_a_quiet_tick_says_nothing(database, caplog) -> None:
    """Nothing due must not produce log noise on every poll interval."""
    import logging

    await cycle(database, started_at=datetime.now(tz=UTC))

    with caplog.at_level(logging.DEBUG):
        await LeadFollowUpWorker(database).tick()

    assert _worker_log(caplog) == []
    assert await followups(database) == []

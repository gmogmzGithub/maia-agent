"""Conversation content expires; commercial history does not (ADR-0026).

The test that matters most is the negative one: after the sweep, the messages
are gone but the Contact, the Opportunity, its first attribution, its outcome,
the consent record, the Suppression Record and the audit trail are all still
there. Deleting the rows instead of blanking the bodies would take the evidence
with them, and the eligibility gate needs that evidence to keep failing closed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from realestate.db.models import (
    CONVERSATION_CONTENT_RETENTION_DAYS,
    AgentRole,
    AgentSession,
    AuditEvent,
    ConsentCategory,
    ConsentRecord,
    ConsentState,
    Contact,
    ContactChannelIdentity,
    InboxMessage,
    Opportunity,
    OpportunityOrigin,
    OpportunityStage,
    OutboundDecision,
    OutboxMessage,
    OutboxStatus,
    SuppressionRecord,
)
from realestate.db.engine import Database
from realestate.domain.commercial.maintenance import (
    DORMANCY_DAYS,
    CommercialMaintenance,
)
from realestate.domain.commercial.opportunities import (
    LostReason,
    OpportunityManagement,
    RecordLost,
)
from realestate.domain.commercial.retention import ConversationRetention
from realestate.domain.commercial.views import EXPIRED_BODY, CommercialInbox
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres

NOW = commercial.now()
LONG_AGO = NOW - timedelta(days=CONVERSATION_CONTENT_RETENTION_DAYS + 5)


@pytest.fixture
async def wired():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)
    yield database
    await database.dispose()


async def _aged_thread(session, *, wa_id="5213312345678"):  # noqa: ANN001, ANN202
    """A Contact with an old conversation, both directions, and full history."""
    contact_id, lead = await commercial.make_contact(
        session, wa_id, profile_name="Ana"
    )
    conversation = await commercial.make_conversation(session, lead, started_at=LONG_AGO)
    inbound = await commercial.make_inbound(
        session,
        conversation,
        text_body="Quiero ver la casa del coto Demo.",
        sent_at=LONG_AGO,
    )
    session.add(
        OutboxMessage(
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            idempotency_key=f"out:{conversation.id}",
            to_wa_id=wa_id,
            kind="AgentReply",
            body="Con gusto, ¿qué día te acomoda?",
            covered_inbox_ids=[str(inbound.id)],
            status=OutboxStatus.SENT.value,
            created_at=LONG_AGO,
            sent_at=LONG_AGO,
        )
    )
    session.add(
        AgentSession(
            organization_id=conversation.organization_id,
            hermes_session_id=f"hermes-{conversation.cycle_id}",
            role=AgentRole.SALES.value,
            cycle_id=conversation.cycle_id,
        )
    )
    session.add(
        ConsentRecord(
            organization_id=lead.organization_id,
            lead_id=lead.id,
            category=ConsentCategory.MARKETING.value,
            state=ConsentState.REVOKED.value,
            source="InboundOptOut",
            evidence="baja",
        )
    )
    session.add(
        SuppressionRecord(
            organization_id=lead.organization_id,
            lead_id=lead.id,
            scope="BusinessInitiated",
            reason="ExplicitOptOut",
            evidence="baja",
            source_inbox_id=inbound.id,
        )
    )
    await session.flush()

    admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
    opportunity_id = await commercial.open_opportunity(
        session, admin, contact_id, conversation=conversation, inbox_id=inbound.id
    )
    await OpportunityManagement(session).record(
        admin,
        RecordLost(
            opportunity_id=opportunity_id,
            reason=LostReason.UNREACHABLE,
            command_key=f"lost:{opportunity_id}",
        ),
    )
    await session.commit()
    return contact_id, conversation.id, opportunity_id, inbound.id, conversation.cycle_id


async def test_the_bodies_expire_and_the_commercial_record_survives(wired) -> None:
    async with wired.session_scope() as session:
        (
            contact_id,
            conversation_id,
            opportunity_id,
            inbox_id,
            cycle_id,
        ) = await _aged_thread(session)

    async with wired.session_scope() as session:
        result = await ConversationRetention(session).expire(now=NOW)

        assert result.conversations == 1
        assert result.inbound_messages == 1
        assert result.outbound_messages == 1
        assert result.sessions_closed == 1
        assert result.any is True

    async with wired.session_scope() as session:
        # The conversational content is gone.
        inbound = await session.get(InboxMessage, inbox_id)
        assert inbound is not None
        assert inbound.text is None
        assert inbound.raw_message == {"expired": True}
        assert inbound.content_expired_at is not None
        outbound = await session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.conversation_id == conversation_id
            )
        )
        assert outbound is not None
        assert outbound.body == ""
        assert outbound.content_expired_at is not None
        # The Hermes session binding is forgotten, so the next contact starts
        # anew. Scoped to this cycle: an Administrative session has no cycle and
        # is none of retention's business.
        assert (
            await session.scalar(
                select(func.count(AgentSession.id)).where(
                    AgentSession.cycle_id == cycle_id
                )
            )
            == 0
        )

        # Everything the operation needs to keep operating lawfully remains.
        assert await session.get(Contact, contact_id) is not None
        identity = await session.scalar(
            select(ContactChannelIdentity).where(
                ContactChannelIdentity.contact_id == contact_id
            )
        )
        assert identity is not None
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.LOST.value
        assert opportunity.lost_reason == LostReason.UNREACHABLE.value
        origin = await session.scalar(
            select(OpportunityOrigin).where(
                OpportunityOrigin.opportunity_id == opportunity_id
            )
        )
        assert origin is not None
        # The attribution still points at the message whose body is gone: the
        # row was blanked, not deleted, so the SET NULL never fired.
        assert origin.first_conversation_id == conversation_id
        assert origin.first_inbox_id == inbox_id
        assert await session.scalar(select(func.count(SuppressionRecord.id))) == 1
        assert await session.scalar(select(func.count(ConsentRecord.id))) == 1
        assert await session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "ExpireConversationContent"
            )
        ) == 1


async def test_the_expiry_audit_records_no_content_and_no_identity(wired) -> None:
    async with wired.session_scope() as session:
        await _aged_thread(session)

    async with wired.session_scope() as session:
        await ConversationRetention(session).expire(now=NOW)

    async with wired.session_scope() as session:
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "ExpireConversationContent"
            )
        )
        assert event is not None
        details = str(event.details)
        assert "5213312345678" not in details
        assert "coto Demo" not in details
        assert "Ana" not in details


async def test_a_suppression_still_blocks_outreach_after_expiry(wired) -> None:
    """The reason not to write must outlive the message that produced it."""
    from realestate.db.models import Conversation, OutboundInitiation
    from realestate.domain.commercial.views import CommercialInbox
    from realestate.domain.outbound import (
        DenialReason,
        Denied,
        OutboundIntent,
        OutboundMessaging,
        Purpose,
    )

    async with wired.session_scope() as session:
        _contact_id, conversation_id, *_rest = await _aged_thread(session)

    async with wired.session_scope() as session:
        await ConversationRetention(session).expire(now=NOW)

    async with wired.session_scope() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        decision = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body="¿Sigues buscando?",
                purpose=Purpose.LEAD_FOLLOW_UP,
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key="after-expiry",
            )
        )
        await session.commit()

        assert isinstance(decision, Denied)
        assert decision.reason is DenialReason.SUPPRESSED
        # No Outbox row was created.
        assert await session.scalar(
            select(func.count(OutboxMessage.id)).where(
                OutboxMessage.conversation_id == conversation_id
            )
        ) == 1  # only the original reply, whose body is now empty

        # And the operator can see the refusal.
        restriction = await CommercialInbox(session).restriction(conversation)
        assert restriction.suppressed is True
        assert any(
            denial.reason == DenialReason.SUPPRESSED.value
            for denial in restriction.denials
        )
        assert await session.scalar(
            select(func.count(OutboundDecision.id)).where(
                OutboundDecision.conversation_id == conversation_id
            )
        ) == 1


async def test_expired_content_reads_as_expired_not_as_empty(wired) -> None:
    async with wired.session_scope() as session:
        _contact_id, conversation_id, *_rest = await _aged_thread(session)

    async with wired.session_scope() as session:
        await ConversationRetention(session).expire(now=NOW)

    async with wired.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        views = CommercialInbox(session)

        view = await views.conversation(admin, conversation_id)
        assert view.messages
        assert all(message.expired for message in view.messages)
        assert all(message.body == EXPIRED_BODY for message in view.messages)

        entries = await views.query(admin)
        assert entries
        assert entries[0].preview_expired is True
        assert entries[0].preview == EXPIRED_BODY


async def test_a_recent_conversation_is_left_alone(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, lead = await commercial.make_contact(session, "5213312345678")
        conversation = await commercial.make_conversation(session, lead)
        await commercial.make_inbound(session, conversation, text_body="Hola")
        await session.commit()
        assert contact_id is not None

    async with wired.session_scope() as session:
        result = await ConversationRetention(session).expire(now=NOW)
        assert result.conversations == 0
        assert result.any is False
        row = await session.scalar(select(InboxMessage))
        assert row is not None and row.text == "Hola"


async def test_a_recent_outbound_keeps_the_thread_active(wired) -> None:
    """Inactivity is measured in both directions."""
    async with wired.session_scope() as session:
        _contact_id, lead = await commercial.make_contact(session, "5213312345678")
        conversation = await commercial.make_conversation(session, lead, started_at=LONG_AGO)
        await commercial.make_inbound(
            session, conversation, text_body="Hola", sent_at=LONG_AGO
        )
        session.add(
            OutboxMessage(
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                idempotency_key="recent",
                to_wa_id="5213312345678",
                kind="AgentReply",
                body="Aquí seguimos.",
                status=OutboxStatus.SENT.value,
                created_at=NOW - timedelta(days=1),
            )
        )
        await session.commit()

    async with wired.session_scope() as session:
        assert (await ConversationRetention(session).expire(now=NOW)).conversations == 0


async def test_the_sweep_is_idempotent(wired) -> None:
    async with wired.session_scope() as session:
        await _aged_thread(session)

    async with wired.session_scope() as session:
        assert (await ConversationRetention(session).expire(now=NOW)).conversations == 1
    async with wired.session_scope() as session:
        assert (await ConversationRetention(session).expire(now=NOW)).conversations == 0


async def test_a_conversation_with_no_messages_is_not_selected(wired) -> None:
    async with wired.session_scope() as session:
        _contact_id, lead = await commercial.make_contact(session, "5213312345678")
        await commercial.make_conversation(session, lead, started_at=LONG_AGO)
        await session.commit()

    async with wired.session_scope() as session:
        # There is no content to expire, so there is nothing to do.
        assert (await ConversationRetention(session).expire(now=NOW)).conversations == 0


async def test_upkeep_runs_staleness_dormancy_and_expiry_together(wired) -> None:
    async with wired.session_scope() as session:
        # An old unanswered inquiry: stale need, dormant Opportunity, expired body.
        contact_id, lead = await commercial.make_contact(session, "5213344440000")
        conversation = await commercial.make_conversation(
            session, lead, started_at=LONG_AGO
        )
        await commercial.make_inbound(
            session, conversation, text_body="¿Está disponible?", sent_at=LONG_AGO
        )
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        opportunity.last_activity_at = LONG_AGO
        opportunity.created_at = LONG_AGO
        need = await session.get(
            __import__(
                "realestate.db.models", fromlist=["PropertyNeed"]
            ).PropertyNeed,
            opportunity.property_need_id,
        )
        assert need is not None
        need.created_at = LONG_AGO
        await session.commit()

    async with wired.session_scope() as session:
        report = await CommercialMaintenance(session).run(now=NOW)

        assert report.stale_needs == 1
        assert report.dormant_opportunities == 1
        assert report.expired_conversations == 1
        assert report.any is True

    async with wired.session_scope() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.DORMANT.value
        # Dormant is not Lost.
        assert opportunity.lost_reason is None
        assert opportunity.dormant_revisit_condition


async def test_a_quiet_upkeep_pass_reports_nothing(wired) -> None:
    async with wired.session_scope() as session:
        report = await CommercialMaintenance(session).run(now=NOW)
        assert report.any is False


async def test_dormancy_only_touches_pre_qualification_stages(wired) -> None:
    """Past Qualified the work belongs to a Responsible Advisor, not a sweep."""
    from realestate.domain.commercial.opportunities import (
        AdvanceStage,
        OpportunityManagement,
    )

    async with wired.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="q:1",
            ),
        )
        opportunity.last_activity_at = NOW - timedelta(days=DORMANCY_DAYS + 10)
        await session.commit()

    async with wired.session_scope() as session:
        assert await CommercialMaintenance(session).sweep_dormancy(now=NOW) == 0

    async with wired.session_scope() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        assert opportunity.stage == OpportunityStage.QUALIFIED.value


async def test_the_dormancy_sweep_is_idempotent_within_a_day(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        opportunity.last_activity_at = NOW - timedelta(days=DORMANCY_DAYS + 1)
        await session.commit()

    async with wired.session_scope() as session:
        assert await CommercialMaintenance(session).sweep_dormancy(now=NOW) == 1
    async with wired.session_scope() as session:
        assert await CommercialMaintenance(session).sweep_dormancy(now=NOW) == 0
    assert opportunity_id is not None


async def test_a_recently_active_opportunity_is_not_paused(wired) -> None:
    async with wired.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await commercial.open_opportunity(session, admin, contact_id)
        await session.commit()

    async with wired.session_scope() as session:
        assert await CommercialMaintenance(session).sweep_dormancy(now=NOW) == 0


async def test_the_sweep_stands_down_when_a_human_already_concluded_it(
    wired, monkeypatch
) -> None:
    """A concurrent human decision wins; the sweep records the skip and moves on."""
    from realestate.domain.commercial.actors import InvalidTransition
    from realestate.domain.commercial import maintenance as maintenance_module

    async with wired.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None
        opportunity.last_activity_at = NOW - timedelta(days=DORMANCY_DAYS + 1)
        await session.commit()

    async with wired.session_scope() as session:
        async def refuse(self, actor, command):  # noqa: ANN001, ANN202
            raise InvalidTransition("Otra persona ya la cerró.")

        monkeypatch.setattr(
            maintenance_module.OpportunityManagement, "record", refuse
        )
        assert await CommercialMaintenance(session).sweep_dormancy(now=NOW) == 0

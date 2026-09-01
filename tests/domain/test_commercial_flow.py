"""Bandeja → Oportunidad → Asignación → Siguiente acción, end to end.

One inbound WhatsApp message has to produce a Contact, a Property Need, a Demand
Opportunity with its first attribution, and a stage that says the conversation
started — atomically, inside the transaction that persisted the message. Then a
human qualifies it, an Advisor becomes responsible, an action is owed, and the
coverage promise reads 100 percent.

The flow is driven through the real webhook route and the real modules, so a
seam that only works when a test constructs its inputs by hand fails here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import func, select

from realestate.api import webhooks as webhook_api
from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    Contact,
    ContactChannelIdentity,
    LeadEngagementCycle,
    NextAction,
    NextActionKind,
    NextActionOutcome,
    NextActionStatus,
    Opportunity,
    OpportunityKind,
    OpportunityOrigin,
    OpportunityOriginSource,
    OpportunityStage,
    PropertyNeed,
    SuppressionRecord,
)
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.intake import CommercialIntake
from realestate.domain.commercial.next_actions import (
    CompleteNextAction,
    NextActions,
    ScheduleNextAction,
)
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    LostReason,
    OpportunityManagement,
    QualificationAction,
    RecordLost,
)
from realestate.domain.commercial.views import CommercialInbox, InboxFilters
from realestate.domain.inbox import InboxService
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial, webhooks

pytestmark = requires_postgres

APP_SECRET = "flow-meta-app-secret"
LEAD_WA_ID = "5215550100100"
NOW = commercial.now()


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.CREDENTIALS_JSON)
    monkeypatch.setenv("ORGANIZATION_ADMIN_LOGINS", commercial.ADMIN_LOGIN)
    monkeypatch.setenv(
        "ORGANIZATION_ADVISOR_LOGINS",
        f"{commercial.ADVISOR_LOGIN},{commercial.SECOND_ADVISOR_LOGIN}",
    )
    monkeypatch.setenv("ORGANIZATION_DEFAULT_ADVISOR_LOGIN", commercial.ADVISOR_LOGIN)
    get_settings.cache_clear()

    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)

    app = create_app(get_settings())
    app.state.database = database
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, database
    await database.dispose()
    get_settings.cache_clear()


async def _deliver(client, body: str, *, wamid: str) -> httpx.Response:  # noqa: ANN001
    payload = webhooks.text_message(
        wamid=wamid,
        body=body,
        from_wa_id=LEAD_WA_ID,
        profile_name="Ana Demo",
    )
    return await webhooks.post_signed(
        client, webhook_api.WEBHOOK_PATH, payload, APP_SECRET
    )


# -- Intake ----------------------------------------------------------------


async def test_one_inbound_message_creates_the_whole_commercial_record(
    wired,
) -> None:
    client, database = wired

    response = await _deliver(
        client, "Hola, me interesa una casa en Zapopan.", wamid="wamid.flow.1"
    )
    assert response.status_code == 200

    async with database.session_scope() as session:
        contact = await session.scalar(select(Contact))
        assert contact is not None
        assert contact.display_name == "Ana Demo"

        identity = await session.scalar(select(ContactChannelIdentity))
        assert identity is not None
        assert identity.identity == LEAD_WA_ID
        assert identity.contact_id == contact.id

        need = await session.scalar(select(PropertyNeed))
        assert need is not None
        assert need.contact_id == contact.id
        # Nothing is assumed about what they want.
        assert need.transaction_intent is None

        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        assert opportunity.contact_id == contact.id
        assert opportunity.property_need_id == need.id
        assert opportunity.kind == OpportunityKind.DEMAND.value
        # The first message opens the pursuit *and* starts the conversation.
        assert opportunity.stage == OpportunityStage.IN_CONVERSATION.value
        assert opportunity.responsible_advisor_id is None
        assert opportunity.organization_id == contact.organization_id

        origin = await session.scalar(select(OpportunityOrigin))
        assert origin is not None
        assert origin.source == OpportunityOriginSource.WHATSAPP_INBOUND.value
        assert origin.channel == "WhatsApp"
        assert origin.first_conversation_id is not None
        assert origin.first_inbox_id is not None


async def test_the_accepted_message_reports_what_it_resolved_to(wired) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        opportunity = await session.scalar(select(Opportunity))
        contact = await session.scalar(select(Contact))
        assert opportunity is not None and contact is not None

    # A redelivery reports the duplicate and deliberately does not re-resolve
    # the commercial record: the first delivery created it in the same
    # transaction, and Meta retries on the latency-sensitive path.
    async with database.session_scope() as session:
        from realestate.channels.whatsapp.payload import parse_webhook

        payload = webhooks.text_message(
            wamid="wamid.flow.1", body="Hola", from_wa_id=LEAD_WA_ID
        )
        parsed = parse_webhook(payload)
        accepted = await InboxService(session).accept(parsed.messages[0])
        assert accepted.duplicate is True
        assert accepted.inbox_id is not None
        assert accepted.contact_id is None
        assert accepted.opportunity_id is None
        # The records the first delivery made are of course still there.
        assert await session.get(Contact, contact.id) is not None
        assert await session.get(Opportunity, opportunity.id) is not None


async def test_a_second_message_continues_the_same_pursuit(wired) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")
    await _deliver(client, "¿Sigue disponible?", wamid="wamid.flow.2")

    async with database.session_scope() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert await session.scalar(select(func.count(Opportunity.id))) == 1
        assert await session.scalar(select(func.count(PropertyNeed.id))) == 1
        # One transition into In Conversation, not one per message.
        transitions = await OpportunityManagement(session).transitions(
            (await session.scalar(select(Opportunity))).id
        )
        assert [row.to_stage for row in transitions] == [
            OpportunityStage.IN_CONVERSATION.value,
            OpportunityStage.NEW.value,
        ]


async def test_a_new_conversation_after_a_closed_pursuit_opens_another(
    wired,
) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        opportunity = await session.scalar(select(Opportunity))
        cycle = await session.scalar(select(LeadEngagementCycle))
        assert opportunity is not None and cycle is not None
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=opportunity.id,
                reason=LostReason.NOT_INTERESTED,
                detail="La primera búsqueda terminó.",
                command_key="close-first-pursuit",
                at=datetime.now(tz=UTC),
            ),
        )
        cycle.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await session.commit()

    response = await _deliver(
        client,
        "Hola de nuevo, quiero iniciar otra búsqueda.",
        wamid="wamid.flow.reentry",
    )
    assert response.status_code == 200

    async with database.session_scope() as session:
        opportunities = list(
            await session.scalars(
                select(Opportunity).order_by(Opportunity.created_at)
            )
        )
        assert [row.stage for row in opportunities] == [
            OpportunityStage.LOST.value,
            OpportunityStage.IN_CONVERSATION.value,
        ]
        origins = list(await session.scalars(select(OpportunityOrigin)))
        assert len({row.first_conversation_id for row in origins}) == 2


async def test_a_later_message_in_the_same_closed_conversation_stays_attached(
    wired,
) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=opportunity.id,
                reason=LostReason.NOT_INTERESTED,
                detail="La búsqueda terminó dentro de la conversación vigente.",
                command_key="close-current-conversation",
                at=datetime.now(tz=UTC),
            ),
        )
        await session.commit()

    response = await _deliver(
        client,
        "Tengo una última pregunta sobre esta búsqueda.",
        wamid="wamid.flow.same-conversation",
    )
    assert response.status_code == 200

    async with database.session_scope() as session:
        opportunities = list(await session.scalars(select(Opportunity)))
        assert len(opportunities) == 1
        assert opportunities[0].stage == OpportunityStage.LOST.value
        assert await session.scalar(select(func.count(PropertyNeed.id))) == 1


async def test_a_redelivered_webhook_creates_nothing_twice(wired) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert await session.scalar(select(func.count(Opportunity.id))) == 1
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "OpenOpportunity"
                )
            )
            == 1
        )


async def test_two_different_people_get_two_records(wired) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")
    other = webhooks.text_message(
        wamid="wamid.flow.other",
        body="Hola",
        from_wa_id="5215550100200",
        profile_name="Beto Demo",
    )
    await webhooks.post_signed(client, webhook_api.WEBHOOK_PATH, other, APP_SECRET)

    async with database.session_scope() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 2
        assert await session.scalar(select(func.count(Opportunity.id))) == 2


async def test_an_opt_out_message_suppresses_and_still_opens_the_record(
    wired,
) -> None:
    """Do Not Contact is a restriction, not an outcome; the record still exists."""
    client, database = wired
    await _deliver(client, "baja", wamid="wamid.flow.optout")

    async with database.session_scope() as session:
        assert await session.scalar(select(func.count(SuppressionRecord.id))) == 1
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        # Not Lost, not Dormant.
        assert opportunity.stage == OpportunityStage.IN_CONVERSATION.value


async def test_the_intake_resolves_the_organization_from_the_channel(wired) -> None:
    """Meta knows a phone number, and Stage 9 makes that the whole answer.

    This test used to assert that intake resolved the Organization *by slug* —
    the shortcut ADR-0019 recorded as "the seam a mapping will land on". The
    mapping has landed: the number the message arrived on is looked up in the
    channel bindings, and an unbound one is refused (ADR-0050).
    """
    from realestate.db.models import ChannelBindingKind
    from realestate.domain.platform.routing import OrganizationRouting

    _client, database = wired
    async with database.session_scope() as session:
        expected = await commercial.organization_id(session)
        routed = await OrganizationRouting(session).resolve(
            ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
            commercial.TEST_PHONE_NUMBER_ID,
        )
        assert routed.organization_id == expected


async def test_an_unbound_number_stops_intake_loudly(wired) -> None:
    """A message on a number nobody claims is refused, never defaulted.

    The failure this replaces is not an exception — it is a *success*: the
    message would have been filed under whichever Organization happened to
    exist, answered from the wrong channel, and attributed to somebody who never
    spoke to that customer.
    """
    from realestate.channels.whatsapp.payload import InboundMessage
    from realestate.domain.inbox import InboxService
    from realestate.domain.platform.routing import UnroutableChannel

    _client, database = wired
    async with database.session_scope() as session:
        with pytest.raises(UnroutableChannel):
            await InboxService(session).accept(
                InboundMessage(
                    wamid="wamid.flow.unbound",
                    from_wa_id="5213300000000",
                    phone_number_id="000000000000000",
                    message_type="text",
                    sent_at=datetime.now(tz=UTC),
                    text="Hola",
                    profile_name=None,
                    raw={},
                )
            )


async def test_a_conversation_without_a_resolved_contact_reports_none(wired) -> None:
    _client, database = wired
    async with database.session_scope() as session:
        lead = await commercial.make_lead(session, "5215559990000")
        conversation = await commercial.make_conversation(session, lead)
        assert (
            await CommercialIntake(session).opportunity_for_conversation(conversation)
            is None
        )


# -- The full operating loop ----------------------------------------------


async def test_inbox_to_opportunity_to_assignment_to_next_action(wired) -> None:
    client, database = wired

    # 1. The lead writes. The Inbox surface shows work waiting for an answer.
    await _deliver(client, "Hola, busco casa en Zapopan norte.", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        views = CommercialInbox(session)
        entries = await views.query(admin, InboxFilters(needs_reply=True), now=NOW)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.contact_name == "Ana Demo"
        assert entry.awaiting_reply is True
        assert entry.stage == OpportunityStage.IN_CONVERSATION.value
        assert entry.advisor_name is None
        assert entry.next_action is None
        opportunity_id = entry.opportunity_id
        assert opportunity_id is not None

        # Follow-up Coverage begins only at Qualified. Pre-qualification work
        # is visible in Inbox and Assignment Queue without diluting the metric.
        coverage = await views.coverage(admin, now=NOW)
        assert coverage.active == 0
        assert coverage.percentage == 100
        assert coverage.complete is True

        # 2. Before qualification it is already visible as unassigned work.
        queue = await Assignment(session).queue(admin)
        assert [item.opportunity.id for item in queue] == [opportunity_id]

    # 3. The criteria get confirmed and the Opportunity qualifies, which is what
    #    triggers assignment.
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        result = await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="flow:qualify",
                at=NOW,
                qualification_action=QualificationAction(
                    kind=NextActionKind.SEND_LISTINGS,
                    due_at=NOW + timedelta(days=1),
                    note="Mandar tres opciones en Zapopan norte.",
                ),
            ),
        )
        await session.commit()

        assert result.stage is OpportunityStage.QUALIFIED
        assert result.queued_for_assignment is False
        advisor_id = result.responsible_advisor_id
        assert advisor_id is not None

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        # The queue emptied itself the moment somebody became responsible.
        assert await Assignment(session).queue(admin) == []
        coverage = await CommercialInbox(session).coverage(admin, now=NOW)
        # Qualification, assignment and the first obligation were atomic.
        assert coverage.without_advisor == 0
        assert coverage.without_action == 0
        assert coverage.complete is True
        scheduled = await session.scalar(
            select(NextAction).where(
                NextAction.opportunity_id == opportunity_id,
                NextAction.status == NextActionStatus.PENDING,
            )
        )
        assert scheduled is not None
        scheduled_action_id = scheduled.id

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        views = CommercialInbox(session)
        coverage = await views.coverage(admin, now=NOW)
        assert coverage.active == 1
        assert coverage.covered == 1
        assert coverage.percentage == 100
        assert coverage.complete is True
        assert coverage.qualified_active == 1
        assert coverage.qualified_covered == 1
        assert coverage.gaps == ()

        rows = await views.opportunities(admin, now=NOW)
        assert len(rows) == 1
        assert rows[0].covered is True
        assert rows[0].advisor_name
        assert rows[0].next_action is not None
        assert rows[0].overdue is False

    # 5. The action is carried out, with a recorded result.
    async with database.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        completed = await NextActions(session).complete(
            advisor,
            CompleteNextAction(
                next_action_id=scheduled_action_id,
                outcome=NextActionOutcome.DONE,
                outcome_detail="Le mandé tres fichas.",
                command_key="flow:complete",
            ),
        )
        await session.commit()
        assert completed.outcome is NextActionOutcome.DONE

    # 6. The system leaves an auditable AdminReview exception instead of
    #    silently claiming there is no remaining obligation.
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        coverage = await CommercialInbox(session).coverage(admin, now=NOW)
        assert coverage.covered == 1
        assert coverage.without_action == 0
        assert coverage.gaps == ()


async def test_an_overdue_action_is_a_coverage_gap(wired) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity.id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="flow:overdue:qualify",
                at=NOW - timedelta(days=1),
                qualification_action=QualificationAction(
                    kind=NextActionKind.CALL,
                    due_at=NOW - timedelta(hours=2),
                ),
            ),
        )
        await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity.id,
                kind=NextActionKind.CALL,
                due_at=NOW - timedelta(hours=1),
                command_key="flow:overdue",
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        coverage = await CommercialInbox(session).coverage(admin, now=NOW)
        assert coverage.overdue == 1
        assert coverage.complete is False
        assert coverage.gaps[0].overdue is True


async def test_a_recorded_exception_satisfies_the_promise(wired) -> None:
    """A Next Action **or** an auditable exception — both discharge it."""
    from realestate.db.models import OpportunityExceptionReason

    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        await Assignment(session).assign(admin, opportunity.id)
        await OpportunityManagement(session).record_exception(
            admin,
            opportunity.id,
            reason=OpportunityExceptionReason.AWAITING_CONTACT,
            detail="Quedó de confirmar el sábado.",
            command_key="flow:exception",
        )
        await session.commit()

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        coverage = await CommercialInbox(session).coverage(admin, now=NOW)
        assert coverage.complete is True
        rows = await CommercialInbox(session).opportunities(admin, now=NOW)
        assert rows[0].exception_reason == "AwaitingContact"
        assert rows[0].covered is True


async def test_a_closed_opportunity_does_not_count_against_coverage(wired) -> None:
    from realestate.domain.commercial.opportunities import LostReason, RecordLost

    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=opportunity.id,
                reason=LostReason.NOT_INTERESTED,
                command_key="flow:lost",
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        coverage = await CommercialInbox(session).coverage(admin, now=NOW)
        assert coverage.active == 0
        assert coverage.percentage == 100
        rows = await CommercialInbox(session).opportunities(
            admin, include_closed=True, now=NOW
        )
        assert len(rows) == 1
        assert rows[0].covered is True


async def test_the_inbox_filters_narrow_without_widening_authority(wired) -> None:
    client, database = wired
    await _deliver(client, "Hola", wamid="wamid.flow.1")

    async with database.session_scope() as session:
        views = CommercialInbox(session)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)

        assert len(await views.query(admin, InboxFilters(scope="unassigned"))) == 1
        assert await views.query(admin, InboxFilters(scope="mine")) == []
        assert await views.query(admin, InboxFilters(overdue=True)) == []
        assert await views.query(admin, InboxFilters(restricted=True)) == []
        assert len(await views.query(admin, InboxFilters(query="Ana"))) == 1
        assert len(await views.query(admin, InboxFilters(query="55501"))) == 1
        assert await views.query(admin, InboxFilters(query="Nadie")) == []
        assert (
            await views.query(
                admin, InboxFilters(stage=OpportunityStage.QUALIFIED.value)
            )
            == []
        )
        # An Advisor asking for everything still gets only their own work.
        assert await views.query(advisor, InboxFilters(scope="all")) == []


async def test_an_unknown_conversation_is_not_found(wired) -> None:
    _client, database = wired
    from realestate.domain.commercial.actors import NotFound

    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        with pytest.raises(NotFound):
            await CommercialInbox(session).conversation(admin, uuid.uuid4())


async def test_a_conversation_with_no_contact_yet_is_not_found(wired) -> None:
    from realestate.domain.commercial.actors import NotFound

    _client, database = wired
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        lead = await commercial.make_lead(session, "5215559990000")
        conversation = await commercial.make_conversation(session, lead)
        await session.commit()
        with pytest.raises(NotFound, match="contacto"):
            await CommercialInbox(session).conversation(admin, conversation.id)

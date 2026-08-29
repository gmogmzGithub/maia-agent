"""Commercial truth becomes analytics events exactly once.

The keys are derived from the subject's identity — ``qualified:<opportunity>``,
``appointment-attended:<appointment>`` — so a second pass cannot emit a second
event no matter how often the worker runs or restarts. These tests drive the
emitter repeatedly on purpose: "runs again and changes nothing" is the whole
contract.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    Appointment,
    AppointmentStatus,
    ChannelHandoffPurpose,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.analytics.emission import AnalyticsEmission
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateProperty,
)
from realestate.domain.commercial.opportunities import (
    LostReason,
    OpportunityManagement,
    RecordLost,
)
from realestate.domain.public.handoff import ChannelHandoff, CreateHandoff
from tests.conftest import (
    DATABASE_URL,
    requires_postgres,
    reset_property_inventory,
)
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    actor_for,
    make_conversation,
    make_inbound,
    opportunity_for,
    provision,
    reset,
)
from tests.fixtures.sponsorship import (
    MOMENT,
    active_campaign,
    published_catalog,
)

pytestmark = requires_postgres


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await provision(session)
        await session.commit()
    yield database
    await database.dispose()


async def test_running_the_emitter_twice_emits_each_fact_once(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213311110001", confirm_criteria=True)
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=state.opportunity_id,
                reason=LostReason.UNREACHABLE,
                command_key="emission:lost",
                at=MOMENT,
            ),
        )
        await session.commit()

        emission = AnalyticsEmission(session, admin)
        first = await emission.emit_operational()
        await session.commit()
        second = await emission.emit_operational()
        await session.commit()

        assert first.total >= 1
        # The second pass finds every key already enqueued.
        assert second.total == 0
        keys = {
            key
            for (key,) in await session.execute(
                select(AnalyticsOutboxEntry.event_key)
            )
        }
        assert f"outcome:{state.opportunity_id}" in keys


async def test_an_appointment_emits_requested_verified_and_only_recorded_attendance(
    database,
) -> None:
    """Attendance is emitted only after a human recorded it.

    That gap is the reason ``Sin registrar`` exists: Product will not manufacture
    a Missed milestone for a visit nobody wrote up.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213311110002")
        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        physical = await CatalogAdministration(session).record(
            admin,
            CreateProperty(
                property_key="casa-emision",
                name="Casa Emisión",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "Test"},
                command_key="emission:property",
            ),
        )
        appointment = Appointment(
            organization_id=admin.organization_id,
            reference="VIS-EMISSION-1",
            idempotency_key="emission-visit-1",
            conversation_id=conversation.id,
            lead_id=state.lead.id,
            property_uuid=physical.subject_id,
            starts_at=MOMENT + timedelta(days=1),
            ends_at=MOMENT + timedelta(days=1, minutes=90),
            status=AppointmentStatus.CONFIRMED.value,
            created_at=MOMENT,
        )
        session.add(appointment)
        await session.commit()

        emission = AnalyticsEmission(session, admin)
        await emission.emit_operational()
        await session.commit()
        keys = await _keys(session)
        assert f"appointment-requested:{appointment.id}" in keys
        assert f"appointment-verified:{appointment.id}" in keys
        assert f"appointment-attended:{appointment.id}" not in keys

        appointment.attendance = "Attended"
        appointment.attendance_recorded_at = MOMENT + timedelta(days=1, hours=2)
        appointment.attendance_recorded_by = admin.member_id
        await session.commit()

        await emission.emit_operational()
        await session.commit()
        assert f"appointment-attended:{appointment.id}" in await _keys(session)


async def test_a_first_response_is_one_event_per_conversation(database) -> None:
    """Several fragments answered by one reply is one first response.

    Counting per covered fragment would make a fast answer to a chatty Contact
    look like three fast answers.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213311110003")
        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        for offset in range(3):
            await make_inbound(
                session, conversation, sent_at=MOMENT + timedelta(seconds=offset)
            )
        session.add(
            OutboxMessage(
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                idempotency_key="emission-outbox-1",
                to_wa_id=state.lead.wa_id,
                kind="AgentReply",
                body="Con gusto te ayudo.",
                status=OutboxStatus.SENT.value,
                created_at=MOMENT,
                sent_at=MOMENT + timedelta(minutes=3),
            )
        )
        await session.commit()

        await AnalyticsEmission(session, admin).emit_operational()
        await session.commit()

        count = await session.scalar(
            select(func.count(AnalyticsOutboxEntry.id)).where(
                AnalyticsOutboxEntry.event_name
                == AnalyticsEventName.FIRST_RESPONSE_RECORDED.value
            )
        )
        assert count == 1


async def test_an_undelivered_reply_produces_no_first_response(database) -> None:
    """A queued reply is not a response. Only a sent one is."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213311110004")
        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        await make_inbound(session, conversation, sent_at=MOMENT)
        session.add(
            OutboxMessage(
                organization_id=conversation.organization_id,
                conversation_id=conversation.id,
                idempotency_key="emission-outbox-pending",
                to_wa_id=state.lead.wa_id,
                kind="AgentReply",
                body="Sin entregar.",
                status=OutboxStatus.PENDING.value,
                created_at=MOMENT,
            )
        )
        await session.commit()

        report = await AnalyticsEmission(session, admin).emit_operational()
        await session.commit()
        assert report.first_responses == 0


async def test_an_emitted_outcome_reaches_the_event_store_pseudonymously(
    database,
) -> None:
    """The subject reference is a digest, never the Contact identifier."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213311110005", confirm_criteria=True)
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=state.opportunity_id,
                reason=LostReason.NO_BUDGET,
                command_key="emission:pseudonym",
                at=MOMENT,
            ),
        )
        await session.commit()
        await AnalyticsEmission(session, admin).emit_operational()
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        row = await session.scalar(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.event_key == f"outcome:{state.opportunity_id}"
            )
        )
        assert row is not None
        assert row.attributes == {"outcome": "Lost"}
        assert row.subject_reference is not None
        assert row.subject_reference != str(state.contact_id)
        assert len(row.subject_reference) == 32


async def test_a_verified_sponsored_handoff_tags_the_later_outcome(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "emission-attribution")
        state = await opportunity_for(session, "5213311110099", confirm_criteria=True)
        handoff = ChannelHandoff(session, admin)
        created = await handoff.create(
            CreateHandoff(
                purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                command_key="emission-sponsored-handoff",
                listing_id=campaign.listing.listing_id,
                sponsorship_campaign_id=campaign.campaign_id,
            ),
            at=MOMENT,
        )
        await handoff.resolve(
            created.token,
            verified_contact_id=state.contact_id,
            whatsapp_conversation_id=None,
            at=MOMENT,
        )
        await OpportunityManagement(session).record(
            admin,
            RecordLost(
                opportunity_id=state.opportunity_id,
                reason=LostReason.NO_BUDGET,
                command_key="emission:sponsored-outcome",
                at=MOMENT + timedelta(days=3),
            ),
        )
        await session.commit()

        await AnalyticsEmission(session, admin).emit_operational()
        await session.commit()
        outcome = await session.scalar(
            select(AnalyticsOutboxEntry).where(
                AnalyticsOutboxEntry.event_key == f"outcome:{state.opportunity_id}"
            )
        )
        assert outcome is not None
        assert outcome.payload["campaign_id"] == str(campaign.campaign_id)


async def _keys(session) -> set[str]:
    return {
        key for (key,) in await session.execute(select(AnalyticsOutboxEntry.event_key))
    }

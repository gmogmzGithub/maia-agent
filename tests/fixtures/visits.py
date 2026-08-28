"""Shared setup for the Stage 3 human-operation suites.

One place builds the pieces every one of them needs — a team whose Advisors have
authoritative calendars, an accepted Property, a WhatsApp conversation — so the
suites assert behaviour rather than re-deriving the same wiring, and so a schema
change breaks one helper instead of nine files.

Everything goes through the real modules. A fixture that inserted an Appointment
row or a member row directly would not exercise the invariants these tests exist
to prove.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.payload import parse_webhook
from realestate.db.models import (
    Appointment,
    AvailabilitySnapshot,
    Conversation,
    InboxGroup,
    InboxMessage,
    Lead,
    LeadEngagementCycle,
    OrganizationMember,
    OutboxMessage,
    Property,
)
from realestate.domain.appointments import AppointmentPolicy
from realestate.domain.commercial.actors import Actor
from realestate.domain.inbox import InboxService
from realestate.domain.properties import ArtifactStore, PropertyService
from realestate.domain.scheduling.advisors import AdvisorScheduling
from realestate.domain.scheduling.appointments import Appointments
from tests.fixtures import commercial, webhooks
from tests.fixtures.stubs import SCHEDULE, StubCalendar, StubCalendarDirectory

FIXTURES = Path(__file__).parent
CASA_ROBLE = (FIXTURES / "casa-roble.md").read_bytes()

#: Tables the Stage 3 suites clear. Conversation-scoped rows cascade from
#: ``leads``; the rest reference ``organization_members`` with RESTRICT and have
#: to go explicitly, before any suite replaces the directory.
RESET_ORDER = (
    "internal_alerts",
    "appointment_reminders",
    "human_handoff_requests",
    "conversation_handling",
    "advisor_absences",
    "property_experts",
    "appointments",
    "availability_snapshots",
    "listing_media",
    "listing_offers",
    "catalog_listings",
    "outbox_messages",
    "outbound_decisions",
    "inbox_messages",
    "inbox_groups",
    "conversations",
    "lead_engagement_cycles",
    "audit_events",
    "commercial_command_receipts",
    "contacts",
    "leads",
    "properties",
    "unit_models",
    "developments",
    # Last, and only after everything that references it with RESTRICT is gone.
    # These suites are about the team itself, so each starts from the plan
    # ``build`` reconciles rather than inheriting a member another test created.
    "organization_members",
)


def policy(*, day_of_reminder_hour: int = 9) -> AppointmentPolicy:
    return AppointmentPolicy(
        schedule=SCHEDULE,
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
        day_of_reminder_hour=day_of_reminder_hour,
    )


@dataclass
class Operation:
    """Everything a Stage 3 suite drives, already wired together."""

    admin: Actor
    advisor: Actor
    second_advisor: Actor
    product: Actor
    members: dict[str, uuid.UUID]
    calendars: StubCalendarDirectory
    #: The default Advisor's calendar, which is the one most suites touch.
    calendar: StubCalendar
    second_calendar: StubCalendar
    property_uuid: uuid.UUID

    @property
    def advisor_id(self) -> uuid.UUID:
        return self.members[commercial.ADVISOR_LOGIN]

    @property
    def second_advisor_id(self) -> uuid.UUID:
        return self.members[commercial.SECOND_ADVISOR_LOGIN]

    @property
    def admin_id(self) -> uuid.UUID:
        return self.members[commercial.ADMIN_LOGIN]

    def scheduling(self, session: AsyncSession) -> AdvisorScheduling:
        return AdvisorScheduling(session, self.calendars, policy().scheduling)

    def visits(
        self, session: AsyncSession, *, day_of_reminder_hour: int = 9
    ) -> Appointments:
        return Appointments(
            session,
            self.scheduling(session),
            schedule=SCHEDULE,
            day_of_reminder_hour=day_of_reminder_hour,
            max_candidates=6,
        )


async def reset(session: AsyncSession) -> None:
    for table_name in RESET_ORDER:
        await session.execute(text(f"DELETE FROM {table_name}"))
    await session.commit()


async def build(session: AsyncSession, artifacts_root: Path) -> Operation:
    """A team with calendars, one accepted Property, and nothing else.

    Reconciliation happens first because intake assigns an Opportunity as it
    opens it: a team provisioned after the first message would leave every
    pursuit in the Assignment Queue and the suites would assert on that instead
    of on what they are about.
    """
    members = await commercial.provision_bookable_team(session)
    calendars = StubCalendarDirectory()
    calendar = calendars.add(commercial.ADVISOR_CALENDAR_ID)
    second = calendars.add(commercial.SECOND_ADVISOR_CALENDAR_ID)

    accepted = await PropertyService(
        session, ArtifactStore(artifacts_root)
    ).accept_upload("casa-roble.md", CASA_ROBLE, actor_id="developer")
    property_uuid = await session.scalar(
        select(Property.id).where(Property.property_key == accepted.property_key)
    )
    assert property_uuid is not None

    return Operation(
        admin=await commercial.actor_for(session, commercial.ADMIN_LOGIN),
        advisor=await commercial.actor_for(session, commercial.ADVISOR_LOGIN),
        second_advisor=await commercial.actor_for(
            session, commercial.SECOND_ADVISOR_LOGIN
        ),
        product=await commercial.product_actor(session),
        members=members,
        calendars=calendars,
        calendar=calendar,
        second_calendar=second,
        property_uuid=property_uuid,
    )


async def inbound(
    session: AsyncSession,
    *,
    wamid: str,
    body: str,
    from_wa_id: str = "5213312345678",
) -> Conversation:
    """One authenticated inbound message, through the real Inbox path.

    Using ``InboxService.accept`` rather than inserting rows is the point: the
    opt-out rule, the commercial record and the Stage 3 inbound routing all run
    inside that transaction, and a fixture that skipped it would test none of
    them.
    """
    message = parse_webhook(
        webhooks.text_message(wamid=wamid, body=body, from_wa_id=from_wa_id)
    ).messages[0]
    accepted = await InboxService(session).accept(message)
    conversation = await session.get(Conversation, accepted.conversation_id)
    assert conversation is not None
    return conversation


async def first_slot(
    operation: Operation, session: AsyncSession, *, advisor_id: uuid.UUID | None = None
) -> datetime:
    """The earliest Available Slot for one Advisor, read authoritatively."""
    from realestate.domain.scheduling.advisors import SlotQuery, SlotsUnavailable

    found = await operation.scheduling(session).find_slots(
        SlotQuery(
            organization_id=operation.admin.organization_id,
            advisor_id=advisor_id or operation.advisor_id,
        )
    )
    assert not isinstance(found, SlotsUnavailable), found
    assert found.slots, "the stub calendar should be empty"
    return found.slots[0].start


async def confirmed_visit(
    operation: Operation,
    session: AsyncSession,
    conversation: Conversation,
    *,
    start: datetime | None = None,
) -> Appointment:
    """One Confirmed visit, booked through the real module."""
    from realestate.domain.scheduling.appointments import BookVisit, VisitRefused

    moment = start or await first_slot(operation, session)
    outcome = await operation.visits(session).book(
        operation.product,
        BookVisit(
            conversation_id=conversation.id,
            property_uuid=operation.property_uuid,
            start=moment,
            command_key=f"book:{uuid.uuid4().hex}",
            attendee_name="Ana Demo",
        ),
    )
    assert not isinstance(outcome, VisitRefused), outcome
    row = await session.get(Appointment, outcome.appointment_id)
    assert row is not None
    return row


async def age_absence(
    session: AsyncSession, absence_id: uuid.UUID, *, days: int
) -> None:
    """Shift an absence into the past so a suite can assert on its end."""
    from realestate.db.models import AdvisorAbsence

    row = await session.get(AdvisorAbsence, absence_id)
    assert row is not None
    row.starts_at = row.starts_at - timedelta(days=days)
    row.ends_at = row.ends_at - timedelta(days=days)
    await session.commit()


def now() -> datetime:
    return datetime.now(tz=UTC)


__all__ = [
    "Appointment",
    "AvailabilitySnapshot",
    "CASA_ROBLE",
    "Conversation",
    "InboxGroup",
    "InboxMessage",
    "Lead",
    "LeadEngagementCycle",
    "Operation",
    "OrganizationMember",
    "OutboxMessage",
    "age_absence",
    "build",
    "confirmed_visit",
    "delete",
    "first_slot",
    "inbound",
    "now",
    "policy",
    "reset",
    # Re-exported so a suite that already imports this module does not need a
    # second datetime import just to age a row.
    "timedelta",
]


def key(name: str) -> str:
    """A unique command key, so a replay is deliberate rather than accidental."""
    return f"{name}:{uuid.uuid4().hex}"

"""Visits: booked, rescheduled, cancelled, and recorded afterwards.

Every appointment here belongs to one Advisor and is written to that Advisor's
authoritative calendar (PROJECT_MEMORY, ADR-0048). Stage 0 booked against one
global Broker calendar, which was correct when the operation had one person and
becomes a lie the moment it has two.

Four properties are load-bearing.

**Nothing is Confirmed without an owner and authority.** A visit with no
Responsible Advisor, with an absent one, or with one whose calendar Product
cannot read, is refused. The refusal is a named reason with its own Spanish
sentence, because "no se pudo agendar" in front of five different remedies is
not an error report.

**The attempt is durable before the side effect.** The row is written and
committed before Calendar is touched, so a crash reconciles *this* attempt
instead of issuing a logically new booking (P-042). An inconclusive Calendar
answer becomes ``NeedsReview`` — never a confirmation, never a blind retry.

**Rescheduling secures the new slot first.** The successor is created and
confirmed before the original's event is released, so a failure anywhere leaves
the original Confirmed. That ordering is the whole guarantee ADR-0037 asks for,
and it is why ``Rescheduled`` is a state a row only reaches *after* its
successor exists.

**Cancellation decides nothing commercial.** It does not close the Opportunity,
does not make it Lost, and does not make it Dormant. The Advisor decides that
later, with evidence (ADR-0032, ADR-0037).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.google.calendar import CalendarOutcome
from realestate.db.models import (
    Appointment,
    AppointmentAttendance,
    AppointmentStatus,
    AssignmentQueueReason,
    Conversation,
    InternalAlertKind,
    Lead,
    LeadEngagementCycle,
    NextActionKind,
    NextActionOutcome,
    Opportunity,
    OrganizationMember,
    OutboundInitiation,
    Property,
    PropertyExpert,
    PropertyStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.availability import Interval, WeeklySchedule
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, NotAuthorized, NotFound
from realestate.domain.commercial.idempotency import CommercialCommands
from realestate.domain.internal_alerts import InternalAlerts
from realestate.domain.scheduling.advisors import (
    AdvisorScheduling,
    SlotQuery,
    SlotsUnavailable,
    Unavailable,
)
from realestate.domain.scheduling.appointment_handoff import AppointmentHandoff
from realestate.domain.scheduling.calendars import CalendarPort

logger = logging.getLogger(__name__)


class _SlotAlreadyClaimed(Exception):
    """The database serialized two otherwise-authoritative slot reads."""


class _RescheduleAlreadyInProgress(Exception):
    """One original appointment already has an unrejected successor."""


def _reference() -> str:
    return f"APT-{secrets.token_hex(4).upper()}"


class Refusal(str, Enum):
    """Why a visit could not be booked, moved or closed. Stable codes."""

    CONVERSATION_EXPIRED = "ConversationExpired"
    PROPERTY_NOT_FOUND = "PropertyNotFound"
    PROPERTY_INACTIVE = "PropertyInactive"
    NO_RESPONSIBLE_ADVISOR = "NoResponsibleAdvisor"
    ADVISOR_INELIGIBLE = "AdvisorIneligible"
    CONDUCTOR_NOT_EXPERT = "ConductorNotPropertyExpert"
    ADVISOR_ABSENT = "AdvisorAbsent"
    NO_AUTHORITATIVE_CALENDAR = "NoAuthoritativeCalendar"
    CALENDAR_UNREADABLE = "CalendarUnreadable"
    SLOT_UNAVAILABLE = "SlotUnavailable"
    NOT_CONFIRMED = "NotConfirmed"
    ALREADY_STARTED = "AlreadyStarted"
    NOT_YET_HELD = "NotYetHeld"
    UNCHANGED = "Unchanged"
    INCONCLUSIVE = "Inconclusive"


REFUSAL_MESSAGES: dict[str, str] = {
    Refusal.CONVERSATION_EXPIRED.value: "Esa conversación ya expiró.",
    Refusal.PROPERTY_NOT_FOUND.value: "No encontramos esa propiedad.",
    Refusal.PROPERTY_INACTIVE.value: (
        "Esa propiedad no está disponible para agendar visitas."
    ),
    Refusal.NO_RESPONSIBLE_ADVISOR.value: (
        "Esta oportunidad no tiene asesor responsable. Asígnala antes de "
        "agendar la visita."
    ),
    Refusal.ADVISOR_INELIGIBLE.value: "Ese asesor no puede recibir visitas.",
    Refusal.CONDUCTOR_NOT_EXPERT.value: (
        "Ese asesor no está designado como especialista de la propiedad."
    ),
    Refusal.ADVISOR_ABSENT.value: (
        "El asesor tiene una ausencia registrada en esa fecha."
    ),
    Refusal.NO_AUTHORITATIVE_CALENDAR.value: (
        "El asesor no tiene calendario configurado, así que no podemos "
        "confirmar la visita."
    ),
    Refusal.CALENDAR_UNREADABLE.value: (
        "No pudimos consultar la disponibilidad en este momento."
    ),
    Refusal.SLOT_UNAVAILABLE.value: "Ese horario ya no está disponible.",
    Refusal.NOT_CONFIRMED.value: "Esa cita no está confirmada.",
    Refusal.ALREADY_STARTED.value: "Esa visita ya empezó o ya pasó.",
    Refusal.NOT_YET_HELD.value: (
        "Esa visita todavía no ocurre; no se puede registrar su resultado."
    ),
    Refusal.UNCHANGED.value: "Esa cita ya está a esa hora; no hubo cambios.",
    Refusal.INCONCLUSIVE.value: (
        "No pudimos confirmar el cambio con el calendario. La cita original "
        "sigue en pie y un administrador la revisará."
    ),
}

#: How ``Unavailable`` from the scheduling module maps onto a booking refusal.
#: One translation table rather than a per-branch guess, so a new scheduling
#: reason cannot silently become a generic failure.
_FROM_SCHEDULING: dict[str, Refusal] = {
    Unavailable.NO_ADVISOR.value: Refusal.NO_RESPONSIBLE_ADVISOR,
    Unavailable.ADVISOR_INELIGIBLE.value: Refusal.ADVISOR_INELIGIBLE,
    Unavailable.ADVISOR_ABSENT.value: Refusal.ADVISOR_ABSENT,
    Unavailable.NO_AUTHORITATIVE_CALENDAR.value: Refusal.NO_AUTHORITATIVE_CALENDAR,
    Unavailable.CALENDAR_UNREADABLE.value: Refusal.CALENDAR_UNREADABLE,
}

#: How the assignment rule's "nobody" reason reads as a booking refusal.
_FROM_QUEUE_REASON: dict[str, Refusal] = {
    AssignmentQueueReason.EVERY_CANDIDATE_ABSENT.value: Refusal.ADVISOR_ABSENT,
    AssignmentQueueReason.DEFAULT_ADVISOR_INACTIVE.value: Refusal.ADVISOR_INELIGIBLE,
    AssignmentQueueReason.NO_ELIGIBLE_ADVISOR.value: Refusal.NO_RESPONSIBLE_ADVISOR,
}

ATTENDANCE_LABELS: dict[str, str] = {
    AppointmentAttendance.ATTENDED.value: "Sí se realizó",
    AppointmentAttendance.MISSED.value: "No se realizó",
}

STATUS_LABELS: dict[str, str] = {
    AppointmentStatus.PENDING.value: "En proceso",
    AppointmentStatus.CONFIRMED.value: "Confirmada",
    AppointmentStatus.REJECTED.value: "Rechazada",
    AppointmentStatus.NEEDS_REVIEW.value: "Requiere revisión",
    AppointmentStatus.CANCELLED.value: "Cancelada",
    AppointmentStatus.RESCHEDULED.value: "Reagendada",
}


# ---------------------------------------------------------------- Commands ---


@dataclass(frozen=True)
class BookVisit:
    """Book one 90-minute visit.

    ``advisor_id`` is normally absent: the visit belongs to whoever is
    responsible for the Opportunity, and letting a caller name somebody else
    would make ownership a matter of which surface booked it. An Administrator
    may name one explicitly from the CRM.

    ``conducting_advisor_id`` is the ADR-0037 case: a Property Expert conducts
    the visit instead of the owner *only when that is made explicit*. Set it and
    the expert's calendar is the one that must be free, because they are the
    person who will be standing at the door.
    """

    conversation_id: uuid.UUID
    property_uuid: uuid.UUID
    start: datetime
    command_key: str
    attendee_name: str | None = None
    advisor_id: uuid.UUID | None = None
    conducting_advisor_id: uuid.UUID | None = None


@dataclass(frozen=True)
class RescheduleVisit:
    appointment_id: uuid.UUID
    new_start: datetime
    command_key: str


@dataclass(frozen=True)
class CancelVisit:
    appointment_id: uuid.UUID
    command_key: str
    #: Inbound messages a Contact-facing confirmation would be answering.
    trigger_inbox_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class RecordVisitOutcome:
    """What the Advisor recorded after the visit (SAN-038 pending).

    The fields are the four PROJECT_MEMORY names — whether it happened, what is
    known, the next action, the result — kept deliberately minimal because the
    real form is Santiago's to design and a longer one Product invented would be
    a form nobody fills in.
    """

    appointment_id: uuid.UUID
    attendance: AppointmentAttendance
    command_key: str
    notes: str | None = None
    #: Only meaningful for a Missed visit, and only ever an explicit yes.
    authorize_reschedule_invitation: bool = False
    next_action_kind: NextActionKind | None = None
    next_action_due_at: datetime | None = None


# ----------------------------------------------------------------- Results ---


@dataclass(frozen=True)
class VisitBooked:
    appointment_id: uuid.UUID
    reference: str
    #: ``None`` only for a pre-Stage-3 row an Administrator has yet to claim.
    advisor_id: uuid.UUID | None
    advisor_name: str
    conducting_advisor_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    #: False for an idempotent replay of the same command.
    created: bool

    @property
    def confirmed(self) -> bool:
        return self.status is AppointmentStatus.CONFIRMED


@dataclass(frozen=True)
class VisitRefused:
    reason: Refusal
    detail: str = ""
    #: Alternatives, when the refusal was a taken slot and Product could read
    #: the calendar. Empty otherwise: stale candidates must never be presented
    #: as current.
    alternatives: tuple[Interval, ...] = ()
    appointment_id: uuid.UUID | None = None

    @property
    def message(self) -> str:
        return REFUSAL_MESSAGES[self.reason.value]


@dataclass(frozen=True)
class VisitCancelled:
    """A cancelled visit, and whether the Contact was actually told.

    The two facts are separate on purpose. The visit is cancelled the moment
    Calendar conclusively says so; whether the Contact received a message is the
    Outbound Eligibility Gate's decision, and a result that implied a message
    which never went out would be a lie the operator acts on.
    """

    appointment_id: uuid.UUID
    reference: str
    starts_at: datetime
    ends_at: datetime
    contact_notified: bool
    denial_reason: str | None = None
    #: ADR-0037: Maia asks once whether the Contact wants another time.
    reschedule_prompt_required: bool = True


@dataclass(frozen=True)
class VisitOutcome:
    appointment_id: uuid.UUID
    attendance: AppointmentAttendance
    recorded: bool
    next_action_id: uuid.UUID | None = None


#: How far back a read of "the agenda" reaches when the caller does not say.
#: Maia only needs the current week of visits to answer about one.
AGENDA_LOOKBACK = timedelta(days=7)

#: The operator's agenda page reaches further back on purpose: an Advisor needs
#: the last fortnight to record an outcome for a visit they did not write up on
#: the day. Named beside the default so the two cannot silently diverge again.
OPERATOR_AGENDA_LOOKBACK = timedelta(days=14)


class Appointments:
    """The visit module.

    Hides: advisor and calendar resolution, slot authority, the durable attempt,
    the inconclusive-Calendar outcome, atomic rescheduling, the Appointment
    Handoff into the commercial record, reminders, ownership-scoped
    authorization, idempotency and audit.
    """

    def __init__(
        self,
        session: AsyncSession,
        scheduling: AdvisorScheduling,
        *,
        schedule: WeeklySchedule,
        day_of_reminder_hour: int,
        max_candidates: int,
        event_title: str = "Visita — {property} — {name}",
    ) -> None:
        self._session = session
        self._scheduling = scheduling
        self._schedule = schedule
        self._max_candidates = max_candidates
        self._event_title = event_title
        self._commands = CommercialCommands(session)
        self._alerts = InternalAlerts(session)
        self._handoff = AppointmentHandoff(
            session,
            schedule,
            day_of_reminder_hour=day_of_reminder_hour,
        )

    # -- Booking -----------------------------------------------------------

    async def book(
        self, actor: Actor, command: BookVisit
    ) -> VisitBooked | VisitRefused:
        """Book one visit. Commits in three deliberate steps.

        A single transaction is impossible here and pretending otherwise would
        be the bug: the Calendar write is an external side effect, so the
        attempt must be durable *before* it and its outcome durable *after* it.
        The steps are (1) persist the attempt, (2) write Calendar, (3) record
        the outcome together with the Appointment Handoff. A crash between any
        two leaves a row that reconciliation can finish, never a visit the
        Contact was told about that Product does not know exists.
        """
        conversation = await self._session.get(Conversation, command.conversation_id)
        if conversation is None:
            raise NotFound("No encontramos esa conversación.")
        actor.require_same_organization(conversation.organization_id)

        cycle = await self._session.get(LeadEngagementCycle, conversation.cycle_id)
        if cycle is None or not cycle.is_active(utc_now()):
            return VisitRefused(Refusal.CONVERSATION_EXPIRED)

        prop = await self._session.get(Property, command.property_uuid)
        if prop is None or prop.organization_id != actor.organization_id:
            return VisitRefused(Refusal.PROPERTY_NOT_FOUND)
        if prop.status != PropertyStatus.ACTIVE.value:
            return VisitRefused(Refusal.PROPERTY_INACTIVE)

        key = f"apt:{conversation.id}:{prop.id}:{command.start.isoformat()}"
        existing = await self._session.scalar(
            select(Appointment).where(Appointment.idempotency_key == key)
        )
        if existing is not None:
            attending_id = existing.attending_advisor_id
            attending = (
                await self._session.get(OrganizationMember, attending_id)
                if attending_id is not None
                else None
            )
            return self._booked(
                existing,
                attending.display_name if attending else "Asesor sin identificar",
                created=False,
            )

        opportunity = await self._opportunity_for(conversation)
        prospective = await self._prospective_owner(actor, command, opportunity)
        if isinstance(prospective, VisitRefused):
            return prospective
        owner_id = prospective.id
        owner = prospective

        if (
            command.conducting_advisor_id is not None
            and command.conducting_advisor_id != owner_id
        ):
            expert = await self._session.scalar(
                select(PropertyExpert.id)
                .where(PropertyExpert.organization_id == actor.organization_id)
                .where(PropertyExpert.property_uuid == prop.id)
                .where(PropertyExpert.advisor_id == command.conducting_advisor_id)
                .where(PropertyExpert.revoked_at.is_(None))
                .limit(1)
            )
            if expert is None:
                return VisitRefused(Refusal.CONDUCTOR_NOT_EXPERT)

        # Whoever will actually be at the property is whose calendar must be
        # free. Normally the owner; the expert only when made explicit.
        attending_id = command.conducting_advisor_id or owner_id
        resolved = await self._scheduling.resolve_advisor(
            SlotQuery(
                organization_id=actor.organization_id,
                advisor_id=attending_id,
                now=command.start,
            )
        )
        if isinstance(resolved, SlotsUnavailable):
            return VisitRefused(
                _FROM_SCHEDULING[resolved.reason.value], detail=resolved.detail
            )
        attending, calendar = resolved
        if await self._absent_at(attending.id, command.start):
            return VisitRefused(Refusal.ADVISOR_ABSENT)

        # The live authority check: the schedule, the horizon and the calendar
        # in one read. Membership in this set is what makes the start legal —
        # a caller cannot propose 10:17, and a stale conversational snapshot
        # cannot resurrect a taken slot.
        found = await self._scheduling.find_slots(
            SlotQuery(organization_id=actor.organization_id, advisor_id=attending.id)
        )
        if isinstance(found, SlotsUnavailable):
            return VisitRefused(
                _FROM_SCHEDULING[found.reason.value], detail=found.detail
            )
        slot = next((s for s in found.slots if s.start == command.start), None)
        if slot is None:
            return VisitRefused(
                Refusal.SLOT_UNAVAILABLE,
                alternatives=found.slots[: self._max_candidates],
            )

        attending_name = attending.display_name

        # Only now, with a real slot in hand, is responsibility committed. A
        # confirmed visit must have a Responsible Advisor, so booking *applies*
        # the deterministic rule rather than refusing an Opportunity that has
        # not reached Qualified yet — Stage 2 attaches an owner there, and a
        # booked visit is stronger evidence than qualification. Idempotent and
        # preserving: an Opportunity that already has an owner keeps them.
        if opportunity is not None and command.advisor_id is None:
            from realestate.domain.commercial.assignment import Assignment

            attached = await Assignment(self._session).assign(actor, opportunity.id)
            if attached.queued or attached.advisor_id is None:
                return VisitRefused(Refusal.NO_RESPONSIBLE_ADVISOR)
            owner_id = attached.advisor_id

        try:
            attempt = await self._persist_attempt(
                conversation=conversation,
                prop=prop,
                slot=slot,
                attendee_name=command.attendee_name,
                owner_id=owner_id,
                conducting_advisor_id=command.conducting_advisor_id,
                calendar_id=attending.calendar_id or "",
                opportunity_id=opportunity.id if opportunity else None,
                key=key,
            )
        except _SlotAlreadyClaimed:
            return VisitRefused(
                Refusal.SLOT_UNAVAILABLE,
                alternatives=tuple(
                    offered for offered in found.slots if offered.start != slot.start
                )[: self._max_candidates],
            )
        if attempt is None:
            # Another worker committed the same key first. The rollback inside
            # ``_persist_attempt`` expired this session, so only the freshly
            # read row and the name captured above are safe to touch.
            again = await self._session.scalar(
                select(Appointment).where(Appointment.idempotency_key == key)
            )
            assert again is not None
            return self._booked(again, attending_name, created=False)

        event = await calendar.create_event(
            slot=slot,
            summary=self._event_title.format(
                property=prop.name, name=command.attendee_name or ""
            ),
            description=await self._describe(conversation, command.attendee_name, owner),
            reference=attempt.reference,
            location=prop.visit_address,
        )
        if event.outcome is CalendarOutcome.OK:
            attempt.status = AppointmentStatus.CONFIRMED.value
            attempt.calendar_event_id = event.event_id
            attempt.resolved_at = utc_now()
            await self._on_confirmed(actor, attempt, opportunity)
        else:
            # Inconclusive: the event may exist. Not a Confirmed Appointment,
            # not retried, and nobody may call it confirmed (P-042).
            attempt.status = AppointmentStatus.NEEDS_REVIEW.value
            attempt.last_error = event.detail
            await self._alert_needs_review(actor, attempt, owner, event.detail)
        await self._audit(
            actor,
            attempt,
            "BookVisit",
            {
                "advisor_id": str(owner_id),
                "conducting_advisor_id": (
                    str(command.conducting_advisor_id)
                    if command.conducting_advisor_id
                    else None
                ),
                "calendar_id": attempt.calendar_id,
                "status": attempt.status,
            },
        )
        await self._session.commit()
        return self._booked(attempt, attending_name, created=True)

    # -- Rescheduling ------------------------------------------------------

    async def reschedule(
        self, actor: Actor, command: RescheduleVisit
    ) -> VisitBooked | VisitRefused:
        """Move a confirmed visit. Secures the new slot before releasing the old.

        The ordering is the guarantee: the successor is written and confirmed
        first, and only a conclusive success releases the original. Every
        failure path therefore leaves the original Confirmed, which is what
        ADR-0037 requires and what a customer expects when they hear "no pude
        cambiarla".
        """
        original = await self._visit_for_update(actor, command.appointment_id)
        if original.status != AppointmentStatus.CONFIRMED.value:
            return VisitRefused(Refusal.NOT_CONFIRMED, appointment_id=original.id)
        active_successor = await self._session.scalar(
            select(Appointment.id)
            .where(Appointment.rescheduled_from_id == original.id)
            .where(Appointment.status != AppointmentStatus.REJECTED.value)
            .limit(1)
        )
        if active_successor is not None:
            return VisitRefused(Refusal.INCONCLUSIVE, appointment_id=original.id)
        if original.starts_at <= utc_now():
            return VisitRefused(Refusal.ALREADY_STARTED, appointment_id=original.id)
        if original.advisor_id is None:
            return VisitRefused(
                Refusal.NO_RESPONSIBLE_ADVISOR, appointment_id=original.id
            )
        if command.new_start == original.starts_at:
            # Moving a visit to the time it already has would otherwise reach
            # the idempotency key of this very row, find it Confirmed, and
            # report success — telling an operator something changed when
            # nothing did.
            return VisitRefused(Refusal.UNCHANGED, appointment_id=original.id)

        conversation = await self._session.get(Conversation, original.conversation_id)
        assert conversation is not None
        prop = await self._session.get(Property, original.property_uuid)
        if prop is None:
            return VisitRefused(Refusal.PROPERTY_NOT_FOUND)
        if prop.status != PropertyStatus.ACTIVE.value:
            return VisitRefused(Refusal.PROPERTY_INACTIVE)

        attending_id = original.attending_advisor_id
        resolved = await self._scheduling.resolve_advisor(
            SlotQuery(
                organization_id=actor.organization_id, advisor_id=attending_id
            )
        )
        if isinstance(resolved, SlotsUnavailable):
            return VisitRefused(
                _FROM_SCHEDULING[resolved.reason.value], detail=resolved.detail
            )
        attending, calendar = resolved
        if await self._absent_at(attending.id, command.new_start):
            return VisitRefused(Refusal.ADVISOR_ABSENT)

        found = await self._scheduling.find_slots(
            SlotQuery(organization_id=actor.organization_id, advisor_id=attending.id)
        )
        if isinstance(found, SlotsUnavailable):
            return VisitRefused(
                _FROM_SCHEDULING[found.reason.value], detail=found.detail
            )
        slot = next((s for s in found.slots if s.start == command.new_start), None)
        if slot is None:
            return VisitRefused(
                Refusal.SLOT_UNAVAILABLE,
                alternatives=found.slots[: self._max_candidates],
            )

        key = f"apt:{conversation.id}:{prop.id}:{slot.start.isoformat()}"
        replacement = await self._session.scalar(
            select(Appointment).where(Appointment.idempotency_key == key)
        )
        if replacement is None:
            try:
                replacement = await self._persist_attempt(
                    conversation=conversation,
                    prop=prop,
                    slot=slot,
                    attendee_name=original.attendee_name,
                    owner_id=original.advisor_id,
                    conducting_advisor_id=original.conducting_advisor_id,
                    calendar_id=attending.calendar_id or "",
                    opportunity_id=original.opportunity_id,
                    key=key,
                    rescheduled_from_id=original.id,
                )
            except _SlotAlreadyClaimed:
                return VisitRefused(
                    Refusal.SLOT_UNAVAILABLE,
                    alternatives=tuple(
                        offered
                        for offered in found.slots
                        if offered.start != slot.start
                    )[: self._max_candidates],
                    appointment_id=original.id,
                )
            except _RescheduleAlreadyInProgress:
                return VisitRefused(
                    Refusal.INCONCLUSIVE, appointment_id=original.id
                )
            if replacement is None:  # pragma: no cover - the key is unique
                replacement = await self._session.scalar(
                    select(Appointment).where(Appointment.idempotency_key == key)
                )
                assert replacement is not None
        elif replacement.status == AppointmentStatus.CONFIRMED.value:
            # An idempotent replay: the successor already exists and the
            # original was already released.
            return self._booked(
                replacement, attending.display_name, created=False
            )

        event = await calendar.create_event(
            slot=slot,
            summary=self._event_title.format(
                property=prop.name, name=original.attendee_name or ""
            ),
            description=await self._describe(
                conversation, original.attendee_name, attending
            ),
            reference=replacement.reference,
            location=prop.visit_address,
        )
        if event.outcome is not CalendarOutcome.OK:
            # The original is untouched and still Confirmed. That is the point.
            replacement.status = AppointmentStatus.NEEDS_REVIEW.value
            replacement.last_error = event.detail
            await self._audit(
                actor,
                original,
                "RescheduleVisitFailed",
                {
                    "replacement_id": str(replacement.id),
                    "detail": event.detail,
                    "original_preserved": True,
                },
            )
            await self._alert_needs_review(
                actor, replacement, attending, event.detail
            )
            await self._session.commit()
            return VisitRefused(
                Refusal.INCONCLUSIVE,
                detail=event.detail,
                appointment_id=original.id,
            )

        replacement.status = AppointmentStatus.CONFIRMED.value
        replacement.calendar_event_id = event.event_id
        replacement.resolved_at = utc_now()

        # Only now is the old slot released. A failure here does not un-book the
        # new visit — the customer has a confirmed time and taking it away
        # would be worse — so the stale event becomes a named review task.
        released = await self._release(calendar, original)
        original.status = AppointmentStatus.RESCHEDULED.value
        original.rescheduled_to_id = replacement.id
        original.resolved_at = original.resolved_at or utc_now()
        if released:
            original.calendar_event_id = None
        else:
            original.last_error = (
                "El evento anterior no se pudo eliminar del calendario."
            )
            await self._alerts.raise_alert(
                actor,
                kind=InternalAlertKind.APPOINTMENT_ADVISOR_REVIEW,
                subject_type="Appointment",
                subject_id=str(original.id),
                title=f"Evento duplicado en el calendario ({original.reference})",
                body="\n".join(
                    [
                        "La cita se reagendó correctamente, pero el evento "
                        "anterior no se pudo eliminar del calendario.",
                        f"Cita anterior: {original.reference}",
                        f"Cita nueva: {replacement.reference}",
                        "Borra el evento anterior a mano.",
                    ]
                ),
                dedupe_key=f"stale-calendar-event:{original.id}",
                recipient_member_id=original.advisor_id,
            )
        await self._on_confirmed(
            actor, replacement, await self._opportunity_for(conversation)
        )
        await self._audit(
            actor,
            replacement,
            "RescheduleVisit",
            {
                "from_appointment": str(original.id),
                "from_start": original.starts_at.isoformat(),
                "to_start": replacement.starts_at.isoformat(),
                "previous_event_released": released,
            },
        )
        attending_name = attending.display_name
        await self._session.commit()
        logger.info(
            "Rescheduled %s to %s (new reference %s)",
            original.reference,
            replacement.starts_at.isoformat(),
            replacement.reference,
        )
        return self._booked(replacement, attending_name, created=True)

    # -- Cancellation ------------------------------------------------------

    async def cancel(
        self, actor: Actor, command: CancelVisit
    ) -> VisitCancelled | VisitRefused:
        """Cancel a confirmed visit. Commits.

        Deliberately says nothing about the Opportunity. A cancelled visit is
        not a lost pursuit, and encoding it as one here would let an operational
        hiccup rewrite the operation's conversion history (ADR-0037).

        Calendar first, then state, then the Contact-facing notice. If Calendar
        is inconclusive nothing is written and nobody is told: an Advisor whose
        calendar still shows the visit would go to the property.
        """
        appointment = await self._visit_for_update(actor, command.appointment_id)
        if appointment.status == AppointmentStatus.CANCELLED.value:
            return VisitCancelled(
                appointment_id=appointment.id,
                reference=appointment.reference,
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                contact_notified=False,
            )
        if appointment.status != AppointmentStatus.CONFIRMED.value:
            return VisitRefused(
                Refusal.NOT_CONFIRMED, appointment_id=appointment.id
            )
        active_successor = await self._session.scalar(
            select(Appointment.id)
            .where(Appointment.rescheduled_from_id == appointment.id)
            .where(Appointment.status != AppointmentStatus.REJECTED.value)
            .limit(1)
        )
        if active_successor is not None:
            return VisitRefused(
                Refusal.INCONCLUSIVE, appointment_id=appointment.id
            )

        calendar = await self._calendar_of(appointment)
        if calendar is None:
            return VisitRefused(
                Refusal.NO_AUTHORITATIVE_CALENDAR, appointment_id=appointment.id
            )
        if not await self._release(calendar, appointment):
            return VisitRefused(
                Refusal.INCONCLUSIVE, appointment_id=appointment.id
            )

        moment = utc_now()
        appointment.status = AppointmentStatus.CANCELLED.value
        appointment.cancelled_at = moment
        appointment.calendar_event_id = None
        appointment.resolved_at = appointment.resolved_at or moment
        await self._audit(
            actor,
            appointment,
            "CancelVisit",
            {
                "advisor_id": (
                    str(appointment.advisor_id) if appointment.advisor_id else None
                ),
                # Named in the trail because it is the invariant somebody will
                # eventually doubt.
                "opportunity_outcome_changed": False,
            },
        )
        notified, denial = await self._tell_contact_cancelled(appointment, command)
        await self._session.commit()
        return VisitCancelled(
            appointment_id=appointment.id,
            reference=appointment.reference,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            contact_notified=notified,
            denial_reason=denial,
        )

    async def _tell_contact_cancelled(
        self, appointment: Appointment, command: CancelVisit
    ) -> tuple[bool, str | None]:
        """The Contact-facing cancellation, through the gate. Never commits.

        The initiation is derived from evidence rather than declared: with
        trigger messages this answers a Contact who just asked to cancel, and
        without them it is the operation reaching out on its own. Getting that
        backwards would let an operator's cancellation borrow a service window
        it never had (ADR-0045).
        """
        from realestate.domain.appointments import cancellation_message
        from realestate.domain.outbound import (
            Denied,
            OutboundIntent,
            OutboundMessaging,
            Purpose,
        )

        conversation = await self._session.get(
            Conversation, appointment.conversation_id
        )
        if conversation is None:  # pragma: no cover - the FK forbids it
            return False, None
        prop = await self._session.get(Property, appointment.property_uuid)
        outcome = await OutboundMessaging(self._session).request(
            OutboundIntent(
                conversation=conversation,
                body=cancellation_message(
                    property_name=prop.name if prop else "la propiedad",
                    starts_at=appointment.starts_at,
                    schedule=self._schedule,
                ),
                purpose=Purpose.APPOINTMENT_CANCELLATION,
                initiation=(
                    OutboundInitiation.REACTIVE
                    if command.trigger_inbox_ids
                    else OutboundInitiation.BUSINESS_INITIATED
                ),
                trigger_inbox_ids=command.trigger_inbox_ids,
                idempotency_key=f"appointment-cancellation:{appointment.id}",
            )
        )
        if isinstance(outcome, Denied):
            return False, outcome.reason.value
        return True, None

    # -- After the visit ---------------------------------------------------

    async def record_outcome(
        self, actor: Actor, command: RecordVisitOutcome
    ) -> VisitOutcome | VisitRefused:
        """The Advisor records whether the visit happened, and what is next.

        Never commits. Only a human writes this: Product does not infer that a
        visit occurred from the clock having passed, because "the Advisor did
        not record it" and "the customer did not come" are different facts and
        the operation is measured on both (SAN-038).
        """
        appointment = await self._visit_for_update(actor, command.appointment_id)
        if actor.is_product:
            raise NotAuthorized(
                "El resultado de una visita lo registra una persona."
            )
        if appointment.status not in (
            AppointmentStatus.CONFIRMED.value,
            AppointmentStatus.NEEDS_REVIEW.value,
        ):
            return VisitRefused(
                Refusal.NOT_CONFIRMED, appointment_id=appointment.id
            )
        if appointment.starts_at > utc_now():
            return VisitRefused(
                Refusal.NOT_YET_HELD, appointment_id=appointment.id
            )
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="RecordVisitOutcome",
            subject_type="Appointment",
            subject_id=str(appointment.id),
            payload={"attendance": command.attendance.value},
        )
        if replay or appointment.attendance is not None:
            return VisitOutcome(
                appointment_id=appointment.id,
                attendance=AppointmentAttendance(
                    appointment.attendance or command.attendance.value
                ),
                recorded=False,
            )

        moment = utc_now()
        appointment.attendance = command.attendance.value
        appointment.attendance_recorded_at = moment
        appointment.attendance_recorded_by = actor.member_id
        appointment.visit_outcome = (command.notes or "").strip() or None
        appointment.reschedule_invitation_authorized = (
            command.attendance is AppointmentAttendance.MISSED
            and command.authorize_reschedule_invitation
        )
        await self._session.flush()

        next_action_id = await self._settle_commercial_follow_up(
            actor, appointment, command
        )
        await self._audit(
            actor,
            appointment,
            "RecordVisitOutcome",
            {
                "attendance": command.attendance.value,
                "reschedule_invitation_authorized": (
                    appointment.reschedule_invitation_authorized
                ),
                "next_action_id": str(next_action_id) if next_action_id else None,
            },
        )
        return VisitOutcome(
            appointment_id=appointment.id,
            attendance=command.attendance,
            recorded=True,
            next_action_id=next_action_id,
        )

    # -- Reads -------------------------------------------------------------

    async def visit(self, actor: Actor, appointment_id: uuid.UUID) -> Appointment:
        return await self._visit_for_update(actor, appointment_id, lock=False)

    async def agenda(
        self,
        actor: Actor,
        *,
        advisor_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Appointment]:
        """Visits this Actor may see, earliest first.

        An Advisor sees their own — as owner *or* as the person conducting one,
        because somebody standing at a door needs the address whether or not
        they own the Opportunity. An Administrator sees the whole operation.
        """
        moment = since or (utc_now() - AGENDA_LOOKBACK)
        query = (
            select(Appointment)
            .where(Appointment.organization_id == actor.organization_id)
            .where(Appointment.starts_at >= moment)
            .order_by(Appointment.starts_at)
        )
        if until is not None:
            query = query.where(Appointment.starts_at < until)
        if advisor_id is not None:
            query = query.where(
                (Appointment.advisor_id == advisor_id)
                | (Appointment.conducting_advisor_id == advisor_id)
            )
        elif not actor.sees_whole_operation:
            query = query.where(
                (Appointment.advisor_id == actor.member_id)
                | (Appointment.conducting_advisor_id == actor.member_id)
            )
        return list(await self._session.scalars(query))

    async def unowned(self, actor: Actor) -> list[Appointment]:
        """Confirmed visits with no Advisor — the pre-Stage-3 rows.

        Surfaced rather than backfilled with a guess. An Administrator decides
        who owns a visit booked when the concept did not exist.
        """
        actor.require_administrator()
        query = (
            select(Appointment)
            .where(Appointment.organization_id == actor.organization_id)
            .where(Appointment.advisor_id.is_(None))
            .where(
                Appointment.status.in_(
                    (
                        AppointmentStatus.CONFIRMED.value,
                        AppointmentStatus.NEEDS_REVIEW.value,
                    )
                )
            )
            .order_by(Appointment.starts_at)
        )
        return list(await self._session.scalars(query))

    # -- Internals ---------------------------------------------------------

    async def _visit_for_update(
        self, actor: Actor, appointment_id: uuid.UUID, *, lock: bool = True
    ) -> Appointment:
        query = select(Appointment).where(Appointment.id == appointment_id)
        if lock:
            query = query.with_for_update()
        appointment: Appointment | None = await self._session.scalar(query)
        if appointment is None:
            raise NotFound("No encontramos esa cita.")
        actor.require_same_organization(appointment.organization_id)
        if not actor.sees_whole_operation and actor.member_id not in (
            appointment.advisor_id,
            appointment.conducting_advisor_id,
        ):
            raise NotFound("No encontramos esa cita.")
        return appointment

    async def _prospective_owner(
        self,
        actor: Actor,
        command: BookVisit,
        opportunity: Opportunity | None,
    ) -> OrganizationMember | VisitRefused:
        """Who would own this visit, before anything is written.

        An explicit ``advisor_id`` is an Administrator naming the owner from the
        CRM and is taken as given. Otherwise the deterministic assignment rule
        answers, read-only: preserve an existing Responsible Advisor, else the
        Property's present expert, else the default Advisor.
        """
        if command.advisor_id is not None:
            actor.require_administrator()
            return await self._eligible_member(actor, command.advisor_id)
        if opportunity is None:
            return VisitRefused(Refusal.NO_RESPONSIBLE_ADVISOR)
        from realestate.domain.commercial.assignment import Assignment

        candidate, why = await Assignment(self._session).prospective(
            actor, opportunity.id
        )
        if candidate is None:
            # The Assignment Queue exists for exactly this. Booking a visit
            # nobody is accountable for is the failure this stage removes — and
            # the reason is carried through, because "everybody is away" and
            # "nobody is configured" are different problems for whoever reads it.
            return VisitRefused(
                _FROM_QUEUE_REASON.get(
                    why.value if why else "", Refusal.NO_RESPONSIBLE_ADVISOR
                )
            )
        return await self._eligible_member(actor, candidate.id)

    async def _eligible_member(
        self, actor: Actor, member_id: uuid.UUID
    ) -> OrganizationMember | VisitRefused:
        member = await self._session.get(OrganizationMember, member_id)
        if (
            member is None
            or member.organization_id != actor.organization_id
            or not member.active
            or not member.advises
        ):
            return VisitRefused(Refusal.ADVISOR_INELIGIBLE)
        return member

    async def _absent_at(self, advisor_id: uuid.UUID, moment: datetime) -> bool:
        """Whether this Advisor is away at *moment*.

        Kept at the booking callers rather than folded into
        ``resolve_advisor``: availability deliberately reports an absence as a
        successful answer with no free slots, while a booking has to *refuse*.
        Collapsing the two would turn "genuinely busy" into "cannot answer".
        """
        from realestate.domain.commercial.team import current_absence

        return await current_absence(self._session, advisor_id, moment) is not None

    async def _opportunity_for(
        self, conversation: Conversation
    ) -> Opportunity | None:
        from realestate.domain.commercial.identity import CommercialIdentity
        from realestate.domain.commercial.opportunities import OpportunityManagement

        contact_id = await CommercialIdentity(self._session).contact_for_lead(
            conversation.lead_id
        )
        if contact_id is None:
            return None
        return await OpportunityManagement(self._session).open_demand_for_contact(
            contact_id
        )

    async def _persist_attempt(
        self,
        *,
        conversation: Conversation,
        prop: Property,
        slot: Interval,
        attendee_name: str | None,
        owner_id: uuid.UUID,
        conducting_advisor_id: uuid.UUID | None,
        calendar_id: str,
        opportunity_id: uuid.UUID | None,
        key: str,
        rescheduled_from_id: uuid.UUID | None = None,
    ) -> Appointment | None:
        attempt = Appointment(
            organization_id=conversation.organization_id,
            reference=_reference(),
            idempotency_key=key,
            conversation_id=conversation.id,
            lead_id=conversation.lead_id,
            property_uuid=prop.id,
            starts_at=slot.start,
            ends_at=slot.end,
            attendee_name=attendee_name,
            status=AppointmentStatus.PENDING.value,
            advisor_id=owner_id,
            conducting_advisor_id=conducting_advisor_id,
            calendar_id=calendar_id,
            opportunity_id=opportunity_id,
            rescheduled_from_id=rescheduled_from_id,
        )
        self._session.add(attempt)
        try:
            # Committed before Calendar is touched: the attempt has to survive a
            # crash mid-write so recovery reconciles it instead of booking a
            # second visit (P-042).
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            same_command = await self._session.scalar(
                select(Appointment.id).where(Appointment.idempotency_key == key)
            )
            if same_command is not None:
                return None
            constraint = getattr(
                getattr(exc.orig, "diag", None), "constraint_name", None
            )
            if constraint == "ex_appointments_calendar_overlap":
                raise _SlotAlreadyClaimed() from exc
            if constraint == "uq_appointments_active_reschedule":
                raise _RescheduleAlreadyInProgress() from exc
            raise
        return attempt

    async def _release(self, calendar: CalendarPort, appointment: Appointment) -> bool:
        """Remove this appointment's Calendar event. True only when conclusive.

        A missing event is a conclusive success: the desired Calendar state is
        already true. Anything inconclusive is a failure, because telling a
        Contact their visit is cancelled while the Advisor's calendar still
        shows it would send somebody to an empty house.
        """
        event_id = appointment.calendar_event_id
        if event_id is None:
            evidence = await calendar.find_by_reference(appointment.reference)
            if evidence.outcome is not CalendarOutcome.OK:
                return False
            event_id = evidence.event_id
        if event_id is None:
            return True
        deleted = await calendar.delete_event(event_id)
        return deleted.outcome is CalendarOutcome.OK

    async def _calendar_of(self, appointment: Appointment) -> CalendarPort | None:
        """The calendar this appointment's event actually lives on.

        Resolved from the stored ``calendar_id`` rather than from the Advisor's
        current configuration: an Advisor whose calendar was changed after
        booking still has an event to cancel on the old one.
        """
        if appointment.calendar_id:
            found = self._scheduling.calendars.for_calendar_id(appointment.calendar_id)
            if found is not None:
                return found
        advisor_id = appointment.attending_advisor_id
        if advisor_id is None:
            return None
        advisor = await self._session.get(OrganizationMember, advisor_id)
        if advisor is None:
            return None
        return self._scheduling.calendars.for_advisor(advisor)

    async def _describe(
        self,
        conversation: Conversation,
        attendee_name: str | None,
        advisor: OrganizationMember | None,
    ) -> str:
        lead = await self._session.get(Lead, conversation.lead_id)
        lines = []
        if attendee_name:
            lines.append(f"Nombre: {attendee_name}")
        if lead is not None:
            if lead.profile_name:
                lines.append(f"WhatsApp: {lead.profile_name}")
            lines.append(f"Teléfono: +{lead.wa_id}")
        if advisor is not None:
            lines.append(f"Asesor: {advisor.display_name}")
        return "\n".join(lines)

    async def _on_confirmed(
        self,
        actor: Actor,
        appointment: Appointment,
        opportunity: Opportunity | None,
    ) -> None:
        """The Appointment Handoff (ADR-0037), in the confirming transaction.

        Three things become true together: the reminders exist, the Advisor owes
        a post-visit record, and — when the pipeline legally allows it — the
        Opportunity says Visiting. The stage is *not* forced: a visit does not
        manufacture the confirmed criteria that Qualified requires (ADR-0031),
        so an Opportunity still in conversation stays there and the visit is
        recorded against it regardless.
        """
        if opportunity is not None:
            appointment.opportunity_id = appointment.opportunity_id or opportunity.id
        await self._handoff.complete(actor, appointment)

    async def _settle_commercial_follow_up(
        self,
        actor: Actor,
        appointment: Appointment,
        command: RecordVisitOutcome,
    ) -> uuid.UUID | None:
        """Close the post-visit action and owe the next one, if asked."""
        if appointment.opportunity_id is None:
            return None
        from realestate.domain.commercial.next_actions import (
            CompleteNextAction,
            NextActions,
            ScheduleNextAction,
        )

        actions = NextActions(self._session)
        pending = await actions.pending(appointment.opportunity_id)
        if pending is not None and pending.kind == NextActionKind.VISIT_FOLLOW_UP.value:
            await actions.complete(
                actor,
                CompleteNextAction(
                    next_action_id=pending.id,
                    outcome=(
                        NextActionOutcome.DONE
                        if command.attendance is AppointmentAttendance.ATTENDED
                        else NextActionOutcome.NO_ANSWER
                    ),
                    outcome_detail=command.notes,
                    command_key=f"visit-outcome:{appointment.id}",
                ),
            )
        if command.next_action_kind is None or command.next_action_due_at is None:
            return None
        scheduled = await actions.schedule(
            actor,
            ScheduleNextAction(
                opportunity_id=appointment.opportunity_id,
                kind=command.next_action_kind,
                due_at=command.next_action_due_at,
                command_key=f"post-visit-action:{appointment.id}",
                responsible_member_id=appointment.advisor_id,
                note=command.notes,
            ),
        )
        return scheduled.next_action_id

    async def _alert_needs_review(
        self,
        actor: Actor,
        appointment: Appointment,
        advisor: OrganizationMember | None,
        detail: str,
    ) -> None:
        await self._alerts.raise_alert(
            actor,
            kind=InternalAlertKind.APPOINTMENT_ADVISOR_REVIEW,
            subject_type="Appointment",
            subject_id=str(appointment.id),
            title=f"Cita sin confirmar ({appointment.reference})",
            body="\n".join(
                [
                    "El calendario no respondió de forma concluyente: el evento "
                    "pudo haberse creado o no.",
                    f"Referencia: {appointment.reference}",
                    f"Horario propuesto: {appointment.starts_at.isoformat()}",
                    f"Detalle técnico: {detail}",
                    "Al cliente no se le confirmó la cita.",
                ]
            ),
            dedupe_key=f"appointment-needs-review:{appointment.id}",
            recipient_member_id=advisor.id if advisor else None,
        )

    async def _audit(
        self,
        actor: Actor,
        appointment: Appointment,
        action: str,
        details: dict[str, object],
    ) -> None:
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action=action,
            subject_type="Appointment",
            subject_id=str(appointment.id),
            details={"reference": appointment.reference, **details},
            commit=False,
        )

    def _booked(
        self,
        appointment: Appointment,
        advisor_name: str,
        *,
        created: bool,
    ) -> VisitBooked:
        """Build the result from values already loaded.

        Takes the Advisor's *name* rather than the row on purpose. Losing an
        idempotency race rolls the session back, which expires every ORM object
        this method might otherwise touch — and reading an expired attribute
        from a synchronous helper emits IO with no greenlet to run it on, so the
        loser would crash instead of reporting the winner's appointment.
        """
        return VisitBooked(
            appointment_id=appointment.id,
            reference=appointment.reference,
            advisor_id=appointment.advisor_id,
            advisor_name=advisor_name,
            conducting_advisor_id=appointment.conducting_advisor_id,
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            status=AppointmentStatus(appointment.status),
            created=created,
        )

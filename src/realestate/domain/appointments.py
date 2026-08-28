"""Maia's conversational view of availability and appointments.

This module is the *conversation's* half of scheduling: the Availability
Snapshot a Contact was shown, the exact-membership rule that stops the Model
inventing a time, and the tool-shaped result dictionaries. It decides nothing
consequential any more.

Everything consequential moved to :mod:`realestate.domain.scheduling` in Stage
3, because those decisions stopped being about a conversation. Which Advisor
owns the visit, whose calendar is authoritative, whether they are absent,
whether the attempt is durable before Calendar is touched, and how a reschedule
stays atomic are all facts about the operation — and the CRM has to reach them
too. Two implementations of "book a visit" is how the two surfaces end up
disagreeing about who owns what.

So the ordering that used to live here is now stated where it is enforced, and
what remains is:

1. resolve the Property and the trusted Conversation;
2. require the exact start to be a member of *this* Conversation's snapshot, so
   the Model cannot invent a time;
3. hand the decision to :class:`~realestate.domain.scheduling.Appointments`;
4. translate its named refusal into the tool contract the Model already reads.

Step 2 is the part that genuinely belongs to a conversation. The snapshot is
durable evidence of what one Contact was offered, not current truth — the
authoritative recheck happens inside ``Appointments.book``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    AvailabilitySnapshot,
    Conversation,
    LeadEngagementCycle,
    Property,
    PropertyStatus,
)
from realestate.domain.outbox import OutboxKind
from realestate.domain.availability import (
    Interval,
    WeeklySchedule,
    filter_slots,
)
from realestate.domain.properties import resolve_property
from realestate.domain.commercial.actors import Actor
from realestate.domain.scheduling.advisors import (
    AdvisorScheduling,
    SchedulingPolicy,
    SlotQuery,
    SlotsUnavailable,
    Unavailable,
)
from realestate.domain.scheduling.appointments import (
    Appointments,
    BookVisit,
    CancelVisit,
    Refusal,
    RescheduleVisit,
    VisitBooked,
    VisitCancelled,
    VisitRefused,
)
from realestate.domain.scheduling.calendars import CalendarDirectory


@dataclass(frozen=True)
class AppointmentPolicy:
    schedule: WeeklySchedule
    visit_minutes: int
    horizon_days: int
    max_candidates: int
    #: The local hour the day-of reminder is due (SAN-036 pending). Carried here
    #: so the conversational service and the CRM build the same visit module.
    #: No default: when a customer is messaged is an operational decision, and a
    #: number here would quietly stand in for the configured one.
    day_of_reminder_hour: int
    event_title: str = "Visita — {property} — {name}"

    @property
    def scheduling(self) -> SchedulingPolicy:
        """The Organization-wide rules the scheduling module needs."""
        return SchedulingPolicy(
            schedule=self.schedule,
            visit_minutes=self.visit_minutes,
            horizon_days=self.horizon_days,
            max_candidates=self.max_candidates,
        )


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _to_json(slots: list[Interval], zone: ZoneInfo | None = None) -> list[dict[str, Any]]:
    """Serialise intervals, optionally normalising to one zone.

    Candidates the Model sees must always carry the Broker's offset so the same
    instant is never quoted two different ways (see AppointmentService._local).
    """
    if zone is None:
        return [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots]
    return [
        {
            "start": s.start.astimezone(zone).isoformat(),
            "end": s.end.astimezone(zone).isoformat(),
        }
        for s in slots
    ]


def _from_json(rows: list[dict[str, Any]]) -> list[Interval]:
    return [
        Interval(
            start=datetime.fromisoformat(r["start"]), end=datetime.fromisoformat(r["end"])
        )
        for r in rows
    ]


# How a named scheduling or booking refusal reaches the Model. The tool contract
# has four ways to say "not now" and the Model already knows them, so a new
# internal reason maps onto one of those rather than inventing a fifth the guide
# has never seen. ``detail`` carries the specific sentence for the operator log.
_TOOL_RESULTS: dict[str, str] = {
    Refusal.CONVERSATION_EXPIRED.value: "conversation_expired",
    Refusal.PROPERTY_NOT_FOUND.value: "not_found",
    Refusal.PROPERTY_INACTIVE.value: "property_inactive",
    Refusal.SLOT_UNAVAILABLE.value: "slot_unavailable",
    Refusal.NOT_CONFIRMED.value: "not_found",
    Refusal.ALREADY_STARTED.value: "not_found",
    Refusal.NOT_YET_HELD.value: "not_found",
    Refusal.UNCHANGED.value: "not_found",
    Refusal.NO_RESPONSIBLE_ADVISOR.value: "temporarily_unavailable",
    Refusal.ADVISOR_INELIGIBLE.value: "temporarily_unavailable",
    Refusal.CONDUCTOR_NOT_EXPERT.value: "temporarily_unavailable",
    Refusal.ADVISOR_ABSENT.value: "temporarily_unavailable",
    Refusal.NO_AUTHORITATIVE_CALENDAR.value: "temporarily_unavailable",
    Refusal.CALENDAR_UNREADABLE.value: "temporarily_unavailable",
    Refusal.INCONCLUSIVE.value: "needs_review",
}


class AppointmentService:
    """The conversational adapter over :mod:`realestate.domain.scheduling`.

    Takes a :class:`~realestate.domain.scheduling.calendars.CalendarDirectory`
    rather than one calendar, because "the Broker's calendar" stopped being a
    single thing the moment the operation had two Advisors.
    """

    def __init__(
        self,
        session: AsyncSession,
        calendars: CalendarDirectory,
        policy: AppointmentPolicy,
    ) -> None:
        self._session = session
        self._calendars = calendars
        self._policy = policy
        self._scheduling = AdvisorScheduling(session, calendars, policy.scheduling)
        self._appointments = Appointments(
            session,
            self._scheduling,
            schedule=policy.schedule,
                day_of_reminder_hour=policy.day_of_reminder_hour,
            max_candidates=policy.max_candidates,
            event_title=policy.event_title,
        )

    # -- get_available_slots ----------------------------------------------

    async def available_slots(
        self,
        *,
        conversation: Conversation,
        reference: str,
        date_from: date | None = None,
        date_to: date | None = None,
        time_from: time | None = None,
        time_to: time | None = None,
    ) -> dict[str, Any]:
        """Filter this Conversation-and-Property snapshot, creating it if needed."""
        prop = await self._resolve_active(reference, conversation.organization_id)
        if isinstance(prop, dict):
            return prop

        # One SELECT: the row is reused whether it is answerable as-is or has to
        # be replaced by a recompute.
        row = await self._snapshot_row(conversation, prop)
        snapshot = self._usable(row)
        if snapshot is None:
            recomputed = await self._recompute(conversation, prop, existing=row)
            if isinstance(recomputed, dict):
                return recomputed
            snapshot, _ = recomputed

        candidates = filter_slots(
            _from_json(snapshot.slots),
            date_from=date_from,
            date_to=date_to,
            time_from=time_from,
            time_to=time_to,
            limit=self._policy.max_candidates,
        )
        return {
            "result": "available",
            "property_id": prop.property_key,
            "snapshot_created_at": snapshot.created_at.isoformat(),
            "time_zone": snapshot.time_zone,
            # Zero to six intervals. An empty list is a successful filter with no
            # matches, not a Calendar failure.
            "candidates": _to_json(candidates, self._policy.schedule.zone),
        }

    async def _resolve_active(
        self, reference: str, organization_id: uuid.UUID
    ) -> Property | dict[str, Any]:
        prop = await resolve_property(self._session, reference, organization_id)
        if prop is None:
            return {"result": "not_found"}
        if prop.status != PropertyStatus.ACTIVE.value:
            return {
                "result": "property_inactive",
                "property_id": prop.property_key,
                "name": prop.name,
            }
        from realestate.domain.catalog.eligibility import EligibilityPurpose
        from realestate.domain.catalog.projection import (
            AuthorizedListingQuery,
            CatalogProjection,
            ListingNotEligible,
        )
        from realestate.domain.commercial.actors import Actor, NotFound

        try:
            await CatalogProjection(
                self._session,
                Actor.product(organization_id, "AppointmentEligibility"),
            ).get_authorized_listing(
                AuthorizedListingQuery(
                    purpose=EligibilityPurpose.APPOINTMENT,
                    at=datetime.now(tz=UTC),
                    property_uuid=prop.id,
                )
            )
        except (ListingNotEligible, NotFound):
            return {
                "result": "property_inactive",
                "property_id": prop.property_key,
                "name": prop.name,
            }
        return prop

    async def _snapshot_row(
        self, conversation: Conversation, prop: Property
    ) -> AvailabilitySnapshot | None:
        """This Conversation-and-Property snapshot, however stale."""
        return (
            await self._session.execute(
                select(AvailabilitySnapshot)
                .where(AvailabilitySnapshot.conversation_id == conversation.id)
                .where(AvailabilitySnapshot.property_uuid == prop.id)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _usable(row: AvailabilitySnapshot | None) -> AvailabilitySnapshot | None:
        """The snapshot a turn may answer from, or None.

        Takes an already-loaded row rather than querying: the caller keeps the
        row so a recompute can update it without a second identical SELECT.
        """
        if row is None:
            return None
        # An expired horizon is replaced only on new explicit intent (P-058);
        # here it simply is not usable.
        if row.horizon_end <= _now():
            return None
        return row

    async def _recompute(
        self,
        conversation: Conversation,
        prop: Property,
        existing: AvailabilitySnapshot | None,
    ) -> tuple[AvailabilitySnapshot, list[Interval]] | dict[str, Any]:
        """One authoritative availability read, then persist every interval.

        The Advisor is the one who is responsible for this Contact's
        Opportunity, resolved by :class:`~realestate.domain.scheduling.Appointments`
        the same way at booking. Quoting one person's calendar and then booking
        another's is the drift the stored ``advisor_id`` exists to make
        impossible to miss.

        Returns ``(snapshot, slots)``, or a refusal dict when no availability is
        authoritative. Both the first snapshot and the post-conflict refresh go
        through here so they cannot drift on horizon or candidate policy.
        """
        advisor_id = await self._responsible_advisor(conversation)
        if advisor_id is None:
            # No owner, no availability. The Assignment Queue is where this gets
            # fixed; offering times nobody is accountable for would produce
            # exactly the appointment this stage forbids.
            return {
                "result": "temporarily_unavailable",
                "detail": Unavailable.NO_ADVISOR.value,
            }
        found = await self._scheduling.find_slots(
            SlotQuery(
                organization_id=conversation.organization_id,
                advisor_id=advisor_id,
            )
        )
        if isinstance(found, SlotsUnavailable):
            # Never fall back to "nothing is busy" — that would offer times the
            # Advisor is not free.
            return {
                "result": "temporarily_unavailable",
                "detail": found.reason.value,
            }
        slots = list(found.slots)
        stored = await self._store_snapshot(
            conversation, prop, slots, found.horizon_end, existing, advisor_id
        )
        return stored, slots

    async def _responsible_advisor(
        self, conversation: Conversation
    ) -> uuid.UUID | None:
        """Whose availability this Conversation should be quoted, if anybody's.

        The deterministic assignment rule, read without applying it: a Contact
        asking about times must not create a period of responsibility, and the
        booking that follows applies the same rule for real. An Opportunity
        early in its life legitimately has no Responsible Advisor yet — Stage 2
        attaches one at Qualified — so the rule's later clauses, the present
        Property Expert and the default Advisor, are what answer here.
        """
        from realestate.domain.commercial.assignment import Assignment
        from realestate.domain.commercial.identity import CommercialIdentity
        from realestate.domain.commercial.opportunities import OpportunityManagement

        contact_id = await CommercialIdentity(self._session).contact_for_lead(
            conversation.lead_id
        )
        if contact_id is None:
            return None
        opportunity = await OpportunityManagement(
            self._session
        ).open_demand_for_contact(contact_id)
        if opportunity is None:
            return None
        candidate, _why = await Assignment(self._session).prospective(
            self._actor(conversation), opportunity.id
        )
        return candidate.id if candidate else None

    async def _store_snapshot(
        self,
        conversation: Conversation,
        prop: Property,
        slots: list[Interval],
        end: datetime,
        existing: AvailabilitySnapshot | None,
        advisor_id: uuid.UUID | None,
    ) -> AvailabilitySnapshot:
        if existing is not None:
            existing.slots = _to_json(slots)
            existing.horizon_end = end
            existing.created_at = _now()
            existing.time_zone = self._policy.schedule.timezone
            existing.advisor_id = advisor_id
            await self._session.commit()
            return existing

        row = AvailabilitySnapshot(
            conversation_id=conversation.id,
            property_uuid=prop.id,
            horizon_end=end,
            time_zone=self._policy.schedule.timezone,
            slots=_to_json(slots),
            advisor_id=advisor_id,
        )
        self._session.add(row)
        await self._session.commit()
        return row

    # -- book_appointment --------------------------------------------------

    async def book(
        self,
        *,
        conversation: Conversation,
        reference: str,
        start: datetime,
        attendee_name: str | None = None,
    ) -> dict[str, Any]:
        """Book the exact slot this Conversation was offered.

        The snapshot check is the conversational guard: a start the Contact was
        never shown is a time the Model invented, and it is refused before any
        authority is consulted. Everything after that — the owner, the
        authoritative calendar, the durable attempt, the inconclusive outcome —
        belongs to :class:`~realestate.domain.scheduling.Appointments`.
        """
        prop = await self._resolve_active(reference, conversation.organization_id)
        if isinstance(prop, dict):
            # A live Inactive Property creates no attempt and no event (P-063).
            return prop

        row = await self._snapshot_row(conversation, prop)
        snapshot = self._usable(row)
        if snapshot is None:
            return {"result": "invalid_candidate", "detail": "no current snapshot"}
        if self._member_of(snapshot, start) is None:
            # The Model proposed a time this Conversation never observed.
            return {"result": "invalid_candidate"}

        # Captured before delegating: losing an idempotency race inside the
        # visit module rolls the session back, which expires ``prop`` — and a
        # result built from an expired attribute would emit IO from a
        # synchronous helper and crash the loser instead of reporting the
        # winner's appointment.
        property_key, property_name = prop.property_key, prop.name

        outcome = await self._appointments.book(
            self._actor(conversation),
            BookVisit(
                conversation_id=conversation.id,
                property_uuid=prop.id,
                start=start,
                attendee_name=attendee_name,
                command_key=f"maia-book:{conversation.id}:{start.isoformat()}",
            ),
        )
        if isinstance(outcome, VisitRefused):
            if outcome.reason is Refusal.SLOT_UNAVAILABLE:
                # Resolving *this* attempt, not permission to poll: the
                # conversational snapshot is replaced so the Contact is offered
                # current times rather than the stale ones that just failed.
                return await self._refresh_after_conflict(conversation, prop, row)
            return self._refusal(outcome, prop)
        return self._result_for(
            await self._reload(outcome), property_key, property_name
        )

    async def reschedule(
        self,
        *,
        conversation: Conversation,
        new_start: datetime,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Move this Conversation's own future confirmed visit.

        Bounded Appointment Logistics, which is the one thing Maia keeps after
        the Appointment Handoff (ADR-0037). The atomicity — new slot secured
        before the old is released, original preserved on failure — is the
        visit module's, not restated here.
        """
        cycle = await self._session.get(LeadEngagementCycle, conversation.cycle_id)
        if cycle is None or not cycle.is_active(_now()):
            return {"result": "conversation_expired"}

        chosen = await self._one_future_appointment(conversation, reference)
        if isinstance(chosen, dict):
            return chosen

        outcome = await self._appointments.reschedule(
            self._actor(conversation),
            RescheduleVisit(
                appointment_id=chosen.id,
                new_start=new_start,
                command_key=f"maia-reschedule:{chosen.id}:{new_start.isoformat()}",
            ),
        )
        prop = await self._session.get(Property, chosen.property_uuid)
        if isinstance(outcome, VisitRefused):
            answer = self._refusal(outcome, prop)
            if outcome.reason is Refusal.SLOT_UNAVAILABLE and prop is not None:
                # Re-quote from the same authority the booking just used.
                refreshed = await self._refresh_after_conflict(
                    conversation, prop, await self._snapshot_row(conversation, prop)
                )
                return refreshed
            if outcome.reason is Refusal.INCONCLUSIVE:
                answer["appointment_reference"] = chosen.reference
                answer["original_preserved"] = True
            return answer
        moved = await self._reload(outcome)
        return {
            "result": "rescheduled",
            "appointment_reference": moved.reference,
            "previous_reference": chosen.reference,
            "property_id": prop.property_key if prop else None,
            "property_name": prop.name if prop else None,
            "start": self._local(moved.starts_at),
            "end": self._local(moved.ends_at),
            "time_zone": self._policy.schedule.timezone,
        }

    # -- cancel_appointment ------------------------------------------------

    async def cancel(
        self,
        *,
        conversation: Conversation,
        trigger_inbox_ids: tuple[uuid.UUID, ...],
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Cancel this Lead conversation's own future confirmed appointment."""
        cycle = await self._session.get(LeadEngagementCycle, conversation.cycle_id)
        if cycle is None or not cycle.is_active(_now()):
            return {"result": "conversation_expired"}

        chosen = await self._one_future_appointment(conversation, reference)
        if isinstance(chosen, dict):
            return chosen

        prop = await self._session.get(Property, chosen.property_uuid)
        outcome = await self._appointments.cancel(
            self._actor(conversation),
            CancelVisit(
                appointment_id=chosen.id,
                command_key=f"maia-cancel:{chosen.id}",
                trigger_inbox_ids=trigger_inbox_ids,
            ),
        )
        if isinstance(outcome, VisitRefused):
            answer = self._refusal(outcome, prop)
            answer["appointment_reference"] = chosen.reference
            return answer
        assert isinstance(outcome, VisitCancelled)
        return {
            "result": "cancelled",
            # Reported rather than assumed: the visit is cancelled either way,
            # and the tool's answer must not imply a message the gate refused.
            "lead_notified": outcome.contact_notified,
            "appointment_reference": outcome.reference,
            "property_id": prop.property_key if prop else None,
            "property_name": prop.name if prop else None,
            "start": self._local(outcome.starts_at),
            "end": self._local(outcome.ends_at),
            "time_zone": self._policy.schedule.timezone,
            "reschedule_prompt_required": outcome.reschedule_prompt_required,
        }

    # -- Shared conversational plumbing ------------------------------------

    def _actor(self, conversation: Conversation) -> Actor:
        """Product acting on the Contact's behalf inside the Organization.

        Maia is not a member of the team and holds no authority of her own; the
        Actor is Product's, which is organization-scoped and deliberately not an
        administrator (ADR-0046).
        """
        return Actor.product(conversation.organization_id, "MaiaAppointments")

    async def _reload(self, outcome: VisitBooked) -> Appointment:
        row = await self._session.get(Appointment, outcome.appointment_id)
        assert row is not None
        return row

    def _refusal(
        self, outcome: VisitRefused, prop: Property | None
    ) -> dict[str, Any]:
        """One named refusal, in the vocabulary the Model's guide already has."""
        answer: dict[str, Any] = {
            "result": _TOOL_RESULTS[outcome.reason.value],
            "detail": outcome.reason.value,
        }
        if prop is not None:
            answer["property_id"] = prop.property_key
        if outcome.alternatives:
            answer["candidates"] = _to_json(
                list(outcome.alternatives)[: self._policy.max_candidates],
                self._policy.schedule.zone,
            )
        return answer

    async def _one_future_appointment(
        self, conversation: Conversation, reference: str | None
    ) -> Appointment | dict[str, Any]:
        """The confirmed future visit a logistics request is about.

        Ambiguity is handed back to the Model rather than guessed: two future
        visits and no reference means asking which one, not picking the earlier.
        """
        query = (
            select(Appointment)
            .where(Appointment.conversation_id == conversation.id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
            .where(Appointment.starts_at > _now())
            .order_by(Appointment.starts_at)
        )
        if reference:
            query = query.where(Appointment.reference == reference)
        rows = list(await self._session.scalars(query))
        if not rows:
            return {"result": "not_found"}
        if len(rows) > 1 and not reference:
            return {
                "result": "ambiguous",
                "appointments": [self._summary_for(row) for row in rows],
            }
        return rows[0]

    def _summary_for(self, row: Appointment) -> dict[str, Any]:
        return {
            "appointment_reference": row.reference,
            "start": self._local(row.starts_at),
            "end": self._local(row.ends_at),
            "time_zone": self._policy.schedule.timezone,
        }

    def _member_of(self, snapshot: AvailabilitySnapshot, start: datetime) -> Interval | None:
        """Exact membership. Nothing is rounded onto the grid for the Model."""
        for slot in _from_json(snapshot.slots):
            if slot.start == start:
                return slot
        return None

    async def _refresh_after_conflict(
        self,
        conversation: Conversation,
        prop: Property,
        existing: AvailabilitySnapshot | None,
    ) -> dict[str, Any]:
        """One Calendar refresh, replacing the stale snapshot (P-062).

        Part of resolving this booking attempt — not permission to poll. If the
        refresh itself is inconclusive, stale candidates are never presented as
        current.
        """
        recomputed = await self._recompute(conversation, prop, existing=existing)
        if isinstance(recomputed, dict):
            return recomputed
        snapshot, slots = recomputed
        return {
            "result": "slot_unavailable",
            "property_id": prop.property_key,
            "time_zone": snapshot.time_zone,
            "candidates": _to_json(
                slots[: self._policy.max_candidates], self._policy.schedule.zone
            ),
        }

    def _local(self, moment: datetime) -> str:
        """Always render in the Broker's zone.

        PostgreSQL returns timestamps in UTC while freshly computed slots carry
        the local offset. Without this, the same instant reaches the Model as
        13:00-06:00 on booking and 19:00+00:00 on an idempotent replay — and the
        Agent would quote two different times for one appointment.
        """
        return moment.astimezone(self._policy.schedule.zone).isoformat()

    def _result_for(
        self, attempt: Appointment, property_key: str, property_name: str
    ) -> dict[str, Any]:
        """The tool answer for one attempt, from values already loaded.

        Takes the Property's key and name rather than the row, for the reason
        spelled out in :meth:`book`: the row may be expired by then.
        """
        if attempt.status == AppointmentStatus.CONFIRMED.value:
            return {
                "result": "confirmed",
                "appointment_reference": attempt.reference,
                "property_id": property_key,
                "property_name": property_name,
                "start": self._local(attempt.starts_at),
                "end": self._local(attempt.ends_at),
                "time_zone": self._policy.schedule.timezone,
            }
        if attempt.status == AppointmentStatus.NEEDS_REVIEW.value:
            return {
                "result": "needs_review",
                "appointment_reference": attempt.reference,
                "property_id": property_key,
            }
        if attempt.status == AppointmentStatus.REJECTED.value:
            return {
                "result": "slot_unavailable",
                "property_id": property_key,
                "candidates": [],
            }
        return {"result": "temporarily_unavailable"}


def confirmation_message(
    *,
    property_name: str,
    starts_at: datetime,
    schedule: WeeklySchedule,
    visit_address: str | None = None,
) -> str:
    """The deterministic confirmation (P-044). Rendered from persisted state only."""
    local = starts_at.astimezone(schedule.zone)
    message = (
        f"Tu cita para visitar {property_name} quedó confirmada para el "
        f"{local.strftime('%d/%m/%Y')} a las {local.strftime('%H:%M')}. "
    )
    if visit_address:
        message += f"La dirección de la visita es: {visit_address}. "
    return message + "Si necesitas cambiarla, responde a este mensaje."


def cancellation_message(
    *, property_name: str, starts_at: datetime, schedule: WeeklySchedule
) -> str:
    """The deterministic cancellation confirmation rendered from persisted state."""
    local = starts_at.astimezone(schedule.zone)
    return (
        f"Tu cita para visitar {property_name} del {local.strftime('%d/%m/%Y')} "
        f"a las {local.strftime('%H:%M')} quedó cancelada. "
        "¿Quieres que busquemos otro horario para reagendar?"
    )


# P-042: the Lead-facing message for an ambiguous booking result. The Model may
# not replace this with confirmation language.
NEEDS_REVIEW_MESSAGE = (
    "No pude confirmar la cita en este momento. El concierge revisará la "
    "disponibilidad y te confirmará lo antes posible."
)


# -- The Lead-facing outcome message ------------------------------------------
#
# A booking outcome reaches the Lead as *product* text, never as the Model's
# account of it. The Worker asks for a pending notice at settlement and releases
# it in place of the draft, so what the Lead reads about an appointment is
# rendered from the persisted row — the same source Calendar was written from.


LEAD_NOTICE_CONFIRMATION = OutboxKind.APPOINTMENT_CONFIRMATION
LEAD_NOTICE_NEEDS_REVIEW = OutboxKind.APPOINTMENT_NEEDS_REVIEW


@dataclass(frozen=True)
class LeadNotice:
    appointment_id: uuid.UUID
    reference: str
    kind: str
    body: str


async def pending_lead_notice(
    session: AsyncSession, conversation: Conversation, schedule: WeeklySchedule
) -> LeadNotice | None:
    """The deterministic message this Conversation still owes the Lead, if any.

    Only a resolved attempt qualifies. A ``Pending`` row is an attempt still in
    flight and says nothing to anyone yet.

    A notice is owed only while the visit is still ahead. Normally it is
    released seconds after booking, so a notice whose slot has already passed
    means something went wrong for hours — and confirming a visit that has
    already started would be worse than the silence. Those are retired here
    instead, which also stops one stale row from displacing every future reply
    in the Conversation.
    """
    unnotified = (
        (
            await session.execute(
                select(Appointment)
                .where(Appointment.conversation_id == conversation.id)
                .where(Appointment.lead_notice_at.is_(None))
                .where(
                    Appointment.status.in_(
                        (
                            AppointmentStatus.CONFIRMED.value,
                            AppointmentStatus.NEEDS_REVIEW.value,
                        )
                    )
                )
                .order_by(Appointment.created_at)
            )
        )
        .scalars()
        .all()
    )

    now = _now()
    row = None
    lapsed = 0
    for candidate in unnotified:
        if candidate.starts_at > now and row is None:
            row = candidate
        elif candidate.starts_at <= now:
            candidate.lead_notice_at = now
            lapsed += 1
    if lapsed:
        await session.commit()
    if row is None:
        return None

    if row.status == AppointmentStatus.NEEDS_REVIEW.value:
        return LeadNotice(
            appointment_id=row.id,
            reference=row.reference,
            kind=LEAD_NOTICE_NEEDS_REVIEW,
            body=NEEDS_REVIEW_MESSAGE,
        )

    prop = await session.get(Property, row.property_uuid)
    return LeadNotice(
        appointment_id=row.id,
        reference=row.reference,
        kind=LEAD_NOTICE_CONFIRMATION,
        body=confirmation_message(
            property_name=prop.name if prop else "la propiedad",
            starts_at=row.starts_at,
            schedule=schedule,
            visit_address=prop.visit_address if prop else None,
        ),
    )


async def mark_lead_notified(session: AsyncSession, appointment_id: uuid.UUID) -> None:
    """Record that the notice was released, so the next turn does not repeat it."""
    row = await session.get(Appointment, appointment_id)
    if row is not None and row.lead_notice_at is None:
        row.lead_notice_at = _now()
        await session.commit()

"""Availability snapshots and appointment booking (P-010, P-042, P-057…P-063).

The two model-facing operations live here. Everything consequential is decided by
this module, not by the Model: which slots exist, whether the Property is still
Active, whether the exact interval is still free, and whether an attempt became a
Confirmed Appointment.

The ordering in :meth:`book` is the whole point and is deliberate:

1. resolve the Property and the trusted Conversation;
2. require the exact start to be a member of *this* Conversation's snapshot, so
   the Model cannot invent a time;
3. re-read Property Status — must still be ``Active``;
4. re-read Calendar for that exact interval — must still be free;
5. persist the Appointment Booking Attempt **before** touching Calendar;
6. create the Calendar event carrying a deterministic reference to the attempt;
7. only a conclusive result becomes ``Confirmed``.

Steps 3 and 4 are what stop a stale snapshot from producing a real booking.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.google.calendar import CalendarOutcome, GoogleCalendar
from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    AvailabilitySnapshot,
    Conversation,
    Lead,
    LeadEngagementCycle,
    OutboundInitiation,
    Property,
    PropertyStatus,
)
from realestate.domain.outbound import (
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
)
from realestate.domain.outbox import OutboxKind
from realestate.domain.availability import (
    Interval,
    WeeklySchedule,
    candidate_slots,
    filter_slots,
    horizon_end,
)
from realestate.domain.properties import resolve_property


@dataclass(frozen=True)
class AppointmentPolicy:
    schedule: WeeklySchedule
    visit_minutes: int
    horizon_days: int
    max_candidates: int
    event_title: str = "Visita — {property} — {name}"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _reference() -> str:
    return f"APT-{secrets.token_hex(4).upper()}"


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


class AppointmentService:
    def __init__(
        self,
        session: AsyncSession,
        calendar: GoogleCalendar,
        policy: AppointmentPolicy,
    ) -> None:
        self._session = session
        self._calendar = calendar
        self._policy = policy

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
        prop = await self._resolve_active(reference)
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
        self, reference: str
    ) -> Property | dict[str, Any]:
        prop = await resolve_property(self._session, reference)
        if prop is None:
            return {"result": "not_found"}
        if prop.status != PropertyStatus.ACTIVE.value:
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
        """One Calendar read for the whole horizon, then persist every interval.

        Returns ``(snapshot, slots)``, or a refusal dict when Calendar was
        inconclusive. Both the first snapshot and the post-conflict refresh go
        through here so they cannot drift on horizon or candidate policy.
        """
        now = _now()
        end = horizon_end(now, self._policy.horizon_days, self._policy.schedule)

        busy = await self._calendar.busy_between(now, end)
        if not busy.ok:
            # Never fall back to "nothing is busy" — that would offer times the
            # Broker is not free.
            return {"result": "temporarily_unavailable", "detail": busy.detail}

        slots = candidate_slots(
            now=now,
            schedule=self._policy.schedule,
            visit_minutes=self._policy.visit_minutes,
            horizon_days=self._policy.horizon_days,
            busy=busy.busy,
        )
        stored = await self._store_snapshot(conversation, prop, slots, end, existing)
        return stored, slots

    async def _store_snapshot(
        self,
        conversation: Conversation,
        prop: Property,
        slots: list[Interval],
        end: datetime,
        existing: AvailabilitySnapshot | None,
    ) -> AvailabilitySnapshot:
        if existing is not None:
            existing.slots = _to_json(slots)
            existing.horizon_end = end
            existing.created_at = _now()
            existing.time_zone = self._policy.schedule.timezone
            await self._session.commit()
            return existing

        row = AvailabilitySnapshot(
            conversation_id=conversation.id,
            property_uuid=prop.id,
            horizon_end=end,
            time_zone=self._policy.schedule.timezone,
            slots=_to_json(slots),
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
        cycle = await self._session.get(LeadEngagementCycle, conversation.cycle_id)
        if cycle is None or not cycle.is_active(_now()):
            return {"result": "conversation_expired"}

        prop = await self._resolve_active(reference)
        if isinstance(prop, dict):
            # A live Inactive Property creates no attempt and no event (P-063).
            return prop

        row = await self._snapshot_row(conversation, prop)
        snapshot = self._usable(row)
        if snapshot is None:
            return {"result": "invalid_candidate", "detail": "no current snapshot"}

        slot = self._member_of(snapshot, start)
        if slot is None:
            # The Model proposed a time this Conversation never observed.
            return {"result": "invalid_candidate"}

        # An idempotent replay of the same accepted slot returns the prior
        # outcome rather than booking twice.
        property_uuid = prop.id
        key = f"apt:{conversation.id}:{property_uuid}:{slot.start.isoformat()}"
        existing = (
            await self._session.execute(
                select(Appointment).where(Appointment.idempotency_key == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._result_for(existing, prop)

        live = await self._calendar.is_free(slot)
        if live.outcome is CalendarOutcome.CONFLICT:
            return await self._refresh_after_conflict(conversation, prop, row)
        if not live.ok:
            return {"result": "temporarily_unavailable", "detail": live.detail}

        attempt = await self._persist_attempt(conversation, prop, slot, attendee_name)
        if attempt is None:
            # Another worker won the same key between the check and the insert.
            again = (
                await self._session.execute(
                    select(Appointment).where(Appointment.idempotency_key == key)
                )
            ).scalar_one()
            # The rollback inside _persist_attempt expired this session's
            # identity map, so `prop` is re-read here. _result_for is a plain
            # method: reading an expired attribute from it would emit IO with no
            # greenlet to run it on, and the loser of the race would crash
            # instead of reporting the winner's outcome.
            found = await self._session.get(Property, property_uuid)
            if found is None:  # pragma: no cover - the row was just read
                raise RuntimeError(f"Property {property_uuid} vanished mid-booking.")
            return self._result_for(again, found)

        lead = await self._session.get(Lead, conversation.lead_id)
        event = await self._calendar.create_event(
            slot=slot,
            summary=self._policy.event_title.format(
                property=prop.name, name=attendee_name or (lead.profile_name if lead else "")
            ),
            description=self._describe(lead, attendee_name),
            reference=attempt.reference,
            location=prop.visit_address,
        )

        if event.outcome is CalendarOutcome.OK:
            attempt.status = AppointmentStatus.CONFIRMED.value
            attempt.calendar_event_id = event.event_id
            attempt.resolved_at = _now()
        else:
            # Inconclusive: the event may exist. Not a Confirmed Appointment,
            # not retried, and the Model may not call it confirmed (P-042).
            attempt.status = AppointmentStatus.NEEDS_REVIEW.value
            attempt.last_error = event.detail
        await self._session.commit()

        return self._result_for(attempt, prop)

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

        query = (
            select(Appointment)
            .where(Appointment.conversation_id == conversation.id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
            .where(Appointment.starts_at > _now())
            .order_by(Appointment.starts_at)
        )
        if reference:
            query = query.where(Appointment.reference == reference)
        rows = (await self._session.execute(query)).scalars().all()
        if not rows:
            return {"result": "not_found"}
        if len(rows) > 1 and not reference:
            return {
                "result": "ambiguous",
                "appointments": [self._summary_for(row) for row in rows],
            }

        row = rows[0]
        prop = await self._session.get(Property, row.property_uuid)
        lead = await self._session.get(Lead, row.lead_id)

        event_id = row.calendar_event_id
        if event_id is None:
            evidence = await self._calendar.find_by_reference(row.reference)
            if evidence.outcome is not CalendarOutcome.OK:
                return {
                    "result": "needs_review",
                    "appointment_reference": row.reference,
                    "detail": evidence.detail,
                }
            event_id = evidence.event_id

        if event_id is not None:
            deleted = await self._calendar.delete_event(event_id)
            if deleted.outcome is not CalendarOutcome.OK:
                return {
                    "result": "needs_review",
                    "appointment_reference": row.reference,
                    "detail": deleted.detail,
                }

        row.status = AppointmentStatus.CANCELLED.value
        row.cancelled_at = _now()
        row.calendar_event_id = None
        row.resolved_at = row.resolved_at or row.cancelled_at
        await self._session.commit()

        notified = lead is not None
        if lead is not None:
            # Reached through the Hermes cancel tool, so the Contact is asking
            # for this in an open conversation. It is still put to the gate: if
            # the tool ran long after their last message the window may have
            # closed, and a send that Meta would reject must fail here instead.
            confirmation = await OutboundMessaging(self._session).request(
                OutboundIntent(
                    conversation=conversation,
                    body=cancellation_message(
                        property_name=prop.name if prop else "la propiedad",
                        starts_at=row.starts_at,
                        schedule=self._policy.schedule,
                    ),
                    purpose=Purpose.APPOINTMENT_CANCELLATION,
                    initiation=OutboundInitiation.REACTIVE,
                    trigger_inbox_ids=trigger_inbox_ids,
                    idempotency_key=f"appointment-cancellation:{row.id}",
                )
            )
            await self._session.commit()
            if isinstance(confirmation, Denied):
                # The visit is cancelled either way — that already happened in
                # Calendar. What the Contact was not told is reported, so the
                # tool's answer cannot imply a message that never went out.
                notified = False

        return {
            "result": "cancelled",
            "lead_notified": notified,
            "appointment_reference": row.reference,
            "property_id": prop.property_key if prop else None,
            "property_name": prop.name if prop else None,
            "start": self._local(row.starts_at),
            "end": self._local(row.ends_at),
            "time_zone": self._policy.schedule.timezone,
            "reschedule_prompt_required": True,
        }

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

    async def _persist_attempt(
        self,
        conversation: Conversation,
        prop: Property,
        slot: Interval,
        attendee_name: str | None,
    ) -> Appointment | None:
        attempt = Appointment(
            # The appointment belongs to the Organization that owns the
            # Conversation. Derived rather than passed in: two sources for the
            # same fact could disagree (ADR-0019).
            organization_id=conversation.organization_id,
            reference=_reference(),
            idempotency_key=f"apt:{conversation.id}:{prop.id}:{slot.start.isoformat()}",
            conversation_id=conversation.id,
            lead_id=conversation.lead_id,
            property_uuid=prop.id,
            starts_at=slot.start,
            ends_at=slot.end,
            attendee_name=attendee_name,
            status=AppointmentStatus.PENDING.value,
        )
        self._session.add(attempt)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            return None
        return attempt

    def _describe(self, lead: Lead | None, attendee_name: str | None) -> str:
        lines = []
        if attendee_name:
            lines.append(f"Nombre: {attendee_name}")
        if lead is not None:
            if lead.profile_name:
                lines.append(f"WhatsApp: {lead.profile_name}")
            lines.append(f"Teléfono: +{lead.wa_id}")
        return "\n".join(lines)

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

    def _result_for(self, attempt: Appointment, prop: Property) -> dict[str, Any]:
        if attempt.status == AppointmentStatus.CONFIRMED.value:
            return {
                "result": "confirmed",
                "appointment_reference": attempt.reference,
                "property_id": prop.property_key,
                "property_name": prop.name,
                "start": self._local(attempt.starts_at),
                "end": self._local(attempt.ends_at),
                "time_zone": self._policy.schedule.timezone,
            }
        if attempt.status == AppointmentStatus.NEEDS_REVIEW.value:
            return {
                "result": "needs_review",
                "appointment_reference": attempt.reference,
                "property_id": prop.property_key,
            }
        if attempt.status == AppointmentStatus.REJECTED.value:
            return {"result": "slot_unavailable", "property_id": prop.property_key, "candidates": []}
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

"""Deterministic visit reminders, and why they are not being sent yet.

The cadence PROJECT_MEMORY records is a hypothesis: confirmation immediately
after booking, one reminder 24 hours before, one on the day of the visit.
SAN-036 asks Santiago to validate the content, the timing, and the conditions
that would avoid a duplicate or pointless message. He has not answered.

So this module does the half that is safe and refuses the half that is not.

**Implemented:** the schedule is computed deterministically when a visit is
confirmed, stored one row per reminder, and settled exactly once. There is
nothing probabilistic about which reminders a visit owes, and a restart cannot
duplicate or lose one.

**Blocked:** dispatch. ``REMINDER_POLICY_ACTIVATED`` is ``False``, so every due
reminder is settled with the recorded reason ``PolicyNotValidated`` and no
message is composed. Turning it on is one edit *and* it still has to get past
the Outbound Eligibility Gate, which denies free-form text outside Meta's
24-hour window — and the day-before reminder is by definition outside it unless
the Contact happens to have written that day. Reminders are therefore structural
template work, exactly as ADR-0045 says proactive follow-up is.

The wording of a reminder is Product's, never the Model's: a reminder that
paraphrased the appointment could contradict the row it was rendered from.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Appointment,
    AppointmentReminder,
    AppointmentReminderKind,
    AppointmentStatus,
    Conversation,
    OutboundInitiation,
    Property,
)
from realestate.domain.audit import record_audit
from realestate.domain.availability import WeeklySchedule
from realestate.domain.clock import utc_now
from realestate.domain.copy import visit_stamp
from realestate.domain.outbound import (
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
)

logger = logging.getLogger(__name__)

#: The named hypothesis a settled reminder was produced under, so a later report
#: can explain why a given moment was chosen after the hypothesis changes.
REMINDER_POLICY_VERSION = "visit-reminders-hypothesis-1"

#: Deliberately off. SAN-036 is unanswered, and a reminder cadence Product
#: invented would reach real customers. Flipping this does not bypass the
#: Outbound Eligibility Gate; it only stops this module from withholding first.
REMINDER_POLICY_ACTIVATED = False

#: How long before the visit the first reminder is owed.
DAY_BEFORE_LEAD = timedelta(hours=24)

OUTCOME_LABELS: dict[str, str] = {
    "Queued": "Enviado",
    "PolicyNotValidated": "Retenido: la política de recordatorios no está validada",
    "AppointmentNotConfirmed": "Retenido: la cita ya no está confirmada",
    "VisitAlreadyStarted": "Retenido: la visita ya empezó",
}

REMINDER_KIND_LABELS: dict[str, str] = {
    AppointmentReminderKind.DAY_BEFORE.value: "24 horas antes",
    AppointmentReminderKind.DAY_OF.value: "El día de la visita",
}


@dataclass(frozen=True)
class DueReminder:
    reminder: AppointmentReminder
    appointment: Appointment


class AppointmentReminders:
    """The reminder module.

    Hides: the cadence arithmetic, one-row-per-reminder idempotency, the
    activation gate, the eligibility gate, and settling a reminder whose visit
    has already started.
    """

    def __init__(
        self,
        session: AsyncSession,
        schedule: WeeklySchedule,
        *,
        day_of_hour: int,
        organization_id: uuid.UUID | None = None,
    ) -> None:
        self._session = session
        self._schedule = schedule
        self._day_of_hour = day_of_hour
        self._organization_id = organization_id

    async def schedule_for(self, appointment: Appointment) -> list[AppointmentReminder]:
        """Create the reminders this confirmed visit owes. Never commits.

        Idempotent through ``uq_reminder_appointment_kind``: booking, an
        idempotent replay of booking, and a reschedule that lands on the same
        row all produce the same two reminders.
        """
        if appointment.status != AppointmentStatus.CONFIRMED.value:
            return []
        wanted = {
            AppointmentReminderKind.DAY_BEFORE: appointment.starts_at - DAY_BEFORE_LEAD,
            AppointmentReminderKind.DAY_OF: self._day_of_moment(appointment.starts_at),
        }
        existing = {
            row.kind
            for row in await self._session.scalars(
                select(AppointmentReminder).where(
                    AppointmentReminder.appointment_id == appointment.id
                )
            )
        }
        created: list[AppointmentReminder] = []
        for kind, due_at in wanted.items():
            if kind.value in existing:
                continue
            row = AppointmentReminder(
                organization_id=appointment.organization_id,
                appointment_id=appointment.id,
                kind=kind.value,
                due_at=due_at,
            )
            self._session.add(row)
            try:
                async with self._session.begin_nested():
                    await self._session.flush()
            except IntegrityError:
                # Another transaction scheduled the same reminder. One row is
                # the whole guarantee, so the loser simply has nothing to do.
                continue
            created.append(row)
        return created

    def _day_of_moment(self, starts_at: datetime) -> datetime:
        """The day-of reminder time, in the operation's zone.

        The hour is configuration rather than a number chosen here, because the
        hour a customer should be messaged is an operational decision Santiago
        owns (SAN-036). A reminder that would fall after the visit has already
        started is pulled back to the visit's own morning boundary: it is still
        deterministic, and it will be withheld anyway while the policy is
        inactive.
        """
        local = starts_at.astimezone(self._schedule.zone)
        candidate = local.replace(
            hour=self._day_of_hour, minute=0, second=0, microsecond=0
        )
        if candidate >= local:
            candidate = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return candidate

    async def due(self, now: datetime | None = None) -> list[DueReminder]:
        """Reminders owed right now, earliest first."""
        moment = now or utc_now()
        query = (
            select(AppointmentReminder, Appointment)
            .join(Appointment, Appointment.id == AppointmentReminder.appointment_id)
            .where(AppointmentReminder.settled_at.is_(None))
            .where(AppointmentReminder.due_at <= moment)
            .order_by(AppointmentReminder.due_at)
        )
        if self._organization_id is not None:
            query = query.where(
                Appointment.organization_id == self._organization_id
            )
        rows = await self._session.execute(query)
        return [DueReminder(reminder=r, appointment=a) for r, a in rows.all()]

    async def settle_due(self, now: datetime | None = None) -> dict[str, int]:
        """Settle every due reminder exactly once. Commits.

        Returns a count per outcome, which is what the worker logs and what the
        tests assert on. Every path settles the row: a reminder left unsettled
        because the policy is off would be re-examined on every tick forever.
        """
        moment = now or utc_now()
        outcomes: dict[str, int] = {}
        for item in await self.due(moment):
            outcome = await self._settle_one(item, moment)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        if outcomes:
            await self._session.commit()
        return outcomes

    async def _settle_one(self, item: DueReminder, moment: datetime) -> str:
        appointment = item.appointment
        if appointment.status != AppointmentStatus.CONFIRMED.value:
            return await self._settle(item.reminder, "AppointmentNotConfirmed", moment)
        if appointment.starts_at <= moment:
            # A reminder is only a reminder beforehand. Announcing a visit that
            # has already begun is worse than the silence.
            return await self._settle(item.reminder, "VisitAlreadyStarted", moment)
        if not REMINDER_POLICY_ACTIVATED:
            logger.info(
                "Withholding the %s reminder for appointment %s: the reminder "
                "policy is not validated (SAN-036)",
                item.reminder.kind,
                appointment.reference,
            )
            await record_audit(
                self._session,
                organization_id=appointment.organization_id,
                actor_type="Product",
                actor_id="AppointmentReminders",
                action="WithholdAppointmentReminder",
                subject_type="Appointment",
                subject_id=str(appointment.id),
                details={
                    "kind": item.reminder.kind,
                    "policy_version": REMINDER_POLICY_VERSION,
                    "reason": "PolicyNotValidated",
                },
                commit=False,
            )
            return await self._settle(item.reminder, "PolicyNotValidated", moment)

        conversation = await self._session.get(
            Conversation, appointment.conversation_id
        )
        if conversation is None:  # pragma: no cover - the FK forbids it
            return await self._settle(item.reminder, "AppointmentNotConfirmed", moment)
        prop = await self._session.get(Property, appointment.property_uuid)
        outcome = await OutboundMessaging(self._session).request(
            OutboundIntent(
                conversation=conversation,
                body=reminder_body(
                    property_name=prop.name if prop else "la propiedad",
                    starts_at=appointment.starts_at,
                    schedule=self._schedule,
                    visit_address=prop.visit_address if prop else None,
                ),
                purpose=Purpose.APPOINTMENT_REMINDER,
                # The operation reaching out on a schedule. Declaring this
                # Reactive would be a lie the gate is entitled to disbelieve.
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key=f"appointment-reminder:{item.reminder.id}",
            )
        )
        if isinstance(outcome, Denied):
            return await self._settle(item.reminder, outcome.reason.value, moment)
        return await self._settle(item.reminder, "Queued", moment)

    async def _settle(
        self, reminder: AppointmentReminder, outcome: str, moment: datetime
    ) -> str:
        reminder.settled_at = moment
        reminder.outcome = outcome[:40]
        await self._session.flush()
        return outcome

    async def for_appointment(
        self, appointment_id: uuid.UUID
    ) -> list[AppointmentReminder]:
        return (await self.for_appointments([appointment_id])).get(appointment_id, [])

    async def for_appointments(
        self, appointment_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[AppointmentReminder]]:
        """Reminders for a whole agenda, in one query.

        The agenda renders a reminder column per visit; asking per row turned a
        two-week page into one query per appointment.
        """
        if not appointment_ids:
            return {}
        rows = await self._session.scalars(
            select(AppointmentReminder)
            .where(AppointmentReminder.appointment_id.in_(appointment_ids))
            .order_by(AppointmentReminder.due_at)
        )
        grouped: dict[uuid.UUID, list[AppointmentReminder]] = {}
        for row in rows:
            grouped.setdefault(row.appointment_id, []).append(row)
        return grouped


def reminder_body(
    *,
    property_name: str,
    starts_at: datetime,
    schedule: WeeklySchedule,
    visit_address: str | None,
) -> str:
    """The Contact-facing reminder. Product copy, rendered from the row."""
    stamp = visit_stamp(starts_at, schedule.zone)
    text = f"Te recordamos tu visita a {property_name} el {stamp}. "
    if visit_address:
        text += f"La dirección es: {visit_address}. "
    return text + "Si necesitas cambiarla, responde a este mensaje."

"""The Broker's appointment notifications (amendment 2 in checkpoint-3-inputs.md).

Three notifications, all Telegram, all originated by the product:

| Trigger | Message |
|---|---|
| A booking resolves | one immediate notice per Appointment |
| Every morning, from ``digest_hour`` | one digest of that day's visits |
| ``reminder_minutes`` before a visit | one reminder per Appointment |

No model tool is involved and no Meta messaging rule applies: the recipient is an
administrator on a channel he opened himself.

Selection is here and sending is in :mod:`realestate.worker.broker`, for the
usual reason — every rule about *which* notice is owed is then testable without a
Telegram token, and the worker holds no policy.

Each notice is claimed by stamping the Appointment row it covers, so at-most-once
survives a restart. An unstamped notice can be sent twice if the process dies
between the send and the stamp; for an internal Telegram message that trade is
correct, and it is the opposite of the Lead-facing choice (P-036), where a
missing message beats a duplicate one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import Appointment, AppointmentStatus, Lead, Property
from realestate.domain.availability import WeeklySchedule
from realestate.domain.copy import SPANISH_DAYS as _DAYS

BOOKED = "Booked"
NEEDS_REVIEW = "NeedsReview"
DIGEST = "Digest"
REMINDER = "Reminder"


@dataclass(frozen=True)
class BrokerNotice:
    """One Telegram message, and the Appointment rows sending it settles."""

    kind: str
    body: str
    appointment_ids: tuple[uuid.UUID, ...]
    # Only the digest carries this: the local day it reports on.
    local_day: str | None = None


@dataclass(frozen=True)
class _Visit:
    """One Appointment with the display facts a notice needs."""

    appointment: Appointment
    property_name: str
    lead: Lead | None

    @property
    def who(self) -> str:
        name = self.appointment.attendee_name or (
            self.lead.profile_name if self.lead else None
        )
        return name or "sin nombre"

    @property
    def phone(self) -> str:
        return f"+{self.lead.wa_id}" if self.lead else "—"


def _now() -> datetime:
    return datetime.now(tz=UTC)


class BrokerNotificationService:
    def __init__(
        self,
        session: AsyncSession,
        schedule: WeeklySchedule,
        *,
        digest_hour: int,
        reminder_minutes: int,
    ) -> None:
        self._session = session
        self._schedule = schedule
        self._digest_hour = digest_hour
        self._reminder_minutes = reminder_minutes

    # -- Selection ---------------------------------------------------------

    async def due(self, now: datetime | None = None) -> list[BrokerNotice]:
        """Every notice the Broker is owed right now, in the order to send them."""
        moment = now or _now()
        notices = await self._immediate()
        digest = await self._digest(moment)
        if digest is not None:
            notices.append(digest)
        notices.extend(await self._reminders(moment))
        return notices

    async def _immediate(self) -> list[BrokerNotice]:
        """One notice per resolved Appointment the Broker has not seen yet.

        ``NeedsReview`` is included deliberately: an inconclusive Calendar write
        is exactly the case a human has to look at, and it is the only one where
        the Lead was told the concierge would follow up.
        """
        rows = (
            (
                await self._session.execute(
                    select(Appointment)
                    .where(Appointment.booked_notice_at.is_(None))
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

        notices = []
        for row in rows:
            visit = await self._visit(row)
            confirmed = row.status == AppointmentStatus.CONFIRMED.value
            notices.append(
                BrokerNotice(
                    kind=BOOKED if confirmed else NEEDS_REVIEW,
                    body=(
                        booked_body(visit, self._schedule)
                        if confirmed
                        else needs_review_body(visit, self._schedule)
                    ),
                    appointment_ids=(row.id,),
                )
            )
        return notices

    async def _digest(self, now: datetime) -> BrokerNotice | None:
        """One digest per local day, once the digest hour has arrived.

        It reports *all* of the day's Confirmed visits, not only the unstamped
        ones: a digest that omitted a visit because the Broker was already told
        about it individually would be a worse digest.
        """
        local = now.astimezone(self._schedule.zone)
        if local.hour < self._digest_hour:
            return None

        today = self._schedule.local_day(now)
        visits = await self._confirmed_on(local.date())
        if not visits:
            return None
        if all(v.appointment.digest_sent_on == today for v in visits):
            return None

        return BrokerNotice(
            kind=DIGEST,
            body=digest_body(visits, local, self._schedule),
            appointment_ids=tuple(v.appointment.id for v in visits),
            local_day=today,
        )

    async def _reminders(self, now: datetime) -> list[BrokerNotice]:
        """One reminder per Confirmed visit inside the reminder window."""
        rows = (
            (
                await self._session.execute(
                    select(Appointment)
                    .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                    .where(Appointment.reminder_sent_at.is_(None))
                    .where(
                        Appointment.starts_at
                        <= now + timedelta(minutes=self._reminder_minutes)
                    )
                    .where(Appointment.starts_at > now)
                    .order_by(Appointment.starts_at)
                )
            )
            .scalars()
            .all()
        )

        notices = []
        for row in rows:
            visit = await self._visit(row)
            notices.append(
                BrokerNotice(
                    kind=REMINDER,
                    body=reminder_body(visit, now, self._schedule),
                    appointment_ids=(row.id,),
                )
            )
        return notices

    async def lapse_stale_reminders(self, now: datetime | None = None) -> int:
        """Retire reminders whose visit already started.

        A reminder is only a reminder before the fact. If the process was down
        through the window, the honest outcome is to drop it rather than announce
        a visit that is already under way.
        """
        moment = now or _now()
        rows = (
            (
                await self._session.execute(
                    select(Appointment)
                    .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                    .where(Appointment.reminder_sent_at.is_(None))
                    .where(Appointment.starts_at <= moment)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.reminder_sent_at = moment
        if rows:
            await self._session.commit()
        return len(rows)

    # -- Settlement --------------------------------------------------------

    async def mark_sent(self, notice: BrokerNotice, now: datetime | None = None) -> None:
        """Stamp the rows a delivered notice covers."""
        moment = now or _now()
        local_today = self._schedule.local_day(moment)

        for appointment_id in notice.appointment_ids:
            row = await self._session.get(Appointment, appointment_id)
            if row is None:
                continue
            if notice.kind in (BOOKED, NEEDS_REVIEW):
                row.booked_notice_at = moment
                # A visit later today, booked after the digest hour: the Broker
                # has just been told, so today's digest owes him nothing more.
                if (
                    row.status == AppointmentStatus.CONFIRMED.value
                    and self._schedule.local_day(row.starts_at) == local_today
                    and moment.astimezone(self._schedule.zone).hour
                    >= self._digest_hour
                ):
                    row.digest_sent_on = local_today
            elif notice.kind == DIGEST:
                row.digest_sent_on = notice.local_day or local_today
            elif notice.kind == REMINDER:
                row.reminder_sent_at = moment
        await self._session.commit()

    # -- Reading the rows --------------------------------------------------

    async def _visit(self, row: Appointment) -> _Visit:
        prop = await self._session.get(Property, row.property_uuid)
        lead = await self._session.get(Lead, row.lead_id)
        return _Visit(
            appointment=row,
            property_name=prop.name if prop else "propiedad desconocida",
            lead=lead,
        )

    async def _confirmed_on(self, day) -> list[_Visit]:  # noqa: ANN001 - datetime.date
        """Every Confirmed visit whose *local* start falls on ``day``."""
        zone = self._schedule.zone
        start = datetime.combine(day, datetime.min.time(), tzinfo=zone)
        rows = (
            (
                await self._session.execute(
                    select(Appointment)
                    .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                    .where(Appointment.starts_at >= start)
                    .where(Appointment.starts_at < start + timedelta(days=1))
                    .order_by(Appointment.starts_at)
                )
            )
            .scalars()
            .all()
        )
        return [await self._visit(row) for row in rows]


# -- Copy ----------------------------------------------------------------------
#
# Broker-facing, so it is written for someone who has to act on it: the property,
# when, who, the phone number to call, and the reference to quote. Spanish day
# and month names are spelled out here rather than taken from the C locale, which
# is not guaranteed to be installed and would silently produce English.


def _stamp(moment: datetime, schedule: WeeklySchedule) -> str:
    local = moment.astimezone(schedule.zone)
    return f"{_DAYS[local.weekday()]} {local.strftime('%d/%m')} a las {local.strftime('%H:%M')}"


def booked_body(visit: _Visit, schedule: WeeklySchedule) -> str:
    return "\n".join(
        [
            "🗓️ Nueva visita agendada",
            visit.property_name,
            _stamp(visit.appointment.starts_at, schedule),
            f"{visit.who} — {visit.phone}",
            f"Ref: {visit.appointment.reference}",
        ]
    )


def needs_review_body(visit: _Visit, schedule: WeeklySchedule) -> str:
    return "\n".join(
        [
            "⚠️ Cita sin confirmar — requiere revisión",
            visit.property_name,
            _stamp(visit.appointment.starts_at, schedule),
            f"{visit.who} — {visit.phone}",
            f"Ref: {visit.appointment.reference}",
            "",
            "Google Calendar no respondió de forma concluyente: el evento pudo "
            "haberse creado o no. Revísalo antes de contactar.",
            "Al cliente se le dijo que el concierge le confirmará; no se le "
            "confirmó la cita.",
        ]
    )


def digest_body(
    visits: list[_Visit], local_now: datetime, schedule: WeeklySchedule
) -> str:
    header = (
        f"📋 Visitas de hoy, {_DAYS[local_now.weekday()]} "
        f"{local_now.strftime('%d/%m')}:"
    )
    lines = [header]
    for visit in visits:
        local = visit.appointment.starts_at.astimezone(schedule.zone)
        lines.append(
            f"• {local.strftime('%H:%M')} — {visit.property_name} — "
            f"{visit.who} ({visit.phone})"
        )
    return "\n".join(lines)


def reminder_body(visit: _Visit, now: datetime, schedule: WeeklySchedule) -> str:
    local = visit.appointment.starts_at.astimezone(schedule.zone)
    minutes = max(0, int((visit.appointment.starts_at - now).total_seconds() // 60))
    return "\n".join(
        [
            f"⏰ Visita en {minutes} min — {local.strftime('%H:%M')}",
            visit.property_name,
            f"{visit.who} — {visit.phone}",
            f"Ref: {visit.appointment.reference}",
        ]
    )

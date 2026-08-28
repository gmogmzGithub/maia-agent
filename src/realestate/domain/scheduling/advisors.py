"""What times could this Advisor actually receive a visit?

``AdvisorScheduling.find_slots(query)`` answers that and nothing else. It does
not book, does not persist a snapshot, and does not decide who the Advisor
should be when the caller already knows — those are three different
responsibilities and each has its own module.

What it does own is the whole chain of reasons the answer might be "no times":

* nobody is designated for this Property and no Advisor was named;
* the Advisor cannot own work, or has been deactivated;
* the Advisor has a declared Advisor Absence covering the whole window;
* the Advisor has no configured calendar, so Product has no authority to quote;
* the calendar could not be read.

Each is a distinct refusal with its own Mexican Spanish sentence, because they
have distinct remedies and an operator reading "no hay horarios" would have no
idea which one to fix.

The Weekly Bookable Schedule and the 90-minute visit come from configuration and
apply to the whole Organization. Per-Advisor working hours are *not* invented
here: SAN-032 and SAN-031 are unanswered, and a per-person schedule Product made
up would be worse than one the operation has already agreed on. An Advisor
expresses their own limits as busy time in their authoritative calendar, which
is exactly what PROJECT_MEMORY says they do for travel.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AdvisorAbsence, OrganizationMember
from realestate.domain.availability import (
    Interval,
    WeeklySchedule,
    candidate_slots,
    filter_slots,
    horizon_end,
)
from realestate.domain.scheduling.calendars import CalendarDirectory, CalendarPort

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Unavailable(str, Enum):
    """Why no availability could be offered. Stable codes: they are reported."""

    NO_ADVISOR = "NoAdvisor"
    ADVISOR_INELIGIBLE = "AdvisorIneligible"
    ADVISOR_ABSENT = "AdvisorAbsent"
    NO_AUTHORITATIVE_CALENDAR = "NoAuthoritativeCalendar"
    CALENDAR_UNREADABLE = "CalendarUnreadable"


UNAVAILABLE_MESSAGES: dict[str, str] = {
    Unavailable.NO_ADVISOR.value: (
        "No hay un asesor asignado para esta propiedad todavía."
    ),
    Unavailable.ADVISOR_INELIGIBLE.value: (
        "El asesor indicado no puede recibir visitas."
    ),
    Unavailable.ADVISOR_ABSENT.value: (
        "El asesor tiene una ausencia registrada en esas fechas."
    ),
    Unavailable.NO_AUTHORITATIVE_CALENDAR.value: (
        "El asesor no tiene calendario configurado, así que no podemos "
        "confirmar horarios."
    ),
    Unavailable.CALENDAR_UNREADABLE.value: (
        "No pudimos leer la disponibilidad en este momento."
    ),
}


@dataclass(frozen=True)
class SlotQuery:
    """One request for availability.

    Exactly one of ``advisor_id`` and ``property_uuid`` is required. Naming the
    Property is the ordinary conversational case — the Contact asked about a
    house, not about a person — and resolving it to the present Property Expert
    is this module's job rather than the caller's.
    """

    organization_id: uuid.UUID
    advisor_id: uuid.UUID | None = None
    property_uuid: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    time_from: time | None = None
    time_to: time | None = None
    now: datetime | None = None
    #: Zero means "every slot in the horizon". The conversational caller passes
    #: the configured maximum; the CRM Calendar wants them all.
    limit: int = 0

    @property
    def moment(self) -> datetime:
        return self.now or _now()


@dataclass(frozen=True)
class SlotsFound:
    """Availability for one named Advisor. May legitimately be empty.

    An empty ``slots`` here is a *successful* answer: the calendar was read, the
    schedule was applied, and the Advisor is genuinely busy. It is not the same
    as :class:`SlotsUnavailable`, and collapsing the two would tell a Contact
    "no hay horarios" when the truth is "no pudimos consultar".
    """

    advisor_id: uuid.UUID
    advisor_name: str
    calendar_id: str
    time_zone: str
    slots: tuple[Interval, ...]
    #: The end of the window this answer covers.
    horizon_end: datetime


@dataclass(frozen=True)
class SlotsUnavailable:
    reason: Unavailable
    detail: str = ""
    advisor_id: uuid.UUID | None = None

    @property
    def message(self) -> str:
        """Mexican Spanish, safe to show an operator or hand to Maia."""
        return UNAVAILABLE_MESSAGES[self.reason.value]


@dataclass(frozen=True)
class SchedulingPolicy:
    """The Organization-wide booking rules, from configuration.

    Not per-Advisor and not per-Property: both need answers Santiago has not
    given (SAN-031, SAN-032), and this stage must not invent them.
    """

    schedule: WeeklySchedule
    visit_minutes: int
    horizon_days: int


class AdvisorScheduling:
    """The availability module.

    Hides: resolving a Property to its present expert, the eligibility and
    absence checks, calendar resolution, the schedule arithmetic, and the
    distinction between "busy" and "unknown".
    """

    def __init__(
        self,
        session: AsyncSession,
        calendars: CalendarDirectory,
        policy: SchedulingPolicy,
    ) -> None:
        self._session = session
        self._calendars = calendars
        self._policy = policy

    @property
    def calendars(self) -> CalendarDirectory:
        """The calendar directory this module was given.

        Exposed because :class:`~realestate.domain.scheduling.appointments.Appointments`
        has to reach the calendar an *existing* appointment was written to,
        which is a stored id rather than an Advisor. Injecting the directory
        twice would let the two disagree about which provider is configured.
        """
        return self._calendars

    async def find_slots(self, query: SlotQuery) -> SlotsFound | SlotsUnavailable:
        """Available Slots for the Advisor this query resolves to."""
        resolved = await self.resolve_advisor(query)
        if isinstance(resolved, SlotsUnavailable):
            return resolved
        advisor, calendar = resolved

        moment = query.moment
        end = horizon_end(moment, self._policy.horizon_days, self._policy.schedule)
        busy = await calendar.busy_between(moment, end)
        if not busy.ok:
            # Never "nothing is busy": that would offer times the Advisor is not
            # free, and the Contact would arrive to an empty house.
            return SlotsUnavailable(
                Unavailable.CALENDAR_UNREADABLE,
                detail=busy.detail,
                advisor_id=advisor.id,
            )

        blocked = list(busy.busy)
        # A declared absence is authority too, and it is Product's own. An
        # Advisor who told the Administrator they are away should not be
        # bookable merely because they forgot to block the calendar.
        blocked.extend(await self._absence_intervals(advisor.id, moment, end))

        slots = candidate_slots(
            now=moment,
            schedule=self._policy.schedule,
            visit_minutes=self._policy.visit_minutes,
            horizon_days=self._policy.horizon_days,
            busy=blocked,
        )
        filtered = filter_slots(
            slots,
            date_from=query.date_from,
            date_to=query.date_to,
            time_from=query.time_from,
            time_to=query.time_to,
            limit=query.limit or len(slots) or 1,
        )
        return SlotsFound(
            advisor_id=advisor.id,
            advisor_name=advisor.display_name,
            calendar_id=advisor.calendar_id or "",
            time_zone=self._policy.schedule.timezone,
            slots=tuple(filtered),
            horizon_end=end,
        )

    async def resolve_advisor(
        self, query: SlotQuery
    ) -> tuple[OrganizationMember, CalendarPort] | SlotsUnavailable:
        """The Advisor a query is about, with a calendar Product may quote from.

        Public because :class:`~realestate.domain.scheduling.appointments.Appointments`
        needs the identical chain of checks before it writes anything. Two
        copies of "may this person receive a visit" is how one of them ends up
        permitting a booking the other would refuse.
        """
        advisor = await self._advisor_for(query)
        if advisor is None:
            return SlotsUnavailable(Unavailable.NO_ADVISOR)
        if not advisor.active or not advisor.advises:
            return SlotsUnavailable(
                Unavailable.ADVISOR_INELIGIBLE, advisor_id=advisor.id
            )
        calendar = self._calendars.for_advisor(advisor)
        if calendar is None:
            return SlotsUnavailable(
                Unavailable.NO_AUTHORITATIVE_CALENDAR, advisor_id=advisor.id
            )
        return advisor, calendar

    async def present_expert(
        self, organization_id: uuid.UUID, property_uuid: uuid.UUID, moment: datetime
    ) -> OrganizationMember | None:
        """The Property's primary expert, or the first present backup.

        The same ordering the assignment rule uses, applied to conducting a
        visit rather than owning an Opportunity. They are different questions
        about the same designation, which is why the ordering lives in
        :mod:`~realestate.domain.commercial.team` and both callers read it.
        """
        from realestate.domain.commercial.team import (
            TeamAdministration,
            absent_advisor_ids,
            expert_candidates,
        )

        designations = await TeamAdministration(self._session).experts_for(property_uuid)
        candidates = expert_candidates(designations)
        if not candidates:
            return None
        away = await absent_advisor_ids(
            self._session,
            organization_id,
            moment,
            among=[advisor_id for advisor_id, _ in candidates],
        )
        for advisor_id, _role in candidates:
            if advisor_id in away:
                continue
            member = await self._session.get(OrganizationMember, advisor_id)
            if member is not None and member.active and member.advises:
                return member
        return None

    # -- Internals ---------------------------------------------------------

    async def _advisor_for(self, query: SlotQuery) -> OrganizationMember | None:
        if query.advisor_id is not None:
            member = await self._session.get(OrganizationMember, query.advisor_id)
            if member is None or member.organization_id != query.organization_id:
                return None
            return member
        if query.property_uuid is None:
            return None
        return await self.present_expert(
            query.organization_id, query.property_uuid, query.moment
        )

    async def _absence_intervals(
        self, advisor_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[Interval]:
        """Declared absences overlapping the window, as busy time."""
        rows = await self._session.scalars(
            select(AdvisorAbsence)
            .where(AdvisorAbsence.advisor_id == advisor_id)
            .where(AdvisorAbsence.cancelled_at.is_(None))
            .where(AdvisorAbsence.ends_at > start)
            .where(AdvisorAbsence.starts_at < end)
        )
        return [Interval(start=row.starts_at, end=row.ends_at) for row in rows]

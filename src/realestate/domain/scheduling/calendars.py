"""Reaching one Advisor's authoritative calendar — or knowing there is not one.

The port is the shape :class:`~realestate.channels.google.calendar.GoogleCalendar`
already has, so the real adapter is that class with a per-Advisor calendar id and
the test adapter is a dictionary of stubs. No *caller* names a provider: every
one of them depends on :class:`CalendarPort` and on ``for_advisor`` returning
``None``. The Google directory below is the one place the provider is named, and
it is the only thing that would be replaced to run on another calendar.

The interesting method is the one that returns ``None``. An Advisor whose
``calendar_id`` is unset has no authoritative availability, and every caller has
to treat that as a refusal rather than as an empty calendar. Stage 0's single
global calendar made that impossible to express: an unconfigured integration and
a genuinely free week looked identical, and the difference is whether Product may
promise a visit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol, runtime_checkable

from realestate.channels.google.calendar import BusyResult, EventResult, GoogleCalendar
from realestate.db.models import OrganizationMember
from realestate.domain.availability import Interval

logger = logging.getLogger(__name__)


@runtime_checkable
class CalendarPort(Protocol):
    """What the domain needs from a calendar. Conclusive or inconclusive, never
    an exception: the difference between "rejected" and "we do not know" decides
    whether an appointment may be called Confirmed (P-042)."""

    async def busy_between(self, start: datetime, end: datetime) -> BusyResult: ...

    async def is_free(self, slot: Interval) -> BusyResult: ...

    async def create_event(
        self,
        *,
        slot: Interval,
        summary: str,
        description: str,
        reference: str,
        location: str | None = None,
    ) -> EventResult: ...

    async def find_by_reference(self, reference: str) -> EventResult: ...

    async def delete_event(self, event_id: str) -> EventResult: ...


class CalendarDirectory(Protocol):
    """The calendars of the Organization's Advisors."""

    def for_calendar_id(self, calendar_id: str) -> CalendarPort | None:
        """The calendar with this id, or ``None`` when it cannot be reached."""

    def for_advisor(self, advisor: OrganizationMember) -> CalendarPort | None:
        """This Advisor's authoritative calendar, or ``None`` when unconfigured."""


class GoogleCalendarDirectory:
    """Google Calendar, one calendar per Advisor.

    One service-account credential reaches every calendar the Organization has
    shared with it, so the credential is directory-wide and the calendar id is
    per Advisor. Clients are cached because building one reads a key file from
    disk, and availability is queried on nearly every conversational turn.
    """

    def __init__(self, credentials_path: str) -> None:
        self._credentials_path = credentials_path
        self._clients: dict[str, GoogleCalendar] = {}

    @property
    def configured(self) -> bool:
        return bool(self._credentials_path)

    def for_calendar_id(self, calendar_id: str) -> CalendarPort | None:
        if not calendar_id or not self._credentials_path:
            return None
        client = self._clients.get(calendar_id)
        if client is None:
            client = GoogleCalendar(
                credentials_path=self._credentials_path, calendar_id=calendar_id
            )
            self._clients[calendar_id] = client
        return client

    def for_advisor(self, advisor: OrganizationMember) -> CalendarPort | None:
        if not advisor.calendar_id:
            logger.info(
                "Advisor %s has no configured calendar; no availability is "
                "authoritative for them",
                advisor.login,
            )
            return None
        return self.for_calendar_id(advisor.calendar_id)

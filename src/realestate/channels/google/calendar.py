"""Google Calendar as the authoritative source of Broker availability (S-007).

The Deterministic Backend is the only component that touches Calendar; the Model
never receives create or delete authority (ADR-0009).

Every method returns a *conclusive or inconclusive* answer rather than raising,
because the difference matters: a conclusive rejection lets the Agent offer
another time, while an inconclusive result must become ``NeedsReview`` instead of
either a confirmation or a blind retry (P-042).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from datetime import datetime
from enum import Enum

from realestate.domain.availability import Interval

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarOutcome(str, Enum):
    OK = "ok"
    CONFLICT = "conflict"
    FAILED = "failed"
    # May or may not have happened. Never retried blindly.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BusyResult:
    outcome: CalendarOutcome
    busy: list[Interval]
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is CalendarOutcome.OK


@dataclass(frozen=True)
class EventResult:
    outcome: CalendarOutcome
    event_id: str | None = None
    detail: str = ""
    start: datetime | None = None
    end: datetime | None = None
    summary: str | None = None


class GoogleCalendar:
    def __init__(self, credentials_path: str, calendar_id: str) -> None:
        self._credentials_path = credentials_path
        self._calendar_id = calendar_id
        self._service = None

    @property
    def configured(self) -> bool:
        return bool(self._credentials_path and self._calendar_id)

    def _client(self) -> Any:
        """The Google client, typed as ``Any`` on purpose.

        ``googleapiclient`` ships neither stubs nor a ``py.typed`` marker, so its
        dynamically built service object cannot be described. Confining that to
        this one accessor keeps the untyped surface at the boundary: every value
        taken from it is narrowed before it leaves this module.
        """
        if self._service is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                self._credentials_path, scopes=SCOPES
            )
            self._service = build(
                "calendar", "v3", credentials=credentials, cache_discovery=False
            )
        return self._service

    async def check_health(self) -> dict[str, object]:
        if not self.configured:
            return {
                "status": "unconfigured",
                "detail": "GOOGLE_CALENDAR_CREDENTIALS / GOOGLE_CALENDAR_ID are not set.",
            }

        def probe() -> str:
            calendar = self._client().calendars().get(calendarId=self._calendar_id).execute()
            return f"{calendar.get('summary')} ({calendar.get('timeZone')})"

        try:
            return {"status": "ok", "detail": await asyncio.to_thread(probe)}
        except Exception as exc:  # noqa: BLE001
            return {"status": "invalid", "detail": f"{type(exc).__name__}: {exc}"}

    async def busy_between(self, start: datetime, end: datetime) -> BusyResult:
        """Busy intervals in [start, end). Anything on the calendar blocks."""
        if not self.configured:
            return BusyResult(
                CalendarOutcome.FAILED, [], "Google Calendar is not configured."
            )

        def query() -> list[Interval]:
            body = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": self._calendar_id}],
            }
            response = self._client().freebusy().query(body=body).execute()
            periods = response["calendars"][self._calendar_id].get("busy", [])
            return [
                Interval(
                    start=datetime.fromisoformat(p["start"]),
                    end=datetime.fromisoformat(p["end"]),
                )
                for p in periods
            ]

        try:
            return BusyResult(CalendarOutcome.OK, await asyncio.to_thread(query))
        except Exception as exc:  # noqa: BLE001
            # A failed read is never treated as "nothing is busy": that would
            # offer times the Broker is not actually free.
            logger.error("Calendar free/busy read failed: %s", exc)
            return BusyResult(CalendarOutcome.FAILED, [], f"{type(exc).__name__}: {exc}")

    async def is_free(self, slot: Interval) -> BusyResult:
        """Live recheck of one exact interval, immediately before booking (P-010)."""
        result = await self.busy_between(slot.start, slot.end)
        if not result.ok:
            return result
        if any(slot.overlaps(busy) for busy in result.busy):
            return BusyResult(CalendarOutcome.CONFLICT, result.busy)
        return result

    async def create_event(
        self,
        *,
        slot: Interval,
        summary: str,
        description: str,
        reference: str,
        location: str | None = None,
    ) -> EventResult:
        """Create the visit, carrying a deterministic reference to the attempt.

        The reference is stored as a private extended property so recovery can
        find the event again and reconcile the *same* attempt rather than booking
        a second time (P-042).
        """
        if not self.configured:
            return EventResult(CalendarOutcome.FAILED, detail="not configured")

        def insert() -> str:
            body = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": slot.start.isoformat()},
                "end": {"dateTime": slot.end.isoformat()},
                "extendedProperties": {"private": {"appointmentReference": reference}},
            }
            if location:
                body["location"] = location
            created = (
                self._client()
                .events()
                .insert(calendarId=self._calendar_id, body=body)
                .execute()
            )
            event_id = created["id"]
            return str(event_id)

        try:
            event_id = await asyncio.to_thread(insert)
        except Exception as exc:  # noqa: BLE001
            # This cannot distinguish "rejected" from "accepted but the answer
            # was lost", so it is inconclusive by construction. The caller turns
            # that into NeedsReview, never into a confirmation or a retry.
            logger.error("Calendar event creation was inconclusive: %s", exc)
            return EventResult(
                CalendarOutcome.UNKNOWN, detail=f"{type(exc).__name__}: {exc}"
            )
        return EventResult(CalendarOutcome.OK, event_id=event_id)

    async def find_by_reference(self, reference: str) -> EventResult:
        """Look for the event an attempt would have created, to reconcile it.

        ``OK`` with ``event_id=None`` is a *conclusive absence*; ``UNKNOWN`` means
        the question could not be answered and the attempt must stay ambiguous.
        """
        if not self.configured:
            return EventResult(CalendarOutcome.FAILED, detail="not configured")

        def search() -> dict[str, Any] | None:
            response = (
                self._client()
                .events()
                .list(
                    calendarId=self._calendar_id,
                    privateExtendedProperty=f"appointmentReference={reference}",
                    maxResults=2,
                )
                .execute()
            )
            items = response.get("items", [])
            if len(items) > 1:
                raise ValueError(
                    f"Calendar contains {len(items)} events for appointment {reference}"
                )
            return items[0] if items else None

        try:
            found = await asyncio.to_thread(search)
        except Exception as exc:  # noqa: BLE001
            return EventResult(
                CalendarOutcome.UNKNOWN, detail=f"{type(exc).__name__}: {exc}"
            )
        if found is None:
            return EventResult(CalendarOutcome.OK)
        try:
            start = datetime.fromisoformat(found["start"]["dateTime"])
            end = datetime.fromisoformat(found["end"]["dateTime"])
            event_id = str(found["id"])
        except (KeyError, TypeError, ValueError) as exc:
            return EventResult(
                CalendarOutcome.UNKNOWN,
                detail=f"Calendar event has an invalid shape: {type(exc).__name__}: {exc}",
            )
        return EventResult(
            CalendarOutcome.OK,
            event_id=event_id,
            start=start,
            end=end,
            summary=str(found.get("summary") or ""),
        )

    async def delete_event(self, event_id: str) -> EventResult:
        """Delete one known Calendar event.

        A missing event is a conclusive success for cancellation: the product's
        desired Calendar state is already true. Transport or API failures are
        inconclusive and must not be reported to the Lead as cancelled.
        """
        if not self.configured:
            return EventResult(CalendarOutcome.FAILED, detail="not configured")

        def delete() -> None:
            try:
                (
                    self._client()
                    .events()
                    .delete(calendarId=self._calendar_id, eventId=event_id)
                    .execute()
                )
            except Exception as exc:  # noqa: BLE001
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status in {404, 410}:
                    return
                raise

        try:
            await asyncio.to_thread(delete)
        except Exception as exc:  # noqa: BLE001
            logger.error("Calendar event deletion was inconclusive: %s", exc)
            return EventResult(
                CalendarOutcome.UNKNOWN, detail=f"{type(exc).__name__}: {exc}"
            )
        return EventResult(CalendarOutcome.OK, event_id=event_id)

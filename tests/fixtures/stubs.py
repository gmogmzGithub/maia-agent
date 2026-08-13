"""Test doubles for the three external transports, spelled once.

Calendar, WhatsApp, and Telegram are the boundaries every integration suite has
to replace, and each suite used to carry its own copy. They live here so a
change to one of those protocols is a single edit, and so two suites cannot
disagree about what a stubbed provider does.

The schedule constants live here for the same reason: the weekly spec below is
the production default from ``realestate.config``, and every appointment suite
needs the parsed form of it.
"""

from __future__ import annotations

from typing import NamedTuple
from zoneinfo import ZoneInfo

from realestate.channels.google.calendar import BusyResult, CalendarOutcome, EventResult
from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.domain.availability import Interval, WeeklySchedule

TIMEZONE = "America/Mexico_City"
ZONE = ZoneInfo(TIMEZONE)
SPEC = (
    "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
    "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
)
SCHEDULE = WeeklySchedule.parse(SPEC, TIMEZONE)


class SentText(NamedTuple):
    """One recorded WhatsApp send. Indexable, so ``sent[0][1]`` still reads."""

    to_wa_id: str
    body: str
    provider_message_id: str


class SentNotice(NamedTuple):
    """One recorded Telegram send."""

    chat_id: str
    body: str


class StubCalendar:
    """Answers each test controls; nothing here reaches Google.

    Default state is a conclusively empty calendar, which is what a suite that
    only needs booking to succeed wants. Append to ``busy`` to create conflicts.
    """

    def __init__(self) -> None:
        self.busy: list[Interval] = []
        self.created: list[str] = []
        self.deleted: list[str] = []

    async def busy_between(self, start, end) -> BusyResult:  # noqa: ANN001
        return BusyResult(CalendarOutcome.OK, list(self.busy))

    async def is_free(self, slot: Interval) -> BusyResult:
        result = await self.busy_between(slot.start, slot.end)
        if any(slot.overlaps(b) for b in result.busy):
            return BusyResult(CalendarOutcome.CONFLICT, result.busy)
        return result

    async def create_event(self, *, slot, summary, description, reference) -> EventResult:  # noqa: ANN001
        self.created.append(reference)
        return EventResult(CalendarOutcome.OK, event_id=f"evt-{reference}")

    async def find_by_reference(self, reference) -> EventResult:  # noqa: ANN001
        if reference in self.created:
            return EventResult(CalendarOutcome.OK, event_id=f"evt-{reference}")
        return EventResult(CalendarOutcome.OK)

    async def delete_event(self, event_id) -> EventResult:  # noqa: ANN001
        self.deleted.append(event_id)
        return EventResult(CalendarOutcome.OK, event_id=event_id)


class StubWhatsApp:
    """Accepts Product Outbox sends without contacting Meta."""

    def __init__(self) -> None:
        self.sent: list[SentText] = []

    async def send_text(self, to_wa_id: str, body: str) -> SendResult:
        provider_id = f"wamid.{len(self.sent) + 1}"
        self.sent.append(SentText(to_wa_id, body, provider_id))
        return SendResult(SendOutcome.SENT, provider_message_id=provider_id)


class StubTelegram:
    """Records every send; ``accepts`` decides whether Telegram takes them."""

    def __init__(self, *, accepts: bool = True) -> None:
        self.sent: list[SentNotice] = []
        self.accepts = accepts
        self.configured = True

    async def send_message(self, chat_id: str, text: str) -> bool:
        self.sent.append(SentNotice(chat_id, text))
        return self.accepts

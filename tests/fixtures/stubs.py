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


class SentTemplate(NamedTuple):
    """One recorded WhatsApp template send."""

    to_wa_id: str
    template_id: str
    language_code: str
    provider_message_id: str


class StubCalendar:
    """Answers each test controls; nothing here reaches Google.

    Default state is a conclusively empty calendar that accepts every booking,
    which is what a suite that only needs booking to succeed wants. The knobs
    cover what the others need: append to ``busy`` to create conflicts, set
    ``busy_outcome``/``create_outcome`` to make Google fail or answer
    inconclusively, read ``busy_reads`` to count availability queries, and set
    ``find_result`` to pin what a reference lookup reports.
    """

    def __init__(self) -> None:
        self.busy: list[Interval] = []
        self.busy_outcome = CalendarOutcome.OK
        self.create_outcome = CalendarOutcome.OK
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.busy_reads = 0
        self.find_reads = 0
        self.find_result: EventResult | None = None

    async def busy_between(self, start, end) -> BusyResult:  # noqa: ANN001
        self.busy_reads += 1
        if self.busy_outcome is not CalendarOutcome.OK:
            return BusyResult(self.busy_outcome, [], "stubbed failure")
        return BusyResult(CalendarOutcome.OK, list(self.busy))

    async def is_free(self, slot: Interval) -> BusyResult:
        result = await self.busy_between(slot.start, slot.end)
        if not result.ok:
            return result
        if any(slot.overlaps(b) for b in result.busy):
            return BusyResult(CalendarOutcome.CONFLICT, result.busy)
        return result

    async def create_event(
        self, *, slot, summary, description, reference, location=None
    ) -> EventResult:  # noqa: ANN001
        if self.create_outcome is not CalendarOutcome.OK:
            return EventResult(self.create_outcome, detail="stubbed")
        self.created.append(reference)
        return EventResult(CalendarOutcome.OK, event_id=f"evt-{reference}")

    async def find_by_reference(self, reference) -> EventResult:  # noqa: ANN001
        self.find_reads += 1
        if self.find_result is not None:
            return self.find_result
        if reference in self.created:
            return EventResult(CalendarOutcome.OK, event_id=f"evt-{reference}")
        return EventResult(CalendarOutcome.OK)

    async def delete_event(self, event_id) -> EventResult:  # noqa: ANN001
        self.deleted.append(event_id)
        return EventResult(CalendarOutcome.OK, event_id=event_id)

    # -- Also a CalendarDirectory ------------------------------------------
    #
    # Stage 3 gave each Advisor their own calendar, so the domain takes a
    # directory rather than one client. A stub that answers both protocols is
    # the honest double for "one shared calendar": every Advisor resolves to the
    # same conclusive answers, which is what a suite that only cares about
    # booking wants. Use :class:`StubCalendarDirectory` when the point of the
    # test is that two Advisors have *different* calendars.

    def for_calendar_id(self, calendar_id):  # noqa: ANN001, ANN201
        return self

    def for_advisor(self, advisor):  # noqa: ANN001, ANN201
        # Absent configuration still means "no authoritative availability",
        # because that refusal is the behaviour under test in several suites.
        return self if advisor.calendar_id else None


class StubCalendarDirectory:
    """One calendar per Advisor, for the suites where that difference matters.

    ``calendars`` is keyed by calendar id. An Advisor whose configured calendar
    is not in it resolves to ``None``, which is how "this Advisor has no
    authoritative availability" is set up.
    """

    def __init__(self, calendars: dict[str, StubCalendar] | None = None) -> None:
        self.calendars: dict[str, StubCalendar] = calendars or {}

    def add(self, calendar_id: str) -> StubCalendar:
        calendar = StubCalendar()
        self.calendars[calendar_id] = calendar
        return calendar

    def for_calendar_id(self, calendar_id: str) -> StubCalendar | None:
        return self.calendars.get(calendar_id)

    def for_advisor(self, advisor):  # noqa: ANN001, ANN201
        if not advisor.calendar_id:
            return None
        return self.calendars.get(advisor.calendar_id)


class StubWhatsApp:
    """Accepts Product Outbox sends without contacting Meta.

    ``result`` pins the answer Meta gives, for the suites that need a failure or
    an inconclusive send; the default accepts each send with a fresh id.
    """

    def __init__(self, result: SendResult | None = None) -> None:
        self.sent: list[SentText] = []
        self.sent_templates: list[SentTemplate] = []
        self._result = result

    async def send_text(self, to_wa_id: str, body: str) -> SendResult:
        result = self._result or SendResult(
            SendOutcome.SENT, provider_message_id=f"wamid.{len(self.sent) + 1}"
        )
        self.sent.append(SentText(to_wa_id, body, result.provider_message_id or ""))
        return result

    async def send_template(
        self, to_wa_id: str, template_id: str, language_code: str
    ) -> SendResult:
        result = self._result or SendResult(
            SendOutcome.SENT,
            provider_message_id=f"wamid.template.{len(self.sent_templates) + 1}",
        )
        self.sent_templates.append(
            SentTemplate(
                to_wa_id,
                template_id,
                language_code,
                result.provider_message_id or "",
            )
        )
        return result


class StubTelegram:
    """Records every send; ``accepts`` decides whether Telegram takes them."""

    def __init__(self, *, accepts: bool = True) -> None:
        self.sent: list[SentNotice] = []
        self.accepts = accepts
        self.configured = True

    async def send_message(self, chat_id: str, text: str) -> bool:
        self.sent.append(SentNotice(chat_id, text))
        return self.accepts

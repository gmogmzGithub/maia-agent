"""Google Calendar, the authoritative source of Broker availability (S-007).

The behaviour worth pinning here is not the Google client library — it is the
*conclusiveness* of each answer. Every method returns rather than raises, and
the difference between a conclusive rejection and an inconclusive one decides
whether the Agent may offer another time, must say nothing, or must escalate to
``NeedsReview`` (P-042).

The service object is replaced with a recording fake, so these run without a
credential and without touching a real calendar. What they assert is the exact
request shape the Backend sends and the outcome each Google answer produces.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from realestate.channels.google.calendar import (
    SCOPES,
    CalendarOutcome,
    GoogleCalendar,
)
from realestate.domain.availability import Interval

CALENDAR_ID = "broker@example.com"


class FakeExecutable:
    """The ``.execute()`` tail of every Google API call."""

    def __init__(self, result: object, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self) -> object:
        if self._error is not None:
            raise self._error
        return self._result


class FakeResource:
    """One Google API collection: records its kwargs, replays a scripted answer."""

    def __init__(self, owner: "FakeService", name: str) -> None:
        self._owner = owner
        self._name = name

    def _record(self, verb: str, **kwargs: object) -> FakeExecutable:
        self._owner.calls.append((f"{self._name}.{verb}", kwargs))
        answer = self._owner.answers.get(f"{self._name}.{verb}")
        if isinstance(answer, Exception):
            return FakeExecutable(None, error=answer)
        return FakeExecutable(answer)

    def get(self, **kwargs: object) -> FakeExecutable:
        return self._record("get", **kwargs)

    def query(self, **kwargs: object) -> FakeExecutable:
        return self._record("query", **kwargs)

    def insert(self, **kwargs: object) -> FakeExecutable:
        return self._record("insert", **kwargs)

    def list(self, **kwargs: object) -> FakeExecutable:
        return self._record("list", **kwargs)


class FakeService:
    def __init__(self, **answers: object) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def calendars(self) -> FakeResource:
        return FakeResource(self, "calendars")

    def freebusy(self) -> FakeResource:
        return FakeResource(self, "freebusy")

    def events(self) -> FakeResource:
        return FakeResource(self, "events")


def calendar(**answers: object) -> tuple[GoogleCalendar, FakeService]:
    client = GoogleCalendar(credentials_path="/tmp/creds.json", calendar_id=CALENDAR_ID)
    service = FakeService(**answers)
    client._service = service
    return client, service


def unconfigured(credentials: str = "", calendar_id: str = "") -> GoogleCalendar:
    return GoogleCalendar(credentials_path=credentials, calendar_id=calendar_id)


START = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
END = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def slot(hour: int, minutes: int = 60) -> Interval:
    start = datetime(2026, 8, 10, hour, 0, tzinfo=UTC)
    return Interval(start=start, end=start + timedelta(minutes=minutes))


def busy(start_hour: int, end_hour: int) -> dict[str, str]:
    return {
        "start": datetime(2026, 8, 10, start_hour, 0, tzinfo=UTC).isoformat(),
        "end": datetime(2026, 8, 10, end_hour, 0, tzinfo=UTC).isoformat(),
    }


def free_busy(*periods: dict[str, str]) -> dict:
    return {"calendars": {CALENDAR_ID: {"busy": list(periods)}}}


# -- Configuration ------------------------------------------------------------


@pytest.mark.parametrize(
    ("credentials", "calendar_id", "expected"),
    [
        ("/tmp/creds.json", CALENDAR_ID, True),
        ("", CALENDAR_ID, False),
        ("/tmp/creds.json", "", False),
        ("", "", False),
    ],
)
def test_both_halves_of_the_credential_are_required(
    credentials: str, calendar_id: str, expected: bool
) -> None:
    assert unconfigured(credentials, calendar_id).configured is expected


async def test_an_unconfigured_calendar_reports_itself_rather_than_failing_health() -> None:
    report = await unconfigured().check_health()

    assert report["status"] == "unconfigured"
    assert "GOOGLE_CALENDAR_CREDENTIALS" in report["detail"]


async def test_an_unconfigured_read_is_a_failure_never_an_empty_calendar() -> None:
    """"Nothing is busy" would offer times the Broker is not actually free."""
    result = await unconfigured().busy_between(START, END)

    assert result.outcome is CalendarOutcome.FAILED
    assert result.busy == []
    assert not result.ok


async def test_an_unconfigured_write_is_a_conclusive_failure_not_an_unknown() -> None:
    # Nothing left the process, so this cannot have half-happened. Reporting it
    # as UNKNOWN would send a bookable attempt to NeedsReview for no reason.
    result = await unconfigured().create_event(
        slot=slot(10), summary="s", description="d", reference="ref-1"
    )

    assert result.outcome is CalendarOutcome.FAILED
    assert result.event_id is None


async def test_an_unconfigured_reconciliation_lookup_is_a_failure() -> None:
    result = await unconfigured().find_by_reference("ref-1")

    assert result.outcome is CalendarOutcome.FAILED


# -- Building the service -----------------------------------------------------


def test_the_service_is_built_once_from_the_service_account_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One authenticated client per process, and the calendar scope it needs."""
    import sys
    import types

    seen: dict[str, object] = {}
    built = FakeService()

    service_account = types.SimpleNamespace(
        Credentials=types.SimpleNamespace(
            from_service_account_file=lambda path, scopes: seen.update(
                path=path, scopes=scopes
            )
            or "credentials-object"
        )
    )

    def build(name: str, version: str, credentials: object, cache_discovery: bool):  # noqa: ANN202
        seen.update(name=name, version=version, credentials=credentials)
        return built

    monkeypatch.setitem(
        sys.modules, "google.oauth2", types.ModuleType("google.oauth2")
    )
    monkeypatch.setitem(
        sys.modules, "google.oauth2.service_account", service_account
    )
    monkeypatch.setitem(
        sys.modules,
        "googleapiclient.discovery",
        types.SimpleNamespace(build=build),
    )

    client = GoogleCalendar(credentials_path="/tmp/creds.json", calendar_id=CALENDAR_ID)

    assert client._client() is built
    assert seen["path"] == "/tmp/creds.json"
    assert seen["scopes"] == SCOPES
    assert (seen["name"], seen["version"]) == ("calendar", "v3")
    # Second call reuses it rather than re-reading the credential from disk.
    assert client._client() is built
    assert seen["credentials"] == "credentials-object"


# -- Health -------------------------------------------------------------------


async def test_a_reachable_calendar_reports_its_name_and_zone() -> None:
    client, _ = calendar(
        **{"calendars.get": {"summary": "Visitas", "timeZone": "America/Mexico_City"}}
    )

    assert await client.check_health() == {
        "status": "ok",
        "detail": "Visitas (America/Mexico_City)",
    }


async def test_a_rejected_credential_is_reported_not_raised() -> None:
    """The probe is gathered with the others; an escape would fail all of /health."""
    client, _ = calendar(**{"calendars.get": PermissionError("insufficient scope")})

    report = await client.check_health()

    assert report["status"] == "invalid"
    assert "PermissionError" in report["detail"]


# -- Free/busy ----------------------------------------------------------------


async def test_the_free_busy_query_asks_only_about_the_broker_calendar() -> None:
    client, service = calendar(**{"freebusy.query": free_busy()})

    await client.busy_between(START, END)

    method, kwargs = service.calls[0]
    assert method == "freebusy.query"
    assert kwargs["body"] == {
        "timeMin": START.isoformat(),
        "timeMax": END.isoformat(),
        "items": [{"id": CALENDAR_ID}],
    }


async def test_busy_periods_come_back_as_intervals() -> None:
    client, _ = calendar(**{"freebusy.query": free_busy(busy(10, 11), busy(14, 15))})

    result = await client.busy_between(START, END)

    assert result.ok
    assert [(i.start.hour, i.end.hour) for i in result.busy] == [(10, 11), (14, 15)]


async def test_a_completely_free_calendar_is_a_conclusive_empty_list() -> None:
    client, _ = calendar(**{"freebusy.query": free_busy()})

    result = await client.busy_between(START, END)

    assert result.ok and result.busy == []


async def test_a_calendar_absent_from_the_response_is_not_treated_as_free() -> None:
    # A KeyError inside the worker thread must surface as FAILED, because an
    # empty busy list here would be read as "the whole horizon is offerable".
    client, _ = calendar(**{"freebusy.query": {"calendars": {}}})

    result = await client.busy_between(START, END)

    assert result.outcome is CalendarOutcome.FAILED
    assert "KeyError" in result.detail


async def test_a_failed_read_is_never_treated_as_nothing_is_busy() -> None:
    client, _ = calendar(**{"freebusy.query": TimeoutError("upstream timed out")})

    result = await client.busy_between(START, END)

    assert result.outcome is CalendarOutcome.FAILED
    assert result.busy == []
    assert "TimeoutError" in result.detail


# -- The live recheck before booking (P-010) ----------------------------------


async def test_a_free_slot_passes_the_live_recheck() -> None:
    client, _ = calendar(**{"freebusy.query": free_busy()})

    result = await client.is_free(slot(10))

    assert result.ok


async def test_an_overlapping_busy_interval_is_a_conflict() -> None:
    client, _ = calendar(**{"freebusy.query": free_busy(busy(10, 11))})

    result = await client.is_free(slot(10))

    assert result.outcome is CalendarOutcome.CONFLICT
    # The conflicting intervals travel with the verdict so the caller can
    # recompute and offer another time.
    assert len(result.busy) == 1


async def test_a_recheck_that_could_not_be_answered_stays_a_failure() -> None:
    """Not a conflict, and not a green light: the caller must not book on it."""
    client, _ = calendar(**{"freebusy.query": ConnectionError("no route")})

    result = await client.is_free(slot(10))

    assert result.outcome is CalendarOutcome.FAILED


async def test_a_busy_interval_that_only_touches_the_slot_is_not_a_conflict() -> None:
    # Half-open intervals: a visit ending at 11:00 does not collide with an
    # event starting at 11:00.
    client, _ = calendar(**{"freebusy.query": free_busy(busy(11, 12))})

    result = await client.is_free(slot(10))

    assert result.ok


# -- Creating the visit -------------------------------------------------------


async def test_the_created_event_carries_the_attempt_reference_privately() -> None:
    """Recovery finds the event again by this reference and reconciles the
    *same* attempt rather than booking a second time (P-042)."""
    client, service = calendar(**{"events.insert": {"id": "evt-1"}})

    result = await client.create_event(
        slot=slot(10),
        summary="Visita Casa Roble",
        description="Nombre: Cliente Demo",
        reference="apt-abc",
        location="Calle Privada 123, Zapopan",
    )

    assert result.outcome is CalendarOutcome.OK
    assert result.event_id == "evt-1"
    _, kwargs = service.calls[0]
    assert kwargs["calendarId"] == CALENDAR_ID
    body = kwargs["body"]
    assert body["extendedProperties"]["private"]["appointmentReference"] == "apt-abc"
    assert body["summary"] == "Visita Casa Roble"
    assert body["description"] == "Nombre: Cliente Demo"
    assert body["location"] == "Calle Privada 123, Zapopan"
    assert body["start"] == {"dateTime": slot(10).start.isoformat()}
    assert body["end"] == {"dateTime": slot(10).end.isoformat()}


async def test_a_failed_creation_is_inconclusive_by_construction() -> None:
    """It cannot distinguish "rejected" from "accepted but the answer was lost",
    so the caller turns this into NeedsReview — never a retry, never a
    confirmation."""
    client, _ = calendar(**{"events.insert": TimeoutError("gateway timeout")})

    result = await client.create_event(
        slot=slot(10), summary="s", description="d", reference="apt-abc"
    )

    assert result.outcome is CalendarOutcome.UNKNOWN
    assert result.event_id is None
    assert "TimeoutError" in result.detail


async def test_a_creation_answer_without_an_id_is_inconclusive_too() -> None:
    client, _ = calendar(**{"events.insert": {}})

    result = await client.create_event(
        slot=slot(10), summary="s", description="d", reference="apt-abc"
    )

    assert result.outcome is CalendarOutcome.UNKNOWN


# -- Reconciling an ambiguous attempt -----------------------------------------


async def test_the_reference_lookup_searches_the_private_property() -> None:
    client, service = calendar(
        **{
            "events.list": {
                "items": [
                    {
                        "id": "evt-9",
                        "summary": "Visita — Casa Roble — Cliente Demo",
                        "start": {"dateTime": "2026-08-10T10:00:00-06:00"},
                        "end": {"dateTime": "2026-08-10T11:30:00-06:00"},
                    }
                ]
            }
        }
    )

    result = await client.find_by_reference("apt-abc")

    assert (result.outcome, result.event_id) == (CalendarOutcome.OK, "evt-9")
    _, kwargs = service.calls[0]
    assert kwargs["privateExtendedProperty"] == "appointmentReference=apt-abc"
    assert kwargs["calendarId"] == CALENDAR_ID
    # Two is enough to answer "does it exist"; more would be wasted transfer.
    assert kwargs["maxResults"] == 2


async def test_no_matching_event_is_a_conclusive_absence() -> None:
    """OK with no id means the attempt definitely did not create an event."""
    client, _ = calendar(**{"events.list": {"items": []}})

    result = await client.find_by_reference("apt-abc")

    assert result.outcome is CalendarOutcome.OK
    assert result.event_id is None


async def test_a_missing_items_key_is_also_a_conclusive_absence() -> None:
    client, _ = calendar(**{"events.list": {}})

    result = await client.find_by_reference("apt-abc")

    assert (result.outcome, result.event_id) == (CalendarOutcome.OK, None)


async def test_an_unanswerable_lookup_leaves_the_attempt_ambiguous() -> None:
    client, _ = calendar(**{"events.list": ConnectionError("no route")})

    result = await client.find_by_reference("apt-abc")

    assert result.outcome is CalendarOutcome.UNKNOWN
    assert "ConnectionError" in result.detail

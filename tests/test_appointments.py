"""Availability snapshots and appointment booking (P-010, P-042, P-057…P-063).

Calendar is stubbed here so every branch is reachable, including the ones a real
calendar will not produce on demand — a slot going busy between offer and
booking, and an inconclusive create. Those two are the whole reason the attempt
is persisted before Calendar is touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from realestate.channels.google.calendar import BusyResult, CalendarOutcome, EventResult
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.db.engine import Database
from realestate.db.models import (
    Appointment,
    AppointmentStatus,
    AvailabilitySnapshot,
    Conversation,
    Lead,
    LeadEngagementCycle,
    Property,
    PropertyStatus,
    OutboxMessage,
)
from realestate.domain.appointments import AppointmentPolicy, AppointmentService
from realestate.domain.availability import Interval, WeeklySchedule
from realestate.domain.inbox import InboxService
from realestate.domain.properties import ArtifactStore, PropertyService
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import webhooks

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = requires_postgres

SPEC = (
    "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
    "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
)


class StubCalendar:
    """A calendar whose answers each test controls."""

    def __init__(self) -> None:
        self.busy: list[Interval] = []
        self.busy_outcome = CalendarOutcome.OK
        self.create_outcome = CalendarOutcome.OK
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.busy_reads = 0

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
        if reference in self.created:
            return EventResult(CalendarOutcome.OK, event_id=f"evt-{reference}")
        return EventResult(CalendarOutcome.OK)

    async def delete_event(self, event_id) -> EventResult:  # noqa: ANN001
        self.deleted.append(event_id)
        return EventResult(CalendarOutcome.OK, event_id=event_id)


def policy() -> AppointmentPolicy:
    return AppointmentPolicy(
        schedule=WeeklySchedule.parse(SPEC, "America/Mexico_City"),
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
    )


@pytest.fixture
async def booking(tmp_path: Path):
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        for model in (Appointment, AvailabilitySnapshot, Conversation,
                      LeadEngagementCycle, Lead, Property):
            await session.execute(delete(model))
        await session.commit()

    artifacts = ArtifactStore(tmp_path / "artifacts")
    async with database.session_scope() as session:
        await PropertyService(session, artifacts).accept_upload(
            "casa-roble.md", V1, actor_id="developer"
        )
        message = parse_webhook(
            webhooks.text_message(wamid="w-apt", body="hola")
        ).messages[0]
        await InboxService(session).accept(message)

    calendar = StubCalendar()

    async def service(session):  # noqa: ANN001
        return AppointmentService(session, calendar, policy())

    yield database, calendar, service
    await database.dispose()


async def conversation_of(database) -> Conversation:
    async with database.session_scope() as session:
        return (await session.execute(select(Conversation))).scalar_one()


async def offer(database, service, **filters) -> dict:
    async with database.session_scope() as session:
        conversation = await session.merge(await conversation_of(database))
        return await (await service(session)).available_slots(
            conversation=conversation, reference="casa-roble", **filters
        )


async def book(database, service, start: str, **kwargs) -> dict:
    async with database.session_scope() as session:
        conversation = await session.merge(await conversation_of(database))
        return await (await service(session)).book(
            conversation=conversation,
            reference="casa-roble",
            start=datetime.fromisoformat(start),
            **kwargs,
        )


async def cancel(database, service, **kwargs) -> dict:
    async with database.session_scope() as session:
        conversation = await session.merge(await conversation_of(database))
        return await (await service(session)).cancel(
            conversation=conversation,
            **kwargs,
        )


# --- Offering slots -----------------------------------------------------------


async def test_the_first_call_creates_a_snapshot_and_returns_candidates(booking) -> None:
    database, calendar, service = booking

    result = await offer(database, service)

    assert result["result"] == "available"
    assert result["property_id"] == "casa-roble"
    assert result["time_zone"] == "America/Mexico_City"
    assert 0 < len(result["candidates"]) <= 6
    assert calendar.busy_reads == 1

    async with database.session_scope() as session:
        assert (await session.execute(select(AvailabilitySnapshot))).scalar_one()


async def test_later_calls_filter_the_snapshot_without_reading_calendar(booking) -> None:
    # ADR-0011: Calendar is not polled on every conversational turn.
    database, calendar, service = booking
    await offer(database, service)

    await offer(database, service)
    await offer(database, service)

    assert calendar.busy_reads == 1


async def test_a_result_is_capped_at_six(booking) -> None:
    database, _, service = booking

    assert len((await offer(database, service))["candidates"]) == 6


async def test_busy_time_is_excluded_from_the_snapshot(booking) -> None:
    database, calendar, service = booking
    first = (await offer(database, service))["candidates"][0]
    busy_start = datetime.fromisoformat(first["start"])
    calendar.busy = [Interval(start=busy_start, end=busy_start + timedelta(hours=3))]

    async with database.session_scope() as session:
        await session.execute(delete(AvailabilitySnapshot))
        await session.commit()
    result = await offer(database, service)

    starts = [c["start"] for c in result["candidates"]]
    assert first["start"] not in starts


async def test_a_calendar_failure_never_becomes_an_empty_calendar(booking) -> None:
    # Falling back to "nothing is busy" would offer times the Broker is not free.
    database, calendar, service = booking
    calendar.busy_outcome = CalendarOutcome.FAILED

    result = await offer(database, service)

    assert result["result"] == "temporarily_unavailable"


async def test_an_inactive_property_offers_no_times(booking) -> None:
    database, _, service = booking
    async with database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.status = PropertyStatus.INACTIVE.value
        prop.inactive_reason = "Unspecified"
        await session.commit()

    assert (await offer(database, service))["result"] == "property_inactive"


async def test_an_unknown_property_is_not_found(booking) -> None:
    database, _, service = booking
    async with database.session_scope() as session:
        conversation = await session.merge(await conversation_of(database))
        result = await (await service(session)).available_slots(
            conversation=conversation, reference="casa-fantasma"
        )

    assert result["result"] == "not_found"


# --- Booking ------------------------------------------------------------------


async def test_booking_an_offered_candidate_confirms_it(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]

    result = await book(database, service, candidate["start"], attendee_name="Cliente Demo")

    assert result["result"] == "confirmed"
    assert result["appointment_reference"].startswith("APT-")
    assert result["property_name"] == "Casa Roble"
    assert len(calendar.created) == 1

    async with database.session_scope() as session:
        attempt = (await session.execute(select(Appointment))).scalar_one()
    assert attempt.status == AppointmentStatus.CONFIRMED.value
    assert attempt.calendar_event_id == f"evt-{attempt.reference}"
    assert attempt.attendee_name == "Cliente Demo"
    # 90 minutes, from trusted state rather than a model argument.
    assert attempt.ends_at - attempt.starts_at == timedelta(minutes=90)


async def test_the_calendar_event_carries_the_attempt_reference(booking) -> None:
    # P-042: recovery reconciles the same attempt instead of booking twice.
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]

    result = await book(database, service, candidate["start"])

    assert calendar.created == [result["appointment_reference"]]


async def test_a_time_that_was_never_offered_is_refused(booking) -> None:
    # The Model cannot invent a time, even a plausible one on the grid.
    database, calendar, service = booking
    await offer(database, service)

    result = await book(database, service, "2027-03-01T11:00:00-06:00")

    assert result["result"] == "invalid_candidate"
    assert calendar.created == []


async def test_booking_without_a_snapshot_is_refused(booking) -> None:
    database, _, service = booking
    candidate_start = "2026-08-10T09:00:00-06:00"

    assert (await book(database, service, candidate_start))["result"] == "invalid_candidate"


async def test_repeating_the_same_booking_returns_the_same_appointment(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]

    first = await book(database, service, candidate["start"])
    second = await book(database, service, candidate["start"])

    assert first == second
    # One attempt, one Calendar event.
    assert len(calendar.created) == 1
    async with database.session_scope() as session:
        assert len((await session.execute(select(Appointment))).scalars().all()) == 1


async def test_a_lead_can_cancel_their_confirmed_future_appointment(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    booked = await book(database, service, candidate["start"])

    result = await cancel(database, service)

    assert result["result"] == "cancelled"
    assert result["appointment_reference"] == booked["appointment_reference"]
    assert result["reschedule_prompt_required"] is True
    assert calendar.deleted == [f"evt-{booked['appointment_reference']}"]
    async with database.session_scope() as session:
        appointment = (await session.execute(select(Appointment))).scalar_one()
        assert appointment.status == AppointmentStatus.CANCELLED.value
        assert appointment.cancelled_at is not None
        assert appointment.calendar_event_id is None
        outbox = (await session.execute(select(OutboxMessage))).scalar_one()
        assert outbox.kind == "AppointmentCancellation"
        assert "quedó cancelada" in outbox.body
        assert "reagendar" in outbox.body


async def test_cancellation_without_a_future_confirmed_appointment_is_not_found(
    booking,
) -> None:
    database, _, service = booking

    assert await cancel(database, service) == {"result": "not_found"}


async def test_a_property_deactivated_after_the_offer_blocks_the_booking(booking) -> None:
    # Step 3 of the ordering: the live status recheck (P-063).
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    async with database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.status = PropertyStatus.INACTIVE.value
        prop.inactive_reason = "Unspecified"
        await session.commit()

    result = await book(database, service, candidate["start"])

    assert result["result"] == "property_inactive"
    assert calendar.created == []
    async with database.session_scope() as session:
        assert (await session.execute(select(Appointment))).scalars().all() == []


async def test_a_slot_taken_between_offer_and_booking_yields_alternatives(booking) -> None:
    # Step 4: the live exact-interval recheck (P-062).
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    taken = datetime.fromisoformat(candidate["start"])
    calendar.busy = [Interval(start=taken, end=taken + timedelta(minutes=90))]

    result = await book(database, service, candidate["start"])

    assert result["result"] == "slot_unavailable"
    assert calendar.created == []
    # Refreshed alternatives, and the lost slot is not among them.
    assert candidate["start"] not in [c["start"] for c in result["candidates"]]
    assert len(result["candidates"]) <= 6


async def test_a_conflict_replaces_the_stale_snapshot(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    taken = datetime.fromisoformat(candidate["start"])
    calendar.busy = [Interval(start=taken, end=taken + timedelta(minutes=90))]

    await book(database, service, candidate["start"])

    async with database.session_scope() as session:
        snapshot = (await session.execute(select(AvailabilitySnapshot))).scalar_one()
    assert candidate["start"] not in [s["start"] for s in snapshot.slots]


async def test_an_inconclusive_refresh_does_not_reuse_stale_candidates(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    taken = datetime.fromisoformat(candidate["start"])
    calendar.busy = [Interval(start=taken, end=taken + timedelta(minutes=90))]

    # The conflict is detected, then the refresh read itself fails.
    calls = {"n": 0}
    original = calendar.busy_between

    async def flaky(start, end):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] > 1:
            return BusyResult(CalendarOutcome.FAILED, [], "refresh failed")
        return await original(start, end)

    calendar.busy_between = flaky  # type: ignore[assignment]
    result = await book(database, service, candidate["start"])

    assert result["result"] == "temporarily_unavailable"
    assert "candidates" not in result


async def test_an_inconclusive_calendar_create_becomes_needs_review(booking) -> None:
    # P-042: neither a Confirmed Appointment nor an instruction to retry.
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    calendar.create_outcome = CalendarOutcome.UNKNOWN

    result = await book(database, service, candidate["start"])

    assert result["result"] == "needs_review"
    assert result["appointment_reference"].startswith("APT-")

    async with database.session_scope() as session:
        attempt = (await session.execute(select(Appointment))).scalar_one()
    # The attempt is persisted, so reconciliation has something to work with.
    assert attempt.status == AppointmentStatus.NEEDS_REVIEW.value
    assert attempt.calendar_event_id is None
    assert attempt.last_error


async def test_needs_review_is_not_retried_as_a_new_booking(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    calendar.create_outcome = CalendarOutcome.UNKNOWN
    await book(database, service, candidate["start"])

    calendar.create_outcome = CalendarOutcome.OK
    again = await book(database, service, candidate["start"])

    # Still NeedsReview, and no second event: only reconciliation may resolve it.
    assert again["result"] == "needs_review"
    assert calendar.created == []
    async with database.session_scope() as session:
        assert len((await session.execute(select(Appointment))).scalars().all()) == 1


async def test_an_expired_cycle_cannot_book(booking) -> None:
    database, calendar, service = booking
    candidate = (await offer(database, service))["candidates"][0]
    async with database.session_scope() as session:
        cycle = (await session.execute(select(LeadEngagementCycle))).scalar_one()
        cycle.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
        await session.commit()

    result = await book(database, service, candidate["start"])

    assert result["result"] == "conversation_expired"
    assert calendar.created == []


# --- The deterministic confirmation -------------------------------------------


def test_the_confirmation_is_rendered_from_persisted_state() -> None:
    from realestate.domain.appointments import confirmation_message

    message = confirmation_message(
        property_name="Casa Roble",
        starts_at=datetime.fromisoformat("2026-08-10T09:00:00-06:00"),
        schedule=WeeklySchedule.parse(SPEC, "America/Mexico_City"),
    )

    assert message == (
        "Tu cita para visitar Casa Roble quedó confirmada para el 10/08/2026 "
        "a las 09:00. Si necesitas cambiarla, responde a este mensaje."
    )


def test_private_visit_address_is_disclosed_in_the_confirmation() -> None:
    from realestate.domain.appointments import confirmation_message

    message = confirmation_message(
        property_name="Casa Roble",
        starts_at=datetime.fromisoformat("2026-08-10T09:00:00-06:00"),
        schedule=WeeklySchedule.parse(SPEC, "America/Mexico_City"),
        visit_address="Calle Privada 123, Zapopan",
    )

    assert "La dirección de la visita es: Calle Privada 123, Zapopan." in message


# --- Snapshots that can no longer be answered from ----------------------------


async def test_a_snapshot_past_its_horizon_is_not_usable(booking) -> None:
    """An expired horizon is replaced only on new explicit intent (P-058); until
    then a booking against it is an invalid candidate, not a stale confirmation."""
    database, _, service = booking
    start = (await offer(database, service))["candidates"][0]["start"]

    async with database.session_scope() as session:
        row = (await session.execute(select(AvailabilitySnapshot))).scalar_one()
        row.horizon_end = datetime.now(tz=UTC) - timedelta(minutes=1)
        await session.commit()

    result = await book(database, service, start)

    assert result == {"result": "invalid_candidate", "detail": "no current snapshot"}


async def test_a_calendar_that_cannot_be_read_at_booking_time_is_not_a_rejection(
    booking,
) -> None:
    """Not "slot unavailable" — the Agent must not tell the Lead the time is
    taken when nobody could check."""
    database, calendar, service = booking
    start = (await offer(database, service))["candidates"][0]["start"]
    calendar.busy_outcome = CalendarOutcome.FAILED

    result = await book(database, service, start)

    assert result["result"] == "temporarily_unavailable"
    assert result["detail"] == "stubbed failure"
    async with database.session_scope() as session:
        assert (await session.execute(select(Appointment))).scalars().all() == []


# --- Two workers booking the same slot ----------------------------------------


async def test_the_loser_of_an_idempotency_race_reports_the_winners_outcome(
    booking, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window between the key check and the insert is real but narrow, so it
    is opened deliberately here: another worker commits the same key first, and
    the loser must report that appointment rather than raise or book a second
    visit."""
    database, calendar, service = booking
    start = (await offer(database, service))["candidates"][0]["start"]

    original = AppointmentService._persist_attempt
    competitor: dict[str, str] = {}

    async def another_worker_wins_first(self, conversation, prop, slot, attendee_name):  # noqa: ANN001, ANN202
        async with database.session_scope() as other:
            row = Appointment(
                reference="APT-COMPETITOR",
                idempotency_key=(
                    f"apt:{conversation.id}:{prop.id}:{slot.start.isoformat()}"
                ),
                conversation_id=conversation.id,
                lead_id=conversation.lead_id,
                property_uuid=prop.id,
                starts_at=slot.start,
                ends_at=slot.end,
                status=AppointmentStatus.CONFIRMED.value,
            )
            other.add(row)
            await other.commit()
            competitor["reference"] = row.reference
        return await original(self, conversation, prop, slot, attendee_name)

    monkeypatch.setattr(
        AppointmentService, "_persist_attempt", another_worker_wins_first
    )

    result = await book(database, service, start)

    assert result["result"] == "confirmed"
    assert result["appointment_reference"] == competitor["reference"]
    async with database.session_scope() as session:
        rows = (await session.execute(select(Appointment))).scalars().all()
    assert len(rows) == 1
    # The loser never reached Calendar, so no second event was created.
    assert calendar.created == []


# --- Reporting an attempt in every state it can be in --------------------------


async def test_a_rejected_attempt_reads_as_slot_unavailable(booking) -> None:
    database, _, service = booking
    start = (await offer(database, service))["candidates"][0]["start"]
    await book(database, service, start)

    async with database.session_scope() as session:
        attempt = (await session.execute(select(Appointment))).scalar_one()
        attempt.status = AppointmentStatus.REJECTED.value
        await session.commit()

    result = await book(database, service, start)

    assert result == {
        "result": "slot_unavailable",
        "property_id": "casa-roble",
        "candidates": [],
    }


async def test_an_attempt_still_pending_reads_as_temporarily_unavailable(
    booking,
) -> None:
    """Pending means the Calendar answer has not landed. It is neither a
    confirmation nor a rejection, and the Model may call it neither."""
    database, _, service = booking
    start = (await offer(database, service))["candidates"][0]["start"]
    await book(database, service, start)

    async with database.session_scope() as session:
        attempt = (await session.execute(select(Appointment))).scalar_one()
        attempt.status = AppointmentStatus.PENDING.value
        await session.commit()

    assert await book(database, service, start) == {"result": "temporarily_unavailable"}

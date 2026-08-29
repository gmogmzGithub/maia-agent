"""Booking, rescheduling, cancelling and recording a visit (ADR-0037).

Calendar is stubbed so every branch is reachable, including the two a real
provider will not produce on demand: a slot going busy between the offer and the
booking, and an inconclusive write. Those are the whole reason the attempt is
persisted before Calendar is touched.

Four guarantees this suite exists to hold:

* nothing is Confirmed without an owner and an authoritative calendar;
* an inconclusive Calendar write becomes ``NeedsReview``, never a confirmation
  and never a blind retry;
* rescheduling secures the new slot first, so **every** failure path leaves the
  original Confirmed;
* cancelling decides nothing commercial.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.channels.google.calendar import CalendarOutcome, EventResult
from realestate.db.models import (
    AppointmentAttendance,
    AppointmentReminder,
    AppointmentStatus,
    AuditEvent,
    InternalAlert,
    InternalAlertKind,
    NextAction,
    NextActionKind,
    NextActionStatus,
    Opportunity,
    OpportunityStage,
    Organization,
    OutboxMessage,
    Property,
    PropertyExpertRole,
    PropertyStatus,
)
from realestate.domain.commercial.actors import NotAuthorized, NotFound
from realestate.domain.commercial.team import (
    DesignateExpert,
    StartAbsence,
    TeamAdministration,
)
from realestate.domain.commercial.organization import OrganizationDirectory
from realestate.domain.admin_work import AdminWorkService
from realestate.domain.administration import Administrator
from realestate.domain.scheduling.appointments import (
    BookVisit,
    CancelVisit,
    RecordVisitOutcome,
    Refusal,
    RescheduleVisit,
    VisitBooked,
    VisitCancelled,
    VisitOutcome,
    VisitRefused,
)
from realestate.domain.scheduling.reminders import (
    REMINDER_POLICY_ACTIVATED,
    AppointmentReminderKind,
    AppointmentReminders,
)
from tests.conftest import requires_postgres
from tests.fixtures.visits import key
from tests.fixtures import commercial, visits
from tests.fixtures.stubs import SCHEDULE

pytestmark = requires_postgres


async def a_conversation(  # noqa: ANN001, ANN202
    database,
    *,
    wamid="w-visit",
    body="Quiero ver la casa",
    from_wa_id="5213312345678",
):
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid=wamid, body=body, from_wa_id=from_wa_id
        )
        await session.commit()
        return conversation


async def book(database, built, conversation, *, start=None, **extra):  # noqa: ANN001, ANN003, ANN202
    async with database.session_scope() as session:
        moment = start or await visits.first_slot(built, session)
        actor = extra.pop("actor", built.product)
        return await built.visits(session).book(
            actor,
            BookVisit(
                conversation_id=conversation.id,
                property_uuid=built.property_uuid,
                start=moment,
                command_key=extra.pop("command_key", key("book")),
                attendee_name="Ana Demo",
                **extra,
            ),
        )


# -- Booking --------------------------------------------------------------


async def test_a_confirmed_visit_belongs_to_an_advisor_and_their_calendar(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)

    outcome = await book(database, built, conversation)

    assert isinstance(outcome, VisitBooked)
    assert outcome.confirmed
    assert outcome.advisor_id == built.advisor_id
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
    assert row is not None
    assert row.calendar_id == commercial.ADVISOR_CALENDAR_ID
    assert row.calendar_event_id is not None
    # The event went to that Advisor's calendar and nobody else's.
    assert built.calendar.created == [row.reference]
    assert built.second_calendar.created == []


async def test_booking_assigns_the_opportunity_and_owes_the_advisor_a_record(
    operation,
) -> None:
    """The Appointment Handoff: the visit exists, and so does the obligation to
    say what happened at it."""
    database, built = operation
    conversation = await a_conversation(database)

    outcome = await book(database, built, conversation)
    assert isinstance(outcome, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
        assert row is not None
        opportunity = await session.get(Opportunity, row.opportunity_id)
        action = await session.scalar(
            select(NextAction)
            .where(NextAction.opportunity_id == row.opportunity_id)
            .where(NextAction.status == NextActionStatus.PENDING.value)
        )

    assert opportunity is not None
    assert opportunity.responsible_advisor_id == built.advisor_id
    assert action is not None
    assert action.kind == NextActionKind.VISIT_FOLLOW_UP.value
    assert action.responsible_member_id == built.advisor_id
    assert action.due_at == row.ends_at


async def test_a_visit_with_no_eligible_advisor_is_refused(operation) -> None:
    """No Responsible Advisor, no visit. The Assignment Queue is the remedy."""
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        from realestate.domain.commercial.organization import DirectoryPlan

        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN, "developer"),
                advisors=(),
                default_advisor=None,
            )
        )

    outcome = await book(database, built, conversation, start=visits.now())

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason in (
        Refusal.NO_RESPONSIBLE_ADVISOR,
        Refusal.ADVISOR_INELIGIBLE,
    )
    async with database.session_scope() as session:
        assert list(await session.scalars(select(visits.Appointment))) == []


async def test_an_advisor_without_a_calendar_cannot_receive_a_visit(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        member = await session.get(visits.OrganizationMember, built.advisor_id)
        assert member is not None
        member.calendar_id = None
        await session.commit()

    outcome = await book(database, built, conversation, start=visits.now())

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.NO_AUTHORITATIVE_CALENDAR
    assert "no tiene calendario" in outcome.message


async def test_an_absent_advisor_cannot_receive_a_visit(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=start - timedelta(hours=1),
                ends_at=start + timedelta(days=1),
            ),
        )
        await session.commit()

    outcome = await book(database, built, conversation, start=start)

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason in (Refusal.ADVISOR_ABSENT, Refusal.SLOT_UNAVAILABLE)


async def test_an_inactive_property_creates_no_attempt(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)
        prop = await session.get(Property, built.property_uuid)
        assert prop is not None
        prop.status = PropertyStatus.INACTIVE.value
        await session.commit()

    outcome = await book(database, built, conversation, start=start)

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.PROPERTY_INACTIVE
    async with database.session_scope() as session:
        assert list(await session.scalars(select(visits.Appointment))) == []
    assert built.calendar.created == []


async def test_a_time_the_calendar_does_not_offer_is_refused(operation) -> None:
    """The Model cannot invent 10:17, and neither can an operator."""
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = (await visits.first_slot(built, session)) + timedelta(minutes=17)

    outcome = await book(database, built, conversation, start=start)

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.SLOT_UNAVAILABLE
    assert outcome.alternatives


async def test_a_slot_taken_between_offer_and_booking_yields_alternatives(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)
        from realestate.domain.availability import Interval

        built.calendar.busy.append(
            Interval(start=start, end=start + timedelta(minutes=90))
        )

    outcome = await book(database, built, conversation, start=start)

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.SLOT_UNAVAILABLE
    assert outcome.alternatives
    assert all(slot.start != start for slot in outcome.alternatives)


async def test_an_inconclusive_calendar_write_becomes_needs_review(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    built.calendar.create_outcome = CalendarOutcome.UNKNOWN

    outcome = await book(database, built, conversation)

    assert isinstance(outcome, VisitBooked)
    assert outcome.status is AppointmentStatus.NEEDS_REVIEW
    assert not outcome.confirmed
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
        alerts = list(
            await session.scalars(
                select(InternalAlert).where(
                    InternalAlert.kind
                    == InternalAlertKind.APPOINTMENT_ADVISOR_REVIEW.value
                )
            )
        )
        reminders = list(await session.scalars(select(AppointmentReminder)))

    assert row is not None
    assert row.last_error
    # The attempt is durable, so recovery reconciles *this* one rather than
    # booking a second visit.
    assert row.status == AppointmentStatus.NEEDS_REVIEW.value
    # Somebody is told, and nothing about the visit is promised.
    assert len(alerts) == 1
    assert alerts[0].recipient_member_id == built.advisor_id
    assert reminders == []


async def test_needs_review_is_not_retried_as_a_new_booking(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)

    first = await book(database, built, conversation, start=start)
    built.calendar.create_outcome = CalendarOutcome.OK
    second = await book(database, built, conversation, start=start)

    assert isinstance(first, VisitBooked)
    assert isinstance(second, VisitBooked)
    assert second.appointment_id == first.appointment_id
    assert second.status is AppointmentStatus.NEEDS_REVIEW
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(visits.Appointment)))
    assert len(rows) == 1


async def test_booking_the_same_slot_twice_returns_the_same_visit(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)

    first = await book(database, built, conversation, start=start)
    second = await book(database, built, conversation, start=start)

    assert isinstance(first, VisitBooked)
    assert isinstance(second, VisitBooked)
    assert first.appointment_id == second.appointment_id
    assert second.created is False
    assert len(built.calendar.created) == 1


async def test_two_conversations_cannot_claim_the_same_advisor_slot(
    operation,
) -> None:
    """Product remains the arbiter even if Calendar has not reflected the event."""
    database, built = operation
    first_conversation = await a_conversation(
        database, wamid="w-slot-first", from_wa_id="5213311110001"
    )
    second_conversation = await a_conversation(
        database, wamid="w-slot-second", from_wa_id="5213311110002"
    )
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)

    first = await book(database, built, first_conversation, start=start)
    second = await book(database, built, second_conversation, start=start)

    assert isinstance(first, VisitBooked)
    assert isinstance(second, VisitRefused)
    assert second.reason is Refusal.SLOT_UNAVAILABLE
    assert len(built.calendar.created) == 1


async def test_concurrent_bookings_leave_exactly_one_slot_authority(
    operation,
) -> None:
    database, built = operation
    first_conversation = await a_conversation(
        database, wamid="w-slot-race-first", from_wa_id="5213311111001"
    )
    second_conversation = await a_conversation(
        database, wamid="w-slot-race-second", from_wa_id="5213311111002"
    )
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)

    original_busy = built.calendar.busy_between
    both_reading = asyncio.Event()
    readers = 0

    async def synchronized_busy(range_start, range_end):  # noqa: ANN001, ANN202
        nonlocal readers
        readers += 1
        if readers == 2:
            both_reading.set()
        await both_reading.wait()
        return await original_busy(range_start, range_end)

    built.calendar.busy_between = synchronized_busy  # type: ignore[method-assign]

    first, second = await asyncio.gather(
        book(database, built, first_conversation, start=start),
        book(database, built, second_conversation, start=start),
    )

    assert sum(isinstance(result, VisitBooked) for result in (first, second)) == 1
    refused = next(
        result for result in (first, second) if isinstance(result, VisitRefused)
    )
    assert refused.reason is Refusal.SLOT_UNAVAILABLE
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(visits.Appointment)))
    assert len(rows) == 1


async def test_an_explicit_conducting_expert_uses_their_calendar(operation) -> None:
    """ADR-0037: somebody other than the owner conducts a visit only when that
    is made explicit — and then it is *their* calendar that must be free."""
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()
        start = await visits.first_slot(
            built, session, advisor_id=built.second_advisor_id
        )

    outcome = await book(
        database,
        built,
        conversation,
        start=start,
        conducting_advisor_id=built.second_advisor_id,
    )

    assert isinstance(outcome, VisitBooked)
    assert outcome.confirmed
    assert outcome.conducting_advisor_id == built.second_advisor_id
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
    assert row is not None
    # Owner and conductor are different recorded facts.
    assert row.advisor_id == built.advisor_id
    assert row.calendar_id == commercial.SECOND_ADVISOR_CALENDAR_ID
    assert built.second_calendar.created == [row.reference]
    assert built.calendar.created == []


async def test_a_different_conductor_must_be_a_property_expert(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(
            built, session, advisor_id=built.second_advisor_id
        )

    outcome = await book(
        database,
        built,
        conversation,
        start=start,
        conducting_advisor_id=built.second_advisor_id,
    )

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.CONDUCTOR_NOT_EXPERT
    assert built.second_calendar.created == []


# -- Reminders ------------------------------------------------------------


async def test_confirming_a_visit_schedules_two_deterministic_reminders(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    outcome = await book(database, built, conversation)
    assert isinstance(outcome, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
        assert row is not None
        reminders = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).for_appointment(row.id)

    kinds = {reminder.kind for reminder in reminders}
    assert kinds == {
        AppointmentReminderKind.DAY_BEFORE.value,
        AppointmentReminderKind.DAY_OF.value,
    }
    day_before = next(
        r for r in reminders if r.kind == AppointmentReminderKind.DAY_BEFORE.value
    )
    assert row.starts_at - day_before.due_at == timedelta(hours=24)


async def test_a_due_reminder_is_withheld_while_the_policy_is_unvalidated(
    operation,
) -> None:
    """SAN-036 is unanswered, so the schedule exists and dispatch does not.

    Settled rather than left pending: a reminder the worker re-examines forever
    is a queue that never drains.
    """
    assert REMINDER_POLICY_ACTIVATED is False
    database, built = operation
    conversation = await a_conversation(database)
    outcome = await book(database, built, conversation)
    assert isinstance(outcome, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
        assert row is not None
        # Both deterministic reminders are due immediately before the visit;
        # one hour before a 09:30 visit is still before the 09:00 day-of due.
        moment = row.starts_at - timedelta(seconds=1)
        outcomes = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).settle_due(moment)

    assert outcomes.get("PolicyNotValidated")
    async with database.session_scope() as session:
        reminders = list(await session.scalars(select(AppointmentReminder)))
        staged = [
            row.kind
            for row in await session.scalars(select(OutboxMessage))
        ]
        withheld = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "WithholdAppointmentReminder"
                )
            )
        )

    assert all(reminder.settled_at is not None for reminder in reminders)
    assert "AppointmentReminder" not in staged
    assert withheld


async def test_a_reminder_for_a_visit_that_already_started_is_retired(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    outcome = await book(database, built, conversation)
    assert isinstance(outcome, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, outcome.appointment_id)
        assert row is not None
        outcomes = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).settle_due(row.starts_at + timedelta(minutes=5))

    assert outcomes.get("VisitAlreadyStarted")


# -- Rescheduling ---------------------------------------------------------


async def test_rescheduling_secures_the_new_slot_then_releases_the_old(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = found.slots[2].start  # type: ignore[union-attr]

    async with database.session_scope() as session:
        moved = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(moved, VisitBooked)
    assert moved.confirmed
    assert moved.appointment_id != original.appointment_id
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
        new = await session.get(visits.Appointment, moved.appointment_id)

    assert old is not None and new is not None
    assert old.status == AppointmentStatus.RESCHEDULED.value
    assert old.rescheduled_to_id == new.id
    assert new.rescheduled_from_id == old.id
    assert new.starts_at == new_start
    assert new.advisor_id == old.advisor_id
    # The old event was released only after the new one existed.
    assert built.calendar.created == [old.reference, new.reference]
    assert built.calendar.deleted == [f"evt-{old.reference}"]


async def test_a_failed_new_booking_preserves_the_original_visit(operation) -> None:
    """The ADR-0037 guarantee, attacked directly."""
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = found.slots[2].start  # type: ignore[union-attr]

    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.INCONCLUSIVE
    assert refused.appointment_id == original.appointment_id
    assert "sigue en pie" in refused.message

    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
        rows = list(await session.scalars(select(visits.Appointment)))
        audits = [
            row.action
            for row in await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "RescheduleVisitFailed"
                )
            )
        ]

    assert old is not None
    # Untouched: still Confirmed, still on the calendar.
    assert old.status == AppointmentStatus.CONFIRMED.value
    assert old.calendar_event_id is not None
    assert built.calendar.deleted == []
    # The failed successor is visible as review work rather than deleted.
    assert len(rows) == 2
    assert audits == ["RescheduleVisitFailed"]


async def test_an_ambiguous_reschedule_blocks_a_competing_replacement(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        first_start = found.slots[0].start  # type: ignore[union-attr]
        second_start = next(  # type: ignore[union-attr]
            slot.start
            for slot in found.slots
            if slot.start >= first_start + timedelta(minutes=90)
        )

    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    async with database.session_scope() as session:
        first = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=first_start,
                command_key=key("ambiguous-reschedule"),
            ),
        )
    assert isinstance(first, VisitRefused)
    assert first.reason is Refusal.INCONCLUSIVE

    built.calendar.create_outcome = CalendarOutcome.OK
    async with database.session_scope() as session:
        second = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=second_start,
                command_key=key("competing-reschedule"),
            ),
        )

    assert isinstance(second, VisitRefused)
    assert second.reason is Refusal.INCONCLUSIVE
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
        rows = list(await session.scalars(select(visits.Appointment)))
    assert old is not None
    assert old.status == AppointmentStatus.CONFIRMED.value
    assert len(rows) == 2


async def test_an_ambiguous_reschedule_blocks_cancelling_the_original(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)
    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = found.slots[0].start  # type: ignore[union-attr]

    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    async with database.session_scope() as session:
        moved = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("ambiguous-before-cancel"),
            ),
        )
    assert isinstance(moved, VisitRefused)
    assert moved.reason is Refusal.INCONCLUSIVE

    async with database.session_scope() as session:
        cancelled = await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=original.appointment_id,
                command_key=key("cancel-with-ambiguous-successor"),
            ),
        )

    assert isinstance(cancelled, VisitRefused)
    assert cancelled.reason is Refusal.INCONCLUSIVE
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
    assert old is not None
    assert old.status == AppointmentStatus.CONFIRMED.value


async def test_reconciling_a_reschedule_releases_and_links_the_original(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)
    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = found.slots[0].start  # type: ignore[union-attr]

    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    async with database.session_scope() as session:
        moved = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reconcile-reschedule"),
            ),
        )
    assert isinstance(moved, VisitRefused)

    async with database.session_scope() as session:
        replacement = await session.scalar(
            select(visits.Appointment).where(
                visits.Appointment.rescheduled_from_id == original.appointment_id
            )
        )
    assert replacement is not None
    built.calendar.find_result = EventResult(
        CalendarOutcome.OK,
        event_id=f"evt-{replacement.reference}",
        start=replacement.starts_at,
        end=replacement.ends_at,
        summary="Visita — Casa Roble — Ana Demo",
    )

    async with database.session_scope() as session:
        result = await AdminWorkService(
            session, built.calendars, SCHEDULE, day_of_reminder_hour=9
        ).resolve(
            replacement.reference,
            "Confirm",
            Administrator(
                organization_id=built.admin.organization_id,
                actor_id="telegram:admin",
                origin_message_id="update:reschedule",
            ),
        )

    assert result["result"] == "resolved"
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
        confirmed = await session.get(visits.Appointment, replacement.id)
    assert old is not None and confirmed is not None
    assert old.status == AppointmentStatus.RESCHEDULED.value
    assert old.rescheduled_to_id == confirmed.id
    assert confirmed.status == AppointmentStatus.CONFIRMED.value
    assert f"evt-{original.reference}" in built.calendar.deleted


async def test_reconciling_a_booking_completes_the_appointment_handoff(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    attempt = await book(database, built, conversation)
    assert isinstance(attempt, VisitBooked)
    assert not attempt.confirmed

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, attempt.appointment_id)
    assert row is not None
    built.calendar.find_result = EventResult(
        CalendarOutcome.OK,
        event_id=f"evt-{row.reference}",
        start=row.starts_at,
        end=row.ends_at,
        summary="Visita — Casa Roble — Ana Demo",
    )

    async with database.session_scope() as session:
        result = await AdminWorkService(
            session, built.calendars, SCHEDULE, day_of_reminder_hour=9
        ).resolve(
            row.reference,
            "Confirm",
            Administrator(
                organization_id=built.admin.organization_id,
                actor_id="telegram:admin",
                origin_message_id="update:booking",
            ),
        )

    assert result["result"] == "resolved"
    async with database.session_scope() as session:
        reminders = list(
            await session.scalars(
                select(AppointmentReminder).where(
                    AppointmentReminder.appointment_id == row.id
                )
            )
        )
        follow_up = await session.scalar(
            select(NextAction).where(
                NextAction.kind == NextActionKind.VISIT_FOLLOW_UP.value
            )
        )
    assert len(reminders) == 2
    assert follow_up is not None
    assert follow_up.responsible_member_id == row.advisor_id


async def test_rescheduling_to_a_taken_slot_changes_nothing(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=original.starts_at + timedelta(minutes=7),
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.SLOT_UNAVAILABLE
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
    assert old is not None
    assert old.status == AppointmentStatus.CONFIRMED.value


async def test_rescheduling_the_same_move_twice_is_idempotent(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = found.slots[3].start  # type: ignore[union-attr]

    async with database.session_scope() as session:
        first = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reschedule"),
            ),
        )
    async with database.session_scope() as session:
        second = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(first, VisitBooked)
    # The original is no longer Confirmed, so a repeat is refused rather than
    # producing a third row.
    assert isinstance(second, VisitRefused)
    assert second.reason is Refusal.NOT_CONFIRMED
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(visits.Appointment)))
    assert len(rows) == 2


async def test_a_past_visit_cannot_be_rescheduled(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, original.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=2)
        row.ends_at = visits.now() - timedelta(minutes=30)
        await session.commit()

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=visits.now() + timedelta(days=1),
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.ALREADY_STARTED


# -- Cancellation ---------------------------------------------------------


async def test_cancelling_removes_the_event_and_decides_nothing_commercial(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        stage_before = (
            await session.get(Opportunity, row.opportunity_id)
        ).stage  # type: ignore[union-attr]

    async with database.session_scope() as session:
        cancelled = await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )

    assert isinstance(cancelled, VisitCancelled)
    assert cancelled.reschedule_prompt_required
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        opportunity = await session.get(Opportunity, row.opportunity_id)
        audits = [
            event.details
            for event in await session.scalars(
                select(AuditEvent).where(AuditEvent.action == "CancelVisit")
            )
        ]

    assert row.status == AppointmentStatus.CANCELLED.value
    assert row.calendar_event_id is None
    assert built.calendar.deleted == [f"evt-{row.reference}"]
    assert opportunity is not None
    # Not Lost, not Dormant, not moved at all.
    assert opportunity.stage == stage_before
    assert opportunity.stage != OpportunityStage.LOST.value
    assert audits and audits[0]["opportunity_outcome_changed"] is False


async def test_an_inconclusive_delete_does_not_cancel_anything(operation) -> None:
    """Telling a Contact their visit is cancelled while the Advisor's calendar
    still shows it would send somebody to an empty house."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async def failing_delete(event_id):  # noqa: ANN001, ANN202
        from realestate.channels.google.calendar import EventResult

        return EventResult(CalendarOutcome.UNKNOWN, detail="stubbed outage")

    built.calendar.delete_event = failing_delete  # type: ignore[assignment]

    async with database.session_scope() as session:
        refused = await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.INCONCLUSIVE
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        staged = [
            message.kind for message in await session.scalars(select(OutboxMessage))
        ]
    assert row is not None
    assert row.status == AppointmentStatus.CONFIRMED.value
    assert "AppointmentCancellation" not in staged


async def test_cancelling_twice_is_idempotent(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        first = await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )
    async with database.session_scope() as session:
        second = await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )

    assert isinstance(first, VisitCancelled)
    assert isinstance(second, VisitCancelled)
    assert not second.contact_notified
    assert len(built.calendar.deleted) == 1


# -- After the visit ------------------------------------------------------


async def test_an_advisor_records_that_the_visit_happened(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=3)
        row.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()

    async with database.session_scope() as session:
        outcome = await built.visits(session).record_outcome(
            built.advisor,
            RecordVisitOutcome(
                appointment_id=booked.appointment_id,
                attendance=AppointmentAttendance.ATTENDED,
                command_key=key("outcome"),
                notes="Le gustó; pidió cotización.",
                next_action_kind=NextActionKind.CALL,
                next_action_due_at=visits.now() + timedelta(days=1),
            ),
        )
        await session.commit()

    assert isinstance(outcome, VisitOutcome)
    assert outcome.recorded
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        actions = list(
            await session.scalars(
                select(NextAction).where(
                    NextAction.opportunity_id == row.opportunity_id
                )
            )
        )

    assert row.attendance == AppointmentAttendance.ATTENDED.value
    assert row.attendance_recorded_by == built.advisor_id
    assert row.visit_outcome == "Le gustó; pidió cotización."
    # The follow-up obligation was discharged and the next one owed.
    by_kind = {action.kind: action for action in actions}
    assert by_kind[NextActionKind.VISIT_FOLLOW_UP.value].status == (
        NextActionStatus.COMPLETED.value
    )
    assert by_kind[NextActionKind.CALL.value].status == NextActionStatus.PENDING.value


async def test_a_missed_visit_authorises_a_rescheduling_invitation_only_explicitly(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=3)
        row.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()

    async with database.session_scope() as session:
        await built.visits(session).record_outcome(
            built.advisor,
            RecordVisitOutcome(
                appointment_id=booked.appointment_id,
                attendance=AppointmentAttendance.MISSED,
                command_key=key("outcome"),
                notes="No llegó y no contestó.",
            ),
        )
        await session.commit()
        row = await session.get(visits.Appointment, booked.appointment_id)

    assert row is not None
    assert row.attendance == AppointmentAttendance.MISSED.value
    # Silence is never permission (ADR-0037).
    assert row.reschedule_invitation_authorized is False
    # And no message went out on its own.
    async with database.session_scope() as session:
        staged = [
            message.kind for message in await session.scalars(select(OutboxMessage))
        ]
    assert all(kind != "LeadFollowUp" for kind in staged)


async def test_a_visit_that_has_not_happened_has_no_outcome_to_record(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        refused = await built.visits(session).record_outcome(
            built.advisor,
            RecordVisitOutcome(
                appointment_id=booked.appointment_id,
                attendance=AppointmentAttendance.ATTENDED,
                command_key=key("outcome"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.NOT_YET_HELD


async def test_product_may_not_record_a_visit_outcome(operation) -> None:
    """Product does not infer that a visit happened from the clock (SAN-038)."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=3)
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized):
            await built.visits(session).record_outcome(
                built.product,
                RecordVisitOutcome(
                    appointment_id=booked.appointment_id,
                    attendance=AppointmentAttendance.ATTENDED,
                    command_key=key("outcome"),
                ),
            )


async def test_recording_the_outcome_twice_records_it_once(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)
    command_key = key("outcome")

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=3)
        row.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()

    results = []
    for _ in range(2):
        async with database.session_scope() as session:
            results.append(
                await built.visits(session).record_outcome(
                    built.advisor,
                    RecordVisitOutcome(
                        appointment_id=booked.appointment_id,
                        attendance=AppointmentAttendance.ATTENDED,
                        command_key=command_key,
                    ),
                )
            )
            await session.commit()

    assert [item.recorded for item in results] == [True, False]  # type: ignore[union-attr]


# -- Visibility ----------------------------------------------------------


async def test_an_advisor_cannot_reach_another_advisors_visit(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await built.visits(session).visit(
                built.second_advisor, booked.appointment_id
            )


async def test_the_agenda_shows_visits_an_advisor_owns_or_conducts(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()
        start = await visits.first_slot(
            built, session, advisor_id=built.second_advisor_id
        )
    booked = await book(
        database,
        built,
        conversation,
        start=start,
        conducting_advisor_id=built.second_advisor_id,
    )
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        appointments = built.visits(session)
        owner_view = await appointments.agenda(built.advisor)
        conductor_view = await appointments.agenda(built.second_advisor)
        admin_view = await appointments.agenda(built.admin)

    # Somebody standing at a door needs the address whether or not they own the
    # Opportunity.
    assert [row.id for row in owner_view] == [booked.appointment_id]
    assert [row.id for row in conductor_view] == [booked.appointment_id]
    assert [row.id for row in admin_view] == [booked.appointment_id]


async def test_a_pre_stage_three_visit_is_surfaced_rather_than_backfilled(
    operation,
) -> None:
    """Historical rows have no owner. Inventing one would be worse than showing
    an Administrator that a decision is needed."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.advisor_id = None
        row.calendar_id = None
        await session.commit()

    async with database.session_scope() as session:
        unowned = await built.visits(session).unowned(built.admin)
        with pytest.raises(NotAuthorized):
            await built.visits(session).unowned(built.advisor)

    assert [row.id for row in unowned] == [booked.appointment_id]


# -- Reminders, when the policy is on -------------------------------------


async def test_an_activated_reminder_still_meets_the_outbound_gate(
    operation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning the policy on does not bypass anything.

    A day-before reminder is by definition outside Meta's 24-hour window unless
    the Contact happened to write that day, so with the policy on and no
    approved template the gate is what refuses it. That is the structural point
    of ADR-0045, not a limitation of this module.
    """
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    import realestate.domain.scheduling.reminders as reminders_module

    monkeypatch.setattr(reminders_module, "REMINDER_POLICY_ACTIVATED", True)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        # Age every inbound message past the service window.
        from realestate.db.models import InboxMessage

        for message in await session.scalars(
            select(InboxMessage).where(
                InboxMessage.conversation_id == conversation.id
            )
        ):
            message.sent_at = message.sent_at - timedelta(hours=30)
            message.persisted_at = message.persisted_at - timedelta(hours=30)
        await session.commit()

        outcomes = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).settle_due(row.starts_at - timedelta(hours=2))

    assert "ServiceWindowClosed" in outcomes
    async with database.session_scope() as session:
        staged = [
            message.kind for message in await session.scalars(select(OutboxMessage))
        ]
    assert "AppointmentReminder" not in staged


async def test_an_activated_reminder_inside_the_window_is_queued(
    operation, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    import realestate.domain.scheduling.reminders as reminders_module

    monkeypatch.setattr(reminders_module, "REMINDER_POLICY_ACTIVATED", True)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        outcomes = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).settle_due(row.starts_at - timedelta(hours=2))

    assert outcomes.get("Queued")
    async with database.session_scope() as session:
        staged = [
            message
            for message in await session.scalars(select(OutboxMessage))
            if message.kind == "AppointmentReminder"
        ]
    assert staged
    # Product copy rendered from the row, never the Model's account of it.
    assert "Te recordamos tu visita" in staged[0].body
    assert "Casa Roble" in staged[0].body


async def test_a_reminder_for_a_cancelled_visit_is_retired(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        outcomes = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).settle_due(row.starts_at - timedelta(hours=2))

    assert outcomes.get("AppointmentNotConfirmed")


async def test_nothing_due_settles_nothing(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        assert (
            await AppointmentReminders(session, SCHEDULE, day_of_hour=9).settle_due()
            == {}
        )


# -- Ownership and calendars for edge rows -------------------------------


async def test_a_visit_with_no_calendar_cannot_be_cancelled(operation) -> None:
    """Cancelling with nowhere to check would tell a Contact something Product
    cannot know."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.calendar_id = None
        row.advisor_id = None
        row.conducting_advisor_id = None
        await session.commit()

    async with database.session_scope() as session:
        refused = await built.visits(session).cancel(
            built.admin,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.NO_AUTHORITATIVE_CALENDAR


async def test_an_unknown_visit_reads_as_absent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await built.visits(session).visit(built.admin, uuid.uuid4())


async def test_the_agenda_can_be_filtered_to_one_advisor(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        appointments = built.visits(session)
        mine = await appointments.agenda(built.admin, advisor_id=built.advisor_id)
        theirs = await appointments.agenda(
            built.admin, advisor_id=built.second_advisor_id
        )
        # Bounded exclusively at the visit's own start, so the window
        # genuinely ends before it rather than depending on the wall clock.
        bounded = await appointments.agenda(
            built.admin,
            since=visits.now() - timedelta(days=1),
            until=booked.starts_at,
        )

    assert [row.id for row in mine] == [booked.appointment_id]
    assert theirs == []
    # The visit is beyond the window, so a bounded read excludes it.
    assert bounded == []


async def test_an_expired_conversation_cannot_book(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(built, session)
        cycle = await session.get(
            visits.LeadEngagementCycle, conversation.cycle_id
        )
        assert cycle is not None
        cycle.expires_at = visits.now() - timedelta(days=1)
        await session.commit()

    outcome = await book(database, built, conversation, start=start)

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.CONVERSATION_EXPIRED


async def test_booking_for_an_unknown_property_is_refused(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        outcome = await built.visits(session).book(
            built.product,
            BookVisit(
                conversation_id=conversation.id,
                property_uuid=uuid.uuid4(),
                start=visits.now(),
                command_key=key("book"),
            ),
        )

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.PROPERTY_NOT_FOUND


async def test_booking_cannot_cross_the_property_organization_boundary(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    suffix = uuid.uuid4().hex
    async with database.session_scope() as session:
        other = Organization(slug=f"booking-{suffix}", display_name="Otra organización")
        session.add(other)
        await session.flush()
        foreign_property = Property(
            organization_id=other.id,
            property_key=f"foreign-booking-{suffix}",
            name="Propiedad de otra organización",
            normalized_name=f"propiedad de otra organizacion {suffix}",
            status=PropertyStatus.ACTIVE.value,
        )
        session.add(foreign_property)
        await session.flush()
        foreign_property_id = foreign_property.id
        outcome = await built.visits(session).book(
            built.product,
            BookVisit(
                conversation_id=conversation.id,
                property_uuid=foreign_property_id,
                start=visits.now(),
                command_key=key("foreign-booking"),
            ),
        )
        await session.rollback()

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.PROPERTY_NOT_FOUND


async def test_booking_for_an_unknown_conversation_reads_as_absent(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await built.visits(session).book(
                built.product,
                BookVisit(
                    conversation_id=uuid.uuid4(),
                    property_uuid=built.property_uuid,
                    start=visits.now(),
                    command_key=key("book"),
                ),
            )


async def test_an_administrator_may_name_the_owner_explicitly(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(
            built, session, advisor_id=built.second_advisor_id
        )

    outcome = await book(
        database,
        built,
        conversation,
        start=start,
        actor=built.admin,
        advisor_id=built.second_advisor_id,
    )

    assert isinstance(outcome, VisitBooked)
    assert outcome.advisor_id == built.second_advisor_id


async def test_an_advisor_cannot_name_another_owner_explicitly(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    async with database.session_scope() as session:
        start = await visits.first_slot(
            built, session, advisor_id=built.second_advisor_id
        )

    with pytest.raises(NotAuthorized):
        await book(
            database,
            built,
            conversation,
            start=start,
            actor=built.advisor,
            advisor_id=built.second_advisor_id,
        )


async def test_naming_an_ineligible_owner_is_refused(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    outcome = await book(
        database,
        built,
        conversation,
        start=visits.now(),
        actor=built.admin,
        advisor_id=built.admin_id,
    )

    assert isinstance(outcome, VisitRefused)
    assert outcome.reason is Refusal.ADVISOR_INELIGIBLE


async def test_every_visit_label_has_spanish(operation) -> None:
    from realestate.domain.scheduling.appointments import (
        ATTENDANCE_LABELS,
        REFUSAL_MESSAGES,
        STATUS_LABELS,
    )

    assert set(STATUS_LABELS) == {status.value for status in AppointmentStatus}
    assert set(ATTENDANCE_LABELS) == {
        member.value for member in AppointmentAttendance
    }
    assert set(REFUSAL_MESSAGES) == {member.value for member in Refusal}
    for label in (
        *STATUS_LABELS.values(),
        *ATTENDANCE_LABELS.values(),
        *REFUSAL_MESSAGES.values(),
    ):
        assert label and label[0].isupper()


async def test_rescheduling_to_the_same_time_reports_no_change(operation) -> None:
    """Otherwise the successor key is the original row's own, which is
    Confirmed, and the operator is told something changed when nothing did."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=booked.appointment_id,
                new_start=booked.starts_at,
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.UNCHANGED
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(visits.Appointment)))
    assert len(rows) == 1


async def test_a_qualified_opportunity_advances_to_visiting_on_confirmation(
    operation,
) -> None:
    """The Appointment Handoff moves the stage when the pipeline allows it, and
    never manufactures the qualification evidence it would need otherwise."""
    database, built = operation
    conversation = await a_conversation(database)

    async with database.session_scope() as session:
        from realestate.domain.commercial.opportunities import (
            AdvanceStage,
            OpportunityManagement,
            QualificationAction,
        )
        opportunity = await session.scalar(select(Opportunity))
        assert opportunity is not None
        need_id = opportunity.property_need_id
        assert need_id is not None
        await commercial.confirm_minimum_criteria(session, built.admin, need_id)
        await OpportunityManagement(session).record(
            built.admin,
            AdvanceStage(
                opportunity_id=opportunity.id,
                to_stage=OpportunityStage.QUALIFIED,
                reason="Criterios confirmados",
                command_key=key("qualify"),
                qualification_action=QualificationAction(
                    kind=NextActionKind.SEND_LISTINGS,
                    due_at=visits.now() + timedelta(days=1),
                ),
            ),
        )
        await session.commit()

    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        opportunity = await session.scalar(select(Opportunity))

    assert opportunity is not None
    assert opportunity.stage == OpportunityStage.VISITING.value


async def test_a_stale_calendar_event_after_rescheduling_becomes_review_work(
    operation,
) -> None:
    """The customer keeps the new time; the leftover event becomes a named task
    rather than a silent duplicate on the Advisor's calendar."""
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = next(
            slot.start
            for slot in found.slots  # type: ignore[union-attr]
            if slot.start != original.starts_at
        )

    async def failing_delete(event_id):  # noqa: ANN001, ANN202
        from realestate.channels.google.calendar import EventResult

        return EventResult(CalendarOutcome.UNKNOWN, detail="stubbed outage")

    built.calendar.delete_event = failing_delete  # type: ignore[assignment]

    async with database.session_scope() as session:
        moved = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(moved, VisitBooked)
    assert moved.confirmed
    async with database.session_scope() as session:
        old = await session.get(visits.Appointment, original.appointment_id)
        alerts = list(
            await session.scalars(
                select(InternalAlert).where(
                    InternalAlert.subject_id == str(original.appointment_id)
                )
            )
        )

    assert old is not None
    assert old.status == AppointmentStatus.RESCHEDULED.value
    assert old.last_error and "no se pudo eliminar" in old.last_error
    assert alerts and "Borra el evento anterior a mano." in alerts[0].body


async def test_rescheduling_a_visit_whose_property_went_inactive_is_refused(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        prop = await session.get(Property, built.property_uuid)
        assert prop is not None
        prop.status = PropertyStatus.INACTIVE.value
        await session.commit()

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=original.starts_at + timedelta(days=1),
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.PROPERTY_INACTIVE


async def test_rescheduling_without_an_authoritative_calendar_is_refused(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        member = await session.get(visits.OrganizationMember, built.advisor_id)
        assert member is not None
        member.calendar_id = None
        await session.commit()

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=original.starts_at + timedelta(days=1),
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.NO_AUTHORITATIVE_CALENDAR


async def test_rescheduling_when_the_calendar_cannot_be_read_is_refused(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)
    built.calendar.busy_outcome = CalendarOutcome.FAILED

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=original.starts_at + timedelta(days=1),
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.CALENDAR_UNREADABLE


async def test_rescheduling_to_a_slot_an_absence_now_covers_is_refused(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    original = await book(database, built, conversation)
    assert isinstance(original, VisitBooked)

    async with database.session_scope() as session:
        from realestate.domain.scheduling.advisors import SlotQuery

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        new_start = next(
            slot.start
            for slot in found.slots  # type: ignore[union-attr]
            if slot.start > original.starts_at + timedelta(days=1)
        )
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=new_start - timedelta(hours=1),
                ends_at=new_start + timedelta(hours=4),
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        refused = await built.visits(session).reschedule(
            built.product,
            RescheduleVisit(
                appointment_id=original.appointment_id,
                new_start=new_start,
                command_key=key("reschedule"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.ADVISOR_ABSENT


async def test_an_appointment_whose_calendar_moved_is_still_cancellable(
    operation,
) -> None:
    """The stored calendar is authoritative, and when it is unreachable the
    Advisor's current one is the next best answer."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.calendar_id = "un-calendario-que-ya-no-existe"
        await session.commit()

    async with database.session_scope() as session:
        cancelled = await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )

    assert isinstance(cancelled, VisitCancelled)


async def test_a_needs_review_visit_can_still_have_its_outcome_recorded(
    operation,
) -> None:
    """An ambiguous booking is exactly the case where a human knows what
    happened and Product does not."""
    database, built = operation
    conversation = await a_conversation(database)
    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=3)
        row.ends_at = visits.now() - timedelta(hours=1)
        await session.commit()

    async with database.session_scope() as session:
        outcome = await built.visits(session).record_outcome(
            built.advisor,
            RecordVisitOutcome(
                appointment_id=booked.appointment_id,
                attendance=AppointmentAttendance.MISSED,
                command_key=key("outcome"),
                notes="El evento nunca existió en el calendario.",
            ),
        )
        await session.commit()

    assert isinstance(outcome, VisitOutcome)
    assert outcome.recorded


async def test_a_cancelled_visit_has_no_outcome_to_record(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        await built.visits(session).cancel(
            built.product,
            CancelVisit(
                appointment_id=booked.appointment_id, command_key=key("cancel")
            ),
        )
    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        row.starts_at = visits.now() - timedelta(hours=3)
        await session.commit()

    async with database.session_scope() as session:
        refused = await built.visits(session).record_outcome(
            built.advisor,
            RecordVisitOutcome(
                appointment_id=booked.appointment_id,
                attendance=AppointmentAttendance.ATTENDED,
                command_key=key("outcome"),
            ),
        )

    assert isinstance(refused, VisitRefused)
    assert refused.reason is Refusal.NOT_CONFIRMED


async def test_reminders_are_not_scheduled_for_an_unconfirmed_visit(
    operation,
) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    built.calendar.create_outcome = CalendarOutcome.UNKNOWN
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        created = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).schedule_for(row)

    assert created == []


async def test_scheduling_reminders_twice_creates_them_once(operation) -> None:
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        again = await AppointmentReminders(
            session, SCHEDULE, day_of_hour=9
        ).schedule_for(row)
        await session.commit()

    assert again == []
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(AppointmentReminder)))
    assert len(rows) == 2


async def test_a_day_of_reminder_never_falls_after_the_visit(operation) -> None:
    """A configured hour later than the visit is pulled back to that morning
    rather than scheduled into the past of the visit itself."""
    database, built = operation
    conversation = await a_conversation(database)
    booked = await book(database, built, conversation)
    assert isinstance(booked, VisitBooked)

    async with database.session_scope() as session:
        row = await session.get(visits.Appointment, booked.appointment_id)
        assert row is not None
        # A day-of hour deliberately later than every bookable slot.
        reminders = AppointmentReminders(session, SCHEDULE, day_of_hour=23)
        moment = reminders._day_of_moment(row.starts_at)  # noqa: SLF001

    local = moment.astimezone(SCHEDULE.zone)
    assert local < row.starts_at.astimezone(SCHEDULE.zone)
    assert (local.hour, local.minute) == (0, 0)


def test_the_reminder_copy_includes_the_visit_address_when_there_is_one() -> None:
    from realestate.domain.scheduling.reminders import reminder_body

    with_address = reminder_body(
        property_name="Casa Roble",
        starts_at=visits.now() + timedelta(days=1),
        schedule=SCHEDULE,
        visit_address="Calle Privada 123, Zapopan",
    )
    without = reminder_body(
        property_name="Casa Roble",
        starts_at=visits.now() + timedelta(days=1),
        schedule=SCHEDULE,
        visit_address=None,
    )

    assert "Calle Privada 123, Zapopan" in with_address
    assert "dirección" not in without
    for body in (with_address, without):
        assert "Te recordamos tu visita a Casa Roble" in body
        assert "responde a este mensaje" in body


def test_every_reminder_label_has_spanish() -> None:
    from realestate.domain.scheduling.reminders import (
        OUTCOME_LABELS,
        REMINDER_KIND_LABELS,
    )

    assert set(REMINDER_KIND_LABELS) == {
        member.value for member in AppointmentReminderKind
    }
    for label in (*REMINDER_KIND_LABELS.values(), *OUTCOME_LABELS.values()):
        assert label

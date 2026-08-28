"""Availability is per Advisor, and authoritative or absent (ADR-0048).

The distinction this suite defends is between *busy* and *unknown*. An Advisor
whose calendar is genuinely full has no slots and that is a successful answer. An
Advisor with no configured calendar, or one whose calendar could not be read, has
no availability Product may quote — and offering times in either case would send
a customer to a house nobody is at.

Each refusal is a named reason with its own Spanish sentence, because the
remedies differ: configure a calendar, end an absence, wait for the provider.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from realestate.channels.google.calendar import CalendarOutcome
from realestate.db.engine import Database
from realestate.db.models import PropertyExpertRole
from realestate.domain.availability import Interval
from realestate.domain.commercial.team import (
    DesignateExpert,
    SetMemberActive,
    StartAbsence,
    TeamAdministration,
)
from realestate.domain.scheduling.advisors import (
    UNAVAILABLE_MESSAGES,
    SlotQuery,
    SlotsFound,
    SlotsUnavailable,
    Unavailable,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import visits

pytestmark = requires_postgres


@pytest.fixture
async def operation(tmp_path: Path):
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await visits.reset(session)
        built = await visits.build(session, tmp_path / "artifacts")
        await session.commit()
    yield database, built
    await database.dispose()


def key(name: str) -> str:
    import uuid

    return f"{name}:{uuid.uuid4().hex}"


async def test_each_advisor_is_quoted_from_their_own_calendar(operation) -> None:
    """The whole point of the directory: two Advisors, two answers."""
    database, built = operation
    async with database.session_scope() as session:
        scheduling = built.scheduling(session)
        # The first Advisor is booked solid for the whole horizon.
        built.calendar.busy.append(
            Interval(
                start=visits.now() - timedelta(hours=1),
                end=visits.now() + timedelta(days=10),
            )
        )
        first = await scheduling.find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )
        second = await scheduling.find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.second_advisor_id,
            )
        )

    assert isinstance(first, SlotsFound)
    assert isinstance(second, SlotsFound)
    # Busy is a successful answer with no slots, not a refusal.
    assert first.slots == ()
    assert second.slots
    assert first.calendar_id != second.calendar_id


async def test_an_advisor_with_no_calendar_has_no_authoritative_availability(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        member = await session.get(visits.OrganizationMember, built.advisor_id)
        assert member is not None
        member.calendar_id = None
        await session.commit()

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )

    assert isinstance(found, SlotsUnavailable)
    assert found.reason is Unavailable.NO_AUTHORITATIVE_CALENDAR
    assert "no tiene calendario configurado" in found.message


async def test_an_unreadable_calendar_is_never_an_empty_one(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        built.calendar.busy_outcome = CalendarOutcome.FAILED
        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )

    assert isinstance(found, SlotsUnavailable)
    assert found.reason is Unavailable.CALENDAR_UNREADABLE
    # Distinct from "busy": the Contact must not be told the time is taken.
    assert found.message != UNAVAILABLE_MESSAGES[Unavailable.NO_ADVISOR.value]


async def test_a_declared_absence_blocks_availability_even_with_a_free_calendar(
    operation,
) -> None:
    """Product's own record is authority too.

    An Advisor who told the Administrator they are away should not become
    bookable merely because they forgot to block their calendar.
    """
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() - timedelta(hours=1),
                ends_at=visits.now() + timedelta(days=10),
            ),
        )
        await session.commit()

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )

    assert isinstance(found, SlotsFound)
    assert found.slots == ()


async def test_a_deactivated_advisor_is_ineligible(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            SetMemberActive(
                command_key=key("state"),
                member_id=built.second_advisor_id,
                active=False,
            ),
        )
        await session.commit()

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.second_advisor_id,
            )
        )

    assert isinstance(found, SlotsUnavailable)
    assert found.reason is Unavailable.ADVISOR_INELIGIBLE


async def test_a_property_resolves_to_its_present_expert(operation) -> None:
    database, built = operation
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

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                property_uuid=built.property_uuid,
            )
        )

    assert isinstance(found, SlotsFound)
    assert found.advisor_id == built.second_advisor_id


async def test_an_absent_expert_hands_the_property_to_the_backup(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.BACKUP,
                rank=1,
            ),
        )
        await administration.record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.second_advisor_id,
                starts_at=visits.now() - timedelta(hours=1),
                ends_at=visits.now() + timedelta(days=3),
            ),
        )
        await session.commit()

        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                property_uuid=built.property_uuid,
            )
        )

    assert isinstance(found, SlotsFound)
    assert found.advisor_id == built.advisor_id


async def test_a_property_with_no_expert_and_no_advisor_named_is_refused(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                property_uuid=built.property_uuid,
            )
        )

    assert isinstance(found, SlotsUnavailable)
    assert found.reason is Unavailable.NO_ADVISOR


async def test_slots_respect_the_weekly_schedule_and_the_grid(operation) -> None:
    """Unchanged Stage 0 rules, now applied per Advisor rather than globally."""
    database, built = operation
    async with database.session_scope() as session:
        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=built.admin.organization_id,
                advisor_id=built.advisor_id,
            )
        )

    assert isinstance(found, SlotsFound)
    assert found.slots
    from tests.fixtures.stubs import SCHEDULE

    for slot in found.slots:
        local = slot.start.astimezone(SCHEDULE.zone)
        assert slot.start.minute in (0, 30)
        assert (slot.end - slot.start) == timedelta(minutes=90)
        # Every slot fits entirely inside one approved window for its day.
        assert any(
            window.start <= local.time()
            and (slot.end.astimezone(SCHEDULE.zone)).time() <= window.end
            for window in SCHEDULE.ranges_on(local.date())
        )


async def test_an_advisor_from_another_organization_is_not_found(operation) -> None:
    database, built = operation
    import uuid as _uuid

    async with database.session_scope() as session:
        found = await built.scheduling(session).find_slots(
            SlotQuery(
                organization_id=_uuid.uuid4(),
                advisor_id=built.advisor_id,
            )
        )

    assert isinstance(found, SlotsUnavailable)
    assert found.reason is Unavailable.NO_ADVISOR


# -- The Google adapter, without touching Google --------------------------


def test_the_directory_refuses_an_advisor_with_no_calendar() -> None:
    """The one branch that must not silently succeed."""
    from realestate.db.models import OrganizationMember
    from realestate.domain.scheduling.calendars import GoogleCalendarDirectory

    directory = GoogleCalendarDirectory(credentials_path="/tmp/creds.json")
    assert directory.configured
    member = OrganizationMember(login="a@b.test", display_name="A", role="RealEstateAdvisor")
    member.calendar_id = None
    assert directory.for_advisor(member) is None


def test_the_directory_caches_one_client_per_calendar() -> None:
    """Building a client reads a key file, and availability is queried on nearly
    every conversational turn."""
    from realestate.db.models import OrganizationMember
    from realestate.domain.scheduling.calendars import GoogleCalendarDirectory

    directory = GoogleCalendarDirectory(credentials_path="/tmp/creds.json")
    member = OrganizationMember(login="a@b.test", display_name="A", role="RealEstateAdvisor")
    member.calendar_id = "one@larevia.test"

    first = directory.for_advisor(member)
    second = directory.for_calendar_id("one@larevia.test")
    other = directory.for_calendar_id("two@larevia.test")

    assert first is not None
    assert first is second
    assert other is not None
    assert other is not first


def test_an_unconfigured_directory_reaches_no_calendar() -> None:
    """No credential is a refusal, not a lookup that happens to fail later."""
    from realestate.domain.scheduling.calendars import GoogleCalendarDirectory

    directory = GoogleCalendarDirectory(credentials_path="")
    assert not directory.configured
    assert directory.for_calendar_id("one@larevia.test") is None
    assert directory.for_calendar_id("") is None

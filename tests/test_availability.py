"""Deterministic Available Slot calculation (P-054, P-055, P-056).

These are the rules the Model must never be able to bend, so they are tested
directly rather than through a conversation.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from realestate.domain.availability import (
    Interval,
    ScheduleError,
    WeeklySchedule,
    candidate_slots,
    filter_slots,
)

ZONE = ZoneInfo("America/Mexico_City")
# The project's real schedule (docs/decisions/checkpoint-3-inputs.md).
SPEC = (
    "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;thu=09:00-17:00;"
    "fri=09:00-17:00;sat=10:00-17:00;sun=10:00-17:00"
)


ALL_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def schedule(spec: str = SPEC) -> WeeklySchedule:
    """Parse *spec*, padding unmentioned days with `nada`.

    The parser requires all seven days so a truncated .env value is loud rather
    than silent. Tests that care about one day should not have to spell out the
    other six, so the helper pads — but `parse` is also exercised directly, with
    no padding, in the truncation tests below.
    """
    mentioned = {c.partition("=")[0].strip().lower()[:3] for c in spec.split(";") if c.strip()}
    padded = ";".join([spec] + [f"{d}=nada" for d in ALL_DAYS if d not in mentioned])
    return WeeklySchedule.parse(padded, "America/Mexico_City")


def at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZONE)


def slots(now: datetime, *, busy=None, days: int = 8, spec: str = SPEC, minutes: int = 90):
    return candidate_slots(
        now=now,
        schedule=schedule(spec),
        visit_minutes=minutes,
        horizon_days=days,
        busy=busy or [],
    )


# --- Parsing ------------------------------------------------------------------


def test_the_projects_schedule_parses() -> None:
    parsed = schedule()

    # Monday is 0. Weekdays open at 09:00, weekend at 10:00.
    assert parsed.ranges[0][0].start == time(9, 0)
    assert parsed.ranges[5][0].start == time(10, 0)
    assert parsed.ranges[6][0].start == time(10, 0)


def test_split_ranges_are_supported() -> None:
    parsed = schedule("mon=09:00-14:00,16:00-19:00")

    assert len(parsed.ranges[0]) == 2
    assert parsed.ranges[0][1].start == time(16, 0)


@pytest.mark.parametrize("value", ["nada", "none", "-", ""])
def test_a_day_can_offer_nothing(value: str) -> None:
    parsed = schedule(f"mon=09:00-17:00;sun={value}")

    assert parsed.ranges_on(date(2026, 8, 9)) == ()  # a Sunday


@pytest.mark.parametrize(
    "spec",
    [
        "lunes=09:00-17:00",       # unknown day key
        "mon=9-17",                 # not HH:MM
        "mon=17:00-09:00",          # backwards
        "mon=09:00-09:00",          # zero length
        "sun=10:00-17:00;xyz=1",    # junk
    ],
)
def test_a_malformed_schedule_raises_rather_than_dropping_a_day(spec: str) -> None:
    # A typo that silently removed a working day would be invisible.
    with pytest.raises(ScheduleError):
        schedule(spec)


def test_a_schedule_with_no_visits_at_all_is_rejected() -> None:
    with pytest.raises(ScheduleError):
        schedule("mon=nada")


# --- The truncation guard -----------------------------------------------------
#
# Earned the hard way: .env held the schedule unquoted, shell scripts source
# that file, and an unquoted ';' truncated the value to Monday alone. The
# fragment parsed perfectly and a whole week of availability vanished silently.


def test_a_truncated_schedule_is_rejected_not_silently_accepted() -> None:
    # Exactly what `. ./.env` produced from an unquoted value.
    with pytest.raises(ScheduleError) as caught:
        WeeklySchedule.parse("mon=09:00-17:00", "America/Mexico_City")

    message = str(caught.value)
    assert "missing" in message
    # The error names the likely cause, because the symptom is invisible.
    assert "quoted" in message
    assert ";" in message


def test_every_day_must_appear_explicitly() -> None:
    six_days = ";".join(f"{d}=09:00-17:00" for d in ALL_DAYS[:6])

    with pytest.raises(ScheduleError, match="sun"):
        WeeklySchedule.parse(six_days, "America/Mexico_City")


def test_a_closed_day_is_written_explicitly() -> None:
    spec = ";".join(
        [f"{d}=09:00-17:00" for d in ALL_DAYS[:6]] + ["sun=nada"]
    )

    parsed = WeeklySchedule.parse(spec, "America/Mexico_City")

    assert parsed.ranges_on(date(2026, 8, 9)) == ()  # Sunday
    assert parsed.ranges_on(date(2026, 8, 10))       # Monday


def test_the_configured_schedule_survives_a_round_trip_through_the_env_file() -> None:
    """The real .env value must parse to all seven days after shell sourcing."""
    import subprocess

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        ["bash", "-c", 'set -a; . ./.env; set +a; printf "%s" "$WEEKLY_SCHEDULE"'],
        cwd=root, capture_output=True, text=True,
    ).stdout

    parsed = WeeklySchedule.parse(out, "America/Mexico_City")
    assert len(parsed.ranges) == 7, out


# --- The grid and the window --------------------------------------------------


def test_every_start_is_on_the_half_hour() -> None:
    for slot in slots(at("2026-08-10", "00:00")):
        assert slot.start.minute in (0, 30), slot.start
        assert slot.start.second == 0


def test_every_slot_is_exactly_the_visit_length() -> None:
    for slot in slots(at("2026-08-10", "00:00")):
        assert slot.end - slot.start == timedelta(minutes=90)


def test_no_slot_extends_past_the_end_of_its_window() -> None:
    # Weekdays close at 17:00, so the last 90-minute start is 15:30.
    monday = [s for s in slots(at("2026-08-10", "00:00")) if s.start.weekday() == 0]

    assert max(s.start.time() for s in monday) == time(15, 30)
    assert all(s.end.time() <= time(17, 0) for s in monday)


def test_a_slot_never_starts_before_its_window_opens() -> None:
    monday = [s for s in slots(at("2026-08-10", "00:00")) if s.start.weekday() == 0]

    assert min(s.start.time() for s in monday) == time(9, 0)


def test_free_time_outside_the_schedule_is_never_offered() -> None:
    # An empty calendar at 23:00 is not permission to book (P-054).
    for slot in slots(at("2026-08-10", "00:00")):
        assert time(9, 0) <= slot.start.time() <= time(15, 30)


def test_the_weekend_opens_later_than_the_week() -> None:
    saturday = [s for s in slots(at("2026-08-10", "00:00")) if s.start.weekday() == 5]

    assert min(s.start.time() for s in saturday) == time(10, 0)


def test_sunday_is_offered_because_the_broker_asked_for_it() -> None:
    # Deliberate, confirmed twice. See docs/decisions/checkpoint-3-inputs.md.
    sunday = [s for s in slots(at("2026-08-10", "00:00")) if s.start.weekday() == 6]

    assert sunday


# --- The horizon --------------------------------------------------------------


def test_nothing_is_offered_beyond_the_horizon() -> None:
    now = at("2026-08-10", "00:00")
    result = slots(now, days=8)

    assert max(s.end for s in result) <= now + timedelta(days=8)


def test_a_shorter_horizon_offers_strictly_less() -> None:
    now = at("2026-08-10", "00:00")

    assert len(slots(now, days=8)) < len(slots(now, days=14))


def test_nothing_is_offered_in_the_past() -> None:
    # Mid-morning Monday: the 09:00 slot has already started.
    result = slots(at("2026-08-10", "11:15"))

    assert all(s.start >= at("2026-08-10", "11:15") for s in result)
    # The next grid start is 11:30.
    assert result[0].start == at("2026-08-10", "11:30")


def test_a_query_late_in_the_day_rolls_to_tomorrow() -> None:
    result = slots(at("2026-08-10", "16:00"))

    assert result[0].start.date() == date(2026, 8, 11)


# --- Busy subtraction ---------------------------------------------------------


def test_a_busy_interval_removes_every_overlapping_candidate() -> None:
    busy = [Interval(start=at("2026-08-10", "09:00"), end=at("2026-08-10", "12:00"))]

    monday = [
        s for s in slots(at("2026-08-10", "00:00"), busy=busy)
        if s.start.date() == date(2026, 8, 10)
    ]

    assert all(not s.overlaps(busy[0]) for s in monday)
    # 10:30-12:00 overlaps, so the first survivor starts at 12:00.
    assert monday[0].start == at("2026-08-10", "12:00")


def test_a_partial_overlap_still_removes_the_candidate() -> None:
    # A 15-minute meeting is enough to kill a 90-minute slot.
    busy = [Interval(start=at("2026-08-10", "09:15"), end=at("2026-08-10", "09:30"))]

    monday = [
        s for s in slots(at("2026-08-10", "00:00"), busy=busy)
        if s.start.date() == date(2026, 8, 10)
    ]

    assert at("2026-08-10", "09:00") not in [s.start for s in monday]
    assert at("2026-08-10", "09:30") in [s.start for s in monday]


def test_a_busy_interval_touching_a_boundary_does_not_remove_it() -> None:
    # Half-open intervals: a meeting ending exactly at 10:30 leaves 10:30 free.
    busy = [Interval(start=at("2026-08-10", "09:00"), end=at("2026-08-10", "10:30"))]

    monday = [
        s for s in slots(at("2026-08-10", "00:00"), busy=busy)
        if s.start.date() == date(2026, 8, 10)
    ]

    assert monday[0].start == at("2026-08-10", "10:30")


def test_a_fully_booked_day_yields_nothing_for_that_day() -> None:
    busy = [Interval(start=at("2026-08-10", "00:00"), end=at("2026-08-11", "00:00"))]

    monday = [
        s for s in slots(at("2026-08-10", "00:00"), busy=busy)
        if s.start.date() == date(2026, 8, 10)
    ]

    assert monday == []


# --- Filtering ----------------------------------------------------------------


def test_filtering_by_date_narrows_to_that_day() -> None:
    result = filter_slots(
        slots(at("2026-08-10", "00:00")),
        date_from=date(2026, 8, 12),
        date_to=date(2026, 8, 12),
        limit=6,
    )

    assert result
    assert {s.start.date() for s in result} == {date(2026, 8, 12)}


def test_filtering_by_time_bounds_the_start_not_the_end() -> None:
    # "por la tarde, antes de las 4" means starting before 16:00. Bounding the
    # end instead would silently drop the last slot of every window.
    result = filter_slots(
        slots(at("2026-08-10", "00:00")),
        time_from=time(12, 0),
        time_to=time(16, 0),
        limit=50,
    )

    assert all(time(12, 0) <= s.start.time() <= time(16, 0) for s in result)
    assert any(s.end.time() > time(16, 0) for s in result)


def test_a_result_is_capped() -> None:
    assert len(filter_slots(slots(at("2026-08-10", "00:00")), limit=6)) == 6


def test_no_filter_returns_the_earliest_candidates() -> None:
    everything = slots(at("2026-08-10", "00:00"))

    assert filter_slots(everything, limit=6) == everything[:6]


def test_an_impossible_filter_is_empty_not_an_error() -> None:
    # An empty list is a successful filter with no matches, not a failure.
    result = filter_slots(
        slots(at("2026-08-10", "00:00")),
        time_from=time(3, 0),
        time_to=time(4, 0),
        limit=6,
    )

    assert result == []


# --- Parsing tolerance and the :00/:30 grid ----------------------------------


def test_a_trailing_separator_in_the_schedule_is_ignored() -> None:
    """.env values are hand-edited; a stray final ``;`` is not a truncation."""
    parsed = WeeklySchedule.parse(SPEC + ";", "America/Mexico_City")

    assert len(parsed.ranges) == 7


def test_repeated_separators_are_ignored_too() -> None:
    parsed = WeeklySchedule.parse(SPEC.replace(";", ";;"), "America/Mexico_City")

    assert len(parsed.ranges) == 7


@pytest.mark.parametrize(
    ("minute", "second", "expected_hour", "expected_minute"),
    [
        # Already on the grid: kept exactly.
        (0, 0, 10, 0),
        (30, 0, 10, 30),
        # A stray second is not "on the grid" — it would produce a 10:00:14 start.
        (0, 14, 10, 30),
        # Below the half hour rounds up to :30, above it rolls to the next hour.
        (1, 0, 10, 30),
        (29, 0, 10, 30),
        (31, 0, 11, 0),
        (59, 0, 11, 0),
    ],
)
def test_the_first_candidate_start_lands_on_the_grid(
    minute: int, second: int, expected_hour: int, expected_minute: int
) -> None:
    """A Lead's arbitrary request is never silently rounded onto the grid; the
    *search window* is what moves forward to the next legal start."""
    from realestate.domain.availability import _first_grid_start

    moment = datetime(2026, 8, 10, 10, minute, second, tzinfo=ZONE)

    start = _first_grid_start(moment)

    assert (start.hour, start.minute, start.second) == (
        expected_hour,
        expected_minute,
        0,
    )


def test_a_grid_start_drops_a_stray_microsecond() -> None:
    from realestate.domain.availability import _first_grid_start

    moment = datetime(2026, 8, 10, 10, 30, 0, 500, tzinfo=ZONE)

    assert _first_grid_start(moment).microsecond == 0

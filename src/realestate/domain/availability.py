"""Deterministic Available Slot calculation (P-054, P-055, P-056).

Pure functions. No Calendar client, no database, no clock of its own — every
input is passed in, which is what makes the rules testable and what keeps the
Model from ever influencing them.

The three rules that matter, and that the Model cannot bend:

* an Available Slot is exactly ``visit_minutes`` long and fits **entirely**
  inside one Weekly Bookable Schedule range. Free Calendar time outside the
  schedule is never a slot — an empty calendar at 23:00 is not permission.
* starts lie on a ``:00``/``:30`` grid. No ``10:17``, and a Lead's arbitrary
  request is never silently rounded onto the grid.
* the search is bounded to the Booking Horizon from the query moment.

Busy intervals subtract from candidates by overlap: a candidate survives only if
no busy interval intersects it at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

GRID_MINUTES = 30

_DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")


class ScheduleError(ValueError):
    """The configured Weekly Bookable Schedule cannot be parsed."""


@dataclass(frozen=True)
class TimeRange:
    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ScheduleError(f"range {self.start}-{self.end} does not move forward")


@dataclass(frozen=True)
class Interval:
    """A half-open interval [start, end). Timezone-aware."""

    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class WeeklySchedule:
    """The Broker-approved days and local ranges when visits may be offered."""

    # Keyed by Python weekday(): Monday is 0.
    ranges: dict[int, tuple[TimeRange, ...]]
    timezone: str

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def ranges_on(self, day: date) -> tuple[TimeRange, ...]:
        return self.ranges.get(day.weekday(), ())

    def local_day(self, moment: datetime) -> str:
        """The calendar day *moment* falls on in the Broker's time zone.

        The at-most-once key for anything scoped to a local day, so it is spelled
        once: two spellings would let a daily notice repeat or be skipped either
        side of midnight.
        """
        return moment.astimezone(self.zone).strftime("%Y-%m-%d")

    @classmethod
    def parse(cls, spec: str, timezone: str) -> "WeeklySchedule":
        """Parse ``mon=09:00-17:00;sat=10:00-14:00,16:00-19:00``.

        All seven days must appear. A closed day is written explicitly as
        ``sun=nada`` rather than omitted.

        That strictness is deliberate and was earned: the value lives in .env,
        which shell scripts ``source``, and an unquoted ``;`` truncated the
        schedule to Monday alone. Nothing complained — the remaining fragment
        parsed perfectly. Requiring every day turns a truncated value into a
        loud error instead of a week of missing availability.
        """
        ranges: dict[int, tuple[TimeRange, ...]] = {}
        for chunk in (part.strip() for part in spec.split(";")):
            if not chunk:
                continue
            key, _, value = chunk.partition("=")
            key = key.strip().lower()[:3]
            if key not in _DAY_KEYS:
                raise ScheduleError(f"unknown day {key!r} in schedule")
            value = value.strip()
            if not value or value.lower() in {"nada", "none", "-"}:
                ranges[_DAY_KEYS.index(key)] = ()
                continue
            parsed: list[TimeRange] = []
            for piece in value.split(","):
                match = _RANGE.match(piece.strip())
                if not match:
                    raise ScheduleError(f"bad range {piece.strip()!r}; use HH:MM-HH:MM")
                sh, sm, eh, em = (int(g) for g in match.groups())
                parsed.append(TimeRange(start=time(sh, sm), end=time(eh, em)))
            ranges[_DAY_KEYS.index(key)] = tuple(
                sorted(parsed, key=lambda r: r.start)
            )
        missing = [d for i, d in enumerate(_DAY_KEYS) if i not in ranges]
        if missing:
            raise ScheduleError(
                f"schedule is missing {', '.join(missing)}. Every day must appear; "
                f"write a closed day as e.g. '{missing[0]}=nada'. "
                "If the value came from .env, check it is quoted — an unquoted ';' "
                "is a shell command separator and truncates it."
            )
        if not any(ranges.values()):
            raise ScheduleError("the schedule offers no visits on any day")
        return cls(ranges=ranges, timezone=timezone)


def horizon_end(now: datetime, days: int, schedule: WeeklySchedule) -> datetime:
    """End of the Booking Horizon, in the Broker's zone (P-056)."""
    local = now.astimezone(schedule.zone)
    return local + timedelta(days=days)


def candidate_slots(
    *,
    now: datetime,
    schedule: WeeklySchedule,
    visit_minutes: int,
    horizon_days: int,
    busy: list[Interval],
) -> list[Interval]:
    """Every Available Slot between *now* and the horizon, earliest first.

    A candidate must fit entirely inside one schedule range, start on the grid,
    begin at or after *now*, and not overlap any busy interval.
    """
    zone = schedule.zone
    local_now = now.astimezone(zone)
    end_of_horizon = horizon_end(now, horizon_days, schedule)
    duration = timedelta(minutes=visit_minutes)

    slots: list[Interval] = []
    day = local_now.date()
    while day <= end_of_horizon.date():
        for window in schedule.ranges_on(day):
            window_start = datetime.combine(day, window.start, tzinfo=zone)
            window_end = datetime.combine(day, window.end, tzinfo=zone)

            start = _first_grid_start(window_start)
            while start + duration <= window_end:
                candidate = Interval(start=start, end=start + duration)
                if candidate.start >= local_now and candidate.end <= end_of_horizon:
                    if not any(candidate.overlaps(b) for b in busy):
                        slots.append(candidate)
                start += timedelta(minutes=GRID_MINUTES)
        day += timedelta(days=1)

    return sorted(slots, key=lambda s: s.start)


def _first_grid_start(window_start: datetime) -> datetime:
    """The first ``:00``/``:30`` start at or after *window_start*."""
    if window_start.minute in (0, 30) and window_start.second == 0:
        return window_start.replace(microsecond=0)
    if window_start.minute < 30:
        return window_start.replace(minute=30, second=0, microsecond=0)
    return (window_start + timedelta(hours=1)).replace(
        minute=0, second=0, microsecond=0
    )


def filter_slots(
    slots: list[Interval],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    time_from: time | None = None,
    time_to: time | None = None,
    limit: int,
) -> list[Interval]:
    """Apply the tool's structured filters to a snapshot (P-059, P-060).

    ``time_to`` bounds the slot's **start**, not its end: a Lead asking for
    "before 18:00" means starting before 18:00. Bounding the end would silently
    drop the last slot of every window.
    """
    result = []
    for slot in slots:
        local = slot.start
        if date_from and local.date() < date_from:
            continue
        if date_to and local.date() > date_to:
            continue
        if time_from and local.time() < time_from:
            continue
        if time_to and local.time() > time_to:
            continue
        result.append(slot)
    return result[:limit]

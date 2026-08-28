"""The shared shell's pure helpers: dates, relative time, escaping, options.

Small and worth testing directly. An operator reading a UTC timestamp will
mis-schedule a visit, and a `datetime-local` value parsed in the wrong zone is
off by hours — neither shows up as an exception anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from realestate.api.ui import (
    OPERATION_TIMEZONE,
    datetime_input_value,
    empty,
    errors_box,
    escape,
    flash,
    local,
    options,
    parse_datetime_input,
    relative,
)

NOON_UTC = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)


def test_times_are_rendered_in_the_operations_timezone() -> None:
    assert local(NOON_UTC) == "1 septiembre 2026, 12:00"
    assert local(None) == "—"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "hace un momento"),
        (timedelta(minutes=7), "hace 7 min"),
        (timedelta(hours=5), "hace 5 h"),
        (timedelta(days=1), "hace 1 día"),
        (timedelta(days=9), "hace 9 días"),
    ],
)
def test_relative_time_reads_naturally_in_spanish(
    delta: timedelta, expected: str
) -> None:
    assert relative(NOON_UTC - delta, now=NOON_UTC) == expected


def test_a_future_moment_reads_as_upcoming_not_as_past() -> None:
    assert relative(NOON_UTC + timedelta(days=2), now=NOON_UTC) == "en 2 días"
    assert relative(NOON_UTC + timedelta(hours=3), now=NOON_UTC) == "en 3 h"
    assert relative(None, now=NOON_UTC) == "—"


def test_a_datetime_local_value_round_trips_through_the_operations_zone() -> None:
    value = datetime_input_value(NOON_UTC)
    assert value == "2026-09-01T12:00"
    parsed = parse_datetime_input(value)
    assert parsed is not None
    assert parsed.utcoffset() == NOON_UTC.astimezone(OPERATION_TIMEZONE).utcoffset()
    assert parsed.astimezone(UTC) == NOON_UTC


@pytest.mark.parametrize(
    "raw",
    ["2026-09-01T12:00", "2026-09-01T12:00:00", "2026-09-01 12:00"],
)
def test_the_shapes_a_browser_may_submit_are_all_accepted(raw: str) -> None:
    parsed = parse_datetime_input(raw)
    assert parsed is not None
    assert parsed.hour == 12


@pytest.mark.parametrize("raw", ["", "   ", "mañana", "2026-13-45T99:99", "1/9/2026"])
def test_an_unparseable_moment_is_reported_rather_than_raised(raw: str) -> None:
    """The caller turns ``None`` into a Spanish message next to the field."""
    assert parse_datetime_input(raw) is None


def test_escaping_covers_attributes_and_none() -> None:
    assert escape(None) == ""
    assert escape('<a href="x">') == "&lt;a href=&quot;x&quot;&gt;"
    assert escape(7) == "7"


def test_a_status_region_is_announced_or_absent() -> None:
    assert flash(None) == ""
    rendered = flash("Se guardó.", "ok")
    assert 'role="status"' in rendered
    assert 'aria-live="polite"' in rendered
    assert "Se guardó." in rendered


def test_validation_problems_are_announced_assertively() -> None:
    assert errors_box([]) == ""
    rendered = errors_box(["Falta la zona.", "Falta el <presupuesto>."])
    assert 'role="alert"' in rendered
    assert "No se guardó el cambio." in rendered
    assert "Falta la zona." in rendered
    assert "&lt;presupuesto&gt;" in rendered


def test_an_empty_state_can_carry_a_hint_or_not() -> None:
    assert "Agrega una." in empty("Nada aquí.", "Agrega una.")
    plain = empty("Nada aquí.")
    assert "Nada aquí." in plain
    assert "<p class=\"hint\">" not in plain


def test_options_select_the_current_value_and_use_its_label() -> None:
    rendered = options(("Buy", "Rent"), "Rent", {"Buy": "Compra", "Rent": "Renta"})
    assert '<option value="Buy">Compra</option>' in rendered
    assert '<option value="Rent" selected>Renta</option>' in rendered
    # Without labels the raw value is shown, escaped.
    assert options(("<x>",), "") == '<option value="&lt;x&gt;">&lt;x&gt;</option>'

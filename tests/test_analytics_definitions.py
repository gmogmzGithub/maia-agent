"""The exact borders. Served, visible, and Significant Gallery Exploration.

Every one of these assertions is on a boundary value, because the boundary is
where a measurement definition either means what it says or quietly means
something else. ADR-0043 publishes "50 percent of the card for one second" and
ADR-0044 publishes "five photographs or 30 percent of the gallery": exactly at
the threshold has to count, or the product under-reports the placements that met
its own published rule.
"""

from __future__ import annotations

import pytest

from realestate.db.engine import Database
from realestate.domain.analytics.definitions import MeasurementDefinitions, parse
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures.sponsorship import MOMENT

pytestmark = requires_postgres


@pytest.fixture
async def definition():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        resolved = await MeasurementDefinitions(session).resolve()
    await database.dispose()
    return resolved


def test_the_seeded_version_carries_the_published_thresholds(definition) -> None:
    assert definition.minimum_visible_fraction == 0.5
    assert definition.minimum_continuous_milliseconds == 1000
    assert definition.minimum_photographs == 5
    assert definition.minimum_gallery_fraction == 0.3
    assert definition.attribution.view_through_days == 7
    assert definition.attribution.engaged_days == 90
    assert definition.session_daily_visible_impression_cap == 3


def test_serving_is_products_own_fact_and_needs_no_observation(definition) -> None:
    """A Served Impression is "we put it in the response" and nothing more.

    Kept distinct from visibility so the two can be reported side by side: a
    served count much larger than the visible count is a real finding about the
    surface, not a measurement bug.
    """
    assert definition.served() is True


@pytest.mark.parametrize(
    ("fraction", "milliseconds", "visible"),
    [
        (0.5, 1000, True),
        (0.5, 999, False),
        (0.4999, 1000, False),
        (0.49, 5000, False),
        (1.0, 1000, True),
        (0.75, 2500, True),
        (0.0, 0, False),
    ],
)
def test_visible_impression_borders_are_inclusive_on_both_axes(
    definition, fraction, milliseconds, visible
) -> None:
    assert (
        definition.visible(
            visible_fraction=fraction, continuous_milliseconds=milliseconds
        )
        is visible
    )


@pytest.mark.parametrize(
    ("photographs", "fraction", "significant"),
    [
        (5, 0.0, True),
        (4, 0.0, False),
        (0, 0.3, True),
        (0, 0.2999, False),
        (4, 0.3, True),
        (20, 1.0, True),
    ],
)
def test_significant_exploration_needs_either_threshold_not_both(
    definition, photographs, fraction, significant
) -> None:
    """Either suffices. Requiring both would break the smallest tier.

    A six-photograph Larevia gallery reaches five photographs at 83 percent, so
    an ``and`` would make the milestone unreachable there and trivial on a
    twenty-photograph Super Premium gallery.
    """
    assert (
        definition.significant_exploration(
            photographs=photographs, gallery_fraction=fraction
        )
        is significant
    )


@pytest.mark.parametrize(
    ("surface", "results", "slots"),
    [
        ("Search", 12, 2),
        ("Search", 6, 1),
        ("Search", 5, 0),
        ("Search", 0, 0),
        ("Search", 24, 4),
        ("Homepage", 0, 2),
        ("Homepage", 40, 2),
    ],
)
def test_slot_counts_follow_the_published_ratios(
    definition, surface, results, slots
) -> None:
    """One sponsored result per six visible ones; at most two on the homepage.

    Integer division on purpose: a five-result page sells nothing. Rounding up
    would let a nearly empty page be a majority-sponsored page.
    """
    assert (
        definition.sponsored_slots(surface=surface, visible_results=results) == slots
    )


def test_a_stored_version_with_different_thresholds_reproduces_its_own_rules() -> None:
    """A historic report keeps its own borders when the current ones move.

    Parsed from raw JSON rather than from the database, because the point is
    that the *stored* numbers decide — not a constant in the code that happens
    to agree with today's row.
    """
    stricter = parse(
        "measurement-v2-test",
        MOMENT,
        {
            "visible_impression": {
                "minimum_visible_fraction": 0.75,
                "minimum_continuous_milliseconds": 2000,
            },
            "significant_gallery_exploration": {
                "minimum_photographs": 10,
                "minimum_gallery_fraction": 0.6,
            },
            "search_visible_results_per_sponsored": 12,
            "homepage_maximum_sponsored": 1,
        },
    )
    assert stricter.visible(visible_fraction=0.5, continuous_milliseconds=1000) is False
    assert stricter.visible(visible_fraction=0.75, continuous_milliseconds=2000) is True
    assert (
        stricter.significant_exploration(photographs=5, gallery_fraction=0.3) is False
    )
    assert stricter.sponsored_slots(surface="Search", visible_results=12) == 1
    assert stricter.sponsored_slots(surface="Homepage", visible_results=12) == 1


def test_an_incomplete_stored_definition_falls_back_to_the_published_defaults() -> None:
    """A row missing a key keeps the published rule rather than becoming zero.

    A defaulted threshold of ``0`` would make every exposure visible, which is
    the most damaging possible reading of a partial row.
    """
    sparse = parse("measurement-sparse-test", MOMENT, {})
    assert sparse.minimum_visible_fraction == 0.5
    assert sparse.minimum_continuous_milliseconds == 1000
    assert sparse.minimum_photographs == 5
    assert sparse.comparable_minimum_sample == 3
    assert sparse.funnel == ()

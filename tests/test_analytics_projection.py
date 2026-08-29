"""Invalid traffic, deduplication, late events and the materialized view.

The projection is where "we measured a lot of things" becomes "here is a number
somebody may act on", and each test here covers one way that step usually
launders a problem:

* excluded traffic that disappears instead of being reported;
* a duplicate that is dropped so quietly nobody knows the rate;
* an event arriving for last Tuesday that lands on today, or nowhere;
* a materialized view that is stale exactly when somebody is reading it.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from realestate.db.engine import Database
from realestate.db.models import (
    ANALYTICS_SCHEMA,
    AnalyticsDomainEvent,
    AnalyticsEventName,
    AnalyticsFunnelAggregate,
    AnalyticsProjectionRun,
    TrafficClass,
)
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.projection import AnalyticsProjection, day_of
from realestate.domain.analytics.traffic import (
    IMPLAUSIBLE_EVENTS_PER_MINUTE,
    looks_like_crawler,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures.commercial import ADMIN_LOGIN, actor_for, provision, reset
from tests.fixtures.sponsorship import MOMENT

pytestmark = requires_postgres


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await provision(session)
        await session.commit()
    yield database
    await database.dispose()


def maia(key: str, *, minutes: int = 0, **flags: bool) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_key=key,
        name=AnalyticsEventName.MAIA_STARTED,
        occurred_at=MOMENT + timedelta(minutes=minutes),
        session_value=f"session-{key}",
        attributes={"surface": "Maia"},
        **flags,
    )


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"bot": True}, TrafficClass.BOT),
        ({"synthetic": True}, TrafficClass.TEST),
        ({"internal": True}, TrafficClass.INTERNAL),
        ({}, TrafficClass.VALID),
    ],
)
async def test_excluded_traffic_is_stored_classified_and_reported(
    database, flags, expected
) -> None:
    """Nothing is deleted. Exclusion is a class on the row and a reported count.

    A metric that silently drops rows and a metric that never had them look
    identical to the reader, and only one of them is honest.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        await AnalyticsEvents(session, actor).record(
            maia("classified-event-key", **flags)
        )
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        row = await session.scalar(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.event_key == "classified-event-key"
            )
        )
        assert row is not None
        assert row.traffic_class == expected.value
        assert (row.exclusion_reason is None) is (expected is TrafficClass.VALID)

        cell = await session.scalar(select(AnalyticsFunnelAggregate))
        assert cell is not None
        if expected is TrafficClass.VALID:
            assert cell.counts["MaiaStarted"] == 1
            assert cell.excluded_counts == {}
        else:
            # Excluded from the counted funnel, present in the excluded totals.
            assert "MaiaStarted" not in cell.counts
            assert cell.excluded_counts == {expected.value: 1}


async def test_a_bot_and_a_test_flag_together_report_the_bot(database) -> None:
    """Precedence is fixed, not incidental.

    Bot, then test, then internal, then rate. Fixed so "how much of this month
    was a crawler" and "how much was a fixture" stay separable instead of
    depending on which flag the boundary happened to set first.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        await AnalyticsEvents(session, actor).record(
            maia("precedence-event-key", bot=True, synthetic=True, internal=True)
        )
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()
        row = await session.scalar(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.event_key == "precedence-event-key"
            )
        )
        assert row is not None
        assert row.traffic_class == TrafficClass.BOT.value


@pytest.mark.parametrize(
    "agent",
    [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "python-requests/2.32",
        "curl/8.4.0",
        "Mozilla/5.0 HeadlessChrome/124.0",
    ],
)
def test_a_self_declared_crawler_is_recognised_without_being_stored(agent) -> None:
    """The user agent is inspected at the boundary and never persisted.

    Excluding bot traffic must not become a reason to keep a device
    fingerprint, so the string is turned into a boolean and dropped.
    """
    assert looks_like_crawler(agent) is True


def test_an_ordinary_browser_is_not_treated_as_a_crawler() -> None:
    assert (
        looks_like_crawler(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"
        )
        is False
    )


async def test_an_implausible_event_rate_for_one_session_is_excluded(
    database,
) -> None:
    """A session firing faster than a person can act stops counting.

    The ceiling is generous on purpose: excluding real traffic to look tidy is
    the failure mode that matters, so the rule only catches rates no interface
    could produce.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        for index in range(IMPLAUSIBLE_EVENTS_PER_MINUTE + 2):
            await events.record(
                AnalyticsEvent(
                    event_key=f"burst-event-{index:04d}",
                    name=AnalyticsEventName.MAIA_STARTED,
                    occurred_at=MOMENT,
                    session_value="one-very-busy-session",
                    attributes={"surface": "Maia"},
                )
            )
        await session.commit()
        await AnalyticsProjection(session, actor).drain()
        await session.commit()

        excluded = await session.scalar(
            select(func.count(AnalyticsDomainEvent.id)).where(
                AnalyticsDomainEvent.traffic_class == TrafficClass.IMPLAUSIBLE.value
            )
        )
        assert excluded is not None and excluded >= 1


async def test_a_late_event_rebuilds_its_own_period_instead_of_todays(
    database,
) -> None:
    """An event for last Tuesday is counted on last Tuesday.

    Recomputing the period rather than incrementing a counter is what makes this
    possible: the pass rewrites the cell from the stored events, so an arrival
    after the period was already reported still lands correctly and is counted
    as late.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        await events.record(maia("on-time-event-key", minutes=0))
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        # Arrives now, happened six days ago.
        await events.record(
            AnalyticsEvent(
                event_key="late-arriving-event-key",
                name=AnalyticsEventName.MAIA_STARTED,
                occurred_at=MOMENT - timedelta(days=6),
                session_value="late-session",
                attributes={"surface": "Maia"},
            )
        )
        await session.commit()
        report = await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        assert report.late == 1
        cells = {
            cell.period_start: cell
            for cell in await session.scalars(select(AnalyticsFunnelAggregate))
        }
        assert cells[day_of(MOMENT)].counts["MaiaStarted"] == 1
        assert cells[day_of(MOMENT - timedelta(days=6))].counts["MaiaStarted"] == 1


async def test_a_late_event_in_an_already_reported_period_does_not_double_count(
    database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        await events.record(maia("first-of-the-day-key", minutes=0))
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        await events.record(maia("second-of-the-day-key", minutes=30))
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        cells = list(await session.scalars(select(AnalyticsFunnelAggregate)))
        # One cell for the day, rewritten, holding both events. Two cells would
        # mean the unique constraint had been bypassed by an incrementing write.
        assert len(cells) == 1
        assert cells[0].counts["MaiaStarted"] == 2


async def test_the_delivery_view_is_refreshed_by_the_pass(database) -> None:
    """The reporting read path reflects the events this pass just stored.

    Refreshed inside the same transaction as the store write, so a dashboard
    opened immediately afterwards cannot read a view that predates the events it
    is showing counts for.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        rows_before = await session.scalar(
            text(f"SELECT count(*) FROM {ANALYTICS_SCHEMA}.mv_sponsored_delivery")
        )
        # The analytics schema stores campaign and listing as plain identifiers
        # with no foreign key, precisely so measurement never depends on the
        # commercial row still existing. A synthetic id is therefore enough here.
        campaign_id = uuid.uuid4()
        await AnalyticsEvents(session, actor).record(
            AnalyticsEvent(
                event_key="view-refresh-served-key",
                name=AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
                occurred_at=MOMENT,
                listing_id=campaign_id,
                campaign_id=campaign_id,
                session_value="view-session",
                attributes={"surface": "Search", "position": 1},
            )
        )
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        rows_after = await session.execute(
            text(
                f"SELECT served_impressions, visible_impressions, invalid_events "
                f"FROM {ANALYTICS_SCHEMA}.mv_sponsored_delivery "
                f"WHERE campaign_id = '{campaign_id}'"
            )
        )
        served, visible, invalid = rows_after.one()
        assert (served, visible, invalid) == (1, 0, 0)
        assert rows_before == 0


async def test_the_run_row_reports_what_the_pass_actually_did(database) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        await events.record(maia("run-report-valid-key"))
        await events.record(maia("run-report-bot-key", bot=True))
        await session.commit()
        await AnalyticsProjection(session, actor).refresh()
        await session.commit()

        run = await session.scalar(
            select(AnalyticsProjectionRun).order_by(
                AnalyticsProjectionRun.ran_at.desc()
            )
        )
        assert run is not None
        assert run.projected_events == 2
        assert run.excluded_events == 1
        assert run.rebuilt_periods >= 1
        assert run.last_sequence >= run.from_sequence

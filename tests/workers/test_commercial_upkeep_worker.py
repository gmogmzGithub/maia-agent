"""The upkeep worker paces the time-driven rules against a one-second loop.

The background loop ticks once a second. The rules it drives have 28- and
90-day horizons. Without a guard the pass issued three queries and two empty
commits every second — roughly 86,400 passes a day, essentially all of them
scanning to discover there was nothing to do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from realestate.db.engine import Database
from realestate.domain.commercial.maintenance import (
    UPKEEP_INTERVAL_SECONDS,
    MaintenanceReport,
)
from realestate.worker.upkeep import CommercialUpkeepWorker
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_the_interval_is_long_enough_to_be_worth_having() -> None:
    """A quarter-hour is indistinguishable from a second to a 28-day rule."""
    assert UPKEEP_INTERVAL_SECONDS >= 300


def test_the_first_pass_after_startup_is_owed() -> None:
    """A process restarted often would otherwise never reach the rules."""
    worker = CommercialUpkeepWorker(database=None)  # type: ignore[arg-type]

    assert worker.due_at is None
    assert worker.due(NOW) is True


def test_a_pass_is_not_owed_again_until_the_interval_elapses() -> None:
    worker = CommercialUpkeepWorker(database=None, interval_seconds=900)  # type: ignore[arg-type]
    worker._last_run = NOW

    assert worker.due_at == NOW + timedelta(seconds=900)
    assert worker.due(NOW) is False
    assert worker.due(NOW + timedelta(seconds=899)) is False
    assert worker.due(NOW + timedelta(seconds=900)) is True


@requires_postgres
async def test_a_tick_inside_the_interval_does_no_work_at_all(monkeypatch) -> None:
    """Skipped means skipped: no session, no query, no commit."""
    database = Database(DATABASE_URL)
    try:
        worker = CommercialUpkeepWorker(database=database, interval_seconds=3600)

        first = await worker.tick()
        assert isinstance(first, MaintenanceReport)

        def forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a skipped tick must not open a session")

        monkeypatch.setattr(database, "session_scope", forbidden)
        assert await worker.tick() is None
    finally:
        await database.dispose()


@requires_postgres
async def test_a_failing_pass_does_not_retry_every_second(monkeypatch) -> None:
    """The clock advances before the work, as the Broker notifier's does.

    Otherwise a failing pass would run again on the very next tick — a query
    flood with nothing accomplished at the end of it.
    """
    from realestate.worker import upkeep as upkeep_module

    database = Database(DATABASE_URL)
    try:
        worker = CommercialUpkeepWorker(database=database, interval_seconds=3600)
        assert worker.due_at is None

        async def failing_run(self, *, now=None):  # noqa: ANN001, ANN202
            raise RuntimeError("PostgreSQL went away mid-pass")

        monkeypatch.setattr(
            upkeep_module.CommercialMaintenance, "run", failing_run
        )
        with pytest.raises(RuntimeError):
            await worker.tick()

        assert worker.due_at is not None
        assert worker.due(datetime.now(tz=UTC)) is False
    finally:
        await database.dispose()


@requires_postgres
async def test_the_pass_runs_the_rules_when_it_is_owed() -> None:
    from datetime import timedelta as delta

    from realestate.db.models import Opportunity, OpportunityStage
    from realestate.domain.commercial.maintenance import DORMANCY_DAYS

    database = Database(DATABASE_URL)
    try:
        async with database.session_scope() as session:
            await commercial.reset(session)
            await commercial.provision(session)
            state = await commercial.opportunity_for(session, "5213355551234")
            opportunity = await session.get(Opportunity, state.opportunity_id)
            assert opportunity is not None
            opportunity.last_activity_at = datetime.now(tz=UTC) - delta(
                days=DORMANCY_DAYS + 1
            )
            await session.commit()

        report = await CommercialUpkeepWorker(database=database).tick()

        assert report is not None
        assert report.dormant_opportunities == 1
        async with database.session_scope() as session:
            opportunity = await session.get(Opportunity, state.opportunity_id)
            assert opportunity is not None
            assert opportunity.stage == OpportunityStage.DORMANT.value
    finally:
        await database.dispose()

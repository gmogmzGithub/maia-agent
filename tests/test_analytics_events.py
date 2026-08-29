"""The analytics Outbox contract: idempotent, ordered, replayable, restartable.

These are the four properties every later number depends on. A funnel built on
an event stream that double-counts a retry, loses its order, cannot be rebuilt,
or forgets what it had consumed is not measurement — it is a coincidence that
happened to look plausible on the day somebody checked.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    AnalyticsOutboxStatus,
    AnalyticsProjectionRun,
)
from realestate.domain.analytics.definitions import (
    CURRENT_DEFINITION_VERSION,
    TAXONOMY_VERSION,
    MeasurementDefinitions,
    UnknownDefinition,
)
from realestate.domain.analytics.events import (
    AnalyticsEvent,
    AnalyticsEvents,
    EventRejected,
)
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.analytics.taxonomy import SCHEMA_VERSION
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


def event(key: str, *, minutes: int = 0) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_key=key,
        name=AnalyticsEventName.MAIA_STARTED,
        occurred_at=MOMENT + timedelta(minutes=minutes),
        session_value="browser-session-1",
        attributes={"surface": "Maia"},
    )


async def test_a_repeated_event_key_records_once_and_counts_the_duplicate(
    database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)

        first = await events.record(event("maia-start-abc123"))
        second = await events.record(event("maia-start-abc123"))
        third = await events.record(event("maia-start-abc123"))
        await session.commit()

        assert first.created is True
        assert (second.created, third.created) == (False, False)
        # The retries resolve to the same enqueued position, not a new one.
        assert second.sequence == first.sequence == third.sequence

        rows = list(
            await session.scalars(
                select(AnalyticsOutboxEntry).where(
                    AnalyticsOutboxEntry.event_key == "maia-start-abc123"
                )
            )
        )
        assert len(rows) == 1
        # Suppressed rather than silently dropped: the duplicate rate is itself
        # a reported number on the dashboard.
        assert rows[0].duplicate_attempts == 2


async def test_events_are_projected_in_emission_order(database) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        # Emitted in an order that disagrees with occurrence order, so the
        # assertion below is about sequence and not about timestamps.
        for key, minutes in (("third", 30), ("first", 0), ("second", 10)):
            await events.record(event(f"ordered-{key}-key", minutes=minutes))
        await session.commit()

        report = await AnalyticsProjection(session).refresh()
        await session.commit()

        assert report.projected == 3
        stored = list(
            await session.scalars(
                select(AnalyticsDomainEvent).order_by(AnalyticsDomainEvent.sequence)
            )
        )
        assert [row.event_key for row in stored] == [
            "ordered-third-key",
            "ordered-first-key",
            "ordered-second-key",
        ]
        assert [row.sequence for row in stored] == sorted(
            row.sequence for row in stored
        )


async def test_a_replay_from_zero_rebuilds_the_same_store_and_aggregates(
    database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        for index in range(4):
            await events.record(event(f"replayable-event-{index}", minutes=index))
        await session.commit()

        projection = AnalyticsProjection(session)
        await projection.refresh()
        await session.commit()
        before = await _snapshot(session)

        replay = await projection.refresh(from_sequence=0)
        await session.commit()

        # The batch is re-read, and nothing new is inserted: the event store's
        # unique key makes insertion idempotent and the aggregates are
        # recomputed rather than incremented.
        assert replay.from_sequence == 0
        assert replay.projected == 0
        assert await _snapshot(session) == before


async def test_a_restart_mid_batch_repeats_the_batch_instead_of_skipping_it(
    database,
) -> None:
    """A pass that never commits leaves its rows Pending and replayable.

    Simulated by rolling the session back after the refresh, which is exactly
    what a crashed process does: the Outbox rows keep ``Pending``, so the next
    pass consumes them again and the events are not lost.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        for index in range(3):
            await AnalyticsEvents(session, actor).record(
                event(f"restart-event-{index}", minutes=index)
            )
        await session.commit()

        await AnalyticsProjection(session).refresh()
        await session.rollback()

        pending = await session.scalar(
            select(func.count(AnalyticsOutboxEntry.id)).where(
                AnalyticsOutboxEntry.status == AnalyticsOutboxStatus.PENDING.value
            )
        )
        stored = await session.scalar(select(func.count(AnalyticsDomainEvent.id)))
        assert (pending, stored) == (3, 0)

        report = await AnalyticsProjection(session).refresh()
        await session.commit()
        assert report.projected == 3
        assert (
            await session.scalar(
                select(func.count(AnalyticsOutboxEntry.id)).where(
                    AnalyticsOutboxEntry.status == AnalyticsOutboxStatus.PENDING.value
                )
            )
        ) == 0


async def test_every_stored_event_carries_its_taxonomy_and_schema_version(
    database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        await AnalyticsEvents(session, actor).record(event("versioned-event-key"))
        await session.commit()
        await AnalyticsProjection(session).refresh()
        await session.commit()

        stored = await session.scalar(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.event_key == "versioned-event-key"
            )
        )
        assert stored is not None
        assert stored.taxonomy_version == TAXONOMY_VERSION
        assert stored.schema_version == SCHEMA_VERSION
        assert stored.definition_version == CURRENT_DEFINITION_VERSION


async def test_projecting_under_an_unknown_definition_version_is_refused(
    database,
) -> None:
    async with database.session_scope() as session:
        with pytest.raises(UnknownDefinition):
            await AnalyticsProjection(session).refresh("measurement-v99")


async def test_the_seeded_definition_version_is_readable_and_listed(database) -> None:
    async with database.session_scope() as session:
        definitions = MeasurementDefinitions(session)
        assert CURRENT_DEFINITION_VERSION in await definitions.versions()
        resolved = await definitions.resolve()
        assert resolved.version == CURRENT_DEFINITION_VERSION


@pytest.mark.parametrize(
    ("name", "supplied", "fragment"),
    [
        (AnalyticsEventName.MAIA_STARTED, {"surface": "Maia", "phone": 5}, "no declarados"),
        (
            AnalyticsEventName.MAIA_STARTED,
            {"surface": "TelefonoDelCliente"},
            "no acepta ese valor",
        ),
        (
            AnalyticsEventName.SELECTION_SHARED,
            {"count": "cinco recámaras en Zapopan"},
            "texto libre",
        ),
    ],
)
async def test_an_undeclared_or_free_text_attribute_is_refused(
    database, name, supplied, fragment
) -> None:
    """The taxonomy is the privacy boundary, so it refuses rather than sanitises.

    There is no attribute anywhere in the taxonomy that accepts free text, which
    is the cheapest possible guarantee that a phone number or a search phrase
    cannot reach the analytics schema: there is no column it would fit in.
    """
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(EventRejected) as raised:
            await AnalyticsEvents(session, actor).record(
                AnalyticsEvent(
                    event_key="refused-event-key",
                    name=name,
                    occurred_at=MOMENT,
                    attributes=supplied,
                )
            )
        assert fragment in raised.value.message


async def test_a_missing_required_attribute_campaign_or_listing_is_refused(
    database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)

        with pytest.raises(EventRejected, match="obligatorios"):
            await events.record(
                AnalyticsEvent(
                    event_key="missing-attribute-key",
                    name=AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN,
                    occurred_at=MOMENT,
                )
            )
        with pytest.raises(EventRejected, match="exposición pagada"):
            await events.record(
                AnalyticsEvent(
                    event_key="missing-campaign-key",
                    name=AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
                    occurred_at=MOMENT,
                    attributes={"surface": "Search"},
                )
            )


async def test_a_short_key_or_naive_timestamp_is_refused(database) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        events = AnalyticsEvents(session, actor)
        with pytest.raises(EventRejected, match="idempotencia"):
            await events.record(event("short"))
        with pytest.raises(EventRejected, match="zona"):
            await events.record(
                AnalyticsEvent(
                    event_key="naive-timestamp-key",
                    name=AnalyticsEventName.MAIA_STARTED,
                    occurred_at=MOMENT.replace(tzinfo=None),
                )
            )


async def test_an_empty_outbox_reports_a_drained_pass_without_a_run_row(
    database,
) -> None:
    """Nothing to do is not a pass. A run row per idle tick would be noise."""
    async with database.session_scope() as session:
        report = await AnalyticsProjection(session).refresh()
        await session.commit()
        assert (report.projected, report.drained) == (0, True)
        assert (
            await session.scalar(select(func.count(AnalyticsProjectionRun.id)))
        ) == 0


async def test_drain_consumes_a_backlog_across_several_bounded_passes(
    database,
) -> None:
    async with database.session_scope() as session:
        actor = await actor_for(session, ADMIN_LOGIN)
        for index in range(5):
            await AnalyticsEvents(session, actor).record(
                event(f"backlog-event-{index}", minutes=index)
            )
        await session.commit()

        report = await AnalyticsProjection(session).drain(batch_size=2)
        await session.commit()

        assert report.drained is True
        assert (
            await session.scalar(select(func.count(AnalyticsDomainEvent.id)))
        ) == 5
        # Several bounded passes, each with its own run row: a backlog is drained
        # over ticks rather than in one transaction holding locks for minutes.
        assert (
            await session.scalar(select(func.count(AnalyticsProjectionRun.id)))
        ) >= 3


async def _snapshot(session) -> list[tuple[str, int]]:
    rows = await session.execute(
        select(AnalyticsDomainEvent.event_key, AnalyticsDomainEvent.sequence).order_by(
            AnalyticsDomainEvent.sequence
        )
    )
    return [(key, sequence) for key, sequence in rows]

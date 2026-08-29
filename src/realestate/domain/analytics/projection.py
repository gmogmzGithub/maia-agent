"""``AnalyticsProjection.refresh`` — drain the Outbox, rebuild the aggregates.

The projection is the only writer of the event store, the aggregates and the
materialized view, and it is written to be safe to run again. Three properties
make that true, and each one exists because the obvious implementation would
lose data:

* **Ordering and resumption.** Rows are consumed in ``sequence`` order and left
  ``Pending`` until the same transaction that stores their event marks them
  ``Projected``. A restart mid-batch repeats the batch instead of skipping it.
* **Idempotent insertion.** The event store's unique ``event_key`` means a
  repeated batch inserts nothing new, so a replay from sequence zero rebuilds
  exactly the same store.
* **Recomputed periods.** An aggregate cell is deleted and rewritten from the
  events for its period, never incremented. That is what makes a late event
  correct: an event arriving today for last Tuesday rebuilds last Tuesday
  rather than being added to today or dropped for being old.

The pass counts what it did — projected, excluded, late, periods rebuilt — into
``analytics.projection_runs``, because "the numbers moved and nobody knows why"
is the failure this table exists to prevent.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ANALYTICS_SCHEMA,
    AnalyticsDomainEvent,
    AnalyticsEventName,
    AnalyticsFunnelAggregate,
    AnalyticsOutboxEntry,
    AnalyticsOutboxStatus,
    AnalyticsProjectionRun,
    TrafficClass,
)
from realestate.domain.analytics.definitions import (
    Definition,
    MeasurementDefinitions,
)
from realestate.domain.analytics.taxonomy import FUNNEL_STEP_FOR_EVENT
from realestate.domain.analytics.traffic import TrafficClassifier
from realestate.domain.clock import utc_now

#: How many Outbox rows one pass consumes. Bounded so a backlog is drained over
#: several loop ticks instead of one transaction that holds locks for minutes.
BATCH_SIZE = 500

#: The materialized view the reporting read path uses.
DELIVERY_VIEW = f"{ANALYTICS_SCHEMA}.mv_sponsored_delivery"

#: One aggregate period. Day grain, so the interval is a day wide.
PERIOD = timedelta(days=1)


def day_of(moment: datetime) -> datetime:
    """The UTC day one event belongs to.

    UTC rather than ``America/Mexico_City`` deliberately: the aggregate is the
    reproducible storage grain, and a local-day grain would move every historic
    cell the first time the offset changed. Reports label periods in local time
    when they render them.
    """
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class RefreshReport:
    """What one projection pass consumed and rebuilt."""

    definition_version: str
    from_sequence: int
    last_sequence: int
    projected: int
    excluded: int
    late: int
    rebuilt_periods: int
    drained: bool

    @property
    def changed(self) -> bool:
        return self.projected > 0


@dataclass(frozen=True)
class _Cell:
    """The identity of one aggregate cell."""

    organization_id: uuid.UUID
    period_start: datetime
    campaign_id: uuid.UUID | None
    listing_id: uuid.UUID | None
    surface: str | None
    sponsored: bool


class AnalyticsProjection:
    """Project enqueued events into versioned, reproducible aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh(
        self,
        version: str | None = None,
        *,
        from_sequence: int | None = None,
        at: datetime | None = None,
        batch_size: int = BATCH_SIZE,
    ) -> RefreshReport:
        """Project one batch under *version* and rebuild the periods it touched.

        ``from_sequence`` replays: passing ``0`` re-reads every Outbox row
        regardless of status, which is safe because insertion is idempotent and
        aggregation is a recomputation. Left unset, the pass consumes only what
        is still ``Pending``.
        """
        moment = at or utc_now()
        definition = await MeasurementDefinitions(self._session).resolve(version)
        replaying = from_sequence is not None
        start = from_sequence or 0

        statement = (
            select(AnalyticsOutboxEntry)
            .where(AnalyticsOutboxEntry.sequence > start)
            .order_by(AnalyticsOutboxEntry.sequence)
            .limit(batch_size)
        )
        if not replaying:
            statement = statement.where(
                AnalyticsOutboxEntry.status == AnalyticsOutboxStatus.PENDING.value
            )
        rows = list(await self._session.scalars(statement))
        if not rows:
            return RefreshReport(
                definition_version=definition.version,
                from_sequence=start,
                last_sequence=start,
                projected=0,
                excluded=0,
                late=0,
                rebuilt_periods=0,
                drained=True,
            )

        # The watermark before this batch. An event whose day is at or before it
        # is late: its period has already been aggregated and reported.
        watermark = await self._latest_period(definition.version)
        classifier = TrafficClassifier(self._session)
        touched: set[_Cell] = set()
        projected = excluded = late = 0

        for row in rows:
            payload = dict(row.payload)
            classification = await classifier.classify(
                payload, occurred_at=row.occurred_at
            )
            event = self._event_for(row, payload, definition, classification, moment)
            inserted = await self._store(event)
            row.status = AnalyticsOutboxStatus.PROJECTED.value
            row.projected_at = moment
            if not inserted:
                continue
            projected += 1
            if not classification.counts:
                excluded += 1
            period = day_of(row.occurred_at)
            if watermark is not None and period <= watermark:
                late += 1
            touched.add(
                _Cell(
                    organization_id=row.organization_id,
                    period_start=period,
                    campaign_id=event.campaign_id,
                    listing_id=event.listing_id,
                    surface=event.surface,
                    sponsored=event.sponsored,
                )
            )

        rebuilt = await self._rebuild(definition, touched, moment)
        await self._refresh_view()
        last = rows[-1].sequence
        self._session.add(
            AnalyticsProjectionRun(
                definition_version=definition.version,
                from_sequence=start,
                last_sequence=last,
                projected_events=projected,
                late_events=late,
                excluded_events=excluded,
                rebuilt_periods=rebuilt,
                ran_at=moment,
            )
        )
        await self._session.flush()
        return RefreshReport(
            definition_version=definition.version,
            from_sequence=start,
            last_sequence=last,
            projected=projected,
            excluded=excluded,
            late=late,
            rebuilt_periods=rebuilt,
            drained=len(rows) < batch_size,
        )

    async def drain(
        self,
        version: str | None = None,
        *,
        at: datetime | None = None,
        batch_size: int = BATCH_SIZE,
        max_passes: int = 20,
    ) -> RefreshReport:
        """Run passes until the Outbox is empty, or *max_passes* is reached."""
        report = await self.refresh(version, at=at, batch_size=batch_size)
        passes = 1
        while not report.drained and passes < max_passes:
            report = await self.refresh(version, at=at, batch_size=batch_size)
            passes += 1
        return report

    # -- one event ---------------------------------------------------------

    @staticmethod
    def _event_for(
        row: AnalyticsOutboxEntry,
        payload: dict[str, Any],
        definition: Definition,
        classification: Any,
        moment: datetime,
    ) -> AnalyticsDomainEvent:
        attributes = dict(payload.get("attributes") or {})
        listing = payload.get("listing_id")
        campaign = payload.get("campaign_id")
        name = AnalyticsEventName(row.event_name)
        return AnalyticsDomainEvent(
            sequence=row.sequence,
            organization_id=row.organization_id,
            event_key=row.event_key,
            event_name=row.event_name,
            schema_version=row.schema_version,
            taxonomy_version=row.taxonomy_version,
            definition_version=definition.version,
            traffic_class=classification.traffic_class.value,
            exclusion_reason=classification.reason,
            subject_reference=str(payload.get("subject_reference") or "") or None,
            session_reference=str(payload.get("session_reference") or "") or None,
            listing_id=uuid.UUID(str(listing)) if listing else None,
            campaign_id=uuid.UUID(str(campaign)) if campaign else None,
            surface=str(attributes.get("surface")) if attributes.get("surface") else None,
            placement_position=(
                int(attributes["position"]) if "position" in attributes else None
            ),
            sponsored=campaign is not None
            or name
            in {
                AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
                AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION,
            },
            attributes=attributes,
            occurred_at=row.occurred_at,
            projected_at=moment,
        )

    async def _store(self, event: AnalyticsDomainEvent) -> bool:
        """Insert one event, or report that it was already stored.

        ``ON CONFLICT DO NOTHING`` rather than a read-then-write: the read would
        make a replay racing a live pass insert twice, and the whole reason this
        module can be re-run is that it cannot.
        """
        statement = (
            insert(AnalyticsDomainEvent)
            .values(
                id=uuid.uuid4(),
                sequence=event.sequence,
                organization_id=event.organization_id,
                event_key=event.event_key,
                event_name=event.event_name,
                schema_version=event.schema_version,
                taxonomy_version=event.taxonomy_version,
                definition_version=event.definition_version,
                traffic_class=event.traffic_class,
                exclusion_reason=event.exclusion_reason,
                subject_reference=event.subject_reference,
                session_reference=event.session_reference,
                listing_id=event.listing_id,
                campaign_id=event.campaign_id,
                surface=event.surface,
                placement_position=event.placement_position,
                sponsored=event.sponsored,
                attributes=event.attributes,
                occurred_at=event.occurred_at,
                projected_at=event.projected_at,
            )
            .on_conflict_do_nothing(index_elements=["event_key"])
            .returning(AnalyticsDomainEvent.id)
        )
        return (await self._session.execute(statement)).scalar() is not None

    # -- aggregates --------------------------------------------------------

    async def _latest_period(self, version: str) -> datetime | None:
        latest: datetime | None = await self._session.scalar(
            select(func.max(AnalyticsFunnelAggregate.period_start)).where(
                AnalyticsFunnelAggregate.definition_version == version
            )
        )
        return latest

    async def _rebuild(
        self, definition: Definition, cells: set[_Cell], moment: datetime
    ) -> int:
        """Recompute each touched cell from the stored events.

        Per cell rather than per day across the whole store: a pass that
        rebuilt every period would make the cost of one late event proportional
        to the campaign's whole history.
        """
        for cell in sorted(
            cells,
            key=lambda item: (
                item.period_start,
                str(item.campaign_id),
                str(item.listing_id),
                str(item.surface),
            ),
        ):
            counts, excluded = await self._counts(definition, cell)
            await self._session.execute(
                delete(AnalyticsFunnelAggregate).where(
                    AnalyticsFunnelAggregate.definition_version == definition.version,
                    AnalyticsFunnelAggregate.organization_id == cell.organization_id,
                    AnalyticsFunnelAggregate.grain == "day",
                    AnalyticsFunnelAggregate.period_start == cell.period_start,
                    AnalyticsFunnelAggregate.campaign_id.is_not_distinct_from(
                        cell.campaign_id
                    ),
                    AnalyticsFunnelAggregate.listing_id.is_not_distinct_from(
                        cell.listing_id
                    ),
                    AnalyticsFunnelAggregate.surface.is_not_distinct_from(cell.surface),
                    AnalyticsFunnelAggregate.sponsored == cell.sponsored,
                )
            )
            self._session.add(
                AnalyticsFunnelAggregate(
                    definition_version=definition.version,
                    organization_id=cell.organization_id,
                    period_start=cell.period_start,
                    grain="day",
                    campaign_id=cell.campaign_id,
                    listing_id=cell.listing_id,
                    surface=cell.surface,
                    sponsored=cell.sponsored,
                    counts=counts,
                    excluded_counts=excluded,
                    refreshed_at=moment,
                )
            )
        await self._session.flush()
        return len(cells)

    async def _counts(
        self, definition: Definition, cell: _Cell
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        rows = list(
            await self._session.scalars(
                select(AnalyticsDomainEvent).where(
                    AnalyticsDomainEvent.definition_version == definition.version,
                    AnalyticsDomainEvent.organization_id == cell.organization_id,
                    AnalyticsDomainEvent.occurred_at >= cell.period_start,
                    AnalyticsDomainEvent.occurred_at < cell.period_start + PERIOD,
                    AnalyticsDomainEvent.campaign_id.is_not_distinct_from(
                        cell.campaign_id
                    ),
                    AnalyticsDomainEvent.listing_id.is_not_distinct_from(
                        cell.listing_id
                    ),
                    AnalyticsDomainEvent.surface.is_not_distinct_from(cell.surface),
                    AnalyticsDomainEvent.sponsored == cell.sponsored,
                )
            )
        )
        counts: dict[str, int] = defaultdict(int)
        excluded: dict[str, int] = defaultdict(int)
        sessions: set[str] = set()
        for row in rows:
            if row.traffic_class != TrafficClass.VALID.value:
                excluded[row.traffic_class] += 1
                continue
            counts[row.event_name] += 1
            step = FUNNEL_STEP_FOR_EVENT.get(AnalyticsEventName(row.event_name))
            if step is not None:
                counts[f"step:{step}"] += 1
            if (
                row.event_name
                == AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value
                and row.session_reference
            ):
                sessions.add(row.session_reference)
        if sessions:
            counts["visible_sessions"] = len(sessions)
        return dict(sorted(counts.items())), dict(sorted(excluded.items()))

    async def _refresh_view(self) -> None:
        """Rebuild the delivery materialized view.

        Not ``CONCURRENTLY``: PostgreSQL refuses that inside a transaction
        block, and this pass is deliberately one transaction so a crash cannot
        leave events stored with their Outbox rows still pending.
        """
        await self._session.execute(text(f"REFRESH MATERIALIZED VIEW {DELIVERY_VIEW}"))

"""The measurement and sponsorship pass, run on its own clock.

Four responsibilities, all of them time-driven and none of them urgent:

1. emit the operational analytics events from recorded commercial truth;
2. drain the analytics Outbox into the event store and rebuild the aggregates;
3. account for one service date per live sponsorship campaign, pausing what is
   no longer eligible and preserving its remaining paid days;
4. expire quotes past their seventh day.

It carries its own interval for the reason
:class:`~realestate.worker.upkeep.CommercialUpkeepWorker` does: the background
loop ticks once a second, and a daily rule asked 86,400 times a day is 86,399
wasted scans. The pass is also idempotent per day, so the interval is a cost
control rather than a correctness requirement — a restart that runs it twice in
one minute changes nothing.

Nothing in here can reach a Contact. It writes no Outbox row, requests no
outbound message and takes no commercial decision a human did not already record.

Since Stage 9 the pass runs **once per operating Organization**, with its own
``Actor`` each time. It used to resolve "the Organization" by slug, which with a
second one would have emitted the founding brokerage's events for everybody's
traffic and left the newcomer's dashboard empty. The projection itself is drained
once, because the emission sequence is one monotonic stream and the events in it
each carry their own Organization (ADR-0050).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from realestate.db.engine import Database
from realestate.domain.analytics.emission import AnalyticsEmission
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor
from realestate.domain.platform.registry import operating_organization_ids
from realestate.domain.sponsorship.campaigns import SponsorshipCampaigns
from realestate.domain.sponsorship.quoting import SponsorshipQuoting

logger = logging.getLogger(__name__)

#: How often the pass runs. Five minutes keeps the dashboard close enough to
#: live for an operator while leaving the loop free for the work customers are
#: waiting on.
ANALYTICS_INTERVAL_SECONDS = 300.0


@dataclass(frozen=True)
class AnalyticsPassReport:
    """What one pass did, for the log line and the tests."""

    emitted: int = 0
    projected: int = 0
    late: int = 0
    #: Live campaigns the pass looked at. Examining one is not doing anything to
    #: it, which is why this is separate from ``days_counted`` below — otherwise
    #: every idle pass would log as if it had changed something.
    campaigns_examined: int = 0
    #: Campaigns that consumed a paid day on this service date.
    days_counted: int = 0
    campaigns_paused: int = 0
    quotes_expired: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.emitted
            or self.projected
            or self.days_counted
            or self.campaigns_paused
            or self.quotes_expired
        )


class AnalyticsWorker:
    """Paces the measurement and sponsorship passes against the loop."""

    def __init__(
        self,
        database: Database,
        *,
        interval_seconds: float = ANALYTICS_INTERVAL_SECONDS,
    ) -> None:
        self._database = database
        self._interval = timedelta(seconds=interval_seconds)
        # None means "never run", so the first tick after startup does a pass.
        # A process restarted every few minutes would otherwise never reach the
        # daily rules at all.
        self._last_run: datetime | None = None

    @property
    def due_at(self) -> datetime | None:
        if self._last_run is None:
            return None
        return self._last_run + self._interval

    def due(self, now: datetime) -> bool:
        return self._last_run is None or now >= self._last_run + self._interval

    async def tick(self, *, now: datetime | None = None) -> AnalyticsPassReport:
        moment = now or utc_now()
        if not self.due(moment):
            return AnalyticsPassReport()
        self._last_run = moment
        report = await self.run(now=moment)
        if report.changed:
            logger.info(
                "Analytics pass: emitted=%d projected=%d late=%d examined=%d "
                "days_counted=%d paused=%d quotes_expired=%d",
                report.emitted,
                report.projected,
                report.late,
                report.campaigns_examined,
                report.days_counted,
                report.campaigns_paused,
                report.quotes_expired,
            )
        return report

    async def run(self, *, now: datetime | None = None) -> AnalyticsPassReport:
        """One pass, ignoring the interval. The seam the suites drive."""
        moment = now or utc_now()
        emitted = 0
        examined = 0
        counted = 0
        paused = 0
        expired = 0
        projected = 0
        late = 0
        async with self._database.session_scope() as session:
            for organization_id in await operating_organization_ids(session):
                actor = Actor.product(organization_id, "AnalyticsWorker")

                emitted += (
                    await AnalyticsEmission(session, actor).emit_operational()
                ).total

                outcomes = await SponsorshipCampaigns(session, actor).run_daily(
                    at=moment
                )
                examined += len(outcomes)
                paused += sum(1 for item in outcomes if item.decision.blocked)
                counted += sum(1 for item in outcomes if item.counted)

                expired += await SponsorshipQuoting(session, actor).expire_due(
                    at=moment
                )

                projection = await AnalyticsProjection(session, actor).drain(at=moment)
                projected += projection.projected
                late += projection.late
            await session.commit()
        return AnalyticsPassReport(
            emitted=emitted,
            projected=projected,
            late=late,
            campaigns_examined=examined,
            days_counted=counted,
            campaigns_paused=paused,
            quotes_expired=expired,
        )

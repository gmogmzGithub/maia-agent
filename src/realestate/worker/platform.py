"""The platform's own upkeep: support-grant expiry and usage.

Two responsibilities that share a cadence and nothing else, kept in one worker
for the reason :mod:`realestate.worker.operations` gives: each is a few lines of
"ask the module what is due, then let it do it", and splitting them would produce
two files of scaffolding.

Neither is on the critical path of anything a customer is waiting for, and both
are deliberately *not* the mechanism that enforces their rule:

* a support grant is refused at login resolution the moment it lapses, so access
  does not depend on this worker having run. What the sweep adds is that the
  member row stops being active, which is what an Organization's own
  Administrator sees on their team surface (ADR-0054);
* usage is recomputed rather than incremented, so a pass that runs twice — or
  never — leaves the store correct. What a missed pass costs is freshness of a
  management number, which the surface reporting it states (ADR-0053).

The worker holds no policy. It does not know how long a grant may run, what
counts as a Conversation, or which Organizations are operating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from realestate.db.engine import Database
from realestate.domain.clock import utc_now
from realestate.domain.platform.support import SupportAccess
from realestate.domain.platform.usage import USAGE_INTERVAL_SECONDS, PlatformUsage

logger = logging.getLogger(__name__)

#: How often the grant sweep runs. Minutes rather than hours: the sweep is what
#: makes an expired support engineer disappear from a customer's team surface, and
#: an hour of a stale row there is an hour of an Administrator wondering who that
#: is.
SUPPORT_INTERVAL_SECONDS = 120.0


@dataclass(frozen=True)
class PlatformPassReport:
    """What one pass did."""

    grants_expired: int = 0
    usage_cells: int = 0
    usage_organizations: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.grants_expired or self.usage_cells)


class PlatformWorker:
    """Paces the platform's upkeep against the background loop.

    Two intervals rather than one, because the two rules genuinely differ by an
    order of magnitude: a lapsed support grant should vanish within minutes, and
    recomputing eight aggregates per Organization is worth doing hourly.
    """

    def __init__(
        self,
        database: Database,
        *,
        support_interval_seconds: float = SUPPORT_INTERVAL_SECONDS,
        usage_interval_seconds: float = USAGE_INTERVAL_SECONDS,
    ) -> None:
        self._database = database
        self._support_interval = timedelta(seconds=support_interval_seconds)
        self._usage_interval = timedelta(seconds=usage_interval_seconds)
        # None means "never ran", so the first tick after startup does both.
        self._support_last: datetime | None = None
        self._usage_last: datetime | None = None

    def support_due(self, now: datetime) -> bool:
        return self._support_last is None or now >= self._support_last + self._support_interval

    def usage_due(self, now: datetime) -> bool:
        return self._usage_last is None or now >= self._usage_last + self._usage_interval

    async def tick(self, *, now: datetime | None = None) -> PlatformPassReport:
        moment = now or utc_now()
        expired = 0
        cells = 0
        organizations = 0

        if self.support_due(moment):
            # The clock advances before the work, not after: a pass that raises
            # must not retry every second until it succeeds.
            self._support_last = moment
            async with self._database.session_scope() as session:
                expired = await SupportAccess(session).expire_due(at=moment)
                await session.commit()

        if self.usage_due(moment):
            self._usage_last = moment
            async with self._database.session_scope() as session:
                refresh = await PlatformUsage(session).refresh(at=moment)
                await session.commit()
            cells = refresh.cells
            organizations = refresh.organizations

        report = PlatformPassReport(
            grants_expired=expired,
            usage_cells=cells,
            usage_organizations=organizations,
        )
        if report.changed:
            logger.info(
                "Platform pass: support grants expired=%d, usage cells=%d "
                "across %d organization(s)",
                report.grants_expired,
                report.usage_cells,
                report.usage_organizations,
            )
        return report

    async def run(self, *, now: datetime | None = None) -> PlatformPassReport:
        """One pass, ignoring both intervals. The seam the suites drive."""
        self._support_last = None
        self._usage_last = None
        return await self.tick(now=now)

"""The commercial upkeep worker: run the time-driven rules, but not constantly.

:class:`~realestate.domain.commercial.maintenance.CommercialMaintenance` knows
*what* the time-driven commercial rules are — Property Need staleness, day-28
dormancy, conversation-content expiry. It does not know when it last ran, and it
cannot: a new one is built per pass from a session.

This worker is the object that lives long enough to remember. It exists for the
same reason :class:`~realestate.worker.broker.BrokerNotifier` holds its own
back-off: the background loop ticks once a second, and rules with 28- and 90-day
horizons have no business being asked that often. Without the guard the pass
issues three queries and two empty commits per second — around 86,400 passes a
day, essentially all of them scanning to discover there is nothing to do.

Nothing here can reach a Contact. The Stage 1 eligibility gate remains the only
path to an outbound message, and none of these rules requests one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from realestate.db.engine import Database
from realestate.domain.commercial.maintenance import (
    UPKEEP_INTERVAL_SECONDS,
    CommercialMaintenance,
    MaintenanceReport,
)

logger = logging.getLogger(__name__)


class CommercialUpkeepWorker:
    """Paces :class:`CommercialMaintenance` against the background loop.

    A plain class rather than a closure over the application: the guard has to
    outlive one tick, and a closure would also keep the whole application scope
    alive for as long as the loop runs.
    """

    def __init__(
        self,
        database: Database,
        *,
        interval_seconds: float = UPKEEP_INTERVAL_SECONDS,
    ) -> None:
        self._database = database
        self._interval = timedelta(seconds=interval_seconds)
        # None means "never run", so the first tick after startup does a pass.
        # That matters: a process restarted every few minutes would otherwise
        # never reach the rules at all.
        self._last_run: datetime | None = None

    @property
    def due_at(self) -> datetime | None:
        """When the next pass becomes due, or ``None`` before the first one."""
        if self._last_run is None:
            return None
        return self._last_run + self._interval

    def due(self, now: datetime) -> bool:
        due_at = self.due_at
        return due_at is None or now >= due_at

    async def tick(self) -> MaintenanceReport | None:
        """Run one upkeep pass if one is owed. Returns ``None`` when skipped.

        The clock is advanced before the work, not after, so a pass that raises
        does not retry every second until it succeeds — the same reason the
        Broker notifier backs off rather than hammering a failing send.
        """
        now = datetime.now(tz=UTC)
        if not self.due(now):
            return None
        self._last_run = now
        async with self._database.session_scope() as session:
            report = await CommercialMaintenance(session).run(now=now)
        if not report.any:
            logger.debug("Commercial upkeep found nothing to do")
        return report

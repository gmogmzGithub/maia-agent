"""Drain contributed market facts into the Platform-wide analytical dataset."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from realestate.db.engine import Database
from realestate.domain.clock import utc_now
from realestate.domain.market_intelligence import MarketProjector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketProjectionPass:
    projected: int = 0
    failed: int = 0


class MarketIntelligenceWorker:
    """A paced, retrying central projector; one pass is safe to replay."""

    def __init__(self, database: Database, *, interval_seconds: float = 30.0) -> None:
        self._database = database
        self._interval = timedelta(seconds=interval_seconds)
        self._last_run: datetime | None = None

    async def tick(self, *, now: datetime | None = None) -> MarketProjectionPass:
        moment = now or utc_now()
        if self._last_run is not None and moment < self._last_run + self._interval:
            return MarketProjectionPass()
        self._last_run = moment
        async with self._database.session_scope() as session:
            report = await MarketProjector(session).drain()
            await session.commit()
        if report.projected or report.failed:
            logger.info(
                "Market projection pass: projected=%d failed=%d",
                report.projected,
                report.failed,
            )
        return MarketProjectionPass(report.projected, report.failed)

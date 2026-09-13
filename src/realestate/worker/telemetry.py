"""Paces bounded retention of the redacted operational trace ledger."""

from __future__ import annotations

from datetime import datetime, timedelta

from realestate.domain.clock import utc_now
from realestate.observability.ledger import TraceLedger


class TelemetryRetentionWorker:
    """Deletes one bounded expiry batch per due pass, never business records."""

    def __init__(
        self,
        ledger: TraceLedger,
        *,
        interval_seconds: float,
        batch_size: int,
    ) -> None:
        self._ledger = ledger
        self._interval = timedelta(seconds=interval_seconds)
        self._batch_size = batch_size
        self._last_run: datetime | None = None

    def due(self, now: datetime) -> bool:
        return self._last_run is None or now >= self._last_run + self._interval

    async def tick(self, *, now: datetime | None = None) -> int:
        moment = now or utc_now()
        if not self.due(moment):
            return 0
        # Advance before attempting work: a broken telemetry table should show
        # up in its health component, not hammer Product once per worker tick.
        self._last_run = moment
        return await self._ledger.purge_due(now=moment, limit=self._batch_size)

    async def run(self, *, now: datetime | None = None) -> int:
        """Force one deterministic pass for tests and operator maintenance."""
        self._last_run = None
        return await self.tick(now=now)

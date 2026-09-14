"""One safe path for emitting the telemetry envelope."""

from __future__ import annotations

from fastapi import FastAPI

from realestate.observability.events import TelemetryEvent
from realestate.observability.ledger import TraceLedger
from realestate.observability.metrics import OperationalMetrics


class TelemetryEmitter:
    """The single non-authoritative sink used by API and worker paths."""

    def __init__(self, ledger: TraceLedger, metrics: OperationalMetrics) -> None:
        self._ledger = ledger
        self._metrics = metrics

    async def emit(self, event: TelemetryEvent) -> None:
        self._metrics.record(event)
        await self._ledger.record(event)


async def emit(app: FastAPI, event: TelemetryEvent) -> None:
    """Aggregate then persist telemetry without changing Product authority."""
    telemetry = getattr(app.state, "telemetry", None)
    if telemetry is not None:
        await telemetry.emit(event)

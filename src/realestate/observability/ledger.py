"""Durable, redacted trace milestones and their bounded retention sweep."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from realestate.db.engine import Database
from realestate.db.models import OperationalTraceEvent
from realestate.domain.clock import utc_now
from realestate.observability.events import TelemetryEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetryHealth:
    """Whether diagnostics are being persisted, never whether Product is ready."""

    ok: bool
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"status": "ok" if self.ok else "degraded", "detail": self.detail}


class TraceLedger:
    """Best-effort persistence for the fixed telemetry envelope.

    The recorder deliberately opens an independent database unit of work. A
    failed telemetry insert can therefore never roll back an Inbox, Outbox,
    audit, or other business transaction that the caller already committed.
    """

    def __init__(self, database: Database, *, retention_days: int = 30) -> None:
        self._database = database
        self._retention = timedelta(days=retention_days)
        self._last_failure: str | None = None

    @property
    def health(self) -> TelemetryHealth:
        if self._last_failure is None:
            return TelemetryHealth(ok=True, detail="Operational telemetry writable")
        return TelemetryHealth(ok=False, detail=self._last_failure)

    async def record(self, event: TelemetryEvent) -> bool:
        """Write one event, returning false rather than affecting Product work."""
        # The JSON object is the structured log contract. No arbitrary caller
        # details are merged into it, so message text and exception strings
        # cannot accidentally become an observability field.
        logger.info("telemetry %s", json.dumps(event.as_dict(), sort_keys=True))
        try:
            async with self._database.session_scope() as session:
                session.add(
                    OperationalTraceEvent(
                        organization_id=event.context.organization_id,
                        interaction_id=event.context.interaction_id,
                        attempt_id=event.context.attempt_id,
                        customer_trace_handle=event.context.customer_trace_handle,
                        channel=event.context.channel,
                        occurred_at=event.occurred_at,
                        expires_at=event.occurred_at + self._retention,
                        event_name=event.event_name,
                        stage=event.stage,
                        outcome=event.outcome.value,
                        severity=event.severity.value,
                        duration_ms=event.duration_ms,
                        error_code=event.error_code,
                        error_type=event.error_type,
                        error_fingerprint=event.fingerprint,
                    )
                )
                await session.commit()
        except Exception as exc:  # diagnostics must never reject customer work
            self._last_failure = f"Operational telemetry write failed ({type(exc).__name__})"
            logger.error("Operational telemetry write failed (type=%s)", type(exc).__name__)
            return False
        self._last_failure = None
        return True

    async def purge_due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 500,
    ) -> int:
        """Physically delete one bounded, lock-safe batch of expired events."""
        moment = now or utc_now()
        try:
            async with self._database.session_scope() as session:
                candidates = list(
                    (
                        await session.scalars(
                            select(OperationalTraceEvent.id)
                            .where(OperationalTraceEvent.expires_at <= moment)
                            .order_by(OperationalTraceEvent.expires_at, OperationalTraceEvent.id)
                            .limit(limit)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                if not candidates:
                    await session.rollback()
                    return 0
                deleted = await session.execute(
                    delete(OperationalTraceEvent)
                    .where(OperationalTraceEvent.id.in_(candidates))
                    .returning(OperationalTraceEvent.id)
                )
                count = len(list(deleted))
                await session.commit()
        except Exception as exc:
            self._last_failure = f"Operational telemetry purge failed ({type(exc).__name__})"
            logger.error("Operational telemetry purge failed (type=%s)", type(exc).__name__)
            return 0
        logger.info("Purged %d expired operational trace event(s)", count)
        return count

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import OperationalTraceEvent
from realestate.observability.events import (
    OperationalOutcome,
    TelemetryEvent,
    TelemetrySeverity,
    TraceContext,
)
from realestate.observability.ledger import TraceLedger
from tests.conftest import DATABASE_URL, larevia_organization_id, requires_postgres


@requires_postgres
async def test_trace_ledger_physically_purges_only_expired_rows() -> None:
    database = Database(DATABASE_URL)
    ledger = TraceLedger(database, retention_days=30)
    now = datetime(2026, 9, 13, tzinfo=UTC)
    try:
        async with database.session_scope() as session:
            organization_id = await larevia_organization_id(session)
        old_context = TraceContext.begin(
            organization_id=organization_id,
            customer_trace_handle="cth_1234567890abcdef1234",
            channel="WhatsApp",
        )
        current_context = TraceContext.begin(
            organization_id=organization_id,
            customer_trace_handle="cth_abcdef12345678901234",
            channel="WhatsApp",
        )
        assert await ledger.record(
            TelemetryEvent(
                occurred_at=now - timedelta(days=31),
                context=old_context,
                event_name="inbound.accepted",
                stage="inbound_acceptance",
                outcome=OperationalOutcome.SUCCEEDED,
                severity=TelemetrySeverity.INFO,
            )
        )
        assert await ledger.record(
            TelemetryEvent(
                occurred_at=now,
                context=current_context,
                event_name="worker.group_claimed",
                stage="worker_claim",
                outcome=OperationalOutcome.SUCCEEDED,
                severity=TelemetrySeverity.INFO,
            )
        )

        assert await ledger.purge_due(now=now, limit=1) == 1
        async with database.session_scope() as session:
            remaining = list(
                (
                    await session.scalars(
                        select(OperationalTraceEvent).where(
                            OperationalTraceEvent.interaction_id
                            == old_context.interaction_id
                        )
                    )
                ).all()
            )
        assert remaining == []
    finally:
        async with database.session_scope() as session:
            await session.execute(
                OperationalTraceEvent.__table__.delete().where(
                    OperationalTraceEvent.interaction_id == old_context.interaction_id
                )
            )
            await session.commit()
        await database.dispose()

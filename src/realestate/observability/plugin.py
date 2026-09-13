"""Safe correlation for Product's authenticated Hermes tool boundary."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.api.plugin import SESSION_HEADER
from realestate.config import get_settings
from realestate.db.models import AgentSession, Conversation, InboxMessage, Lead
from realestate.domain.clock import utc_now
from realestate.observability.events import (
    OperationalOutcome,
    TelemetryEvent,
    TelemetrySeverity,
    TraceContext,
    customer_trace_handle,
)


async def record_plugin_tool_call(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Record a typed tool boundary without changing its authority or result."""
    started = time.perf_counter()
    response = await call_next(request)
    try:
        await _record_completed_tool(request, response.status_code, started)
    except Exception:
        # Telemetry must never turn a working tool into a failed operation.
        pass
    return response


async def _record_completed_tool(
    request: Request, status_code: int, started: float
) -> None:
    hermes_session_id = request.headers.get(SESSION_HEADER, "")
    if not hermes_session_id:
        return
    async with request.app.state.database.session_scope() as session:
        binding = await session.scalar(
            select(AgentSession).where(
                AgentSession.hermes_session_id == hermes_session_id
            )
        )
        if binding is None:
            return
        context = await _trace_context(session, binding)
    if context is None:
        return
    outcome, severity, error_code = _http_outcome(status_code)
    await request.app.state.telemetry.emit(
        TelemetryEvent(
            occurred_at=utc_now(),
            context=context,
            event_name="tool.http_completed",
            stage="typed_tool",
            outcome=outcome,
            severity=severity,
            duration_ms=round((time.perf_counter() - started) * 1000),
            error_code=error_code,
            error_type="HttpStatus" if error_code else None,
        )
    )


async def _trace_context(
    session: AsyncSession, binding: AgentSession
) -> TraceContext | None:
    """Resolve a Sales tool to its latest accepted customer interaction.

    The Product owns this derivation: a model or plugin cannot nominate an
    Interaction ID. Administrative tools have no customer interaction and are
    deliberately excluded from this customer trace ledger.
    """
    if binding.cycle_id is None:
        return None
    row = (
        await session.execute(
            select(InboxMessage, Conversation, Lead)
            .join(
                Conversation,
                (Conversation.organization_id == InboxMessage.organization_id)
                & (Conversation.id == InboxMessage.conversation_id),
            )
            .join(
                Lead,
                (Lead.organization_id == Conversation.organization_id)
                & (Lead.id == Conversation.lead_id),
            )
            .where(InboxMessage.organization_id == binding.organization_id)
            .where(Conversation.cycle_id == binding.cycle_id)
            .order_by(InboxMessage.persisted_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    inbox, conversation, lead = row
    settings = get_settings()
    handle = (
        customer_trace_handle(
            key=settings.telemetry_hmac_key,
            organization_id=binding.organization_id,
            channel=inbox.channel,
            channel_account_id=conversation.channel_account_id,
            provider_user_id=lead.wa_id,
        )
        if settings.telemetry_hmac_key
        else None
    )
    return TraceContext(
        interaction_id=inbox.interaction_id or uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        organization_id=binding.organization_id,
        customer_trace_handle=handle,
        channel=inbox.channel,
    )


def _http_outcome(
    status_code: int,
) -> tuple[OperationalOutcome, TelemetrySeverity, str | None]:
    if status_code < 400:
        return OperationalOutcome.SUCCEEDED, TelemetrySeverity.INFO, None
    if status_code < 500:
        return OperationalOutcome.REFUSED_AS_DESIGNED, TelemetrySeverity.WARNING, (
            f"http_{status_code}"
        )
    return OperationalOutcome.FAILED_RETRYABLE, TelemetrySeverity.ERROR, (
        f"http_{status_code}"
    )

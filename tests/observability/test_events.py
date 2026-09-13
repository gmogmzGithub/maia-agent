from __future__ import annotations

import logging
import sys
import uuid
from datetime import UTC, datetime

import pytest

from realestate.observability.events import (
    OperationalOutcome,
    TelemetryEvent,
    TelemetrySeverity,
    TraceContext,
    customer_trace_handle,
)
from realestate.observability.logging import PrivacyFilter, redact
from realestate.observability.metrics import OperationalMetrics


def test_customer_trace_handle_is_stable_scoped_and_never_reveals_source() -> None:
    organization = uuid.uuid4()
    first = customer_trace_handle(
        key="telemetry-test-key",
        organization_id=organization,
        channel="WhatsApp",
        channel_account_id="receiving-account",
        provider_user_id="5213312345678",
    )
    again = customer_trace_handle(
        key="telemetry-test-key",
        organization_id=organization,
        channel="WhatsApp",
        channel_account_id="receiving-account",
        provider_user_id="5213312345678",
    )
    another_organization = customer_trace_handle(
        key="telemetry-test-key",
        organization_id=uuid.uuid4(),
        channel="WhatsApp",
        channel_account_id="receiving-account",
        provider_user_id="5213312345678",
    )

    assert first == again
    assert first != another_organization
    assert first.startswith("cth_")
    assert "5213312345678" not in first


def test_customer_trace_handle_requires_its_dedicated_key() -> None:
    with pytest.raises(ValueError, match="TELEMETRY_HMAC_KEY"):
        customer_trace_handle(
            key="",
            organization_id=uuid.uuid4(),
            channel="WhatsApp",
            channel_account_id="account",
            provider_user_id="identity",
        )


def test_metrics_exclude_trace_and_customer_identifiers() -> None:
    context = TraceContext.begin(
        organization_id=uuid.uuid4(),
        customer_trace_handle="cth_1234567890abcdef1234",
        channel="WhatsApp",
    )
    event = TelemetryEvent(
        occurred_at=datetime(2026, 9, 13, tzinfo=UTC),
        context=context,
        event_name="outbound.delivery.completed",
        stage="outbound_delivery",
        outcome=OperationalOutcome.UNKNOWN_EXTERNAL_OUTCOME,
        severity=TelemetrySeverity.WARNING,
        duration_ms=1_287,
        error_code="provider_timeout",
        error_type="TimeoutError",
    )
    metrics = OperationalMetrics()
    metrics.record(event)

    rendered = metrics.render_prometheus()
    assert 'stage="outbound_delivery"' in rendered
    assert 'error_code="provider_timeout"' in rendered
    assert str(context.interaction_id) not in rendered
    assert str(context.attempt_id) not in rendered
    assert context.customer_trace_handle not in rendered
    assert str(context.organization_id) not in rendered


def test_legacy_log_redaction_hides_phone_url_and_token() -> None:
    raw = (
        "callback https://example.test/webhook?phone=5213312345678 "
        "Authorization=Bearer secret-token"
    )
    safe = redact(raw)

    assert "5213312345678" not in safe
    assert "secret-token" not in safe
    assert "https://example.test" not in safe


def test_privacy_filter_removes_exception_text() -> None:
    record = logging.LogRecord(
        "realestate.test", 40, __file__, 1, "failed for %s", ("5213312345678",), None
    )
    try:
        raise RuntimeError("Bearer secret-token")
    except RuntimeError:
        record.exc_info = sys.exc_info()
    assert PrivacyFilter().filter(record)
    assert "5213312345678" not in record.getMessage()
    assert "secret-token" not in record.getMessage()
    assert "RuntimeError" in record.getMessage()
    assert record.exc_info is None

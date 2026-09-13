"""The stable, redacted event vocabulary for Maia operational telemetry."""

from __future__ import annotations

import enum
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime


class OperationalOutcome(str, enum.Enum):
    SUCCEEDED = "succeeded"
    REFUSED_AS_DESIGNED = "refused_as_designed"
    DEFERRED_FOR_RETRY = "deferred_for_retry"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    UNKNOWN_EXTERNAL_OUTCOME = "unknown_external_outcome"


class TelemetrySeverity(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TraceContext:
    """The non-authoritative identifiers linking one technical interaction."""

    interaction_id: uuid.UUID
    attempt_id: uuid.UUID
    organization_id: uuid.UUID
    customer_trace_handle: str | None
    channel: str | None

    @classmethod
    def begin(
        cls,
        *,
        organization_id: uuid.UUID,
        customer_trace_handle: str | None,
        channel: str | None,
    ) -> "TraceContext":
        return cls(
            interaction_id=uuid.uuid4(),
            attempt_id=uuid.uuid4(),
            organization_id=organization_id,
            customer_trace_handle=customer_trace_handle,
            channel=channel,
        )

    def next_attempt(self) -> "TraceContext":
        return TraceContext(
            interaction_id=self.interaction_id,
            attempt_id=uuid.uuid4(),
            organization_id=self.organization_id,
            customer_trace_handle=self.customer_trace_handle,
            channel=self.channel,
        )


def customer_trace_handle(
    *,
    key: str,
    organization_id: uuid.UUID,
    channel: str,
    channel_account_id: str,
    provider_user_id: str,
) -> str:
    """Return a stable scoped pseudonym, never the source channel identity.

    The handle is intentionally HMAC rather than a bare hash: phone numbers and
    other provider identifiers have small enough input spaces to be guessed.
    Including the Organization and receiving account makes the same provider
    identifier unlinkable across Brokerage Organizations and channel accounts.
    """
    if not key:
        raise ValueError("TELEMETRY_HMAC_KEY is not configured")
    material = "\x1f".join(
        (
            str(organization_id),
            channel,
            channel_account_id,
            provider_user_id,
        )
    ).encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return f"cth_{digest[:20]}"


def error_fingerprint(error_type: str, error_code: str) -> str:
    """A stable grouping key that cannot reproduce an exception message."""
    material = f"{error_type}\x1f{error_code}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:20]


def new_trace_nonce() -> str:
    """Opaque random material for a short-lived Product-minted trace context."""
    return secrets.token_urlsafe(24)


@dataclass(frozen=True)
class TelemetryEvent:
    """The allowlisted envelope written to logs and the trace ledger."""

    occurred_at: datetime
    context: TraceContext
    event_name: str
    stage: str
    outcome: OperationalOutcome
    severity: TelemetrySeverity
    duration_ms: int | None = None
    error_code: str | None = None
    error_type: str | None = None

    @property
    def fingerprint(self) -> str | None:
        if self.error_code is None or self.error_type is None:
            return None
        return error_fingerprint(self.error_type, self.error_code)

    def as_dict(self) -> dict[str, object]:
        """The JSON-safe log shape. Do not add caller-controlled details here."""
        return {
            "schema_version": 1,
            "occurred_at": self.occurred_at.isoformat(),
            "event_name": self.event_name,
            "stage": self.stage,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "interaction_id": str(self.context.interaction_id),
            "attempt_id": str(self.context.attempt_id),
            "organization_id": str(self.context.organization_id),
            "customer_trace_handle": self.context.customer_trace_handle,
            "channel": self.context.channel,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_type": self.error_type,
            "error_fingerprint": self.fingerprint,
        }

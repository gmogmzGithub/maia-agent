"""The durable Outbox (ADR-0005, P-034, P-036).

Nothing reaches a Lead that was not first persisted here. A Hermes draft becomes
an Outbox row only through response settlement, annotated with every Inbox
identifier it covers, and delivery is attempted from the persisted row.

Enqueueing is idempotent on ``idempotency_key``, so at-least-once recovery
upstream cannot produce a second visible reply.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.db.models import (
    Conversation,
    DeliveryStatus,
    OutboxMessage,
    OutboxStatus,
)

# P-036: three total attempts — immediately, after 5s, after 30s.
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (0, 5, 30)


class OutboxKind(str):
    """Why a message exists. Deterministic kinds are never model-authored."""

    AGENT_REPLY = "AgentReply"
    PROCESSING_FAILURE = "ProcessingFailureNotice"
    APPOINTMENT_RESOLUTION = "AppointmentResolution"
    APPOINTMENT_CANCELLATION = "AppointmentCancellation"
    LEAD_FOLLOW_UP = "LeadFollowUp"


# The deterministic contingency response after exhausted processing (P-035).
# Truthful: it acknowledges receipt without claiming the message was handled.
PROCESSING_FAILURE_BODY = (
    "Gracias por tu mensaje. Tuvimos un problema temporal para procesarlo. "
    "Tu mensaje quedó registrado y el concierge lo revisará."
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def retry_delay_seconds(attempts: int) -> int:
    """The P-036 backoff for a row that has already used *attempts* deliveries."""
    return RETRY_DELAYS_SECONDS[min(attempts, len(RETRY_DELAYS_SECONDS) - 1)]


@dataclass(frozen=True)
class Enqueued:
    outbox_id: uuid.UUID
    created: bool


class OutboxService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        conversation: Conversation,
        to_wa_id: str,
        body: str,
        kind: str,
        idempotency_key: str,
        covered_inbox_ids: list[uuid.UUID],
        inbox_group_id: uuid.UUID | None = None,
    ) -> Enqueued:
        """Persist one outbound intent. Repeating the key is a no-op."""
        existing = (
            await self._session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return Enqueued(outbox_id=existing.id, created=False)

        row = OutboxMessage(
            conversation_id=conversation.id,
            inbox_group_id=inbox_group_id,
            idempotency_key=idempotency_key,
            to_wa_id=to_wa_id,
            kind=kind,
            body=body,
            covered_inbox_ids=[str(i) for i in covered_inbox_ids],
            status=OutboxStatus.PENDING.value,
            next_attempt_at=_now(),
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            again = (
                await self._session.execute(
                    select(OutboxMessage).where(
                        OutboxMessage.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one()
            return Enqueued(outbox_id=again.id, created=False)

        return Enqueued(outbox_id=row.id, created=True)

    async def claim_due(self, limit: int = 10) -> list[OutboxMessage]:
        """Take due Pending rows and mark them Sending under a row lock."""
        now = _now()
        rows = list(
            (
                await self._session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.status == OutboxStatus.PENDING.value)
                    .where(
                        (OutboxMessage.next_attempt_at.is_(None))
                        | (OutboxMessage.next_attempt_at <= now)
                    )
                    .order_by(OutboxMessage.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status = OutboxStatus.SENDING.value
            row.attempts += 1
        await self._session.commit()
        return rows

    async def recover_abandoned_sends(self) -> int:
        """Quarantine sends interrupted after their durable claim.

        Once a row is ``Sending`` the process cannot know whether Meta accepted
        the request before it died. Replaying it could duplicate a visible
        message, so restart recovery uses the same conservative outcome as an
        ambiguous live transport failure (P-036).
        """
        rows = list(
            (
                await self._session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.status == OutboxStatus.SENDING.value)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status = OutboxStatus.DELIVERY_UNKNOWN.value
            row.last_error = "Process stopped while the Meta delivery result was unknown."
            row.next_attempt_at = None
        if rows:
            await self._session.commit()
        return len(rows)

    async def record_result(self, row: OutboxMessage, result: SendResult) -> None:
        """Apply Meta's answer to the persisted row.

        The three outcomes are kept distinct on purpose. An ambiguous send
        becomes ``DeliveryUnknown`` and is never replayed automatically, because
        the POC prefers a missing reply over a duplicate one (P-036).
        """
        now = _now()

        if result.outcome is SendOutcome.SENT:
            row.status = OutboxStatus.SENT.value
            row.provider_message_id = result.provider_message_id
            row.sent_at = now
            row.last_error = None
            row.next_attempt_at = None

        elif result.outcome is SendOutcome.UNKNOWN:
            row.status = OutboxStatus.DELIVERY_UNKNOWN.value
            row.last_error = result.detail
            row.next_attempt_at = None

        elif result.outcome is SendOutcome.FAILED_PERMANENT:
            # Authentication, authorization, validation, payload: not retried.
            row.status = OutboxStatus.FAILED.value
            row.last_error = result.detail
            row.next_attempt_at = None

        else:  # FAILED_RETRYABLE
            row.last_error = result.detail
            if row.attempts >= MAX_ATTEMPTS:
                row.status = OutboxStatus.FAILED.value
                row.next_attempt_at = None
            else:
                delay = (
                    result.retry_after_seconds
                    if result.retry_after_seconds is not None
                    else retry_delay_seconds(row.attempts)
                )
                row.status = OutboxStatus.PENDING.value
                row.next_attempt_at = now + timedelta(seconds=delay)

        await self._session.commit()

    async def record_delivery_status(
        self,
        *,
        provider_message_id: str,
        status: str,
        occurred_at: datetime,
        raw: dict,
    ) -> bool:
        """Reconcile a Meta delivery callback onto its Outbox row.

        Persisted as product state rather than a debug log (TC-006). Duplicate
        callbacks are absorbed by the unique constraint.
        """
        outbox = (
            await self._session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.provider_message_id == provider_message_id
                )
            )
        ).scalar_one_or_none()

        self._session.add(
            DeliveryStatus(
                outbox_id=outbox.id if outbox else None,
                provider_message_id=provider_message_id,
                status=status,
                occurred_at=occurred_at,
                raw=raw,
            )
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            return False
        return True

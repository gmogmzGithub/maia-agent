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
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.db.models import (
    ChannelBindingKind,
    Conversation,
    DeliveryStatus,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.platform.routing import OrganizationRouting

# P-036: three total attempts — immediately, after 5s, after 30s.
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (0, 5, 30)


class OutboxKind(str):
    """What a delivered row is. Deterministic kinds are never model-authored.

    Kind labels the persisted message. It does not say whether the message was
    allowed to be sent, and it must never be used to infer that: proactivity is
    carried by ``OutboundIntent.initiation`` (ADR-0045), not by reading a kind.
    """

    AGENT_REPLY = "AgentReply"
    HUMAN_REPLY = "HumanReply"
    PROCESSING_FAILURE = "ProcessingFailureNotice"
    APPOINTMENT_CONFIRMATION = "AppointmentConfirmation"
    APPOINTMENT_RESCHEDULED = "AppointmentRescheduled"
    APPOINTMENT_REMINDER = "AppointmentReminder"
    APPOINTMENT_RESOLUTION = "AppointmentResolution"
    APPOINTMENT_CANCELLATION = "AppointmentCancellation"
    APPOINTMENT_NEEDS_REVIEW = "AppointmentNeedsReview"
    LEAD_FOLLOW_UP = "LeadFollowUp"
    REACTIVATION = "Reactivation"
    DEVELOPMENT_CAMPAIGN = "DevelopmentCampaign"


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
        # Held rather than built per callback, for the same reason as
        # :class:`~realestate.domain.inbox.InboxService`: one webhook body
        # carries many callbacks from the same phone number id.
        self._routing = OrganizationRouting(session)

    async def stage(
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
        """Persist one outbound row *without committing*.

        The committing :meth:`enqueue` cannot be the only option: the eligibility
        decision that authorised a message, the Outbox row itself, and the
        caller's own record of the attempt have to land or fail together
        (ADR-0045). Staging leaves the transaction boundary to the caller.

        Repeating the key is a no-op within this transaction. Two transactions
        racing on the same key are arbitrated by the unique constraint when they
        commit, which callers already handle.
        """
        existing: uuid.UUID | None = await self._session.scalar(
            select(OutboxMessage.id)
            # The key is unique *per Organization* since Stage 9. Reading it
            # without the Organization would let a key another brokerage minted
            # satisfy this one's staging and return their Outbox row.
            .where(OutboxMessage.organization_id == conversation.organization_id)
            .where(OutboxMessage.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return Enqueued(outbox_id=existing, created=False)

        row = OutboxMessage(
            organization_id=conversation.organization_id,
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
        await self._session.flush()
        return Enqueued(outbox_id=row.id, created=True)

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
        """Stage one outbound row and commit it.

        Reserved for tests and recovery tooling that legitimately own their own
        transaction. Product code reaches the Outbox through
        ``OutboundMessaging.request``, which is the only path that establishes
        whether the message may be sent at all.

        Expressed in terms of :meth:`stage` rather than repeating it: the row
        this writes and the row the gate writes must not be able to differ.
        """
        try:
            staged = await self.stage(
                conversation=conversation,
                to_wa_id=to_wa_id,
                body=body,
                kind=kind,
                idempotency_key=idempotency_key,
                covered_inbox_ids=covered_inbox_ids,
                inbox_group_id=inbox_group_id,
            )
            if not staged.created:
                return staged
            await self._session.commit()
        except IntegrityError:
            # The pre-check is advisory; the unique index is the guarantee. The
            # race can surface at the staging flush or at the commit, and both
            # mean the same thing: report the winner's row rather than raise.
            await self._session.rollback()
            again = await self._session.scalar(
                select(OutboxMessage).where(
                    OutboxMessage.idempotency_key == idempotency_key
                )
            )
            if again is None:  # pragma: no cover - the key just conflicted
                raise RuntimeError(
                    f"Outbox key {idempotency_key!r} conflicted but is absent."
                )
            return Enqueued(outbox_id=again.id, created=False)
        return staged

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
        phone_number_id: str,
        provider_message_id: str,
        status: str,
        occurred_at: datetime,
        raw: dict[str, Any],
    ) -> bool:
        """Reconcile a Meta delivery callback onto its Outbox row.

        Persisted as product state rather than a debug log (TC-006). Duplicate
        callbacks are absorbed by the unique constraint.

        The Organization is resolved here from the WhatsApp phone number id the
        callback arrived on, rather than taken as an argument, for the reason
        :meth:`~realestate.domain.inbox.InboxService.accept` states about the
        inbound path: the refusal for an unbound number is part of what this
        method *is*, and a second copy of it in each caller is how a later fix
        gets applied to one path and silently missed on the other. An unroutable
        number raises rather than defaulting (ADR-0050).

        It is deliberately not derived from the provider identifier: Meta's
        message id is opaque, and searching for it across the whole table would
        let a callback for one brokerage attach itself to another's row if the
        identifier ever collided or was replayed against the wrong endpoint.
        """
        routed = await self._routing.resolve(
            ChannelBindingKind.WHATSAPP_PHONE_NUMBER, phone_number_id
        )
        organization_id = routed.organization_id
        outbox = (
            await self._session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.organization_id == organization_id)
                .where(OutboxMessage.provider_message_id == provider_message_id)
            )
        ).scalar_one_or_none()

        self._session.add(
            DeliveryStatus(
                organization_id=organization_id,
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

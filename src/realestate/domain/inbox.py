"""The durable Inbox (ADR-0005, P-028, P-034, P-035, P-037, P-038).

Two responsibilities, deliberately separated:

* **Acceptance** runs on the API path. It authenticates, resolves Lead ->
  Engagement Cycle -> Conversation, and persists the complete Meta message
  transactionally, keyed on the Meta message identifier. Only then may the
  webhook be acknowledged. If this fails, Meta must be allowed to retry.

* **Claiming** runs on the background loop. It takes the pending messages of one
  Conversation in arrival order as a single group, under a fenced lease.

Nothing here talks to Hermes or to Meta.

**One dependency points the "wrong" way and is deliberate.** Acceptance calls
:class:`~realestate.domain.commercial.intake.CommercialIntake`, so this module
imports the commercial layer. The requirement is real — a Contact or an
Opportunity that outlived the message which produced it would be a record of
something that never durably happened, so they must land in *this* transaction.
The tidier shape is a coordinator above both, which the webhook route would call
instead; that means moving commit ownership and the duplicate-``wamid``
``IntegrityError`` retry out of :meth:`InboxService.accept`, and rewriting a
Stage 1 recovery path is not worth doing on the way past. Recorded rather than
hidden.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.payload import InboundMessage
from realestate.db.models import (
    ENGAGEMENT_CYCLE_DAYS,
    MAIA_MAY_REPLY,
    Conversation,
    ConversationHandlingState,
    InboxGroup,
    InboxGroupStatus,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.intake import CommercialIntake
from realestate.domain.commercial.routing import InboundRouting
from realestate.domain.outbound import detect_opt_out, record_explicit_opt_out

# P-038: a two-minute processing lease, renewed every 30 seconds.
LEASE_SECONDS = 120
LEASE_RENEW_SECONDS = 30
# P-035: three total attempts — immediately, after 5s, after 30s.
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (0, 5, 30)
# ADR-0005: the collection window that groups rapid fragments into one turn.
COLLECTION_WINDOW_SECONDS = 2.0
# P-034: the in-flight reconciliation window, from the start of the turn.
RECONCILIATION_WINDOW_SECONDS = 10.0


def _now() -> datetime:
    return datetime.now(tz=UTC)


def retry_delay_seconds(attempts: int) -> int:
    """The P-035 backoff for a message that has already used *attempts* tries."""
    return RETRY_DELAYS_SECONDS[min(attempts, len(RETRY_DELAYS_SECONDS) - 1)]


def _requeue(message: InboxMessage, now: datetime) -> None:
    """Send one message back to Pending with its backoff, or retire it as Failed.

    The single expression of P-035's ceiling: normal failure and crashed-worker
    recovery must not be able to drift into different retry policies.
    """
    if message.attempts >= MAX_ATTEMPTS:
        message.status = InboxStatus.FAILED.value
        return
    message.status = InboxStatus.PENDING.value
    message.group_id = None
    message.next_attempt_at = now + timedelta(
        seconds=retry_delay_seconds(message.attempts)
    )


@dataclass(frozen=True)
class AcceptedMessage:
    inbox_id: uuid.UUID
    conversation_id: uuid.UUID
    cycle_id: uuid.UUID
    lead_id: uuid.UUID
    duplicate: bool
    cycle_created: bool
    # The commercial record this message resolved to (Stage 2). Set on a first
    # delivery, where they are a by-product of work this transaction already
    # did. ``None`` on a redelivery: the record exists, but looking it up again
    # would cost the webhook path two queries for an answer the original
    # delivery already reported.
    contact_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None


def combined_text(messages: Sequence[InboxMessage]) -> str:
    """Messages in arrival order, as one conversational turn.

    Batching affects processing only; the durable source records are never
    collapsed (ADR-0005). Both the claimed group and any fragment adopted
    mid-turn are folded by this one rule, so an injected fragment always reads
    the way a normal turn would have.
    """
    return "\n".join(m.text for m in messages if m.text)


@dataclass
class ClaimedGroup:
    group_id: uuid.UUID
    conversation_id: uuid.UUID
    claim_token: uuid.UUID
    attempts: int
    messages: list[InboxMessage]

    @property
    def inbox_ids(self) -> list[uuid.UUID]:
        return [message.id for message in self.messages]

    def combined_text(self) -> str:
        return combined_text(self.messages)


class InboxService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- Acceptance (API path) --------------------------------------------

    async def accept(self, message: InboundMessage) -> AcceptedMessage:
        """Persist one authenticated inbound message idempotently.

        A duplicate Meta delivery resolves to the existing record and creates no
        second Inbox row, no second Conversation, and no second engagement
        cycle.
        """
        existing = (
            await self._session.execute(
                select(InboxMessage).where(InboxMessage.wamid == message.wamid)
            )
        ).scalar_one_or_none()
        if existing is not None:
            conversation = await self._session.get(
                Conversation, existing.conversation_id
            )
            assert conversation is not None
            # Deliberately not re-resolving the commercial record here. The
            # first delivery created it in the same transaction as the message,
            # so a redelivery adds nothing — and Meta retries on the latency
            # path, which is the worst place to spend two extra queries on
            # fields no caller reads for a duplicate.
            return AcceptedMessage(
                inbox_id=existing.id,
                conversation_id=conversation.id,
                cycle_id=conversation.cycle_id,
                lead_id=conversation.lead_id,
                duplicate=True,
                cycle_created=False,
            )

        intake = CommercialIntake(self._session)
        organization_id = await intake.organization_id()
        lead = await self._lead(message, organization_id)
        cycle, cycle_created = await self._current_cycle(lead)
        conversation = await self._conversation(lead, cycle, message.phone_number_id)

        row = InboxMessage(
            conversation_id=conversation.id,
            wamid=message.wamid,
            from_wa_id=message.from_wa_id,
            message_type=message.message_type,
            text=message.text,
            sent_at=message.sent_at,
            # The complete authenticated Meta object, retained before any
            # projection into Hermes (P-049, V-001).
            raw_message=message.raw,
            status=InboxStatus.PENDING.value,
        )
        self._session.add(row)
        try:
            # Flushed inside the guard: the duplicate-wamid race can surface
            # here as easily as at commit, and both mean the same thing.
            await self._session.flush()

            # A Contact asking to be left alone is honoured at the moment their
            # message becomes durable, in the same transaction. Doing it later —
            # in the worker, or after Hermes has had an opinion — would leave a
            # window in which the follow-up policy could still write to them.
            phrase = detect_opt_out(message.text)
            if phrase is not None:
                await record_explicit_opt_out(
                    self._session,
                    lead_id=lead.id,
                    phrase=phrase,
                    source_inbox_id=row.id,
                )
                await record_audit(
                    self._session,
                    actor_type="Contact",
                    actor_id=lead.wa_id,
                    action="RecordExplicitOptOut",
                    subject_type="Lead",
                    subject_id=str(lead.id),
                    details={"phrase": phrase, "channel": "WhatsApp"},
                    commit=False,
                )

            # The commercial record is created here, in the same transaction,
            # for the reason the opt-out above is: a Contact or an Opportunity
            # that outlived the message that produced it would be a record of
            # something that never durably happened.
            intake_result = await intake.record_inbound(
                lead=lead, conversation=conversation, inbox_id=row.id
            )

            # Product's deterministic decisions about this message: an explicit
            # request for a person, and where a post-Appointment-Handoff
            # message belongs (ADR-0029, ADR-0037). Here for the same reason as
            # the opt-out and the commercial record — a handoff request that
            # outlived the message asking for it would be a record of something
            # that never durably happened.
            await InboundRouting(self._session).route(
                lead=lead,
                conversation=conversation,
                inbox_id=row.id,
                text=message.text,
            )

            await self._session.commit()
        except IntegrityError:
            # Two concurrent webhook deliveries of the same wamid raced. The
            # unique constraint is the arbiter; re-resolve to the winner.
            await self._session.rollback()
            return await self.accept(message)

        return AcceptedMessage(
            inbox_id=row.id,
            conversation_id=conversation.id,
            cycle_id=cycle.id,
            lead_id=lead.id,
            duplicate=False,
            cycle_created=cycle_created,
            contact_id=intake_result.contact_id,
            opportunity_id=intake_result.opportunity_id,
        )

    async def _lead(self, message: InboundMessage, organization_id: uuid.UUID) -> Lead:
        lead = (
            await self._session.execute(
                select(Lead)
                .where(Lead.organization_id == organization_id)
                .where(Lead.wa_id == message.from_wa_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if lead is not None:
            if message.profile_name and lead.profile_name != message.profile_name:
                lead.profile_name = message.profile_name
            return lead

        lead = Lead(
            organization_id=organization_id,
            wa_id=message.from_wa_id,
            profile_name=message.profile_name,
        )
        self._session.add(lead)
        await self._session.flush()
        return lead

    async def _current_cycle(self, lead: Lead) -> tuple[LeadEngagementCycle, bool]:
        """Return the Lead's active cycle, opening a new one if it has expired.

        An inbound message inside an Active cycle continues it and does **not**
        move its deadline. After expiry a new cycle is created against the same
        Lead; the expired one stays immutable and is never reopened (ADR-0012).
        """
        now = _now()
        latest = (
            await self._session.execute(
                select(LeadEngagementCycle)
                .where(LeadEngagementCycle.lead_id == lead.id)
                .order_by(LeadEngagementCycle.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if latest is not None and latest.is_active(now):
            return latest, False

        cycle = LeadEngagementCycle(
            lead_id=lead.id,
            started_at=now,
            expires_at=now + timedelta(days=ENGAGEMENT_CYCLE_DAYS),
        )
        self._session.add(cycle)
        await self._session.flush()
        return cycle, True

    async def _conversation(
        self, lead: Lead, cycle: LeadEngagementCycle, phone_number_id: str
    ) -> Conversation:
        conversation = (
            await self._session.execute(
                select(Conversation).where(Conversation.cycle_id == cycle.id)
            )
        ).scalar_one_or_none()
        if conversation is not None:
            return conversation

        conversation = Conversation(
            organization_id=lead.organization_id,
            lead_id=lead.id,
            cycle_id=cycle.id,
            phone_number_id=phone_number_id,
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    # -- Claiming (background loop) ---------------------------------------

    async def claimable_conversations(self, limit: int) -> list[uuid.UUID]:
        """Conversations Maia may answer, with settled pending work.

        A Conversation is eligible only once its oldest pending message has
        cleared the two-second collection window, so rapid fragments arrive in
        the same group rather than in consecutive ones — and only while
        Conversation Handling Mode says Maia is the one answering.
        """
        now = _now()
        cutoff = now - timedelta(seconds=COLLECTION_WINDOW_SECONDS)
        active = select(InboxGroup.conversation_id).where(
            InboxGroup.status == InboxGroupStatus.PROCESSING.value
        )
        # Conversations a human holds, or that need Administrator review, are
        # not Maia's to answer (ADR-0029). Excluded here so the ordinary case
        # never even starts a Hermes turn; the worker still re-checks under a
        # lock at settlement, because a human can arrive mid-turn.
        handled_elsewhere = select(ConversationHandlingState.conversation_id).where(
            ConversationHandlingState.mode.not_in(tuple(MAIA_MAY_REPLY))
        )
        rows = await self._session.execute(
            select(InboxMessage.conversation_id)
            .where(InboxMessage.status == InboxStatus.PENDING.value)
            .where(InboxMessage.attempts < MAX_ATTEMPTS)
            .where(
                (InboxMessage.next_attempt_at.is_(None))
                | (InboxMessage.next_attempt_at <= now)
            )
            .where(InboxMessage.conversation_id.not_in(active))
            .where(InboxMessage.conversation_id.not_in(handled_elsewhere))
            .group_by(InboxMessage.conversation_id)
            .having(func.min(InboxMessage.persisted_at) <= cutoff)
            .order_by(func.min(InboxMessage.persisted_at))
            .limit(limit)
        )
        return [row[0] for row in rows]

    async def claim(self, conversation_id: uuid.UUID) -> ClaimedGroup | None:
        """Open one fenced group over a Conversation's pending messages.

        Returns None when another worker won the lane: the partial unique index
        on ``inbox_groups`` makes that a database-enforced outcome rather than a
        coordination convention.
        """
        now = _now()
        group = InboxGroup(
            conversation_id=conversation_id,
            status=InboxGroupStatus.PROCESSING.value,
            claim_token=uuid.uuid4(),
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            attempts=1,
            turn_started_at=now,
        )
        self._session.add(group)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return None

        messages = list(
            (
                await self._session.execute(
                    select(InboxMessage)
                    .where(InboxMessage.conversation_id == conversation_id)
                    .where(InboxMessage.status == InboxStatus.PENDING.value)
                    .where(InboxMessage.attempts < MAX_ATTEMPTS)
                    .where(
                        (InboxMessage.next_attempt_at.is_(None))
                        | (InboxMessage.next_attempt_at <= now)
                    )
                    .order_by(InboxMessage.sent_at, InboxMessage.persisted_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if not messages:
            await self._session.rollback()
            return None

        for message in messages:
            message.status = InboxStatus.PROCESSING.value
            message.group_id = group.id
            message.attempts += 1
        # The group's attempt number is the highest any of its messages has
        # reached, so a message regrouped after a failure keeps its history.
        group.attempts = max(message.attempts for message in messages)
        await self._session.commit()

        return ClaimedGroup(
            group_id=group.id,
            conversation_id=conversation_id,
            claim_token=group.claim_token,
            attempts=group.attempts,
            messages=messages,
        )

    async def peek_pending(self, group: ClaimedGroup) -> list[InboxMessage]:
        """Messages waiting in this Conversation, without adopting them yet.

        Adoption is deliberately a second step: a message must only join the
        active group once Hermes has actually accepted it into the live turn.
        Marking it adopted first and then failing to inject would lose it.
        """
        return list(
            (
                await self._session.execute(
                    select(InboxMessage)
                    .where(InboxMessage.conversation_id == group.conversation_id)
                    .where(InboxMessage.status == InboxStatus.PENDING.value)
                    .order_by(InboxMessage.sent_at, InboxMessage.persisted_at)
                )
            )
            .scalars()
            .all()
        )

    async def adopt(self, group: ClaimedGroup, messages: list[InboxMessage]) -> None:
        """Join *messages* to the active group after Hermes accepted them."""
        if not messages:
            return
        for message in messages:
            message.status = InboxStatus.PROCESSING.value
            message.group_id = group.group_id
        await self._session.commit()
        group.messages.extend(messages)

    async def unadopted_exists(self, group: ClaimedGroup) -> bool:
        """True when same-Conversation messages are still waiting.

        The Worker checks this before releasing a draft: if any exist, the draft
        is withheld and reconciled rather than sent (P-034).
        """
        found = (
            await self._session.execute(
                select(InboxMessage.id)
                .where(InboxMessage.conversation_id == group.conversation_id)
                .where(InboxMessage.status == InboxStatus.PENDING.value)
                .limit(1)
            )
        ).first()
        return found is not None

    async def renew_lease(self, group: ClaimedGroup) -> bool:
        """Extend the lease. False when this worker no longer owns the group."""
        row = await self._fenced(group)
        if row is None:
            return False
        row.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
        await self._session.commit()
        return True

    async def settle(self, group: ClaimedGroup) -> bool:
        """Close the group successfully. False if the lease was lost."""
        row = await self._fenced(group)
        if row is None:
            return False
        row.status = InboxGroupStatus.SETTLED.value
        row.closed_at = _now()
        for message in group.messages:
            message.status = InboxStatus.PROCESSED.value
        await self._session.commit()
        return True

    async def fail(self, group: ClaimedGroup) -> bool:
        """Release the lane after a failed attempt.

        Below the attempt ceiling the messages return to Pending with the next
        backoff applied. At the ceiling they stay durably stored as Failed —
        never deleted, never silently acknowledged as processed (P-035).

        Returns False if the lease was already lost, in which case recovery has
        the work and this worker must not touch it.
        """
        row = await self._fenced(group)
        if row is None:
            return False

        now = _now()
        row.status = InboxGroupStatus.FAILED.value
        row.closed_at = now
        for message in group.messages:
            _requeue(message, now)
        await self._session.commit()
        return True

    @staticmethod
    def is_exhausted(group: ClaimedGroup) -> bool:
        """True when every message in the group has spent its three attempts."""
        return all(message.attempts >= MAX_ATTEMPTS for message in group.messages)

    async def _fenced(self, group: ClaimedGroup) -> InboxGroup | None:
        """Load the group only if this worker still holds the claim token.

        Claim-token fencing is what stops an expired owner from settling work
        that recovery already reassigned (P-038).
        """
        return (
            await self._session.execute(
                select(InboxGroup)
                .where(InboxGroup.id == group.group_id)
                .where(InboxGroup.claim_token == group.claim_token)
                .where(InboxGroup.status == InboxGroupStatus.PROCESSING.value)
            )
        ).scalar_one_or_none()

    async def recover_expired_claims(self) -> int:
        """Return work from crashed workers to Pending.

        An expired lease consumes one of the three attempts. Recovery is
        at-least-once, which is why every downstream command and Outbox write is
        idempotent (P-038).
        """
        now = _now()
        expired = list(
            (
                await self._session.execute(
                    select(InboxGroup)
                    .where(InboxGroup.status == InboxGroupStatus.PROCESSING.value)
                    .where(InboxGroup.lease_expires_at < now)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not expired:
            return 0

        for group in expired:
            group.status = InboxGroupStatus.FAILED.value
            group.closed_at = now

        # One query for every expired group's messages rather than one per group.
        messages = (
            (
                await self._session.execute(
                    select(InboxMessage).where(
                        InboxMessage.group_id.in_([group.id for group in expired])
                    )
                )
            )
            .scalars()
            .all()
        )
        for message in messages:
            # The interrupted execution already consumed an attempt at claim
            # time, so recovery only decides where the message goes next.
            _requeue(message, now)
        await self._session.commit()
        return len(expired)

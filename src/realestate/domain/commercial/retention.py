"""Conversation content expires; commercial history does not (ADR-0026).

Two clocks, deliberately separate. After 90 consecutive days without
interaction the Hermes Conversational Session closes and the message *bodies*
expire: a later contact starts a new session rather than replaying an old chat.
The commercial record follows its own rules — Contacts, Opportunities, their
outcomes, attribution, consent, Suppression Records and audit evidence stay,
because the operation has to keep working lawfully and must not write to
somebody who told it not to.

That is why bodies are emptied rather than rows deleted. ``opportunity_origins``
points at the first inbound message, an eligibility decision names the messages
it answered, and a Suppression Record names the message that expressed the
opt-out. Deleting those rows would take the evidence with them; blanking the
text removes the personal content and keeps the anchor.

The 90-day period, and the exceptions to it, remain subject to Mexican legal
review. This module is the single place that would change.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CONVERSATION_CONTENT_RETENTION_DAYS,
    AgentSession,
    Conversation,
    InboxMessage,
    OutboxMessage,
)
from realestate.domain.audit import record_audit

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class ExpiredContent:
    """What one sweep removed. Reported so the operation can see it happened."""

    conversations: int
    inbound_messages: int
    outbound_messages: int
    sessions_closed: int

    @property
    def any(self) -> bool:
        return bool(self.conversations)


class ConversationRetention:
    """The conversation-content expiry rule.

    Hides: the inactivity clock, which columns hold content, the Hermes session
    binding, idempotency, and the audit trail. Callers ask it to run.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def expire(
        self,
        *,
        now: datetime | None = None,
        days: int = CONVERSATION_CONTENT_RETENTION_DAYS,
        limit: int = 200,
    ) -> ExpiredContent:
        """Expire the bodies of conversations inactive for *days*. Commits.

        Idempotent: a conversation whose messages are already marked expired is
        not selected again, so running the sweep twice costs one query.
        """
        moment = now or _now()
        cutoff = moment - timedelta(days=days)
        candidates = await self._inactive_since(cutoff, limit)
        if not candidates:
            return ExpiredContent(0, 0, 0, 0)

        inbound = await self._session.execute(
            update(InboxMessage)
            .where(InboxMessage.conversation_id.in_(candidates))
            .where(InboxMessage.content_expired_at.is_(None))
            .values(
                text=None,
                # The complete Meta object is the most sensitive thing Product
                # stores. Replaced with a marker rather than dropped, so the
                # column stays NOT NULL and the row stays readable.
                raw_message={"expired": True},
                content_expired_at=moment,
            )
            .returning(InboxMessage.id)
        )
        inbound_ids = [row[0] for row in inbound]

        outbound = await self._session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.conversation_id.in_(candidates))
            .where(OutboxMessage.content_expired_at.is_(None))
            .values(body="", content_expired_at=moment)
            .returning(OutboxMessage.id)
        )
        outbound_ids = [row[0] for row in outbound]

        # The Conversational Session is bounded context, not the commercial
        # record (CONTEXT.md). Forgetting the binding is what makes the next
        # contact a new session instead of a replay of an expired one.
        cycle_ids = [
            row[0]
            for row in await self._session.execute(
                select(Conversation.cycle_id).where(Conversation.id.in_(candidates))
            )
        ]
        closed = await self._session.execute(
            delete(AgentSession)
            .where(AgentSession.cycle_id.in_(cycle_ids))
            .returning(AgentSession.id)
        )
        sessions_closed = len(list(closed))

        for conversation_id in candidates:
            await record_audit(
                self._session,
                actor_type="Product",
                actor_id="ConversationRetention",
                action="ExpireConversationContent",
                subject_type="Conversation",
                subject_id=str(conversation_id),
                details={
                    "inactive_days": days,
                    # Deliberately no message text and no identity: the audit
                    # trail outlives the content it is recording the removal of.
                    "expired_at": moment.isoformat(),
                },
                commit=False,
            )
        await self._session.commit()
        result = ExpiredContent(
            conversations=len(candidates),
            inbound_messages=len(inbound_ids),
            outbound_messages=len(outbound_ids),
            sessions_closed=sessions_closed,
        )
        logger.info(
            "Expired conversation content: %d conversation(s), %d inbound, "
            "%d outbound, %d session(s) closed",
            result.conversations,
            result.inbound_messages,
            result.outbound_messages,
            result.sessions_closed,
        )
        return result

    async def _inactive_since(self, cutoff: datetime, limit: int) -> list[uuid.UUID]:
        """Conversations with no interaction after *cutoff* and content left.

        Inactivity is measured across both directions. A thread Product wrote
        to last month is not inactive just because the Contact stopped
        answering — and a follow-up Product never sent cannot make it look
        active either, because a denied decision produces no Outbox row.
        """
        last_inbound = (
            select(
                InboxMessage.conversation_id.label("conversation_id"),
                func.max(InboxMessage.sent_at).label("at"),
            )
            .group_by(InboxMessage.conversation_id)
            .subquery()
        )
        last_outbound = (
            select(
                OutboxMessage.conversation_id.label("conversation_id"),
                func.max(OutboxMessage.created_at).label("at"),
            )
            .group_by(OutboxMessage.conversation_id)
            .subquery()
        )
        unexpired_inbound = (
            select(InboxMessage.conversation_id)
            .where(InboxMessage.content_expired_at.is_(None))
            .distinct()
        )
        unexpired_outbound = (
            select(OutboxMessage.conversation_id)
            .where(OutboxMessage.content_expired_at.is_(None))
            .distinct()
        )
        rows = await self._session.execute(
            select(Conversation.id)
            .outerjoin(last_inbound, last_inbound.c.conversation_id == Conversation.id)
            .outerjoin(
                last_outbound, last_outbound.c.conversation_id == Conversation.id
            )
            .where(
                func.greatest(
                    func.coalesce(last_inbound.c.at, Conversation.created_at),
                    func.coalesce(last_outbound.c.at, Conversation.created_at),
                )
                <= cutoff
            )
            .where(
                Conversation.id.in_(unexpired_inbound)
                | Conversation.id.in_(unexpired_outbound)
            )
            .order_by(Conversation.created_at)
            .with_for_update(of=Conversation, skip_locked=True)
            .limit(limit)
        )
        return [row[0] for row in rows]

"""The Lead-conversation worker (ADR-0005, ADR-0007, P-034, P-035, P-037).

One tick does three things, in order:

1. recover Inbox groups whose lease expired with a crashed worker;
2. process up to ``max_concurrent_conversations`` claimable Conversations;
3. drain due Outbox rows.

The step that matters most is response settlement. A Hermes draft is *not* a
WhatsApp reply. It becomes one only after the Worker confirms that no
same-Conversation message persisted during the reconciliation window is still
unadopted, and the released row records every Inbox identifier it covers.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from realestate.channels.whatsapp.client import WhatsAppClient
from realestate.db.engine import Database
from realestate.db.models import (
    Conversation,
    InboxGroup,
    InboxGroupStatus,
    InboxMessage,
    Lead,
    LeadEngagementCycle,
    OutboxMessage,
    OutboxStatus,
)
from realestate.domain.appointments import (
    LeadNotice,
    mark_lead_notified,
    pending_lead_notice,
)
from realestate.domain.availability import WeeklySchedule
from realestate.domain.inbox import (
    RECONCILIATION_WINDOW_SECONDS,
    ClaimedGroup,
    InboxService,
    combined_text,
)
from realestate.domain.copy import canonicalize
from realestate.domain.outbox import (
    PROCESSING_FAILURE_BODY,
    OutboxKind,
    OutboxService,
)
from realestate.channels.whatsapp.formatting import to_whatsapp_markup
from realestate.hermes.client import HermesClient
from realestate.hermes.sessions import (
    bind_cycle_session,
    dated_prompt,
    run_turn,
    session_for_cycle,
    trusted_context,
)

logger = logging.getLogger(__name__)


class WhatsAppWorker:
    def __init__(
        self,
        database: Database,
        hermes: HermesClient,
        whatsapp: WhatsAppClient,
        *,
        sales_profile: str,
        schedule: WeeklySchedule,
        max_concurrent: int = 3,
    ) -> None:
        self._database = database
        self._hermes = hermes
        self._whatsapp = whatsapp
        self._sales_profile = sales_profile
        # Only for rendering a persisted appointment in the Broker's zone; this
        # worker computes no availability.
        self._schedule = schedule
        self._max_concurrent = max_concurrent

    # -- One tick ---------------------------------------------------------

    async def tick(self) -> None:
        await self._recover()
        await self._process_conversations()
        await self._drain_outbox()

    async def _recover(self) -> None:
        async with self._database.session_scope() as session:
            recovered = await InboxService(session).recover_expired_claims()
        if recovered:
            logger.warning("Recovered %d Inbox group(s) with an expired lease", recovered)

    async def _process_conversations(self) -> None:
        async with self._database.session_scope() as session:
            candidates = await InboxService(session).claimable_conversations(
                self._max_concurrent
            )
        if not candidates:
            return

        # Separate Conversations proceed independently; one Conversation never
        # runs two groups at once (the database enforces the lane).
        await asyncio.gather(
            *(self._process_one(conversation_id) for conversation_id in candidates),
            return_exceptions=True,
        )

    async def _process_one(self, conversation_id: uuid.UUID) -> None:
        async with self._database.session_scope() as session:
            inbox = InboxService(session)
            group = await inbox.claim(conversation_id)
            if group is None:
                return

            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None
            cycle = await session.get(LeadEngagementCycle, conversation.cycle_id)
            assert cycle is not None
            lead = await session.get(Lead, conversation.lead_id)

            try:
                reply = await self._run_hermes_turn(session, inbox, group, cycle, lead)
            except Exception as exc:
                logger.exception("Processing failed for conversation %s", conversation_id)
                await self._handle_failure(session, inbox, group, conversation, exc)
                return

            await self._settle(session, inbox, group, conversation, reply)

    # -- The Hermes turn --------------------------------------------------

    async def _run_hermes_turn(
        self,
        session,  # AsyncSession
        inbox: InboxService,
        group: ClaimedGroup,
        cycle: LeadEngagementCycle,
        lead: Lead | None,
    ) -> str:
        role_session = await session_for_cycle(session, cycle.id)
        seed, recovered_messages = await self._recovery_seed(
            session, cycle, lead
        )

        async def bind(hermes_session_id: str) -> None:
            await bind_cycle_session(
                session, cycle_id=cycle.id, hermes_session_id=hermes_session_id
            )

        # Local to this call: the worker instance is shared across concurrently
        # processed Conversations, so this must never live on ``self``.
        offered: list = []

        async def offer_late_messages() -> str | None:
            """Offer newly persisted fragments to the live turn.

            Peek first, inject second, adopt only on acceptance — a message
            Hermes will not take stays Pending for the next FIFO cycle rather
            than being swallowed into a turn that ignored it.
            """
            pending = await inbox.peek_pending(group)
            text = combined_text(pending)
            if not text:
                return None
            offered.clear()
            offered.extend(pending)
            return text

        async def adopt_offered() -> None:
            await inbox.adopt(group, list(offered))
            logger.info(
                "Folded %d late fragment(s) into the active turn for %s",
                len(offered),
                group.conversation_id,
            )
            offered.clear()

        turn = await run_turn(
            self._hermes,
            role_session,
            # The Lead's own words, prefixed with today's date in the Broker's
            # zone. Without it the Model guesses at "el viernes" and a wrong
            # guess reads to the Lead as "no availability".
            dated_prompt(
                group.combined_text(),
                today=datetime.now(tz=self._schedule.zone).date(),
            ),
            profile=self._sales_profile,
            on_attached=bind,
            on_poll=offer_late_messages,
            on_adopted=adopt_offered,
            # Applied only when this cycle's session is created. The Model
            # cannot learn the WhatsApp profile name any other way.
            seed=seed,
            minimum_history_messages=recovered_messages,
            window_seconds=RECONCILIATION_WINDOW_SECONDS,
        )
        return turn.text

    async def _recovery_seed(
        self, session, cycle: LeadEngagementCycle, lead: Lead | None
    ) -> tuple[list[dict[str, str]], int]:
        """Rebuild settled Sales history from Product truth when Hermes lost it.

        Only replies Meta conclusively accepted are replayed into the replacement
        session. ``DeliveryUnknown`` is excluded because the Product cannot claim
        the Lead saw it. Each settled group contributes one user/assistant pair,
        preserving strict role alternation.
        """
        conversation = (
            await session.execute(
                select(Conversation).where(Conversation.cycle_id == cycle.id)
            )
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    select(OutboxMessage)
                    .join(InboxGroup, InboxGroup.id == OutboxMessage.inbox_group_id)
                    .where(OutboxMessage.conversation_id == conversation.id)
                    .where(OutboxMessage.status == OutboxStatus.SENT.value)
                    .where(InboxGroup.status == InboxGroupStatus.SETTLED.value)
                    .order_by(OutboxMessage.created_at)
                )
            )
            .scalars()
            .all()
        )
        history = trusted_context(profile_name=lead.profile_name if lead else None)
        pairs = 0
        for outbox in rows:
            messages = (
                (
                    await session.execute(
                        select(InboxMessage)
                        .where(InboxMessage.group_id == outbox.inbox_group_id)
                        .order_by(InboxMessage.sent_at, InboxMessage.id)
                    )
                )
                .scalars()
                .all()
            )
            inbound = combined_text(messages)
            if not inbound:
                continue
            history.extend(
                (
                    {"role": "user", "content": inbound},
                    {"role": "assistant", "content": outbox.body},
                )
            )
            pairs += 1
        return history, pairs * 2

    # -- Settlement -------------------------------------------------------

    async def _settle(
        self,
        session,  # AsyncSession
        inbox: InboxService,
        group: ClaimedGroup,
        conversation: Conversation,
        reply: str,
    ) -> None:
        """Release the draft only when the group truly covers the Conversation.

        If a message persisted during the window was never adopted, the draft is
        withheld: the group fails back into the queue and the next cycle answers
        all of it together, rather than sending a reply that ignores part of
        what the Lead said (P-034).
        """
        if await inbox.unadopted_exists(group):
            logger.info(
                "Withholding a draft for %s: unadopted messages remain",
                conversation.id,
            )
            await inbox.fail(group)
            return

        # What the Lead is told about an Appointment is product text rendered
        # from the persisted row, never the Model's account of the booking. When
        # one is owed it *replaces* the draft, so a confirmed visit produces
        # exactly one confirmation and an inconclusive one cannot be described
        # as confirmed (P-042, P-044).
        notice = await pending_lead_notice(session, conversation, self._schedule)

        if notice is None and not reply.strip():
            logger.warning("Hermes produced an empty draft for %s", conversation.id)
            await inbox.fail(group)
            return

        body, kind = self._release(conversation, reply, notice)

        lead_wa_id = group.messages[0].from_wa_id
        outbox = OutboxService(session)
        enqueued = await outbox.enqueue(
            conversation=conversation,
            to_wa_id=lead_wa_id,
            body=body,
            kind=kind,
            # One reply per Inbox group, whatever happens upstream.
            idempotency_key=f"reply:{group.group_id}",
            covered_inbox_ids=group.inbox_ids,
            inbox_group_id=group.group_id,
        )
        if notice is not None:
            # Persisted immediately: without it, the next turn would release the
            # same confirmation again under a different group key.
            await mark_lead_notified(session, notice.appointment_id)

        if not await inbox.settle(group):
            # The lease was lost to recovery mid-turn. The Outbox row is keyed
            # on the group, so the recovered attempt cannot add a second reply.
            logger.warning(
                "Lost the lease for %s before settlement; outbox row %s stands",
                conversation.id,
                enqueued.outbox_id,
            )

    def _release(
        self, conversation: Conversation, reply: str, notice: LeadNotice | None
    ) -> tuple[str, str]:
        """The exact body to release, and what kind of message it is."""
        if notice is not None:
            logger.info(
                "Releasing the deterministic %s for appointment %s to %s; the "
                "Model's draft is discarded: %r",
                notice.kind,
                notice.reference,
                conversation.id,
                reply.strip()[:120],
            )
            return to_whatsapp_markup(notice.body), notice.kind

        # Restore the approved wording of any accepted message the Model
        # reworded. Canonicalisation only rewrites copy it already emitted; it
        # never decides that a reply should have been an approved message.
        canonical = canonicalize(reply)
        if canonical.changed:
            logger.info(
                "Restored approved copy before release for %s: %s",
                conversation.id,
                "; ".join(m[:40] for m in canonical.replaced),
            )
        return to_whatsapp_markup(canonical.text), OutboxKind.AGENT_REPLY

    async def _handle_failure(
        self,
        session,  # AsyncSession
        inbox: InboxService,
        group: ClaimedGroup,
        conversation: Conversation,
        error: Exception,
    ) -> None:
        """Apply the bounded retry policy, and speak honestly when it runs out."""
        exhausted = inbox.is_exhausted(group)
        await inbox.fail(group)

        if not exhausted:
            return

        logger.error(
            "Conversation %s exhausted its processing attempts: %s",
            conversation.id,
            error,
        )
        # A deterministic, non-model-generated acknowledgement. It does not
        # claim the message was handled, and it does not mark the failed Inbox
        # work as successful (P-035).
        await OutboxService(session).enqueue(
            conversation=conversation,
            to_wa_id=group.messages[0].from_wa_id,
            body=PROCESSING_FAILURE_BODY,
            kind=OutboxKind.PROCESSING_FAILURE,
            idempotency_key=f"processing-failure:{group.group_id}",
            covered_inbox_ids=group.inbox_ids,
            inbox_group_id=group.group_id,
        )

    # -- Outbox -----------------------------------------------------------

    async def _drain_outbox(self) -> None:
        async with self._database.session_scope() as session:
            outbox = OutboxService(session)
            recovered = await outbox.recover_abandoned_sends()
            if recovered:
                logger.error(
                    "Recovered %d abandoned Outbox send(s) as DeliveryUnknown",
                    recovered,
                )
            due = await outbox.claim_due()
            for row in due:
                result = await self._whatsapp.send_text(row.to_wa_id, row.body)
                await outbox.record_result(row, result)
                if result.conclusive and result.provider_message_id:
                    logger.info(
                        "Delivered outbox %s as %s", row.id, result.provider_message_id
                    )
                elif not result.conclusive:
                    # Never replayed automatically (P-036).
                    logger.error(
                        "Outbox %s is DeliveryUnknown: %s", row.id, result.detail
                    )

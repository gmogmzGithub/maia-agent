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
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.client import SendOutcome, SendResult, WhatsAppClient
from realestate.db.engine import Database
from realestate.db.models import (
    Conversation,
    InboxGroup,
    InboxGroupStatus,
    InboxMessage,
    Lead,
    LeadEngagementCycle,
    OutboundInitiation,
    OutboxMessage,
    OutboxStatus,
    Property,
)
from realestate.domain.appointments import (
    LeadNotice,
    mark_lead_notified,
    pending_lead_notice,
)
from realestate.domain.audit import record_audit
from realestate.domain.availability import WeeklySchedule
from realestate.domain.commercial.handling import ConversationHandling
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.inbox import (
    RECONCILIATION_WINDOW_SECONDS,
    ClaimedGroup,
    InboxService,
    combined_text,
)
from realestate.domain.copy import canonicalize
from realestate.domain.outbound import (
    DeliveryDenied,
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
    TemplateDelivery,
)
from realestate.domain.outbox import (
    PROCESSING_FAILURE_BODY,
    OutboxService,
)
from realestate.domain.platform.whatsapp import OrganizationWhatsAppClients
from realestate.domain.platform.runtime import OrganizationAppointmentPolicies
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
        whatsapp: WhatsAppClient | OrganizationWhatsAppClients,
        *,
        sales_profile: str,
        schedule: WeeklySchedule | OrganizationAppointmentPolicies,
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

            # Handling authority, checked again now that the group is claimed.
            # The claimable query already excluded conversations a human holds;
            # this covers the human who arrived between the two.
            handling = ConversationHandling(session)
            if not await handling.maia_may_reply(conversation_id, lock=True):
                await self._withhold_for_human(session, inbox, group, conversation)
                return

            cycle = await session.get(LeadEngagementCycle, conversation.cycle_id)
            assert cycle is not None
            lead = await session.get(Lead, conversation.lead_id)

            try:
                schedule = self._schedule
                if isinstance(schedule, OrganizationAppointmentPolicies):
                    schedule = (
                        await schedule.for_organization(
                            session, conversation.organization_id
                        )
                    ).schedule
                reply = await self._run_hermes_turn(
                    session, inbox, group, cycle, lead, schedule
                )
            except Exception as exc:
                logger.exception("Processing failed for conversation %s", conversation_id)
                await self._handle_failure(session, inbox, group, conversation, exc)
                return

            await self._settle(
                session, inbox, group, conversation, reply, schedule
            )

    # -- The Hermes turn --------------------------------------------------

    async def _run_hermes_turn(
        self,
        session: AsyncSession,
        inbox: InboxService,
        group: ClaimedGroup,
        cycle: LeadEngagementCycle,
        lead: Lead | None,
        schedule: WeeklySchedule,
    ) -> str:
        role_session = await session_for_cycle(
            session, cycle.id, cycle.organization_id
        )
        seed, recovered_messages = await self._recovery_seed(
            session, cycle, lead
        )

        async def bind(hermes_session_id: str) -> None:
            await bind_cycle_session(
                session,
                organization_id=cycle.organization_id,
                cycle_id=cycle.id,
                hermes_session_id=hermes_session_id,
            )

        # Local to this call: the worker instance is shared across concurrently
        # processed Conversations, so this must never live on ``self``.
        offered: list[InboxMessage] = []

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

        conversation = await session.scalar(
            select(Conversation)
            .where(Conversation.organization_id == cycle.organization_id)
            .where(Conversation.id == group.conversation_id)
        )
        required_property_reference: str | None = None
        if conversation is not None and conversation.property_uuid is not None:
            required_property_reference = await session.scalar(
                select(Property.property_key)
                .where(Property.organization_id == cycle.organization_id)
                .where(Property.id == conversation.property_uuid)
            )

        turn = await run_turn(
            self._hermes,
            role_session,
            # The Lead's own words, prefixed with today's date in the Broker's
            # zone. Without it the Model guesses at "el viernes" and a wrong
            # guess reads to the Lead as "no availability".
            dated_prompt(
                group.combined_text(),
                today=datetime.now(tz=schedule.zone).date(),
            ),
            profile=self._sales_profile,
            on_attached=bind,
            on_poll=offer_late_messages,
            on_adopted=adopt_offered,
            # Applied only when this cycle's session is created. The Model
            # cannot learn the WhatsApp profile name any other way.
            seed=seed,
            required_property_reference=required_property_reference,
            minimum_history_messages=recovered_messages,
            window_seconds=RECONCILIATION_WINDOW_SECONDS,
        )
        return turn.text

    async def _recovery_seed(
        self, session: AsyncSession, cycle: LeadEngagementCycle, lead: Lead | None
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
        session: AsyncSession,
        inbox: InboxService,
        group: ClaimedGroup,
        conversation: Conversation,
        reply: str,
        schedule: WeeklySchedule,
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

        # The Maia-against-human race, resolved at the last possible moment and
        # under the handling row's lock. A human who took over while Hermes was
        # composing wins: the draft is discarded rather than delivered beside
        # whatever the person is about to write (ADR-0029).
        if not await ConversationHandling(session).maia_may_reply(
            conversation.id, lock=True
        ):
            await self._withhold_for_human(session, inbox, group, conversation)
            return

        # What the Lead is told about an Appointment is product text rendered
        # from the persisted row, never the Model's account of the booking. When
        # one is owed it *replaces* the draft, so a confirmed visit produces
        # exactly one confirmation and an inconclusive one cannot be described
        # as confirmed (P-042, P-044).
        notice = await pending_lead_notice(session, conversation, schedule)

        if notice is None and not reply.strip():
            logger.warning("Hermes produced an empty draft for %s", conversation.id)
            await inbox.fail(group)
            return

        body, purpose = self._release(conversation, reply, notice)

        outcome = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body=body,
                purpose=purpose,
                # This answers the exact messages in the group, and says which.
                initiation=OutboundInitiation.REACTIVE,
                trigger_inbox_ids=tuple(group.inbox_ids),
                # One reply per Inbox group, whatever happens upstream.
                idempotency_key=f"reply:{group.group_id}",
                inbox_group_id=group.group_id,
            )
        )
        if isinstance(outcome, Denied):
            # The lane still closes: the messages were processed and the answer
            # was withheld on purpose, so replaying them cannot help. The gate
            # has already recorded and logged why.
            await session.commit()
            await inbox.settle(group)
            return

        # Committed here, as the previous committing enqueue did: the reply must
        # survive even if the lease is lost before settlement below.
        await session.commit()

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
                outcome.outbox_id,
            )

    async def _withhold_for_human(
        self,
        session: AsyncSession,
        inbox: InboxService,
        group: ClaimedGroup,
        conversation: Conversation,
    ) -> None:
        """Close the lane without answering, because a human holds this thread.

        The group is *settled*, not failed. Failing it would retry the same
        messages until the attempt budget ran out and then send the Contact a
        processing-failure notice — announcing a fault where the product worked
        exactly as designed. The messages are already visible in the CRM thread
        the human is reading.
        """
        snapshot = await ConversationHandling(session).snapshot(conversation.id)
        logger.info(
            "Withholding Maia for conversation %s: handling mode is %s",
            conversation.id,
            snapshot.mode.value,
        )
        await record_audit(
            session,
            organization_id=conversation.organization_id,
            actor_type="Product",
            actor_id="WhatsAppWorker",
            action="WithholdMaiaReplyForHuman",
            subject_type="Conversation",
            subject_id=str(conversation.id),
            details={
                "mode": snapshot.mode.value,
                "holder_member_id": (
                    str(snapshot.holder_member_id)
                    if snapshot.holder_member_id
                    else None
                ),
                "inbox_ids": [str(identifier) for identifier in group.inbox_ids],
            },
            commit=False,
        )
        await session.commit()
        await inbox.settle(group)

    def _release(
        self, conversation: Conversation, reply: str, notice: LeadNotice | None
    ) -> tuple[str, Purpose]:
        """The exact body to release, and what that body is for."""
        if notice is not None:
            logger.info(
                "Releasing the deterministic %s for appointment %s to %s; the "
                "Model's draft is discarded: %r",
                notice.kind,
                notice.reference,
                conversation.id,
                reply.strip()[:120],
            )
            return to_whatsapp_markup(notice.body), Purpose(notice.kind)

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
        return to_whatsapp_markup(canonical.text), Purpose.AGENT_REPLY

    async def _handle_failure(
        self,
        session: AsyncSession,
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
        await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body=PROCESSING_FAILURE_BODY,
                purpose=Purpose.PROCESSING_FAILURE,
                initiation=OutboundInitiation.REACTIVE,
                trigger_inbox_ids=tuple(group.inbox_ids),
                idempotency_key=f"processing-failure:{group.group_id}",
                inbox_group_id=group.group_id,
            )
        )
        await session.commit()

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
                delivery = await OutboundMessaging(session).prepare_delivery(row)
                if isinstance(delivery, DeliveryDenied):
                    continue
                whatsapp = self._whatsapp
                if isinstance(whatsapp, OrganizationWhatsAppClients):
                    try:
                        whatsapp = await whatsapp.for_organization(
                            session, row.organization_id
                        )
                    except CommercialError as exc:
                        await outbox.record_result(
                            row,
                            SendResult(
                                SendOutcome.FAILED_RETRYABLE,
                                detail=exc.message,
                            ),
                        )
                        continue
                if isinstance(delivery, TemplateDelivery):
                    result = await whatsapp.send_template(
                        delivery.to_wa_id,
                        delivery.template_id,
                        delivery.language_code,
                    )
                else:
                    result = await whatsapp.send_text(
                        delivery.to_wa_id,
                        delivery.body,
                    )
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

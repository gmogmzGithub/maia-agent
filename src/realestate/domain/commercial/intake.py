"""Where an inbound message becomes commercial work.

One message from an unknown number has to produce, atomically: a Contact, a
Property Need to hang interpretations on, a Demand Opportunity with its first
attribution preserved, and a stage that says the conversation has begun. If any
of that lands without the rest, the operation has a person nobody is accountable
for — the exact failure the stage exists to prevent.

So this runs inside the transaction that persists the message. It never commits.
:class:`~realestate.domain.inbox.InboxService` calls it after the Inbox row is
flushed and before its own commit, which means a message and the commercial
record it created are durable together or not at all.

It is deliberately conservative about stage. A message moves ``New`` to
``In Conversation`` and nothing further: qualification needs confirmed criteria
(ADR-0031), and a Dormant Opportunity is not reactivated by an inbound message
because reactivation is an Administrator's judgement (ADR-0021).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.messaging import CustomerChannel
from realestate.db.models import (
    Conversation,
    Lead,
    Opportunity,
    OpportunityKind,
    OpportunityOrigin,
    OpportunityOriginSource,
    OpportunityStage,
)
from realestate.domain.commercial.actors import Actor
from realestate.domain.commercial.identity import ChannelIdentity, CommercialIdentity
from realestate.domain.commercial.needs import PropertyNeeds
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    OpenOpportunity,
    OpportunityManagement,
    OriginFacts,
)
from realestate.domain.engagement.responses import engagement_origin_for_lead

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntakeResult:
    """What the inbound message resolved to."""

    contact_id: uuid.UUID
    opportunity_id: uuid.UUID
    stage: OpportunityStage
    contact_created: bool
    opportunity_created: bool


class CommercialIntake:
    """The seam between the customer Inbox and the commercial record."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_inbound(
        self,
        *,
        lead: Lead,
        conversation: Conversation,
        inbox_id: uuid.UUID,
    ) -> IntakeResult:
        """Resolve the Contact and its Opportunity for one inbound message.

        Never commits. Idempotent: the opening command is scoped to the
        Conversation and the advancement command to the Inbox row, so Meta
        redelivery produces one Contact, one Opportunity and one transition.
        """
        actor = Actor.product(lead.organization_id, "CommercialIntake")
        engagement_origin = await engagement_origin_for_lead(self._session, lead.id)
        channel = CustomerChannel(lead.channel)
        identity = ChannelIdentity.customer_message(
            channel=channel,
            channel_account_id=lead.channel_account_id,
            provider_user_id=lead.provider_user_id,
            lead_id=lead.id,
            profile_name=lead.profile_name,
        )
        resolved = await CommercialIdentity(self._session).resolve(
            identity, organization_id=actor.organization_id
        )

        management = OpportunityManagement(self._session)
        # A later message in the same Conversation still belongs to the
        # pursuit that Conversation opened, even after the pursuit became
        # Dormant, Lost or Won. Only a later Conversation may open a new one.
        existing = await self.opportunity_for_conversation(conversation)
        if existing is None:
            need = await PropertyNeeds(self._session).open(
                actor, contact_id=resolved.contact_id
            )
            opened = await management.record(
                actor,
                OpenOpportunity(
                    contact_id=resolved.contact_id,
                    kind=OpportunityKind.DEMAND,
                    property_need_id=need.id,
                    origin=OriginFacts(
                        source=(
                            OpportunityOriginSource.CAMPAIGN
                            if engagement_origin is not None
                            else (
                                OpportunityOriginSource.WHATSAPP_INBOUND
                                if channel is CustomerChannel.WHATSAPP
                                else OpportunityOriginSource.MESSAGING_INBOUND
                            )
                        ),
                        channel=channel.value,
                        campaign=(
                            engagement_origin.label
                            if engagement_origin is not None
                            else None
                        ),
                        property_uuid=conversation.property_uuid,
                        first_conversation_id=conversation.id,
                        first_inbox_id=inbox_id,
                    ),
                    # One Conversation opens at most one pursuit. A later
                    # Conversation for the same Contact may legitimately open
                    # another after the earlier Opportunity closed; keying on
                    # Contact alone made that re-entry collide with the first
                    # Opportunity's immutable transition.
                    command_key=(
                        f"intake-open:{resolved.contact_id}:{conversation.id}"
                    ),
                ),
            )
            opportunity_id = opened.opportunity_id
            stage = opened.stage
            created = opened.created
        else:
            opportunity_id = existing.id
            stage = OpportunityStage(existing.stage)
            created = False

        await management.note_interaction(opportunity_id)

        if stage is OpportunityStage.NEW:
            advanced = await management.record(
                actor,
                AdvanceStage(
                    opportunity_id=opportunity_id,
                    to_stage=OpportunityStage.IN_CONVERSATION,
                    reason="InboundMessage",
                    # Keyed on the message so a redelivered webhook replays
                    # rather than recording a second transition.
                    command_key=f"intake-converse:{inbox_id}",
                ),
            )
            stage = advanced.stage

        return IntakeResult(
            contact_id=resolved.contact_id,
            opportunity_id=opportunity_id,
            stage=stage,
            contact_created=resolved.created,
            opportunity_created=created,
        )

    async def opportunity_for_conversation(
        self, conversation: Conversation
    ) -> Opportunity | None:
        """The Opportunity a conversation currently belongs to, if any."""
        originated = await self._session.scalar(
            select(Opportunity)
            .join(
                OpportunityOrigin,
                OpportunityOrigin.opportunity_id == Opportunity.id,
            )
            .where(
                Opportunity.organization_id == conversation.organization_id,
                OpportunityOrigin.organization_id == conversation.organization_id,
                OpportunityOrigin.first_conversation_id == conversation.id,
            )
            .limit(1)
        )
        if originated is not None:
            return originated
        contact_id = await CommercialIdentity(self._session).contact_for_lead(
            conversation.lead_id
        )
        if contact_id is None:
            return None
        return await OpportunityManagement(self._session).open_demand_for_contact(
            contact_id
        )

"""Shared setup for the Stage 2 commercial suites.

One place builds Organizations, members, Contacts and Opportunities so the
suites assert behaviour rather than each re-deriving the same wiring — and so a
schema change breaks one helper instead of nine files.

The helpers deliberately go through the real modules. A fixture that inserted an
Opportunity row directly would not exercise the invariants the tests exist to
prove.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ENGAGEMENT_CYCLE_DAYS,
    Conversation,
    InboxMessage,
    InboxStatus,
    Lead,
    LeadEngagementCycle,
    Opportunity,
    OpportunityKind,
    OpportunityOriginSource,
)
from realestate.domain.commercial.actors import Actor
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.identity import ChannelIdentity, CommercialIdentity
from realestate.domain.commercial.needs import (
    REQUIRED_CRITERIA,
    CriterionStatement,
    PropertyNeeds,
)
from realestate.domain.commercial.opportunities import (
    OpenOpportunity,
    OpportunityManagement,
    OriginFacts,
)
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
)


@dataclass(frozen=True)
class OpportunityState:
    """What a suite needs to drive one Opportunity it just built."""

    admin: Actor
    contact_id: uuid.UUID
    lead: Lead
    opportunity_id: uuid.UUID
    need_id: uuid.UUID | None


ADMIN_LOGIN = "admin@larevia.test"
ADVISOR_LOGIN = "asesor@larevia.test"
SECOND_ADVISOR_LOGIN = "asesor2@larevia.test"
ADMIN_PASSWORD = "test-admin-password"
ADVISOR_PASSWORD = "test-advisor-password"
SECOND_ADVISOR_PASSWORD = "test-advisor2-password"

#: The local Basic-auth accounts the operational surface authenticates. Kept as
#: a mapping rather than a literal so a suite can add an account that
#: authenticates but is deliberately absent from the member directory.
ACCOUNTS: dict[str, str] = {
    ADMIN_LOGIN: ADMIN_PASSWORD,
    ADVISOR_LOGIN: ADVISOR_PASSWORD,
    SECOND_ADVISOR_LOGIN: SECOND_ADVISOR_PASSWORD,
}


def credentials_json(**extra: str) -> str:
    """``DEVELOPER_BASIC_CREDENTIALS_JSON`` for the suite's accounts."""
    return json.dumps({**ACCOUNTS, **extra})


CREDENTIALS_JSON = credentials_json()

#: The plan every suite starts from: one Administrator who does not advise, and
#: two Advisors of whom the first is the deterministic fallback.
DEFAULT_PLAN = DirectoryPlan(
    administrators=(ADMIN_LOGIN,),
    advisors=(ADVISOR_LOGIN, SECOND_ADVISOR_LOGIN),
    default_advisor=ADVISOR_LOGIN,
)

#: Tables the commercial suites clear, roots last so cascades do the rest.
#: ``organizations`` is never cleared: migration 0012 creates the row and every
#: scoped table points at it.
_RESET_ORDER = (
    "delivery_statuses",
    "commercial_command_receipts",
    "commercial_transactions",
    "audit_events",
    "contacts",
    "leads",
)


def now() -> datetime:
    return datetime.now(tz=UTC)


async def reset(session: AsyncSession, *, members: bool = False) -> None:
    """Empty the commercial and conversational data, keeping the Organization.

    ``members`` is off by default because most suites want the directory that
    :func:`provision` set up and would otherwise pay for re-creating it. The
    suites that assert *on reconciliation itself* need an empty table, and they
    can only have one after the Contacts whose Opportunities reference those
    members are gone — hence the order.
    """
    for table in _RESET_ORDER:
        await session.execute(text(f"DELETE FROM {table}"))
    if members:
        await session.execute(text("DELETE FROM organization_members"))
    await session.commit()


async def organization_id(session: AsyncSession) -> uuid.UUID:
    """The Organization every commercial fixture row belongs to.

    Resolved through the product's own seam rather than a second copy of the
    query, so a suite exercises the same lookup the webhook path does.
    """
    return await OrganizationDirectory(session).organization_id()


async def provision(
    session: AsyncSession, plan: DirectoryPlan = DEFAULT_PLAN
) -> dict[str, uuid.UUID]:
    """Reconcile the member directory and return each login's member id."""
    directory = OrganizationDirectory(session)
    await directory.reconcile(plan)
    members = await directory.members(await organization_id(session))
    return {member.login: member.id for member in members}


async def actor_for(session: AsyncSession, login: str) -> Actor:
    return await OrganizationDirectory(session).resolve_actor(login)


async def product_actor(session: AsyncSession) -> Actor:
    return Actor.product(await organization_id(session), "TestHarness")


async def make_lead(
    session: AsyncSession,
    wa_id: str,
    *,
    profile_name: str | None = None,
) -> Lead:
    """A WhatsApp channel-identity record, as the webhook path would create it."""
    lead = Lead(
        organization_id=await organization_id(session),
        wa_id=wa_id,
        profile_name=profile_name,
    )
    session.add(lead)
    await session.flush()
    return lead


async def make_conversation(
    session: AsyncSession,
    lead: Lead,
    *,
    started_at: datetime | None = None,
) -> Conversation:
    moment = started_at or now()
    cycle = LeadEngagementCycle(
        lead_id=lead.id,
        started_at=moment,
        expires_at=moment + timedelta(days=ENGAGEMENT_CYCLE_DAYS),
    )
    session.add(cycle)
    await session.flush()
    conversation = Conversation(
        organization_id=lead.organization_id,
        lead_id=lead.id,
        cycle_id=cycle.id,
        phone_number_id="123456",
        created_at=moment,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def make_inbound(
    session: AsyncSession,
    conversation: Conversation,
    *,
    text_body: str = "Hola, me interesa una casa.",
    sent_at: datetime | None = None,
) -> InboxMessage:
    moment = sent_at or now()
    row = InboxMessage(
        conversation_id=conversation.id,
        wamid=f"wamid.{uuid.uuid4().hex}",
        from_wa_id="unknown",
        message_type="text",
        text=text_body,
        sent_at=moment,
        persisted_at=moment,
        raw_message={"text": {"body": text_body}},
        status=InboxStatus.PROCESSED.value,
    )
    session.add(row)
    await session.flush()
    return row


async def make_contact(
    session: AsyncSession,
    wa_id: str,
    *,
    profile_name: str | None = None,
) -> tuple[uuid.UUID, Lead]:
    """A Contact resolved from a Verified WhatsApp identity."""
    lead = await make_lead(session, wa_id, profile_name=profile_name)
    resolved = await CommercialIdentity(session).resolve(
        ChannelIdentity.whatsapp(
            wa_id=wa_id, lead_id=lead.id, profile_name=profile_name
        ),
        organization_id=lead.organization_id,
    )
    await session.flush()
    return resolved.contact_id, lead


async def open_opportunity(
    session: AsyncSession,
    actor: Actor,
    contact_id: uuid.UUID,
    *,
    kind: OpportunityKind = OpportunityKind.DEMAND,
    with_need: bool = True,
    command_key: str | None = None,
    conversation: Conversation | None = None,
    inbox_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Open an Opportunity through the real module, with its first attribution.

    ``conversation`` and ``inbox_id`` are optional because most suites do not
    care where the pursuit came from. The retention suite does: the whole point
    of blanking message bodies rather than deleting rows is that attribution
    keeps its anchor.
    """
    need_id = None
    if with_need:
        need = await PropertyNeeds(session).open(actor, contact_id=contact_id)
        need_id = need.id
    recorded = await OpportunityManagement(session).record(
        actor,
        OpenOpportunity(
            contact_id=contact_id,
            kind=kind,
            property_need_id=need_id,
            origin=OriginFacts(
                source=OpportunityOriginSource.WHATSAPP_INBOUND,
                channel="WhatsApp",
                first_conversation_id=conversation.id if conversation else None,
                first_inbox_id=inbox_id,
            ),
            command_key=command_key or f"open:{uuid.uuid4().hex}",
        ),
    )
    return recorded.opportunity_id


CONFIRMED_CRITERIA = {
    "transaction_intent": "Buy",
    "service_area": "Zapopan norte",
    "economic_range": "3.5 a 4.5 millones MXN",
    "horizon": "Tres meses",
    "essential_requirements": "Tres recámaras y dos estacionamientos",
}


async def confirm_minimum_criteria(
    session: AsyncSession,
    actor: Actor,
    need_id: uuid.UUID,
    *,
    at: datetime | None = None,
    omit: tuple[str, ...] = (),
) -> None:
    """Record every accepted minimum criterion as Confirmed, minus *omit*."""
    statements = [
        CriterionStatement.stated(name, CONFIRMED_CRITERIA[name])
        for name in REQUIRED_CRITERIA
        if name not in omit
    ]
    await PropertyNeeds(session).record(actor, need_id, statements, now=at)


async def opportunity_for(
    session: AsyncSession,
    wa_id: str = "5213312345678",
    *,
    profile_name: str | None = None,
    assign: bool = False,
    confirm_criteria: bool = False,
    conversation: Conversation | None = None,
    inbox_id: uuid.UUID | None = None,
) -> OpportunityState:
    """A Contact with an Opportunity, taken as far as the caller needs.

    One builder instead of the four near-identical ones the suites had grown:
    each opened with the same three lines and then added zero, one or two steps,
    so a new argument to :func:`open_opportunity` meant editing five places.
    """
    contact_id, lead = await make_contact(session, wa_id, profile_name=profile_name)
    admin = await actor_for(session, ADMIN_LOGIN)
    opportunity_id = await open_opportunity(
        session,
        admin,
        contact_id,
        conversation=conversation,
        inbox_id=inbox_id,
    )
    need_id: uuid.UUID | None = await session.scalar(
        select(Opportunity.property_need_id).where(Opportunity.id == opportunity_id)
    )
    if confirm_criteria:
        assert need_id is not None
        await confirm_minimum_criteria(session, admin, need_id)
    if assign:
        await Assignment(session).assign(admin, opportunity_id)
    return OpportunityState(
        admin=admin,
        contact_id=contact_id,
        lead=lead,
        opportunity_id=opportunity_id,
        need_id=need_id,
    )

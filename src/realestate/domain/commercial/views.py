"""The commercial read model: everything an operator surface is allowed to see.

Every CRM screen reads through :class:`CommercialInbox`. That is what keeps four
concerns out of the routers and templates:

* **Organization scoping.** No query here is unscoped.
* **Role visibility.** An Advisor sees their organization and their own
  assignments; an Administrator sees the whole initial operation. Applied in
  the query, so a template cannot widen it by iterating differently.
* **Retention.** A message whose body has expired reads as expired rather than
  as empty (ADR-0026). The commercial row is still there; the words are not.
* **Restrictions.** An active Suppression Record and the Stage 1 denials are
  shown *as facts about what Product refused*, next to the conversation they
  belong to. Showing them is the point; none of these views can send anything.

The one metric the stage exists to prove lives here too. Follow-up Coverage is
the share of active Opportunities that have a Responsible Advisor, an explicit
stage, and either a Next Action that is not overdue or a recorded exception.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy import true as sql_true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from realestate.db.models import (
    ACTIVE_STAGES,
    Contact,
    ContactChannelIdentity,
    Conversation,
    InboxMessage,
    NextAction,
    NextActionStatus,
    Opportunity,
    OpportunityException,
    OpportunityStage,
    QUALIFIED_OR_BEYOND,
    OutboundDecision,
    OutboundOutcome,
    OutboxMessage,
    OrganizationMember,
    SuppressionRecord,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.commercial.next_actions import NextActions

EXPIRED_BODY = "(contenido conversacional expirado)"

#: How many coverage gaps the panel returns. The count is exact; the list is
#: what somebody is going to work through this morning.
GAP_LIMIT = 50


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _preview_of(message: InboxMessage | None) -> str:
    """What the Inbox row shows of the last inbound message.

    An expired body reads as expired rather than as empty (ADR-0026): the
    commercial row is still there, the words are not.
    """
    if message is None:
        return "Sin mensajes todavía."
    if message.content_expired_at is not None:
        return EXPIRED_BODY
    text = (message.text or "").strip()
    if not text:
        return f"(mensaje de tipo {message.message_type})"
    return text[:160]


def _pending_action_alias() -> Any:
    """An aliased ``NextAction`` restricted to the one Pending row.

    A partial unique index already guarantees at most one per Opportunity, so
    this outer-joins as a single entity rather than needing a grouping, and
    SQLAlchemy hydrates a real :class:`NextAction` — or ``None`` — per row.

    A function rather than a module constant because a subquery carries
    per-statement aliasing and must not be shared between statements.
    """
    return aliased(
        NextAction,
        select(NextAction)
        .where(NextAction.status == NextActionStatus.PENDING.value)
        .subquery(),
    )


def _open_exception_subquery() -> Any:
    """The one open Opportunity Exception per Opportunity, reason only."""
    return (
        select(
            OpportunityException.opportunity_id.label("opportunity_id"),
            OpportunityException.reason.label("reason"),
        )
        .where(OpportunityException.cleared_at.is_(None))
        .subquery()
    )


def _first_identity_subquery() -> Any:
    """One channel identity per Contact, for display.

    ``min`` rather than a correlated "first seen": the surfaces show it as a
    recognisable label beside the name, and a deterministic pick is enough for
    that. The full list is on the Contact's own page.
    """
    return (
        select(
            ContactChannelIdentity.contact_id.label("contact_id"),
            func.min(ContactChannelIdentity.identity).label("identity"),
        )
        .group_by(ContactChannelIdentity.contact_id)
        .subquery()
    )


@dataclass(frozen=True)
class InboxFilters:
    """What the operator narrowed the Inbox to.

    ``scope`` is a request, not an authority: ``all`` still means "all I may
    see". An Advisor asking for everything gets their own assignments.
    """

    scope: str = "all"
    needs_reply: bool = False
    overdue: bool = False
    restricted: bool = False
    stage: str | None = None
    query: str | None = None
    limit: int = 50

    SCOPES = ("all", "mine", "unassigned")

    @classmethod
    def parse(cls, params: dict[str, str]) -> InboxFilters:
        """Build filters from query-string values, ignoring anything unknown.

        Unrecognised values fall back to the default rather than erroring: a
        stale bookmark should show a list, not a 422.
        """
        scope = params.get("scope", "all")
        stage = params.get("stage") or None
        if stage is not None and stage not in {s.value for s in OpportunityStage}:
            stage = None
        raw_limit = params.get("limit", "")
        limit = int(raw_limit) if raw_limit.isdigit() else 50
        return cls(
            scope=scope if scope in cls.SCOPES else "all",
            needs_reply=params.get("sin_respuesta") == "1",
            overdue=params.get("vencidas") == "1",
            restricted=params.get("restringidos") == "1",
            stage=stage,
            query=(params.get("q") or "").strip() or None,
            limit=max(1, min(limit, 200)),
        )


@dataclass(frozen=True)
class MessageView:
    """One durable message, with its body only if the body still exists."""

    direction: str
    at: datetime
    body: str
    expired: bool
    kind: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class DenialView:
    """One thing Product decided not to send, and why."""

    at: datetime
    purpose: str
    reason: str
    detail: str | None


@dataclass(frozen=True)
class RestrictionView:
    """Why the operation may not reach out to this Contact right now.

    The Inbox list needs only "is there anything, and how much"; the detail
    surface needs each refusal and its reason. So the count is its own field:
    the list gets it from an aggregate in the page query, and the detail fills
    both. ``denied_count`` is authoritative for "how many" — ``denials`` is the
    most recent few, not necessarily all of them.
    """

    suppressed: bool
    suppression_reason: str | None
    suppressed_at: datetime | None
    denials: tuple[DenialView, ...] = ()
    denied_count: int = 0

    @property
    def any(self) -> bool:
        return self.suppressed or self.denied_count > 0 or bool(self.denials)


@dataclass(frozen=True)
class InboxEntry:
    """One row of the operational Inbox."""

    conversation_id: uuid.UUID
    contact_id: uuid.UUID
    contact_name: str | None
    channel: str
    channel_identity: str
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    preview: str
    preview_expired: bool
    opportunity_id: uuid.UUID | None
    stage: str | None
    advisor_name: str | None
    next_action: NextAction | None
    next_action_overdue: bool
    exception_reason: str | None
    restriction: RestrictionView

    @property
    def awaiting_reply(self) -> bool:
        """The Contact wrote last. The single most useful Inbox signal."""
        if self.last_inbound_at is None:
            return False
        return (
            self.last_outbound_at is None
            or self.last_inbound_at > self.last_outbound_at
        )


@dataclass(frozen=True)
class ConversationView:
    """One conversation in full, for the Inbox detail surface."""

    conversation_id: uuid.UUID
    contact: Contact
    channel: str
    channel_identity: str
    messages: tuple[MessageView, ...]
    restriction: RestrictionView
    opportunity: Opportunity | None
    advisor_name: str | None


@dataclass(frozen=True)
class OpportunityRow:
    """One Opportunity as the pipeline surface shows it."""

    opportunity: Opportunity
    contact_name: str | None
    channel_identity: str | None
    advisor_name: str | None
    next_action: NextAction | None
    overdue: bool
    exception_reason: str | None

    @property
    def covered(self) -> bool:
        """Whether this Opportunity satisfies the operating promise right now."""
        if self.opportunity.stage not in QUALIFIED_OR_BEYOND:
            return True
        if self.opportunity.responsible_advisor_id is None:
            return False
        if self.exception_reason is not None and self.next_action is None:
            return True
        return self.next_action is not None and not self.overdue


@dataclass(frozen=True)
class ContactRow:
    """One Contact as the Contacts surface shows it."""

    contact: Contact
    identities: tuple[str, ...]
    open_opportunities: int
    suppressed: bool
    last_activity_at: datetime | None


@dataclass(frozen=True)
class Coverage:
    """Follow-up Coverage, and the specific gaps behind the number."""

    active: int
    covered: int
    without_advisor: int
    without_action: int
    overdue: int
    qualified_active: int
    qualified_covered: int
    gaps: tuple[OpportunityRow, ...] = field(default_factory=tuple)

    @property
    def percentage(self) -> int:
        """Whole percent, floored. 100 only when there is genuinely no gap."""
        if self.active == 0:
            return 100
        return int(self.covered * 100 // self.active)

    @property
    def complete(self) -> bool:
        return self.active == self.covered


class CommercialInbox:
    """The read model behind every operator surface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- The Inbox ---------------------------------------------------------

    async def query(
        self,
        actor: Actor,
        filters: InboxFilters | None = None,
        *,
        now: datetime | None = None,
    ) -> list[InboxEntry]:
        """Conversations the Actor may work, most recently active first.

        Every filter is applied in SQL. An earlier version fetched four times
        the page size and discarded rows in Python, having already paid six
        lookups for each — so a narrow filter cost over a thousand round trips
        for one page and could still return a short page with no explanation.
        """
        filters = filters or InboxFilters()
        moment = now or _now()

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
        # The Contact's working Opportunity: active first, else the newest. A
        # lateral, because "one row per Contact chosen by an ordering" is what
        # LATERAL is for and the alternative is a query per row.
        pursuit = (
            select(Opportunity)
            .where(Opportunity.contact_id == Contact.id)
            .order_by(
                Opportunity.stage.in_(ACTIVE_STAGES).desc(),
                Opportunity.created_at.desc(),
            )
            .limit(1)
            .lateral("pursuit")
        )
        opportunity = aliased(Opportunity, pursuit)
        pending = _pending_action_alias()
        exceptions = _open_exception_subquery()
        # The reason comes back with the flag: an operator who sees "no
        # contactar" without knowing why cannot judge whether it still applies.
        suppressions = (
            select(
                SuppressionRecord.lead_id.label("lead_id"),
                func.min(SuppressionRecord.reason).label("reason"),
                func.min(SuppressionRecord.recorded_at).label("recorded_at"),
            )
            .where(SuppressionRecord.revoked_at.is_(None))
            .group_by(SuppressionRecord.lead_id)
            .subquery()
        )
        denials = (
            select(
                OutboundDecision.conversation_id.label("conversation_id"),
                func.count(OutboundDecision.id).label("denied"),
            )
            .where(OutboundDecision.outcome == OutboundOutcome.DENIED.value)
            .group_by(OutboundDecision.conversation_id)
            .subquery()
        )
        latest_inbox = (
            select(InboxMessage)
            .where(InboxMessage.conversation_id == Conversation.id)
            .order_by(InboxMessage.sent_at.desc(), InboxMessage.persisted_at.desc())
            .limit(1)
            .lateral("latest_inbox")
        )
        preview_row = aliased(InboxMessage, latest_inbox)

        statement = (
            select(
                Conversation,
                ContactChannelIdentity.identity.label("channel_identity"),
                Contact,
                last_inbound.c.at.label("last_inbound_at"),
                last_outbound.c.at.label("last_outbound_at"),
                opportunity,
                pending,
                exceptions.c.reason.label("exception_reason"),
                OrganizationMember.display_name.label("advisor_name"),
                suppressions.c.lead_id.label("suppressed_lead"),
                suppressions.c.reason.label("suppression_reason"),
                suppressions.c.recorded_at.label("suppressed_at"),
                denials.c.denied,
                preview_row,
            )
            .join(
                ContactChannelIdentity,
                ContactChannelIdentity.lead_id == Conversation.lead_id,
            )
            .join(Contact, Contact.id == ContactChannelIdentity.contact_id)
            .outerjoin(last_inbound, last_inbound.c.conversation_id == Conversation.id)
            .outerjoin(
                last_outbound, last_outbound.c.conversation_id == Conversation.id
            )
            .outerjoin(opportunity, sql_true())
            .outerjoin(pending, pending.opportunity_id == opportunity.id)
            .outerjoin(exceptions, exceptions.c.opportunity_id == opportunity.id)
            .outerjoin(
                OrganizationMember,
                OrganizationMember.id == opportunity.responsible_advisor_id,
            )
            .outerjoin(suppressions, suppressions.c.lead_id == Conversation.lead_id)
            .outerjoin(denials, denials.c.conversation_id == Conversation.id)
            .outerjoin(preview_row, sql_true())
            .where(Conversation.organization_id == actor.organization_id)
        )

        # Role visibility. An Advisor sees their own assignments and nothing
        # else — including nothing unassigned, because nobody is responsible for
        # it yet and that is the Administrator's problem to notice.
        if not actor.sees_whole_operation:
            statement = statement.where(
                opportunity.responsible_advisor_id == actor.member_id
            )

        if filters.query:
            needle = f"%{filters.query.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(func.coalesce(Contact.display_name, "")).like(needle),
                    ContactChannelIdentity.identity.like(f"%{filters.query}%"),
                )
            )
        if filters.scope == "mine":
            statement = statement.where(
                opportunity.responsible_advisor_id == actor.member_id
            )
        elif filters.scope == "unassigned":
            statement = statement.where(opportunity.responsible_advisor_id.is_(None))
        if filters.stage is not None:
            statement = statement.where(opportunity.stage == filters.stage)
        if filters.needs_reply:
            statement = statement.where(
                last_inbound.c.at.isnot(None),
                or_(
                    last_outbound.c.at.is_(None),
                    last_inbound.c.at > last_outbound.c.at,
                ),
            )
        if filters.overdue:
            statement = statement.where(pending.due_at <= moment)
        if filters.restricted:
            statement = statement.where(
                or_(
                    suppressions.c.lead_id.isnot(None),
                    denials.c.denied.isnot(None),
                )
            )

        records = (
            await self._session.execute(
                statement.order_by(
                    func.coalesce(last_inbound.c.at, Conversation.created_at).desc()
                ).limit(filters.limit)
            )
        ).all()

        # The denial *details* are only shown on the detail surface; the list
        # needs the count, which the join already gave. Two batched lookups
        # would otherwise be six per row.
        entries: list[InboxEntry] = []
        for record in records:
            # Unpacked rather than indexed: an aliased entity has no dependable
            # Row key, and positional access shifts silently the moment a column
            # is added to the select list. A mismatch here raises at once.
            (
                conversation,
                channel_identity,
                contact,
                last_inbound_at,
                last_outbound_at,
                opportunity_row,
                action,
                exception_reason,
                advisor_name,
                suppressed_lead,
                suppression_reason,
                suppressed_at,
                denied,
                preview_message,
            ) = record
            entries.append(
                InboxEntry(
                    conversation_id=conversation.id,
                    contact_id=contact.id,
                    contact_name=contact.display_name,
                    channel=conversation.channel,
                    channel_identity=channel_identity,
                    last_inbound_at=last_inbound_at,
                    last_outbound_at=last_outbound_at,
                    preview=_preview_of(preview_message),
                    preview_expired=(
                        preview_message is not None
                        and preview_message.content_expired_at is not None
                    ),
                    opportunity_id=(
                        opportunity_row.id if opportunity_row is not None else None
                    ),
                    stage=(
                        opportunity_row.stage if opportunity_row is not None else None
                    ),
                    advisor_name=advisor_name,
                    next_action=action,
                    next_action_overdue=NextActions.is_overdue(action, now=moment),
                    exception_reason=exception_reason,
                    restriction=RestrictionView(
                        suppressed=suppressed_lead is not None,
                        suppression_reason=suppression_reason,
                        suppressed_at=suppressed_at,
                        denied_count=int(denied or 0),
                    ),
                )
            )
        return entries

    async def conversation(
        self, actor: Actor, conversation_id: uuid.UUID
    ) -> ConversationView:
        """One conversation with its messages, restrictions and Opportunity."""
        conversation = await self._session.get(Conversation, conversation_id)
        if conversation is None:
            raise NotFound("No encontramos esa conversación.")
        actor.require_same_organization(conversation.organization_id)

        identity = await self._session.scalar(
            select(ContactChannelIdentity).where(
                ContactChannelIdentity.lead_id == conversation.lead_id
            )
        )
        if identity is None:
            raise NotFound("Esa conversación aún no tiene un contacto resuelto.")
        contact = await self._session.get(Contact, identity.contact_id)
        assert contact is not None
        opportunity = await self._contact_opportunity(actor, contact.id)
        if not self._visible(actor, opportunity):
            raise NotFound("No encontramos esa conversación.")

        return ConversationView(
            conversation_id=conversation.id,
            contact=contact,
            channel=conversation.channel,
            channel_identity=identity.identity,
            messages=await self._messages(conversation.id),
            restriction=await self.restriction(conversation),
            opportunity=opportunity,
            advisor_name=await self._advisor_name(opportunity),
        )

    async def restriction(self, conversation: Conversation) -> RestrictionView:
        """What Product refused, and what it is currently forbidden to do.

        Read straight from Stage 1's own evidence. Nothing here can send: the
        surface exists so an operator learns *why* a message did not go out
        instead of concluding the system is broken.
        """
        suppression = await self._session.scalar(
            select(SuppressionRecord)
            .where(SuppressionRecord.lead_id == conversation.lead_id)
            .where(SuppressionRecord.revoked_at.is_(None))
            .limit(1)
        )
        denials = await self._session.scalars(
            select(OutboundDecision)
            .where(OutboundDecision.conversation_id == conversation.id)
            .where(OutboundDecision.outcome == OutboundOutcome.DENIED.value)
            .order_by(OutboundDecision.decided_at.desc())
            .limit(10)
        )
        sample = tuple(
            DenialView(
                at=row.decided_at,
                purpose=row.purpose,
                reason=row.reason or "Unknown",
                detail=row.detail,
            )
            for row in denials
        )
        denied_count = int(
            await self._session.scalar(
                select(func.count(OutboundDecision.id))
                .where(OutboundDecision.conversation_id == conversation.id)
                .where(OutboundDecision.outcome == OutboundOutcome.DENIED.value)
            )
            or 0
        )
        return RestrictionView(
            suppressed=suppression is not None,
            suppression_reason=suppression.reason if suppression else None,
            suppressed_at=suppression.recorded_at if suppression else None,
            denials=sample,
            denied_count=denied_count,
        )

    # -- Opportunities -----------------------------------------------------

    async def funnel(self, actor: Actor) -> dict[str, int]:
        """Current Opportunity count by stage inside the Actor's visibility.

        This is Product truth, not an analytics projection. The operational CRM
        needs the current state immediately after a stage transition; historical
        conversion and period reporting remain the analytics pipeline's job.
        """
        statement = (
            select(Opportunity.stage, func.count(Opportunity.id))
            .where(Opportunity.organization_id == actor.organization_id)
            .group_by(Opportunity.stage)
        )
        if not actor.sees_whole_operation:
            statement = statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        observed: dict[str, int] = {
            stage: int(count)
            for stage, count in (await self._session.execute(statement)).all()
        }
        return {
            stage.value: int(observed.get(stage.value, 0)) for stage in OpportunityStage
        }

    async def opportunities(
        self,
        actor: Actor,
        *,
        stage: str | None = None,
        scope: str = "all",
        only_gaps: bool = False,
        include_closed: bool = False,
        now: datetime | None = None,
        limit: int = 200,
    ) -> list[OpportunityRow]:
        """The pipeline the Actor may see, newest first."""
        moment = now or _now()
        statement = select(Opportunity).where(
            Opportunity.organization_id == actor.organization_id
        )
        if stage is not None:
            statement = statement.where(Opportunity.stage == stage)
        elif not include_closed:
            statement = statement.where(Opportunity.stage.in_(ACTIVE_STAGES))
        if scope == "mine" and actor.member_id is not None:
            statement = statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        elif scope == "unassigned":
            statement = statement.where(Opportunity.responsible_advisor_id.is_(None))
        if not actor.sees_whole_operation:
            statement = statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        # One statement for the whole page. The per-row lookups this replaced
        # cost four queries each, so a 200-row pipeline was ~800 round trips —
        # and `coverage()` below reads up to 1,000 rows.
        pending = _pending_action_alias()
        exceptions = _open_exception_subquery()
        identities = _first_identity_subquery()
        statement = (
            statement.add_columns(
                Contact.display_name.label("contact_name"),
                identities.c.identity.label("channel_identity"),
                OrganizationMember.display_name.label("advisor_name"),
                pending,
                exceptions.c.reason.label("exception_reason"),
            )
            .join(Contact, Contact.id == Opportunity.contact_id)
            .outerjoin(identities, identities.c.contact_id == Opportunity.contact_id)
            .outerjoin(
                OrganizationMember,
                OrganizationMember.id == Opportunity.responsible_advisor_id,
            )
            .outerjoin(pending, pending.opportunity_id == Opportunity.id)
            .outerjoin(exceptions, exceptions.c.opportunity_id == Opportunity.id)
        )
        if only_gaps:
            assigned, owed, _excused, _on_time, covered = self._coverage_terms(
                pending, exceptions, moment
            )
            statement = statement.where(
                Opportunity.stage.in_(QUALIFIED_OR_BEYOND)
            ).where(~covered)
        statement = statement.order_by(Opportunity.last_activity_at.desc()).limit(limit)
        out: list[OpportunityRow] = []
        for record in (await self._session.execute(statement)).all():
            row = OpportunityRow(
                opportunity=record[0],
                contact_name=record.contact_name,
                channel_identity=record.channel_identity,
                advisor_name=record.advisor_name,
                next_action=record[4],
                overdue=NextActions.is_overdue(record[4], now=moment),
                exception_reason=record.exception_reason,
            )
            out.append(row)
        return out

    async def coverage(self, actor: Actor, *, now: datetime | None = None) -> Coverage:
        """Follow-up Coverage for the Actor's visible operation.

        Reported with its gaps attached rather than as a bare number: a
        percentage nobody can act on is a dashboard, not an operating tool.
        """
        moment = now or _now()

        # Counted in the database, not by fetching every row. This used to read
        # up to 1,000 Opportunities and issue four lookups per row, so the
        # default landing page could cost ~4,000 round trips; the numbers it
        # needs are aggregates.
        pending = _pending_action_alias()
        exceptions = _open_exception_subquery()
        assigned, owed, excused, on_time, covered = self._coverage_terms(
            pending, exceptions, moment
        )

        totals = (
            await self._session.execute(
                self._coverage_scope(actor)
                .add_columns(
                    func.count(Opportunity.id).label("active"),
                    func.count(Opportunity.id).filter(covered).label("covered"),
                    func.count(Opportunity.id).filter(~assigned).label("unassigned"),
                    func.count(Opportunity.id)
                    .filter(assigned & ~owed & ~excused)
                    .label("without_action"),
                    func.count(Opportunity.id)
                    .filter(owed & (pending.due_at <= moment))
                    .label("overdue"),
                    func.count(Opportunity.id).label("qualified_active"),
                    func.count(Opportunity.id)
                    .filter(covered)
                    .label("qualified_covered"),
                )
                .outerjoin(pending, pending.opportunity_id == Opportunity.id)
                .outerjoin(exceptions, exceptions.c.opportunity_id == Opportunity.id)
            )
        ).one()

        # The gaps are the part an operator acts on, so they come back as rows —
        # bounded, because a panel that lists a thousand of them helps nobody.
        gaps = await self.opportunities(
            actor, only_gaps=True, now=moment, limit=GAP_LIMIT
        )
        return Coverage(
            active=totals.active,
            covered=totals.covered,
            without_advisor=totals.unassigned,
            without_action=totals.without_action,
            overdue=totals.overdue,
            qualified_active=totals.qualified_active,
            qualified_covered=totals.qualified_covered,
            gaps=tuple(gaps),
        )

    def _coverage_scope(self, actor: Actor) -> Select[Any]:
        """The active Opportunities this Actor may count.

        Shared by the aggregate above and, through ``opportunities()``, by the
        gap list, so the number and the list cannot disagree about scope.
        """
        statement = (
            select()
            .select_from(Opportunity)
            .where(Opportunity.organization_id == actor.organization_id)
            .where(Opportunity.stage.in_(QUALIFIED_OR_BEYOND))
        )
        if not actor.sees_whole_operation:
            statement = statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        return statement

    @staticmethod
    def _coverage_terms(
        pending: Any, exceptions: Any, moment: datetime
    ) -> tuple[Any, Any, Any, Any, Any]:
        """One SQL expression of the Qualified follow-up promise."""
        assigned = Opportunity.responsible_advisor_id.isnot(None)
        owed = pending.id.isnot(None)
        excused = exceptions.c.reason.isnot(None)
        on_time = owed & (pending.due_at > moment)
        covered = assigned & (on_time | (excused & ~owed))
        return assigned, owed, excused, on_time, covered

    # -- Contacts ----------------------------------------------------------

    async def contacts(
        self,
        actor: Actor,
        *,
        query: str | None = None,
        limit: int = 100,
    ) -> list[ContactRow]:
        """Contacts the Actor may see.

        An Advisor sees the Contacts behind their own Opportunities. A Contact
        with no Opportunity at all is visible only to an Administrator, because
        nobody is responsible for them yet — which is itself the Administrator's
        problem to notice.
        """
        statement = select(Contact).where(
            Contact.organization_id == actor.organization_id
        )
        if query:
            needle = f"%{query.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(func.coalesce(Contact.display_name, "")).like(needle),
                    Contact.id.in_(
                        select(ContactChannelIdentity.contact_id).where(
                            ContactChannelIdentity.identity.like(f"%{query}%")
                        )
                    ),
                )
            )
        if not actor.sees_whole_operation:
            statement = statement.where(
                Contact.id.in_(
                    select(Opportunity.contact_id).where(
                        Opportunity.responsible_advisor_id == actor.member_id
                    )
                )
            )
        # One statement for the page. The four per-contact lookups this
        # replaced made a 100-row list ~400 round trips.
        pursuits = (
            select(
                Opportunity.contact_id.label("contact_id"),
                func.count(Opportunity.id)
                .filter(Opportunity.stage.in_(ACTIVE_STAGES))
                .label("open_count"),
                func.max(Opportunity.last_activity_at).label("last_activity_at"),
            )
            .group_by(Opportunity.contact_id)
            .subquery()
        )
        # ``string_agg`` rather than a second round trip per contact: the list
        # surface shows the identities inline, and there are one or two of them.
        reach = (
            select(
                ContactChannelIdentity.contact_id.label("contact_id"),
                func.array_agg(ContactChannelIdentity.identity).label("identities"),
                func.count(SuppressionRecord.id)
                .filter(SuppressionRecord.revoked_at.is_(None))
                .label("suppressions"),
            )
            .outerjoin(
                SuppressionRecord,
                SuppressionRecord.lead_id == ContactChannelIdentity.lead_id,
            )
            .group_by(ContactChannelIdentity.contact_id)
            .subquery()
        )
        records = (
            await self._session.execute(
                statement.add_columns(
                    reach.c.identities,
                    reach.c.suppressions,
                    pursuits.c.open_count,
                    pursuits.c.last_activity_at,
                )
                .outerjoin(reach, reach.c.contact_id == Contact.id)
                .outerjoin(pursuits, pursuits.c.contact_id == Contact.id)
                .order_by(Contact.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            ContactRow(
                contact=record[0],
                identities=tuple(record.identities or ()),
                open_opportunities=int(record.open_count or 0),
                suppressed=bool(record.suppressions),
                last_activity_at=record.last_activity_at,
            )
            for record in records
        ]

    # -- internals ---------------------------------------------------------

    def _visible(self, actor: Actor, opportunity: Opportunity | None) -> bool:
        if actor.sees_whole_operation:
            return True
        if opportunity is None:
            return False
        return opportunity.responsible_advisor_id == actor.member_id

    async def _contact_opportunity(
        self, actor: Actor, contact_id: uuid.UUID
    ) -> Opportunity | None:
        """The Contact's most relevant Opportunity: active first, then newest."""
        active_statement = (
            select(Opportunity)
            .where(Opportunity.contact_id == contact_id)
            .where(Opportunity.stage.in_(ACTIVE_STAGES))
            .order_by(Opportunity.created_at)
            .limit(1)
        )
        if not actor.sees_whole_operation:
            active_statement = active_statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        active = await self._session.scalar(active_statement)
        if active is not None:
            return active
        latest_statement = (
            select(Opportunity)
            .where(Opportunity.contact_id == contact_id)
            .order_by(Opportunity.created_at.desc())
            .limit(1)
        )
        if not actor.sees_whole_operation:
            latest_statement = latest_statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        found: Opportunity | None = await self._session.scalar(latest_statement)
        return found

    async def _advisor_name(self, opportunity: Opportunity | None) -> str | None:
        if opportunity is None or opportunity.responsible_advisor_id is None:
            return None
        member = await self._session.get(
            OrganizationMember, opportunity.responsible_advisor_id
        )
        return member.display_name if member else None

    async def _messages(self, conversation_id: uuid.UUID) -> tuple[MessageView, ...]:
        inbound = await self._session.scalars(
            select(InboxMessage)
            .where(InboxMessage.conversation_id == conversation_id)
            .order_by(InboxMessage.sent_at)
        )
        outbound = await self._session.scalars(
            select(OutboxMessage)
            .where(OutboxMessage.conversation_id == conversation_id)
            .order_by(OutboxMessage.created_at)
        )
        views: list[MessageView] = []
        for received in inbound:
            expired = received.content_expired_at is not None
            views.append(
                MessageView(
                    direction="Contacto",
                    at=received.sent_at,
                    body=(
                        EXPIRED_BODY
                        if expired
                        else (received.text or f"({received.message_type})")
                    ),
                    expired=expired,
                    status=received.status,
                )
            )
        for sent in outbound:
            expired = sent.content_expired_at is not None
            views.append(
                MessageView(
                    direction="Maia",
                    at=sent.created_at,
                    body=EXPIRED_BODY if expired else sent.body,
                    expired=expired,
                    kind=sent.kind,
                    status=sent.status,
                )
            )
        return tuple(sorted(views, key=lambda view: view.at))

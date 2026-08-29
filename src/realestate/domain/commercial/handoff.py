"""A Contact asked for a person. Now what (ADR-0029)?

The failure this module exists to prevent is the quiet one: a customer says
"quiero hablar con alguien", Maia answers warmly, and nothing else happens. So
the request becomes a durable row with an alert and a deadline.

The shape of the promise is deliberately modest, and the wording matters as much
as the mechanism. Maia does **not** state a response-time SLA — it cannot know
whether the Advisor is in a car — so the copy says it will notify the Advisor,
admits it cannot confirm their availability, and says it will do what it can to
have them reply within the next few minutes. That exact sentence is approved
product copy, not something the Model composes.

Internally three things happen, in one transaction with the message that asked:

1. handling authority moves off Maia, so she cannot keep selling over the top of
   an unmet request;
2. the responsible Advisor is alerted immediately;
3. a 15-minute deadline is stamped on the row.

If nobody has taken it by the deadline, the Organization Administrator is
alerted. Product does **not** reassign the Opportunity: an operation that
silently moves work when somebody is slow teaches its people that the assignment
means nothing. The escalation is exactly-once across restarts because the alert
row and the ``admin_alert_at`` stamp commit together — a crash before the commit
re-derives the same due request, and a crash after it finds nothing due.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    Contact,
    Conversation,
    HandoffSource,
    HandoffStatus,
    HumanHandoffRequest,
    InternalAlertKind,
    Lead,
    Opportunity,
    OrganizationMember,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, NotAuthorized, NotFound
from realestate.domain.commercial.handling import ConversationHandling
from realestate.domain.internal_alerts import InternalAlerts

logger = logging.getLogger(__name__)

#: PROJECT_MEMORY and ADR-0029: after this long with nobody handling, the
#: Organization Administrator is told. It is an alert threshold, not a promise
#: made to the Contact, and it never moves the Opportunity.
ESCALATION_DELAY = timedelta(minutes=15)

SOURCE_LABELS: dict[str, str] = {
    HandoffSource.CONTACT_REQUEST.value: "El cliente pidió una persona",
    HandoffSource.POST_HANDOFF_ROUTING.value: "Pregunta comercial tras la cita",
    HandoffSource.HUMAN_INITIATED.value: "Una persona lo solicitó",
}

STATUS_LABELS: dict[str, str] = {
    HandoffStatus.PENDING.value: "Sin tomar",
    HandoffStatus.ACKNOWLEDGED.value: "Tomada",
    HandoffStatus.CANCELLED.value: "Cerrada sin atender",
}

#: The approved Contact-facing sentence (PROJECT_MEMORY, SAN-023 pending).
#: Product owns it so no model run can turn it into a commitment: it promises
#: notification and effort, never a deadline or the Advisor's availability.
HUMAN_HANDOFF_ACKNOWLEDGEMENT = (
    "Perfecto, le avisaré al asesor. No puedo confirmar su disponibilidad en "
    "este momento, pero haré todo lo posible para que se comunique contigo en "
    "los próximos minutos."
)


# ---------------------------------------------------------------- Commands ---


@dataclass(frozen=True)
class RequestHumanHandling:
    """One request for a person on one Conversation.

    ``command_key`` is not on this command: the open-request partial unique
    index is the natural idempotency, and the honest behaviour for a Contact
    asking three times is one unmet request rather than three alerts.
    """

    conversation: Conversation
    source: HandoffSource
    trigger_inbox_id: uuid.UUID | None = None
    #: Free-form operator note, never shown to the Contact.
    detail: str | None = None


@dataclass(frozen=True)
class AcknowledgeHandoff:
    request_id: uuid.UUID
    command_key: str


@dataclass(frozen=True)
class HandoffRecorded:
    request_id: uuid.UUID
    created: bool
    advisor_id: uuid.UUID | None
    escalate_at: datetime
    #: The Conversation's handling mode after the request landed.
    mode: str


@dataclass(frozen=True)
class HandoffView:
    """One row of the operator's pending-handoff surface."""

    request: HumanHandoffRequest
    contact_name: str | None
    channel_identity: str | None
    advisor_name: str | None
    waited_seconds: int

    @property
    def escalated(self) -> bool:
        return self.request.admin_alert_at is not None


class HumanHandoff:
    """The human-handoff module.

    Hides: the open-request invariant, pausing Maia, the immediate alert, the
    escalation deadline and its exactly-once stamp, acknowledgement, and the
    audit trail.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._handling = ConversationHandling(session)
        self._alerts = InternalAlerts(session)

    async def request(
        self, actor: Actor, command: RequestHumanHandling
    ) -> HandoffRecorded:
        """Record an unmet request for a person. Never commits.

        Runs in the transaction that persists the message asking for it, so a
        request that outlived the message — or a message with no request — is
        impossible.
        """
        conversation = command.conversation
        actor.require_same_organization(conversation.organization_id)
        moment = utc_now()

        existing = await self.open_for_conversation(conversation.id, lock=True)
        if existing is not None:
            snapshot = await self._handling.snapshot(conversation.id)
            logger.info(
                "Conversation %s already has an unmet handoff request",
                conversation.id,
            )
            return HandoffRecorded(
                request_id=existing.id,
                created=False,
                advisor_id=existing.advisor_id,
                escalate_at=existing.escalate_at,
                mode=snapshot.mode.value,
            )

        opportunity = await self._opportunity_for(conversation)
        advisor_id = opportunity.responsible_advisor_id if opportunity else None
        contact_id = opportunity.contact_id if opportunity else None
        # An absent or deactivated Advisor cannot answer, so alerting only them
        # would be the silent failure this module exists to remove. The
        # Administrator takes it instead — and the Opportunity is still not
        # reassigned.
        advisor_id = await self._reachable(advisor_id, moment)

        row: HumanHandoffRequest | None = None
        try:
            # The row is constructed *inside* the savepoint: an object added
            # before it survives the rollback still pending and is inserted
            # again by the next flush, which reproduces the very violation just
            # handled.
            async with self._session.begin_nested():
                row = HumanHandoffRequest(
                    organization_id=conversation.organization_id,
                    conversation_id=conversation.id,
                    contact_id=contact_id,
                    opportunity_id=opportunity.id if opportunity else None,
                    advisor_id=advisor_id,
                    source=command.source.value,
                    status=HandoffStatus.PENDING.value,
                    requested_at=moment,
                    escalate_at=moment + ESCALATION_DELAY,
                    trigger_inbox_id=command.trigger_inbox_id,
                )
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            again = await self.open_for_conversation(conversation.id, lock=True)
            if again is None:  # pragma: no cover - the index is the only writer
                raise
            snapshot = await self._handling.snapshot(conversation.id)
            return HandoffRecorded(
                request_id=again.id,
                created=False,
                advisor_id=again.advisor_id,
                escalate_at=again.escalate_at,
                mode=snapshot.mode.value,
            )
        assert row is not None

        snapshot = await self._handling.grant_to_advisor(
            actor,
            conversation,
            advisor_id=advisor_id,
            reason=(
                "ContactRequestedHuman"
                if command.source is HandoffSource.CONTACT_REQUEST
                else (
                    "PostAppointmentQuestion"
                    if command.source is HandoffSource.POST_HANDOFF_ROUTING
                    else "HumanTookOver"
                )
            )
            if advisor_id is not None
            else "NoResponsibleAdvisor",
        )
        await self._alert_immediately(actor, row, command)
        await self._acknowledge_to_contact(row, command)
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="RequestHumanHandling",
            subject_type="Conversation",
            subject_id=str(conversation.id),
            details={
                "request_id": str(row.id),
                "source": command.source.value,
                "advisor_id": str(advisor_id) if advisor_id else None,
                "escalate_at": row.escalate_at.isoformat(),
                # Stated in the trail because it is the promise: nothing was
                # reassigned by asking for a human.
                "reassigned_opportunity": False,
            },
            commit=False,
        )
        logger.info(
            "Recorded a human-handoff request for conversation %s (advisor=%s)",
            conversation.id,
            advisor_id,
        )
        return HandoffRecorded(
            request_id=row.id,
            created=True,
            advisor_id=advisor_id,
            escalate_at=row.escalate_at,
            mode=snapshot.mode.value,
        )

    async def acknowledge(
        self, actor: Actor, command: AcknowledgeHandoff
    ) -> HandoffRecorded:
        """A human confirms they picked it up. Never commits.

        Distinct from :meth:`ConversationHandling.take` on purpose, even though
        taking also acknowledges: an Administrator can acknowledge a request
        they are routing by phone without claiming the WhatsApp conversation.
        """
        if actor.member_id is None:
            raise NotAuthorized(
                "Sólo una persona de la organización puede tomar una solicitud."
            )
        row: HumanHandoffRequest | None = await self._session.scalar(
            select(HumanHandoffRequest)
            .where(HumanHandoffRequest.id == command.request_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa solicitud de atención.")
        actor.require_same_organization(row.organization_id)
        if not actor.is_administrator and row.advisor_id not in (
            None,
            actor.member_id,
        ):
            raise NotFound("No encontramos esa solicitud de atención.")
        snapshot = await self._handling.snapshot(row.conversation_id)
        if row.status != HandoffStatus.PENDING.value:
            return HandoffRecorded(
                request_id=row.id,
                created=False,
                advisor_id=row.advisor_id,
                escalate_at=row.escalate_at,
                mode=snapshot.mode.value,
            )
        row.status = HandoffStatus.ACKNOWLEDGED.value
        row.resolved_at = utc_now()
        row.resolved_by = actor.member_id
        await self._session.flush()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="AcknowledgeHumanHandling",
            subject_type="Conversation",
            subject_id=str(row.conversation_id),
            details={"request_id": str(row.id)},
            commit=False,
        )
        return HandoffRecorded(
            request_id=row.id,
            created=False,
            advisor_id=row.advisor_id,
            escalate_at=row.escalate_at,
            mode=snapshot.mode.value,
        )

    async def mark_taken(self, actor: Actor, conversation_id: uuid.UUID) -> bool:
        """Resolve the open request because a human took or released handling.

        Called by :class:`ConversationHandling`; taking the Conversation *is*
        acknowledgement, and requiring the Advisor to also press a second button
        would leave the Administrator escalating a request somebody is already
        answering.
        """
        row = await self.open_for_conversation(conversation_id, lock=True)
        if row is None:
            return False
        row.status = HandoffStatus.ACKNOWLEDGED.value
        row.resolved_at = utc_now()
        row.resolved_by = actor.member_id
        await self._session.flush()
        return True

    async def cancel(
        self, actor: Actor, conversation_id: uuid.UUID, *, reason: str
    ) -> bool:
        """Close an open request without a human having answered. Never commits.

        Administrator only, and audited with its reason: this is the one path
        that makes an unmet request disappear, so it must be attributable.
        """
        actor.require_administrator()
        row = await self.open_for_conversation(conversation_id, lock=True)
        if row is None:
            return False
        row.status = HandoffStatus.CANCELLED.value
        row.resolved_at = utc_now()
        row.resolved_by = actor.member_id
        await self._session.flush()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="CancelHumanHandling",
            subject_type="Conversation",
            subject_id=str(conversation_id),
            details={"request_id": str(row.id), "reason": reason},
            commit=False,
        )
        return True

    # -- The deadline ------------------------------------------------------

    async def escalate_due(
        self,
        now: datetime | None = None,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> int:
        """Alert the Administrator about every request nobody has taken. Commits.

        Exactly-once by construction: the alert row and the ``admin_alert_at``
        stamp are written in one transaction, and the query only selects
        requests whose stamp is still NULL. A restart mid-window changes
        nothing, because the deadline is stored rather than held in a timer.
        """
        moment = now or utc_now()
        query = (
            select(HumanHandoffRequest)
            .where(HumanHandoffRequest.status == HandoffStatus.PENDING.value)
            .where(HumanHandoffRequest.escalate_at <= moment)
            .where(HumanHandoffRequest.admin_alert_at.is_(None))
            .order_by(HumanHandoffRequest.requested_at)
            .with_for_update(skip_locked=True)
        )
        if organization_id is not None:
            query = query.where(
                HumanHandoffRequest.organization_id == organization_id
            )
        rows = list(
            await self._session.scalars(
                query
            )
        )
        escalated = 0
        for row in rows:
            actor = Actor.product(row.organization_id, "HumanHandoff")
            waited = int((moment - row.requested_at).total_seconds() // 60)
            advisor = (
                await self._session.get(OrganizationMember, row.advisor_id)
                if row.advisor_id
                else None
            )
            who = advisor.display_name if advisor else "nadie asignado"
            await self._alerts.raise_alert(
                actor,
                kind=InternalAlertKind.HUMAN_HANDOFF_ESCALATED,
                subject_type="Conversation",
                subject_id=str(row.conversation_id),
                title="Solicitud de atención humana sin tomar",
                body="\n".join(
                    [
                        f"Un cliente pidió hablar con una persona hace {waited} minutos "
                        "y nadie ha tomado la conversación.",
                        f"Asesor avisado: {who}.",
                        "La oportunidad NO se reasignó. Decide quién la atiende.",
                        f"Conversación: /crm/bandeja/{row.conversation_id}",
                    ]
                ),
                dedupe_key=f"handoff-escalation:{row.id}",
                recipient_member_id=None,
            )
            row.admin_alert_at = moment
            await record_audit(
                self._session,
                organization_id=actor.organization_id,
                actor_type=actor.actor_type,
                actor_id=actor.label,
                action="EscalateHumanHandling",
                subject_type="Conversation",
                subject_id=str(row.conversation_id),
                details={
                    "request_id": str(row.id),
                    "waited_minutes": waited,
                    "reassigned_opportunity": False,
                },
                commit=False,
            )
            escalated += 1
        if rows:
            await self._session.commit()
        if escalated:
            logger.warning(
                "Escalated %d unhandled human-handoff request(s) to the administrator",
                escalated,
            )
        return escalated

    # -- Reads -------------------------------------------------------------

    async def pending(
        self, actor: Actor, *, now: datetime | None = None
    ) -> list[HandoffView]:
        """Unmet requests this Actor should act on, longest wait first."""
        moment = now or utc_now()
        query = (
            select(HumanHandoffRequest)
            .where(HumanHandoffRequest.organization_id == actor.organization_id)
            .where(HumanHandoffRequest.status == HandoffStatus.PENDING.value)
            .order_by(HumanHandoffRequest.requested_at)
        )
        if not actor.sees_whole_operation:
            query = query.where(HumanHandoffRequest.advisor_id == actor.member_id)
        rows = list(await self._session.scalars(query))
        if not rows:
            return []

        # Four batched reads rather than four per row: this is the alert list an
        # Administrator refreshes, and it grows with the operation's backlog.
        contact_ids = {row.contact_id for row in rows if row.contact_id}
        advisor_ids = {row.advisor_id for row in rows if row.advisor_id}
        contacts = {
            row.id: row
            for row in await self._session.scalars(
                select(Contact).where(Contact.id.in_(contact_ids))
            )
        } if contact_ids else {}
        advisors = {
            row.id: row
            for row in await self._session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.id.in_(advisor_ids)
                )
            )
        } if advisor_ids else {}
        conversations = {
            row.id: row
            for row in await self._session.scalars(
                select(Conversation).where(
                    Conversation.id.in_({row.conversation_id for row in rows})
                )
            )
        }
        lead_ids = {row.lead_id for row in conversations.values()}
        leads = {
            row.id: row
            for row in await self._session.scalars(
                select(Lead).where(Lead.id.in_(lead_ids))
            )
        } if lead_ids else {}

        views: list[HandoffView] = []
        for row in rows:
            contact = contacts.get(row.contact_id) if row.contact_id else None
            advisor = advisors.get(row.advisor_id) if row.advisor_id else None
            conversation = conversations.get(row.conversation_id)
            lead = leads.get(conversation.lead_id) if conversation else None
            views.append(
                HandoffView(
                    request=row,
                    contact_name=contact.display_name if contact else None,
                    channel_identity=f"+{lead.wa_id}" if lead else None,
                    advisor_name=advisor.display_name if advisor else None,
                    waited_seconds=max(
                        0, int((moment - row.requested_at).total_seconds())
                    ),
                )
            )
        return views

    async def open_for_conversation(
        self, conversation_id: uuid.UUID, *, lock: bool = False
    ) -> HumanHandoffRequest | None:
        """This Conversation's unmet request, if it has one.

        "Open" means ``Pending``: a request an Advisor has acknowledged is no
        longer waiting for anybody.
        """
        query = (
            select(HumanHandoffRequest)
            .where(HumanHandoffRequest.conversation_id == conversation_id)
            .where(HumanHandoffRequest.status == HandoffStatus.PENDING.value)
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        found: HumanHandoffRequest | None = await self._session.scalar(query)
        return found

    # -- Internals ---------------------------------------------------------

    async def _opportunity_for(
        self, conversation: Conversation
    ) -> Opportunity | None:
        """The Opportunity behind this Conversation, without a visibility check.

        Product's own path resolves it, and Product sees the whole operation —
        including work nobody owns, which is precisely the case that has to
        reach an Administrator.
        """
        from realestate.domain.commercial.identity import CommercialIdentity
        from realestate.domain.commercial.opportunities import OpportunityManagement

        contact_id = await CommercialIdentity(self._session).contact_for_lead(
            conversation.lead_id
        )
        if contact_id is None:
            return None
        return await OpportunityManagement(self._session).open_demand_for_contact(
            contact_id
        )

    async def _reachable(
        self, advisor_id: uuid.UUID | None, moment: datetime
    ) -> uuid.UUID | None:
        """The Advisor if they could actually answer right now, else ``None``."""
        if advisor_id is None:
            return None
        from realestate.domain.commercial.team import current_absence

        advisor = await self._session.get(OrganizationMember, advisor_id)
        if advisor is None or not advisor.active:
            return None
        if await current_absence(self._session, advisor_id, moment) is not None:
            logger.info(
                "Advisor %s is absent; the handoff goes to the administrator",
                advisor_id,
            )
            return None
        return advisor_id

    async def _acknowledge_to_contact(
        self, row: HumanHandoffRequest, command: RequestHumanHandling
    ) -> None:
        """Say the approved sentence to the Contact. Never commits.

        Product owns this wording (ADR-0029), and Product sends it — not the
        Model — for two reasons. It must not become a service-level commitment
        because a run phrased it confidently, and the request has just paused
        Maia, so the draft that turn produces will be withheld. Without this the
        Contact would hear nothing at all at the exact moment they asked for
        help.

        A human deciding to take over needs no announcement, so only a request
        that came from the Contact's side produces one.
        """
        if command.source is HandoffSource.HUMAN_INITIATED:
            return
        from realestate.db.models import OutboundInitiation
        from realestate.domain.outbound import (
            OutboundIntent,
            OutboundMessaging,
            Purpose,
        )

        triggers = await self._recent_inbound(row.conversation_id, command)
        if not triggers:
            # No message to answer means this was not the Contact asking, so
            # there is nothing to acknowledge. The gate would refuse it anyway.
            return
        conversation = await self._session.get(Conversation, row.conversation_id)
        if conversation is None:  # pragma: no cover - the FK forbids it
            return
        await OutboundMessaging(self._session).request(
            OutboundIntent(
                conversation=conversation,
                body=HUMAN_HANDOFF_ACKNOWLEDGEMENT,
                purpose=Purpose.AGENT_REPLY,
                initiation=OutboundInitiation.REACTIVE,
                trigger_inbox_ids=triggers,
                idempotency_key=f"handoff-acknowledgement:{row.id}",
            )
        )

    async def _recent_inbound(
        self, conversation_id: uuid.UUID, command: RequestHumanHandling
    ) -> tuple[uuid.UUID, ...]:
        """The messages this acknowledgement answers.

        The triggering message when the caller knows it, otherwise the most
        recent one. Computed from persisted rows either way: the gate validates
        the evidence and a declaration cannot manufacture a service window.
        """
        if command.trigger_inbox_id is not None:
            return (command.trigger_inbox_id,)
        from realestate.db.models import InboxMessage

        latest = await self._session.scalar(
            select(InboxMessage.id)
            .where(InboxMessage.conversation_id == conversation_id)
            .order_by(InboxMessage.sent_at.desc(), InboxMessage.id.desc())
            .limit(1)
        )
        return (latest,) if latest is not None else ()

    async def _alert_immediately(
        self,
        actor: Actor,
        row: HumanHandoffRequest,
        command: RequestHumanHandling,
    ) -> None:
        """One immediate notice, in this transaction, stamped as sent-for.

        ``advisor_alert_at`` records that the notice was *raised*, not that
        Telegram accepted it: delivery is the alert channel's own durable
        problem, and conflating the two would let a Telegram outage look like a
        request nobody was told about.
        """
        contact = (
            await self._session.get(Contact, row.contact_id)
            if row.contact_id
            else None
        )
        name = (contact.display_name if contact else None) or "Un cliente"
        lines = [
            f"{name} pidió hablar con una persona.",
            SOURCE_LABELS[command.source.value] + ".",
        ]
        if command.detail:
            lines.append(command.detail)
        lines.extend(
            [
                "Maia dejó de responder esta conversación.",
                f"Conversación: /crm/bandeja/{row.conversation_id}",
            ]
        )
        await self._alerts.raise_alert(
            actor,
            kind=InternalAlertKind.HUMAN_HANDOFF_REQUESTED,
            subject_type="Conversation",
            subject_id=str(row.conversation_id),
            title=f"{name} pidió atención humana",
            body="\n".join(lines),
            dedupe_key=f"handoff-request:{row.id}",
            recipient_member_id=row.advisor_id,
        )
        row.advisor_alert_at = utc_now()
        await self._session.flush()

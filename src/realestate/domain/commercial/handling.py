"""Who may answer this Contact: Maia, or exactly one human (ADR-0029).

Handling authority is the answer to a question the product could previously only
guess at. Before this module, if an Advisor wanted to write to a Contact they
had to use their own phone, and nothing stopped Maia from replying to the same
message at the same time. Both failures are the same failure: authority was
implicit.

``ConversationHandling`` makes it explicit and singular.

* ``take`` grants authority to one named human and pauses Maia.
* ``release`` returns it, and only an Advisor or an Administrator may do that —
  a timeout never transfers conversational authority silently.
* ``reply`` is the human's message going out on the *Organization's* channel,
  through the same Outbound Eligibility Gate as everything else.

Two races are designed for rather than hoped about.

**Maia against a human.** The Lead worker reads the mode when it claims a
Conversation *and* again at settlement, both under the handling row's lock. A
human taking over mid-turn causes the draft to be withheld: the Contact gets
one answer, from the authority that holds the Conversation, and the withholding
is audited so it is not mistaken for a lost message.

**Human against human.** ``take`` locks the row and refuses a second Advisor
with the holder's name. An Administrator may reassign handling explicitly,
because somebody has to be able to unstick a Conversation held by a person who
went home.

An absent row means Maia. That is deliberate: every Conversation that existed
before this table is answerable by Maia, which is exactly how the product
already behaved, and no backfill can be wrong.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    MAIA_MAY_REPLY,
    Conversation,
    ConversationHandlingState,
    HandlingMode,
    InboxGroup,
    InboxMessage,
    OrganizationMember,
    OutboundInitiation,
    OutboxMessage,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    NotAuthorized,
    NotFound,
)
from realestate.domain.commercial.idempotency import CommercialCommands
from realestate.domain.outbound import (
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
    Queued,
)

logger = logging.getLogger(__name__)


MODE_LABELS: dict[str, str] = {
    HandlingMode.MAIA.value: "Maia está atendiendo",
    HandlingMode.HUMAN.value: "Atiende una persona",
    HandlingMode.AWAITING_CONTACT.value: "En espera del cliente",
    HandlingMode.ADMIN_REVIEW.value: "Requiere revisión del administrador",
}

#: Short operator-facing reasons. Stored on the row, so they are a closed set
#: rather than free text an operator has to interpret.
REASON_LABELS: dict[str, str] = {
    "ContactRequestedHuman": "El cliente pidió hablar con una persona",
    "PostAppointmentQuestion": "Pregunta comercial después de la cita",
    "HumanTookOver": "Una persona tomó la conversación",
    "ReturnedToMaia": "Devuelta a Maia",
    "AwaitingContactReply": "Esperando la respuesta del cliente",
    "ContactWroteAgain": "El cliente volvió a escribir",
    "NoResponsibleAdvisor": "No hay asesor responsable asignado",
    "AdminReassigned": "El administrador cambió quién atiende",
}


class AlreadyHandled(CommercialError):
    """Somebody else already holds this Conversation."""

    def __init__(self, holder_name: str) -> None:
        self.holder_name = holder_name
        super().__init__(
            f"{holder_name} ya está atendiendo esta conversación. Pide al "
            "administrador que la reasigne si necesitas tomarla."
        )


class NotHandling(CommercialError):
    message = (
        "Para responder por WhatsApp primero tienes que tomar la conversación."
    )


# ---------------------------------------------------------------- Commands ---


@dataclass(frozen=True)
class TakeHandling:
    conversation_id: uuid.UUID
    command_key: str
    reason: str = "HumanTookOver"


@dataclass(frozen=True)
class ReleaseHandling:
    conversation_id: uuid.UUID
    command_key: str
    #: Where authority goes. Maia by default; ``AWAITING_CONTACT`` is the
    #: operator saying nobody needs to act until the Contact answers.
    to_mode: HandlingMode = HandlingMode.MAIA
    reason: str = "ReturnedToMaia"


@dataclass(frozen=True)
class HumanReply:
    conversation_id: uuid.UUID
    body: str
    command_key: str


# ------------------------------------------------------------------- Views ---


@dataclass(frozen=True)
class HandlingSnapshot:
    """The handling state of one Conversation, as any surface should read it."""

    conversation_id: uuid.UUID
    mode: HandlingMode
    holder_member_id: uuid.UUID | None
    holder_name: str | None
    since: datetime | None
    reason: str | None
    version: int

    @property
    def maia_may_reply(self) -> bool:
        return self.mode.value in MAIA_MAY_REPLY

    @property
    def mode_label(self) -> str:
        return MODE_LABELS[self.mode.value]

    @property
    def reason_label(self) -> str | None:
        if self.reason is None:
            return None
        return REASON_LABELS.get(self.reason, self.reason)

    def held_by(self, actor: Actor) -> bool:
        return (
            self.mode is HandlingMode.HUMAN
            and actor.member_id is not None
            and self.holder_member_id == actor.member_id
        )

    def may_reply(self, actor: Actor) -> bool:
        """Whether this Actor may write to the Contact right now.

        The holder, or an Administrator while a human holds it — somebody has to
        be able to answer a Contact held by a person who went home. One
        definition, because the reply box, the release controls and
        :meth:`ConversationHandling.reply` must not be able to disagree about
        who is allowed to speak for the Organization.
        """
        return self.held_by(actor) or (
            actor.is_administrator and self.mode is HandlingMode.HUMAN
        )



def _authority_of(
    conversation_id: uuid.UUID,
    row: ConversationHandlingState | None,
    *,
    holder_name: str | None = None,
) -> HandlingSnapshot:
    """A snapshot of a row already in hand. An absent row means Maia.

    ``holder_name`` is supplied only by the read path that needs it; the
    authorization checks do not, and should not pay for a second query.
    """
    if row is None:
        return HandlingSnapshot(
            conversation_id=conversation_id,
            mode=HandlingMode.MAIA,
            holder_member_id=None,
            holder_name=None,
            since=None,
            reason=None,
            version=0,
        )
    return HandlingSnapshot(
        conversation_id=conversation_id,
        mode=HandlingMode(row.mode),
        holder_member_id=row.holder_member_id,
        holder_name=holder_name,
        since=row.since,
        reason=row.reason,
        version=row.version,
    )


@dataclass(frozen=True)
class ReplyRecorded:
    """The outcome of a human reply. ``denied_reason`` is operator-facing."""

    queued: bool
    outbox_id: uuid.UUID | None
    denied_reason: str | None = None
    denied_detail: str | None = None


class ConversationHandling:
    """The handling-authority module.

    Hides: lazy row creation, row locking, the optimistic version, the mode
    invariants, resolving a pending handoff when a human arrives, the audit
    trail, and the reactive-trigger evidence a human reply needs to satisfy the
    Stage 1 gate.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._commands = CommercialCommands(session)

    # -- Reads -------------------------------------------------------------

    async def snapshot(self, conversation_id: uuid.UUID) -> HandlingSnapshot:
        """The current authority. An absent row means Maia."""
        row = await self._row(conversation_id)
        holder_name = None
        if row is not None and row.holder_member_id is not None:
            holder = await self._session.get(OrganizationMember, row.holder_member_id)
            holder_name = holder.display_name if holder else None
        return _authority_of(conversation_id, row, holder_name=holder_name)

    async def maia_may_reply(self, conversation_id: uuid.UUID, *, lock: bool = False) -> bool:
        """Whether the Lead worker may release a draft for this Conversation.

        The Lead worker asks this twice — once to claim, once at settlement with
        ``lock=True`` — because a human can arrive in between and the second
        answer is the one that must be authoritative.
        """
        row = await self._row(conversation_id, lock=lock)
        if row is None:
            return True
        return row.mode in MAIA_MAY_REPLY

    async def modes_for(
        self, conversation_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, ConversationHandlingState]:
        """Handling rows for a whole Inbox page, in one query.

        The Inbox lists dozens of Conversations and every row shows who is
        answering; asking per row would be a query per line.
        """
        if not conversation_ids:
            return {}
        rows = await self._session.scalars(
            select(ConversationHandlingState).where(
                ConversationHandlingState.conversation_id.in_(conversation_ids)
            )
        )
        return {row.conversation_id: row for row in rows}

    # -- Commands ----------------------------------------------------------

    async def take(self, actor: Actor, command: TakeHandling) -> HandlingSnapshot:
        """One human assumes authority. Never commits.

        Refuses Product: Maia does not "take" a Conversation, it is the default.
        Refuses a second Advisor by name, so the loser of the race reads a
        sentence instead of discovering a duplicate reply later.
        """
        if actor.member_id is None:
            raise NotAuthorized(
                "Sólo una persona de la organización puede atender una conversación."
            )
        conversation = await self._conversation(actor, command.conversation_id)
        row = await self._locked_or_created(conversation)
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="TakeHandling",
            subject_type="Conversation",
            subject_id=str(conversation.id),
            payload={"member_id": str(actor.member_id)},
        )
        if replay:
            return await self.snapshot(conversation.id)

        if row.mode == HandlingMode.HUMAN.value:
            if row.holder_member_id == actor.member_id:
                # Already theirs — usually because a handoff request named them
                # as the holder the moment it landed. Pressing the button is
                # still the acknowledgement the escalation is waiting for, so
                # this path is a no-op for the *mode* and not for the request.
                from realestate.domain.commercial.handoff import HumanHandoff

                await HumanHandoff(self._session).mark_taken(actor, conversation.id)
                return await self.snapshot(conversation.id)
            holder = await self._session.get(OrganizationMember, row.holder_member_id)
            if not actor.is_administrator:
                raise AlreadyHandled(holder.display_name if holder else "Otra persona")
            # An Administrator may move handling explicitly. Recorded as a
            # reassignment rather than a fresh take, because "who was answering
            # at 14:00" has to stay answerable.
            command = TakeHandling(
                conversation_id=command.conversation_id,
                command_key=command.command_key,
                reason="AdminReassigned",
            )

        previous = row.mode
        row.mode = HandlingMode.HUMAN.value
        row.holder_member_id = actor.member_id
        row.since = utc_now()
        row.reason = command.reason
        row.version += 1
        row.updated_at = row.since
        await self._session.flush()
        await self._audit(
            actor,
            conversation,
            "TakeConversationHandling",
            {"from": previous, "reason": command.reason},
        )

        # A human arriving is the acknowledgement the escalation was waiting
        # for. Imported here rather than at module scope: HumanHandoff sets the
        # handling mode, so the dependency only runs in this direction.
        from realestate.domain.commercial.handoff import HumanHandoff

        await HumanHandoff(self._session).mark_taken(actor, conversation.id)
        logger.info(
            "%s took handling of conversation %s", actor.label, conversation.id
        )
        return await self.snapshot(conversation.id)

    async def release(self, actor: Actor, command: ReleaseHandling) -> HandlingSnapshot:
        """Return authority. Never commits.

        Only the holder or an Administrator. ``to_mode`` is restricted to the
        two states a human can legitimately hand to: Maia, or waiting on the
        Contact. ``ADMIN_REVIEW`` is Product's own verdict, not a release
        target, and ``HUMAN`` is what :meth:`take` is for.
        """
        if command.to_mode not in (HandlingMode.MAIA, HandlingMode.AWAITING_CONTACT):
            raise NotAuthorized("Esa transición de atención no está permitida.")
        conversation = await self._conversation(actor, command.conversation_id)
        row = await self._locked_or_created(conversation)
        if (
            row.mode == HandlingMode.HUMAN.value
            and row.holder_member_id != actor.member_id
            and not actor.is_administrator
        ):
            holder = await self._session.get(OrganizationMember, row.holder_member_id)
            raise AlreadyHandled(holder.display_name if holder else "Otra persona")
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="ReleaseHandling",
            subject_type="Conversation",
            subject_id=str(conversation.id),
            payload={"to_mode": command.to_mode.value},
        )
        if replay:
            return await self.snapshot(conversation.id)

        previous = row.mode
        if previous == command.to_mode.value:
            return await self.snapshot(conversation.id)

        row.mode = command.to_mode.value
        row.holder_member_id = None
        row.since = utc_now()
        row.reason = command.reason
        row.version += 1
        row.updated_at = row.since
        await self._session.flush()
        await self._audit(
            actor,
            conversation,
            "ReleaseConversationHandling",
            {"from": previous, "to": command.to_mode.value},
        )

        from realestate.domain.commercial.handoff import HumanHandoff

        await HumanHandoff(self._session).mark_taken(actor, conversation.id)
        return await self.snapshot(conversation.id)

    async def reply(self, actor: Actor, command: HumanReply) -> ReplyRecorded:
        """A human's WhatsApp message, on the Organization's own channel.

        Never commits, so the message and the eligibility decision that
        authorised it land together.

        The gate is not bypassed because a person typed it. Suppression and
        Meta's 24-hour window are facts about the Contact, not about the author,
        and a reply Meta would reject has to fail here rather than at delivery.
        The reactive evidence is computed from persisted inbound messages, so a
        human cannot manufacture a window either.
        """
        body = command.body.strip()
        if not body:
            raise NotAuthorized("El mensaje no puede ir vacío.")
        conversation = await self._conversation(actor, command.conversation_id)
        authority = await self._row(conversation.id, lock=True)
        if not _authority_of(conversation.id, authority).may_reply(actor):
            raise NotHandling()

        triggers = await self._unanswered_inbound(conversation)
        outcome = await OutboundMessaging(self._session).request(
            OutboundIntent(
                conversation=conversation,
                body=body,
                purpose=Purpose.HUMAN_REPLY,
                initiation=OutboundInitiation.REACTIVE,
                trigger_inbox_ids=triggers,
                idempotency_key=f"human-reply:{command.command_key}",
            )
        )
        if isinstance(outcome, Denied):
            logger.info(
                "Human reply for %s was denied: %s", conversation.id, outcome.reason.value
            )
            return ReplyRecorded(
                queued=False,
                outbox_id=None,
                denied_reason=outcome.reason.value,
                denied_detail=outcome.detail,
            )
        assert isinstance(outcome, Queued)
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="SendHumanReply",
            subject_type="Conversation",
            subject_id=str(conversation.id),
            details={"outbox_id": str(outcome.outbox_id), "triggers": len(triggers)},
            commit=False,
        )
        return ReplyRecorded(queued=True, outbox_id=outcome.outbox_id)

    # -- Product's own transitions ----------------------------------------

    async def grant_to_advisor(
        self,
        actor: Actor,
        conversation: Conversation,
        *,
        advisor_id: uuid.UUID | None,
        reason: str,
    ) -> HandlingSnapshot:
        """Product pausing Maia because a human is needed. Never commits.

        Called by :mod:`~realestate.domain.commercial.handoff`, not by a router.
        Naming the Advisor as holder is what stops Maia from continuing while
        the request is unmet — and it is *not* a reassignment: the holder is the
        Advisor who is already responsible. With nobody responsible there is no
        holder to name, so the Conversation goes to ``ADMIN_REVIEW``, which is
        the state an Administrator has to clear.
        """
        row = await self._locked_or_created(conversation)
        if row.mode == HandlingMode.HUMAN.value:
            # Already with a human. A second request does not move it.
            return await self.snapshot(conversation.id)
        previous = row.mode
        if advisor_id is None:
            row.mode = HandlingMode.ADMIN_REVIEW.value
            row.holder_member_id = None
        else:
            row.mode = HandlingMode.HUMAN.value
            row.holder_member_id = advisor_id
        row.since = utc_now()
        row.reason = reason
        row.version += 1
        row.updated_at = row.since
        await self._session.flush()
        await self._audit(
            actor,
            conversation,
            "PauseMaiaForHuman",
            {"from": previous, "to": row.mode, "reason": reason},
        )
        return await self.snapshot(conversation.id)

    async def note_inbound(
        self, actor: Actor, conversation: Conversation
    ) -> HandlingSnapshot | None:
        """The Contact wrote. Never commits.

        ``AWAITING_CONTACT`` means "nobody needs to act until they answer", so
        their answer ends it and Maia resumes. ``HUMAN`` and ``ADMIN_REVIEW``
        are deliberately untouched: a Contact writing again is not permission
        for Maia to speak over the human who is handling them, and it is the
        exact moment an impatient Contact would otherwise get two replies.
        """
        row = await self._row(conversation.id, lock=True)
        if row is None or row.mode != HandlingMode.AWAITING_CONTACT.value:
            return None
        row.mode = HandlingMode.MAIA.value
        row.holder_member_id = None
        row.since = utc_now()
        row.reason = "ContactWroteAgain"
        row.version += 1
        row.updated_at = row.since
        await self._session.flush()
        await self._audit(
            actor,
            conversation,
            "ResumeMaiaAfterContactReply",
            {"to": HandlingMode.MAIA.value},
        )
        return await self.snapshot(conversation.id)

    # -- Internals ---------------------------------------------------------

    async def _row(
        self, conversation_id: uuid.UUID, *, lock: bool = False
    ) -> ConversationHandlingState | None:
        query = select(ConversationHandlingState).where(
            ConversationHandlingState.conversation_id == conversation_id
        )
        if lock:
            query = query.with_for_update()
        found: ConversationHandlingState | None = await self._session.scalar(query)
        return found

    async def _locked_or_created(
        self, conversation: Conversation
    ) -> ConversationHandlingState:
        """This Conversation's handling row, locked, creating the default first.

        Creation goes through the unique index rather than a check-then-insert:
        two humans pressing *Atender* on a Conversation that has no row yet
        would otherwise both insert.
        """
        row = await self._row(conversation.id, lock=True)
        if row is not None:
            return row
        fresh = ConversationHandlingState(
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            mode=HandlingMode.MAIA.value,
            since=utc_now(),
        )
        self._session.add(fresh)
        try:
            async with self._session.begin_nested():
                await self._session.flush()
        except IntegrityError:
            existing = await self._row(conversation.id, lock=True)
            if existing is None:  # pragma: no cover - the index is the only writer
                raise
            return existing
        return fresh

    async def _conversation(
        self, actor: Actor, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await self._session.get(Conversation, conversation_id)
        if conversation is None:
            raise NotFound("No encontramos esa conversación.")
        actor.require_same_organization(conversation.organization_id)
        if not actor.sees_whole_operation:
            from realestate.domain.commercial.identity import CommercialIdentity
            from realestate.domain.commercial.opportunities import OpportunityManagement

            contact_id = await CommercialIdentity(self._session).contact_for_lead(
                conversation.lead_id
            )
            opportunity = (
                await OpportunityManagement(self._session).open_demand_for_contact(
                    contact_id
                )
                if contact_id is not None
                else None
            )
            if (
                opportunity is None
                or opportunity.organization_id != actor.organization_id
                or opportunity.responsible_advisor_id != actor.member_id
            ):
                raise NotFound("No encontramos esa conversación.")
        return conversation

    async def _unanswered_inbound(
        self, conversation: Conversation
    ) -> tuple[uuid.UUID, ...]:
        """The Contact's messages since Product last wrote.

        This is the reactive evidence the gate validates. Computed from
        persisted rows here for the same reason the gate recomputes the window:
        a human should not be able to declare a message "an answer" to
        something nobody sent.
        """
        last_outbound = await self._session.scalar(
            select(OutboxMessage.created_at)
            .where(OutboxMessage.conversation_id == conversation.id)
            .order_by(OutboxMessage.created_at.desc())
            .limit(1)
        )
        query = (
            select(InboxMessage.id)
            .join(InboxGroup, InboxGroup.id == InboxMessage.group_id, isouter=True)
            .where(InboxMessage.conversation_id == conversation.id)
            .order_by(InboxMessage.sent_at.desc(), InboxMessage.id.desc())
            .limit(20)
        )
        if last_outbound is not None:
            query = query.where(InboxMessage.persisted_at > last_outbound)
        rows = list(await self._session.scalars(query))
        if rows:
            return tuple(reversed(rows))
        # Nothing new since Product wrote. The most recent inbound message is
        # still the thing a human is answering, so it is offered as the
        # trigger and the gate decides whether the window is still open.
        latest = await self._session.scalar(
            select(InboxMessage.id)
            .where(InboxMessage.conversation_id == conversation.id)
            .order_by(InboxMessage.sent_at.desc(), InboxMessage.id.desc())
            .limit(1)
        )
        return (latest,) if latest is not None else ()

    async def _audit(
        self,
        actor: Actor,
        conversation: Conversation,
        action: str,
        details: dict[str, object],
    ) -> None:
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action=action,
            subject_type="Conversation",
            subject_id=str(conversation.id),
            details=details,
            commit=False,
        )

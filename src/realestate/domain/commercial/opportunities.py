"""Opportunities: one entry point, one command union, one recorded history.

``OpportunityManagement.record(command)`` is the only way an Opportunity comes
into existence or changes stage. Everything that makes that safe lives behind
it: the legal-transition table, the qualification rule, the evidence a terminal
outcome requires, who may declare a win, row locking, idempotency by command
key, the stage-transition history, the audit event, and the assignment the
promise depends on.

Three separations are load-bearing.

**Stage is only stage.** Assignment, appointments, consent and Do Not Contact are
their own state. A suppressed Contact is not Lost, a cancelled appointment moves
nothing here (ADR-0037), and an Opportunity waiting for an Advisor is not in a
special stage — it is in the Assignment Queue.

**Evidence, not inference.** Won needs accepted operational evidence recorded by
an Administrator (ADR-0032): a visit, an offer or a reservation is not a sale.
Lost needs a reason, ``Unknown`` included, because an unexplained loss is a
measurement gap. Dormant needs the condition under which it may be reconsidered,
which is the difference between paused and finished.

**Qualification is earned.** Entering Qualified requires the accepted minimum
criteria to be *confirmed* — a Pending interpretation does not count (ADR-0031)
— and a Verified contact path to exist. Both are checked here, not trusted from
a caller.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ACTIVE_STAGES,
    QUALIFIED_OR_BEYOND,
    ContactChannelIdentity,
    ChannelIdentityTrust,
    NextAction,
    NextActionKind,
    Opportunity,
    OpportunityException,
    OpportunityExceptionReason,
    OpportunityKind,
    OpportunityOrigin,
    OpportunityOriginSource,
    OpportunityStage,
    OpportunityStageTransition,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    InvalidTransition,
    MissingEvidence,
    QualificationIncomplete,
)
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.needs import PropertyNeeds
from realestate.domain.commercial.next_actions import NextActions, ScheduleNextAction
from realestate.domain.commercial.records import visible_opportunity

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


# Which stage may follow which. Written out rather than derived from an ordering
# because the real pipeline is not a line: an Advisor legitimately goes back
# from Visiting to Searching, and Dormant legitimately re-enters the middle.
#
# What is *absent* matters as much: nothing reaches Searching without having
# been Qualified, and nothing leaves Won or Lost. A relationship that resumes
# after a loss is a new Opportunity with its own origin, not a resurrection that
# would silently rewrite the operation's conversion history.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    OpportunityStage.NEW.value: frozenset(
        {
            OpportunityStage.IN_CONVERSATION.value,
            OpportunityStage.QUALIFIED.value,
            OpportunityStage.LOST.value,
            OpportunityStage.DORMANT.value,
        }
    ),
    OpportunityStage.IN_CONVERSATION.value: frozenset(
        {
            OpportunityStage.QUALIFIED.value,
            OpportunityStage.LOST.value,
            OpportunityStage.DORMANT.value,
        }
    ),
    OpportunityStage.QUALIFIED.value: frozenset(
        {
            OpportunityStage.SEARCHING.value,
            OpportunityStage.VISITING.value,
            OpportunityStage.NEGOTIATING.value,
            OpportunityStage.WON.value,
            OpportunityStage.LOST.value,
            OpportunityStage.DORMANT.value,
        }
    ),
    OpportunityStage.SEARCHING.value: frozenset(
        {
            OpportunityStage.VISITING.value,
            OpportunityStage.NEGOTIATING.value,
            OpportunityStage.WON.value,
            OpportunityStage.LOST.value,
            OpportunityStage.DORMANT.value,
        }
    ),
    OpportunityStage.VISITING.value: frozenset(
        {
            OpportunityStage.SEARCHING.value,
            OpportunityStage.NEGOTIATING.value,
            OpportunityStage.WON.value,
            OpportunityStage.LOST.value,
            OpportunityStage.DORMANT.value,
        }
    ),
    OpportunityStage.NEGOTIATING.value: frozenset(
        {
            OpportunityStage.VISITING.value,
            OpportunityStage.WON.value,
            OpportunityStage.LOST.value,
            OpportunityStage.DORMANT.value,
        }
    ),
    # Paused, not finished. Reactivation re-enters where work can resume, and
    # may also conclude as Lost once the operation knows it ended.
    OpportunityStage.DORMANT.value: frozenset(
        {
            OpportunityStage.IN_CONVERSATION.value,
            OpportunityStage.QUALIFIED.value,
            OpportunityStage.SEARCHING.value,
            OpportunityStage.VISITING.value,
            OpportunityStage.LOST.value,
        }
    ),
    OpportunityStage.WON.value: frozenset(),
    OpportunityStage.LOST.value: frozenset(),
}

#: The stages an operator may move an Opportunity to with a plain advance, in
#: pipeline order. Derived from the transition table rather than hand-listed, so
#: a new stage cannot be added to the domain and silently miss the operator's
#: dropdown — and from the same knowledge ``_target`` uses to refuse the three
#: outcomes, so the constant and the refusal cannot disagree.
TERMINAL_STAGES: frozenset[str] = frozenset(
    {
        OpportunityStage.WON.value,
        OpportunityStage.LOST.value,
        OpportunityStage.DORMANT.value,
    }
)

ADVANCEABLE_STAGES: tuple[str, ...] = tuple(
    stage
    for stage in (member.value for member in OpportunityStage)
    if stage not in TERMINAL_STAGES
    and any(stage in targets for targets in ALLOWED_TRANSITIONS.values())
)


STAGE_LABELS: dict[str, str] = {
    OpportunityStage.NEW.value: "Nueva",
    OpportunityStage.IN_CONVERSATION.value: "En conversación",
    OpportunityStage.QUALIFIED.value: "Calificada",
    OpportunityStage.SEARCHING.value: "En búsqueda",
    OpportunityStage.VISITING.value: "En visitas",
    OpportunityStage.NEGOTIATING.value: "En negociación",
    OpportunityStage.WON.value: "Ganada",
    OpportunityStage.LOST.value: "Perdida",
    OpportunityStage.DORMANT.value: "En pausa",
}

KIND_LABELS: dict[str, str] = {
    OpportunityKind.DEMAND.value: "Demanda",
    OpportunityKind.LISTING_ACQUISITION.value: "Captación",
}


class WonEvidence(str, enum.Enum):
    """The only facts that may conclude an Opportunity as Won (ADR-0032).

    Validated here rather than by a CHECK constraint because the Transaction
    record that will extend this vocabulary belongs to a later stage, and a
    constraint would make each addition a migration. What is *not* negotiable
    is the list itself: interest, an accepted offer, a completed visit and a
    reservation are all deliberately absent.
    """

    COMPLETED_SALE = "CompletedSale"
    SIGNED_RENTAL_AGREEMENT = "SignedRentalAgreement"
    ACCEPTED_BINDING_PRESALE = "AcceptedBindingPresale"


WON_EVIDENCE_LABELS: dict[str, str] = {
    WonEvidence.COMPLETED_SALE.value: "Venta concluida legalmente",
    WonEvidence.SIGNED_RENTAL_AGREEMENT.value: "Contrato de renta firmado",
    WonEvidence.ACCEPTED_BINDING_PRESALE.value: "Preventa con contrato aceptado",
}


class LostReason(str, enum.Enum):
    """Why an Opportunity ended without a transaction.

    ``Unknown`` is a real option on purpose. Forcing a specific reason produces
    invented ones, and a reason nobody knows is more useful reported honestly
    than disguised as ``NotInterested``.
    """

    NOT_INTERESTED = "NotInterested"
    BOUGHT_ELSEWHERE = "BoughtElsewhere"
    NO_BUDGET = "NoBudget"
    OUT_OF_SERVICE_AREA = "OutOfServiceArea"
    NO_INVENTORY_MATCH = "NoInventoryMatch"
    UNREACHABLE = "Unreachable"
    DUPLICATE = "Duplicate"
    UNKNOWN = "Unknown"


LOST_REASON_LABELS: dict[str, str] = {
    LostReason.NOT_INTERESTED.value: "Ya no le interesa",
    LostReason.BOUGHT_ELSEWHERE.value: "Compró o rentó en otro lugar",
    LostReason.NO_BUDGET.value: "No cuenta con el presupuesto",
    LostReason.OUT_OF_SERVICE_AREA.value: "Fuera de la zona de servicio",
    LostReason.NO_INVENTORY_MATCH.value: "No tenemos inventario que le sirva",
    LostReason.UNREACHABLE.value: "No fue posible contactarle",
    LostReason.DUPLICATE.value: "Duplicada de otra oportunidad",
    LostReason.UNKNOWN.value: "Sin determinar",
}


class DormantReason(str, enum.Enum):
    """Why the pursuit is paused rather than finished."""

    NO_RESPONSE = "NoResponse"
    POSTPONED_DECISION = "PostponedDecision"
    AWAITING_NEW_INVENTORY = "AwaitingNewInventory"
    AWAITING_FINANCING = "AwaitingFinancing"


DORMANT_REASON_LABELS: dict[str, str] = {
    DormantReason.NO_RESPONSE.value: "Sin respuesta del contacto",
    DormantReason.POSTPONED_DECISION.value: "Posponió su decisión",
    DormantReason.AWAITING_NEW_INVENTORY.value: "Espera inventario nuevo",
    DormantReason.AWAITING_FINANCING.value: "Espera su crédito o financiamiento",
}

EXCEPTION_REASON_LABELS: dict[str, str] = {
    OpportunityExceptionReason.AWAITING_CONTACT.value: "Esperando respuesta del contacto",
    OpportunityExceptionReason.CONTACT_UNREACHABLE.value: "Contacto ilocalizable",
    OpportunityExceptionReason.DO_NOT_CONTACT.value: "Contacto con restricción de comunicación",
    OpportunityExceptionReason.OUT_OF_SERVICE_AREA.value: "Fuera de la zona de servicio",
    OpportunityExceptionReason.ADMIN_REVIEW.value: "En revisión del administrador",
}


# -- Commands ---------------------------------------------------------------
#
# One dataclass per intent, all carrying a ``command_key``. That key is the
# idempotency arbiter: a replay after a timeout records nothing and reports the
# original outcome, because it collides with the unique index on the transition
# it already wrote.


@dataclass(frozen=True)
class OriginFacts:
    """The first known provenance of an Opportunity. Written once, never edited."""

    source: OpportunityOriginSource
    channel: str | None = None
    campaign: str | None = None
    advertisement: str | None = None
    referral: str | None = None
    property_uuid: uuid.UUID | None = None
    first_conversation_id: uuid.UUID | None = None
    first_inbox_id: uuid.UUID | None = None


@dataclass(frozen=True)
class OpenOpportunity:
    """Start a commercial pursuit for a Contact."""

    contact_id: uuid.UUID
    kind: OpportunityKind
    origin: OriginFacts
    command_key: str
    property_need_id: uuid.UUID | None = None
    at: datetime | None = None


@dataclass(frozen=True)
class QualificationAction:
    """The first concrete obligation created with qualification."""

    kind: NextActionKind
    due_at: datetime
    note: str | None = None


@dataclass(frozen=True)
class AdvanceStage:
    """Move an Opportunity to a non-terminal stage."""

    opportunity_id: uuid.UUID
    to_stage: OpportunityStage
    command_key: str
    reason: str | None = None
    detail: str | None = None
    at: datetime | None = None
    qualification_action: QualificationAction | None = None


@dataclass(frozen=True)
class RecordLost:
    """Conclude an Opportunity without a transaction."""

    #: The stage this command reaches. Declared on the command rather than
    #: decided by an ``isinstance`` chain, so adding an outcome is one class.
    stage: ClassVar[OpportunityStage] = OpportunityStage.LOST

    opportunity_id: uuid.UUID
    reason: LostReason
    command_key: str
    detail: str | None = None
    at: datetime | None = None


@dataclass(frozen=True)
class RecordDormant:
    """Pause an Opportunity with the condition for reconsidering it."""

    stage: ClassVar[OpportunityStage] = OpportunityStage.DORMANT

    opportunity_id: uuid.UUID
    reason: DormantReason
    revisit_condition: str
    command_key: str
    at: datetime | None = None


@dataclass(frozen=True)
class RecordWon:
    """Conclude an Opportunity in a completed transaction. Administrator only."""

    stage: ClassVar[OpportunityStage] = OpportunityStage.WON

    opportunity_id: uuid.UUID
    evidence: WonEvidence
    evidence_detail: str
    command_key: str
    at: datetime | None = None


Command = OpenOpportunity | AdvanceStage | RecordLost | RecordDormant | RecordWon


@dataclass(frozen=True)
class OpportunityRecorded:
    """What ``record`` did.

    ``replayed`` distinguishes "this command already ran" from "nothing needed
    doing", which a caller retrying after a timeout has to be able to tell
    apart from a rejection.
    """

    opportunity_id: uuid.UUID
    stage: OpportunityStage
    created: bool
    replayed: bool
    responsible_advisor_id: uuid.UUID | None = None
    queued_for_assignment: bool = False


class OpportunityManagement:
    """The Opportunity module. One entry point, everything else private."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, actor: Actor, command: Command) -> OpportunityRecorded:
        """Apply one command. Never commits.

        Left uncommitted so an Opportunity opened from an inbound message, the
        message itself, and the eligibility decision for the reply all land in
        one transaction or none of them do.
        """
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(command.command_key)))
        )
        if isinstance(command, OpenOpportunity):
            return await self._open(actor, command)
        return await self._transition(actor, command)

    # -- Reads -------------------------------------------------------------

    async def opportunity(
        self, actor: Actor, opportunity_id: uuid.UUID, *, lock: bool = False
    ) -> Opportunity:
        """One Opportunity the Actor may see, or :class:`NotFound`."""
        return await visible_opportunity(
            self._session, actor, opportunity_id, lock=lock
        )

    async def origin(self, opportunity_id: uuid.UUID) -> OpportunityOrigin | None:
        found: OpportunityOrigin | None = await self._session.scalar(
            select(OpportunityOrigin).where(
                OpportunityOrigin.opportunity_id == opportunity_id
            )
        )
        return found

    async def transitions(
        self, opportunity_id: uuid.UUID
    ) -> list[OpportunityStageTransition]:
        rows = await self._session.scalars(
            select(OpportunityStageTransition)
            .where(OpportunityStageTransition.opportunity_id == opportunity_id)
            .order_by(
                OpportunityStageTransition.occurred_at.desc(),
                OpportunityStageTransition.id.desc(),
            )
        )
        return list(rows)

    async def active_for_contact(
        self, actor: Actor, contact_id: uuid.UUID
    ) -> list[Opportunity]:
        statement = (
            select(Opportunity)
            .where(Opportunity.contact_id == contact_id)
            .order_by(Opportunity.created_at.desc())
        )
        if not actor.sees_whole_operation:
            statement = statement.where(
                Opportunity.responsible_advisor_id == actor.member_id
            )
        rows = await self._session.scalars(statement)
        return list(rows)

    async def open_demand_for_contact(
        self, contact_id: uuid.UUID
    ) -> Opportunity | None:
        """The Contact's workable Demand Opportunity, if they have one.

        Used by the inbound path to decide whether a new message continues an
        existing pursuit or starts one. Dormant is excluded: a message from a
        paused Contact is a reason for a human to reconsider it, not an
        automatic reactivation (ADR-0021).
        """
        found: Opportunity | None = await self._session.scalar(
            select(Opportunity)
            .where(Opportunity.contact_id == contact_id)
            .where(Opportunity.kind == OpportunityKind.DEMAND.value)
            .where(Opportunity.stage.in_(ACTIVE_STAGES))
            .order_by(Opportunity.created_at)
            .limit(1)
        )
        return found

    async def note_interaction(
        self, opportunity_id: uuid.UUID, *, at: datetime | None = None
    ) -> None:
        """Record that something happened, without touching the stage.

        Activity and stage are different facts. Conflating them is how a CRM
        ends up advancing a pipeline because somebody said "gracias".
        """
        opportunity = await self._session.get(Opportunity, opportunity_id)
        if opportunity is None:  # pragma: no cover - caller holds the row
            return
        moment = at or _now()
        if moment > opportunity.last_activity_at:
            opportunity.last_activity_at = moment

    async def attach_need(self, actor: Actor, opportunity_id: uuid.UUID) -> uuid.UUID:
        """Give an Opportunity a Property Need to hang criteria on. Never commits.

        Needed because the legacy backfill deliberately invents no need: it
        would have had to make up what the Contact wants. Without this the
        migrated Opportunities could never be qualified, which would make the
        whole backfill a dead end.

        Idempotent: an Opportunity that already has a need keeps it. Replacing
        one would orphan the confirmed criteria it holds.
        """
        opportunity = await self.opportunity(actor, opportunity_id, lock=True)
        if opportunity.property_need_id is not None:
            return opportunity.property_need_id
        need = await PropertyNeeds(self._session).open(
            actor, contact_id=opportunity.contact_id
        )
        opportunity.property_need_id = need.id
        opportunity.updated_at = _now()
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="AttachPropertyNeed",
            subject_type="Opportunity",
            subject_id=str(opportunity_id),
            details={"property_need_id": str(need.id)},
            commit=False,
        )
        await self._session.flush()
        return need.id

    # -- Exceptions --------------------------------------------------------

    async def record_exception(
        self,
        actor: Actor,
        opportunity_id: uuid.UUID,
        *,
        reason: OpportunityExceptionReason,
        detail: str | None,
        command_key: str,
    ) -> OpportunityException:
        """Explain why an active Opportunity has no Next Action. Never commits.

        The alternative is a coverage report full of unexplained gaps, which is
        indistinguishable from the operation quietly dropping people.
        """
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(command_key)))
        )
        replay = await self._session.scalar(
            select(OpportunityException).where(
                OpportunityException.command_key == command_key
            )
        )
        if replay is not None:
            actor.require_same_organization(replay.organization_id)
            if (
                replay.opportunity_id != opportunity_id
                or replay.reason != reason.value
                or replay.detail != detail
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes."
                )
            return replay
        opportunity = await self.opportunity(actor, opportunity_id, lock=True)
        await NextActions(self._session).cancel_pending(
            actor,
            opportunity_id,
            reason="Opportunity exception recorded",
        )
        existing = await self.open_exception(opportunity_id)
        if existing is not None:
            if existing.command_key == command_key:
                return existing
            existing.cleared_at = _now()
        row = OpportunityException(
            organization_id=opportunity.organization_id,
            opportunity_id=opportunity_id,
            reason=reason.value,
            detail=detail,
            recorded_by=actor.label,
            command_key=command_key,
        )
        self._session.add(row)
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="RecordOpportunityException",
            subject_type="Opportunity",
            subject_id=str(opportunity_id),
            details={"reason": reason.value, "detail": detail},
            commit=False,
        )
        await self._session.flush()
        return row

    async def clear_exception(self, actor: Actor, opportunity_id: uuid.UUID) -> bool:
        """Close the open exception, if there is one. Never commits."""
        opportunity = await self.opportunity(actor, opportunity_id, lock=True)
        existing = await self.open_exception(opportunity_id)
        if existing is None:
            return False
        if (
            opportunity.stage in QUALIFIED_OR_BEYOND
            and await NextActions(self._session).pending(opportunity_id) is None
        ):
            raise InvalidTransition(
                "Agenda una siguiente acción antes de cerrar la excepción."
            )
        existing.cleared_at = _now()
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ClearOpportunityException",
            subject_type="Opportunity",
            subject_id=str(opportunity_id),
            details={"reason": existing.reason},
            commit=False,
        )
        await self._session.flush()
        return True

    async def open_exception(
        self, opportunity_id: uuid.UUID
    ) -> OpportunityException | None:
        found: OpportunityException | None = await self._session.scalar(
            select(OpportunityException)
            .where(OpportunityException.opportunity_id == opportunity_id)
            .where(OpportunityException.cleared_at.is_(None))
            .limit(1)
        )
        return found

    # -- Internals ---------------------------------------------------------

    async def _open(
        self, actor: Actor, command: OpenOpportunity
    ) -> OpportunityRecorded:
        replay = await self._replayed_result(actor, command)
        if replay is not None:
            return replay

        moment = command.at or _now()
        opportunity = Opportunity(
            organization_id=actor.organization_id,
            contact_id=command.contact_id,
            property_need_id=command.property_need_id,
            kind=command.kind.value,
            stage=OpportunityStage.NEW.value,
            last_activity_at=moment,
            created_at=moment,
            updated_at=moment,
        )
        self._session.add(opportunity)
        await self._session.flush()

        # Written once. There is no code path that updates this row, which is
        # how "the first known attribution is not lost" stops being a promise
        # and becomes a property of the schema.
        self._session.add(
            OpportunityOrigin(
                organization_id=actor.organization_id,
                opportunity_id=opportunity.id,
                source=command.origin.source.value,
                channel=command.origin.channel,
                campaign=command.origin.campaign,
                advertisement=command.origin.advertisement,
                referral=command.origin.referral,
                property_uuid=command.origin.property_uuid,
                first_conversation_id=command.origin.first_conversation_id,
                first_inbox_id=command.origin.first_inbox_id,
                recorded_at=moment,
            )
        )
        await self._write_transition(
            actor,
            opportunity,
            from_stage=None,
            to_stage=OpportunityStage.NEW,
            reason=command.origin.source.value,
            detail=None,
            command_key=command.command_key,
            moment=moment,
        )
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="OpenOpportunity",
            subject_type="Opportunity",
            subject_id=str(opportunity.id),
            details={
                "kind": command.kind.value,
                "origin": command.origin.source.value,
                "contact_id": str(command.contact_id),
            },
            commit=False,
        )
        await self._session.flush()
        logger.info(
            "Opened %s Opportunity %s for Contact %s",
            command.kind.value,
            opportunity.id,
            command.contact_id,
        )
        return OpportunityRecorded(
            opportunity_id=opportunity.id,
            stage=OpportunityStage.NEW,
            created=True,
            replayed=False,
        )

    async def _transition(
        self,
        actor: Actor,
        command: AdvanceStage | RecordLost | RecordDormant | RecordWon,
    ) -> OpportunityRecorded:
        replay = await self._replayed_result(actor, command)
        if replay is not None:
            return replay

        # Locked before anything is decided: the stage read, the legality check
        # and the write have to be one atomic step, or two concurrent commands
        # can each find a legal transition from a stage neither of them ends in.
        opportunity = await self.opportunity(actor, command.opportunity_id, lock=True)
        moment = command.at or _now()
        to_stage = self._target(command)
        self._require_legal(opportunity.stage, to_stage)

        reason: str | None
        detail: str | None

        needs_coverage = (
            to_stage.value in QUALIFIED_OR_BEYOND
            and opportunity.stage not in QUALIFIED_OR_BEYOND
        )
        if to_stage.value in QUALIFIED_OR_BEYOND and opportunity.qualified_at is None:
            await self._require_qualification(opportunity)
            opportunity.qualified_at = moment

        if isinstance(command, RecordWon):
            # ADR-0032: only an Organization Administrator, and only from
            # accepted evidence. Both halves are refused here rather than in a
            # route, so no future caller can reach the stage without them.
            actor.require_administrator()
            if not command.evidence_detail.strip():
                raise MissingEvidence(
                    "Describe la evidencia que respalda la operación concluida."
                )
            opportunity.won_evidence = command.evidence.value
            opportunity.won_evidence_detail = command.evidence_detail.strip()
            opportunity.won_recorded_by = actor.member_id
            opportunity.closed_at = moment
            reason = command.evidence.value
            detail = opportunity.won_evidence_detail
        elif isinstance(command, RecordLost):
            opportunity.lost_reason = command.reason.value
            opportunity.closed_at = moment
            reason = command.reason.value
            detail = command.detail
        elif isinstance(command, RecordDormant):
            if not command.revisit_condition.strip():
                raise MissingEvidence(
                    "Indica bajo qué condición se puede retomar esta oportunidad."
                )
            opportunity.dormant_reason = command.reason.value
            opportunity.dormant_revisit_condition = command.revisit_condition.strip()
            reason = command.reason.value
            detail = opportunity.dormant_revisit_condition
        else:
            reason = command.reason
            detail = command.detail
            if opportunity.stage == OpportunityStage.DORMANT.value:
                # Reactivated. The recorded pause condition served its purpose
                # and is cleared, while the transition history keeps it.
                opportunity.dormant_reason = None
                opportunity.dormant_revisit_condition = None

        from_stage = opportunity.stage
        opportunity.stage = to_stage.value
        opportunity.updated_at = moment
        if moment > opportunity.last_activity_at:
            opportunity.last_activity_at = moment

        await self._write_transition(
            actor,
            opportunity,
            from_stage=from_stage,
            to_stage=to_stage,
            reason=reason,
            detail=detail,
            command_key=command.command_key,
            moment=moment,
        )
        if isinstance(command, RecordWon):
            from realestate.domain.commercial.transactions import (
                RecordTransaction,
                Transactions,
            )

            await Transactions(self._session).record(
                actor,
                RecordTransaction(
                    opportunity_id=opportunity.id,
                    evidence=command.evidence.value,
                    evidence_detail=opportunity.won_evidence_detail or "",
                    completed_at=moment,
                    command_key="won-transaction:"
                    + str(uuid.uuid5(uuid.NAMESPACE_X500, command.command_key)),
                ),
            )
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ChangeOpportunityStage",
            subject_type="Opportunity",
            subject_id=str(opportunity.id),
            details={
                "from": from_stage,
                "to": to_stage.value,
                "reason": reason,
            },
            commit=False,
        )

        if to_stage.value not in ACTIVE_STAGES:
            # A concluded or paused Opportunity owes nothing. Left Pending, the
            # action would sit in the overdue report forever and train the
            # operation to ignore it; the open exception has likewise stopped
            # describing anything.
            await NextActions(self._session).cancel_pending(
                actor,
                opportunity.id,
                reason=f"Opportunity moved to {to_stage.value}",
            )
            open_exception = await self.open_exception(opportunity.id)
            if open_exception is not None:
                open_exception.cleared_at = moment

        queued = False
        advisor_id = opportunity.responsible_advisor_id
        if to_stage.value in QUALIFIED_OR_BEYOND:
            # The promise: no qualified Opportunity without a Responsible
            # Advisor. Applied here rather than by whoever happened to call
            # this, so no surface can qualify an Opportunity and forget.
            outcome = await Assignment(self._session).assign(actor, opportunity.id)
            advisor_id = outcome.advisor_id
            queued = outcome.queued

        if needs_coverage:
            plan = (
                command.qualification_action
                if isinstance(command, AdvanceStage)
                else None
            )
            if advisor_id is not None and plan is not None:
                if plan.due_at <= moment:
                    raise MissingEvidence(
                        "La primera siguiente acción debe vencer en el futuro."
                    )
                action_key = "qualification-action:" + str(
                    uuid.uuid5(uuid.NAMESPACE_URL, command.command_key)
                )
                await NextActions(self._session).schedule(
                    actor,
                    ScheduleNextAction(
                        opportunity_id=opportunity.id,
                        kind=plan.kind,
                        due_at=plan.due_at,
                        note=plan.note,
                        command_key=action_key,
                        at=moment,
                    ),
                )
            else:
                exception_key = "qualification-exception:" + str(
                    uuid.uuid5(uuid.NAMESPACE_OID, command.command_key)
                )
                await self.record_exception(
                    actor,
                    opportunity.id,
                    reason=OpportunityExceptionReason.ADMIN_REVIEW,
                    detail=(
                        "No hay un asesor elegible; la oportunidad está en la cola "
                        "de asignación."
                        if advisor_id is None
                        else "La calificación no incluyó una siguiente acción."
                    ),
                    command_key=exception_key,
                )

        await self._session.flush()
        return OpportunityRecorded(
            opportunity_id=opportunity.id,
            stage=to_stage,
            created=False,
            replayed=False,
            responsible_advisor_id=advisor_id,
            queued_for_assignment=queued,
        )

    def _target(
        self,
        command: AdvanceStage | RecordLost | RecordDormant | RecordWon,
    ) -> OpportunityStage:
        """Which stage this command asks for.

        An outcome command names its own stage; only the generic advance needs a
        guard, because a terminal outcome has evidence requirements that an
        advance cannot carry and must go through its own command rather than a
        nullable field nobody fills in.
        """
        if not isinstance(command, AdvanceStage):
            return command.stage
        if command.to_stage.value in TERMINAL_STAGES:
            raise InvalidTransition(
                "Usa el comando específico para registrar un resultado final."
            )
        return command.to_stage

    def _require_legal(self, from_stage: str, to_stage: OpportunityStage) -> None:
        if from_stage == to_stage.value:
            raise InvalidTransition(
                f"La oportunidad ya está en «{STAGE_LABELS[to_stage.value]}»."
            )
        if to_stage.value not in ALLOWED_TRANSITIONS[from_stage]:
            raise InvalidTransition(
                f"No se puede pasar de «{STAGE_LABELS[from_stage]}» a "
                f"«{STAGE_LABELS[to_stage.value]}»."
            )

    async def _require_qualification(self, opportunity: Opportunity) -> None:
        """The Qualified rule: confirmed minimum criteria and a real contact path."""
        if opportunity.property_need_id is None:
            raise QualificationIncomplete(
                "Registra la necesidad del contacto antes de calificar."
            )
        snapshot = await PropertyNeeds(self._session).snapshot(
            opportunity.property_need_id
        )
        if snapshot.is_stale:
            raise QualificationIncomplete(
                "La necesidad tiene más de 90 días sin confirmarse; "
                "reconfírmala antes de calificar."
            )
        if snapshot.missing_required:
            from realestate.domain.commercial.needs import criterion_label

            names = ", ".join(
                f"«{criterion_label(name)}»" for name in snapshot.missing_required
            )
            pending = snapshot.pending_required
            hint = (
                " Hay interpretaciones sin confirmar; confírmalas con el contacto."
                if pending
                else ""
            )
            raise QualificationIncomplete(
                f"Faltan criterios confirmados: {names}.{hint}"
            )
        verified = await self._session.scalar(
            select(ContactChannelIdentity.id)
            .where(ContactChannelIdentity.contact_id == opportunity.contact_id)
            .where(ContactChannelIdentity.trust == ChannelIdentityTrust.VERIFIED.value)
            .limit(1)
        )
        if verified is None:
            raise QualificationIncomplete(
                "No hay una vía de contacto verificada para este contacto."
            )

    async def _replayed_result(
        self, actor: Actor, command: Command
    ) -> OpportunityRecorded | None:
        """What this command already did, if it already ran.

        One expression of the idempotency contract, shared by both entry points:
        a replay reports the Opportunity's *current* state rather than the state
        the original command produced, because that is what a caller retrying
        after a timeout needs to act on.
        """
        transition: OpportunityStageTransition | None = await self._session.scalar(
            select(OpportunityStageTransition).where(
                OpportunityStageTransition.command_key == command.command_key
            )
        )
        if transition is None:
            return None
        existing = await self._session.get(Opportunity, transition.opportunity_id)
        assert existing is not None
        actor.require_same_organization(existing.organization_id)
        actor.require_owns(
            existing.responsible_advisor_id, "No encontramos esa oportunidad."
        )
        if isinstance(command, OpenOpportunity):
            origin = await self.origin(existing.id)
            if (
                transition.from_stage is not None
                or existing.contact_id != command.contact_id
                or existing.kind != command.kind.value
                or existing.property_need_id != command.property_need_id
                or origin is None
                or origin.source != command.origin.source.value
                or origin.channel != command.origin.channel
                or origin.campaign != command.origin.campaign
                or origin.advertisement != command.origin.advertisement
                or origin.referral != command.origin.referral
                or origin.property_uuid != command.origin.property_uuid
                or origin.first_conversation_id != command.origin.first_conversation_id
                or origin.first_inbox_id != command.origin.first_inbox_id
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes."
                )
        else:
            target = self._target(command)
            reason: str | None
            detail: str | None
            if isinstance(command, RecordLost):
                reason, detail = command.reason.value, command.detail
            elif isinstance(command, RecordDormant):
                reason, detail = (
                    command.reason.value,
                    command.revisit_condition.strip(),
                )
            elif isinstance(command, RecordWon):
                reason, detail = command.evidence.value, command.evidence_detail.strip()
            else:
                reason, detail = command.reason, command.detail
            if (
                transition.opportunity_id != command.opportunity_id
                or transition.to_stage != target.value
                or transition.reason != reason
                or transition.detail != detail
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes."
                )
            if (
                isinstance(command, AdvanceStage)
                and target is OpportunityStage.QUALIFIED
                and transition.from_stage not in QUALIFIED_OR_BEYOND
            ):
                action_key = "qualification-action:" + str(
                    uuid.uuid5(uuid.NAMESPACE_URL, command.command_key)
                )
                original_action = await self._session.scalar(
                    select(NextAction).where(NextAction.command_key == action_key)
                )
                requested = command.qualification_action
                if (original_action is None) != (requested is None):
                    raise InvalidTransition(
                        "La clave de operación ya se usó con datos diferentes."
                    )
                if (
                    original_action is not None
                    and requested is not None
                    and (
                        original_action.kind != requested.kind.value
                        or original_action.due_at != requested.due_at
                        or original_action.note != requested.note
                    )
                ):
                    raise InvalidTransition(
                        "La clave de operación ya se usó con datos diferentes."
                    )
        return OpportunityRecorded(
            opportunity_id=existing.id,
            stage=OpportunityStage(existing.stage),
            created=False,
            replayed=True,
            responsible_advisor_id=existing.responsible_advisor_id,
        )

    async def _write_transition(
        self,
        actor: Actor,
        opportunity: Opportunity,
        *,
        from_stage: str | None,
        to_stage: OpportunityStage,
        reason: str | None,
        detail: str | None,
        command_key: str,
        moment: datetime,
    ) -> None:
        """Append the transition, with the unique key as the final arbiter.

        The pre-read in :meth:`_replayed_result` catches the ordinary replay.
        The advisory command-key lock catches the race it cannot: two
        identical commands arriving at once, both finding nothing recorded.
        The later caller observes the ordinary replay answer — the same shape
        ``_attach`` and
        ``NextActions.schedule`` use, so one situation has one outcome
        everywhere.
        """
        self._session.add(
            OpportunityStageTransition(
                organization_id=opportunity.organization_id,
                opportunity_id=opportunity.id,
                from_stage=from_stage,
                to_stage=to_stage.value,
                reason=reason,
                detail=detail,
                actor_type=actor.actor_type,
                actor_id=actor.label,
                command_key=command_key,
                occurred_at=moment,
            )
        )
        await self._session.flush()

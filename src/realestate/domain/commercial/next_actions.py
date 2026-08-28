"""Next Actions: what is owed on an Opportunity, by whom, and by when.

The operating promise is measured here. A Next Action is specific, has one
responsible member and one due time, and at most one is Pending per Opportunity
— enforced by the partial unique index ``uq_next_action_pending``, not by
convention. That single constraint is what gives "substituted" a meaning and
what stops two concurrent schedules from both surviving.

Completion requires a result. The database refuses a Completed row without an
outcome, because "we did it" with no recorded consequence is the reporting gap
Follow-up Data Completeness exists to expose.

Two things that look like Next Actions and are not: a Next Action is neither a
reminder Hermes decided to send nor a follow-up message. Outbound messaging
stays behind the Stage 1 eligibility gate; scheduling an action here authorises
nobody to write to anybody.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ACTIVE_STAGES,
    Contact,
    NextAction,
    NextActionKind,
    NextActionOutcome,
    NextActionStatus,
    Opportunity,
    OpportunityException,
    OpportunityExceptionReason,
    OrganizationMember,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    InvalidTransition,
    NotAuthorized,
    NotFound,
)
from realestate.domain.commercial.records import visible_opportunity

logger = logging.getLogger(__name__)

KIND_LABELS: dict[str, str] = {
    NextActionKind.QUALIFY.value: "Calificar la necesidad",
    NextActionKind.CALL.value: "Llamar por teléfono",
    NextActionKind.WHATSAPP_MESSAGE.value: "Escribir por WhatsApp",
    NextActionKind.SEND_LISTINGS.value: "Enviar propiedades",
    NextActionKind.SCHEDULE_VISIT.value: "Agendar una visita",
    NextActionKind.VISIT_FOLLOW_UP.value: "Dar seguimiento a la visita",
    NextActionKind.DOCUMENT_REVIEW.value: "Revisar documentos",
    NextActionKind.OTHER.value: "Otra acción",
}

STATUS_LABELS: dict[str, str] = {
    NextActionStatus.PENDING.value: "Pendiente",
    NextActionStatus.COMPLETED.value: "Completada",
    NextActionStatus.SUPERSEDED.value: "Sustituida",
    NextActionStatus.CANCELLED.value: "Cancelada",
}

OUTCOME_LABELS: dict[str, str] = {
    NextActionOutcome.DONE.value: "Realizada",
    NextActionOutcome.NO_ANSWER.value: "Sin respuesta",
    NextActionOutcome.RESCHEDULED.value: "Reprogramada",
    NextActionOutcome.NOT_INTERESTED.value: "Ya no le interesa",
    NextActionOutcome.BLOCKED.value: "Bloqueada",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class ScheduleNextAction:
    """Owe one specific future action on one Opportunity."""

    opportunity_id: uuid.UUID
    kind: NextActionKind
    due_at: datetime
    command_key: str
    #: Defaults to the Opportunity's Responsible Advisor. Supplying it lets an
    #: Administrator owe themselves the work — reviewing a Listing Acquisition,
    #: for example — without becoming the Responsible Advisor.
    responsible_member_id: uuid.UUID | None = None
    note: str | None = None
    at: datetime | None = None


@dataclass(frozen=True)
class CompleteNextAction:
    """Record what happened when the action was carried out."""

    next_action_id: uuid.UUID
    outcome: NextActionOutcome
    command_key: str
    outcome_detail: str | None = None
    at: datetime | None = None


@dataclass(frozen=True)
class Scheduled:
    """The scheduled action, and what it replaced."""

    next_action_id: uuid.UUID
    superseded_id: uuid.UUID | None
    replayed: bool


@dataclass(frozen=True)
class Completed:
    """The completed action and its recorded result."""

    next_action_id: uuid.UUID
    outcome: NextActionOutcome
    replayed: bool


@dataclass(frozen=True)
class DueAction:
    """One owed action with the Contact label an operator needs."""

    action: NextAction
    contact_name: str | None


class NextActions:
    """The Next Action module.

    Hides: the one-Pending-per-Opportunity invariant, supersession, who may be
    responsible, idempotency and races, the audit trail, and the overdue rule.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def schedule(self, actor: Actor, command: ScheduleNextAction) -> Scheduled:
        """Owe one action, superseding whatever was owed before. Never commits."""
        # Command keys are global. The advisory transaction lock serialises the
        # otherwise-unlockable "row does not exist yet" race before we inspect
        # the unique key. It is released automatically on commit or rollback.
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(command.command_key)))
        )
        replay = await self._by_command_key(command.command_key)
        if replay is not None:
            actor.require_same_organization(replay.organization_id)
            actor.require_owns(
                replay.responsible_member_id, "No encontramos esa acción."
            )
            if (
                replay.opportunity_id != command.opportunity_id
                or replay.kind != command.kind.value
                or replay.due_at != command.due_at
                or replay.responsible_member_id
                != (command.responsible_member_id or replay.responsible_member_id)
                or replay.note != command.note
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes."
                )
            return Scheduled(
                next_action_id=replay.id,
                superseded_id=None,
                replayed=True,
            )

        opportunity = await self._locked_opportunity(actor, command.opportunity_id)
        if opportunity.stage not in ACTIVE_STAGES:
            # A closed or paused Opportunity owes nothing. Allowing an action
            # here would keep it permanently in the overdue report, which is the
            # metric the operation is meant to act on.
            raise InvalidTransition(
                "Esta oportunidad no está activa; no se le pueden agendar acciones."
            )
        moment = command.at or _now()
        member = await self._responsible(actor, opportunity, command)

        previous = await self.pending(command.opportunity_id)
        if previous is not None:
            # Closed before the replacement is inserted: the partial unique
            # index permits exactly one Pending row, so the other order would
            # collide with the action being replaced.
            previous.status = NextActionStatus.SUPERSEDED.value
            await self._session.flush()

        action = NextAction(
            organization_id=opportunity.organization_id,
            opportunity_id=opportunity.id,
            kind=command.kind.value,
            responsible_member_id=member.id,
            due_at=command.due_at,
            status=NextActionStatus.PENDING.value,
            note=command.note,
            created_by=actor.label,
            command_key=command.command_key,
        )
        self._session.add(action)
        await self._session.flush()

        if previous is not None:
            previous.superseded_by_id = action.id
        # An exception means no action is currently owed. Scheduling one makes
        # that exception stale, so the two coverage branches cannot overlap.
        open_exception = await self._session.scalar(
            select(OpportunityException)
            .where(OpportunityException.opportunity_id == opportunity.id)
            .where(OpportunityException.cleared_at.is_(None))
            .limit(1)
        )
        if open_exception is not None:
            open_exception.cleared_at = moment
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ScheduleNextAction",
            subject_type="Opportunity",
            subject_id=str(opportunity.id),
            details={
                "next_action_id": str(action.id),
                "kind": command.kind.value,
                "due_at": command.due_at.isoformat(),
                "responsible_member_id": str(member.id),
                "superseded": str(previous.id) if previous else None,
            },
            commit=False,
        )
        await self._session.flush()
        return Scheduled(
            next_action_id=action.id,
            superseded_id=previous.id if previous else None,
            replayed=False,
        )

    async def complete(self, actor: Actor, command: CompleteNextAction) -> Completed:
        """Record the result of a Pending action. Never commits.

        A retry of the same completion is answered from the stored outcome. A
        *different* outcome for an already-completed action is refused: quietly
        accepting it would overwrite what an Advisor reported.
        """
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(command.command_key)))
        )
        replay = await self._session.scalar(
            select(NextAction).where(
                NextAction.completion_command_key == command.command_key
            )
        )
        if replay is not None:
            actor.require_same_organization(replay.organization_id)
            actor.require_owns(
                replay.responsible_member_id, "No encontramos esa acción."
            )
            assert replay.outcome is not None
            if (
                replay.id != command.next_action_id
                or replay.outcome != command.outcome.value
                or replay.outcome_detail != command.outcome_detail
            ):
                raise InvalidTransition(
                    "La clave de operación ya se usó con datos diferentes."
                )
            return Completed(
                next_action_id=replay.id,
                outcome=NextActionOutcome(replay.outcome),
                replayed=True,
            )

        # Every mutation takes the Opportunity row before the action row.
        # Scheduling, exception recording and completion therefore cannot form
        # an opposite-order deadlock while replacing or discharging the same
        # obligation.
        candidate = await self._locked_action(actor, command.next_action_id, lock=False)
        opportunity = await self._locked_opportunity(actor, candidate.opportunity_id)
        action = await self._locked_action(actor, command.next_action_id)
        if action.status == NextActionStatus.COMPLETED.value:
            raise InvalidTransition(
                "Esta acción ya se registró; usa la clave original para reintentar."
            )
        if action.status != NextActionStatus.PENDING.value:
            raise InvalidTransition(
                f"Esta acción está «{STATUS_LABELS[action.status]}» y ya no se "
                "puede completar."
            )

        moment = command.at or _now()
        action.status = NextActionStatus.COMPLETED.value
        action.outcome = command.outcome.value
        action.outcome_detail = command.outcome_detail
        action.completed_at = moment
        action.completion_command_key = command.command_key
        if opportunity.stage in {
            "Qualified",
            "Searching",
            "Visiting",
            "Negotiating",
        }:
            # Completing the owed work cannot leave Qualified work silently
            # uncovered. Until a concrete successor is scheduled, the explicit
            # AdminReview exception is the actionable, auditable state.
            self._session.add(
                OpportunityException(
                    organization_id=action.organization_id,
                    opportunity_id=action.opportunity_id,
                    reason=OpportunityExceptionReason.ADMIN_REVIEW.value,
                    detail=(
                        "La acción se completó; falta definir la siguiente acción."
                    ),
                    recorded_by=actor.label,
                    command_key="completion-review:"
                    + str(uuid.uuid5(uuid.NAMESPACE_URL, command.command_key)),
                    recorded_at=moment,
                )
            )
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="CompleteNextAction",
            subject_type="Opportunity",
            subject_id=str(action.opportunity_id),
            details={
                "next_action_id": str(action.id),
                "outcome": command.outcome.value,
                "command_key": command.command_key,
            },
            commit=False,
        )
        await self._session.flush()
        return Completed(
            next_action_id=action.id, outcome=command.outcome, replayed=False
        )

    async def cancel_pending(
        self,
        actor: Actor,
        opportunity_id: uuid.UUID,
        *,
        reason: str,
    ) -> uuid.UUID | None:
        """Close the Pending action because the Opportunity stopped being active.

        Called when an Opportunity concludes or pauses. Without it a Pending
        action on a Lost Opportunity would sit in the overdue report forever,
        which trains the operation to ignore the report.
        """
        await visible_opportunity(self._session, actor, opportunity_id, lock=True)
        pending = await self.pending(opportunity_id)
        if pending is None:
            return None
        pending.status = NextActionStatus.CANCELLED.value
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="CancelNextAction",
            subject_type="Opportunity",
            subject_id=str(opportunity_id),
            details={"next_action_id": str(pending.id), "reason": reason},
            commit=False,
        )
        await self._session.flush()
        return pending.id

    # -- Reads -------------------------------------------------------------

    async def pending(self, opportunity_id: uuid.UUID) -> NextAction | None:
        """The one Pending action, if there is one."""
        found: NextAction | None = await self._session.scalar(
            select(NextAction)
            .where(NextAction.opportunity_id == opportunity_id)
            .where(NextAction.status == NextActionStatus.PENDING.value)
            .limit(1)
        )
        return found

    async def history(self, opportunity_id: uuid.UUID) -> list[NextAction]:
        rows = await self._session.scalars(
            select(NextAction)
            .where(NextAction.opportunity_id == opportunity_id)
            .order_by(NextAction.created_at.desc(), NextAction.id.desc())
        )
        return list(rows)

    async def action(self, actor: Actor, next_action_id: uuid.UUID) -> NextAction:
        return await self._locked_action(actor, next_action_id, lock=False)

    async def due(
        self,
        actor: Actor,
        *,
        now: datetime | None = None,
        overdue_only: bool = False,
        limit: int = 200,
    ) -> list[NextAction]:
        """Pending actions the Actor may see, soonest first.

        An Advisor sees their own obligations; an Administrator sees the whole
        operation's. That is the same scoping rule as everywhere else, and it is
        applied here rather than in the template that renders the list.
        """
        moment = now or _now()
        query = (
            select(NextAction)
            .where(NextAction.organization_id == actor.organization_id)
            .where(NextAction.status == NextActionStatus.PENDING.value)
        )
        if overdue_only:
            query = query.where(NextAction.due_at <= moment)
        if not actor.sees_whole_operation:
            query = query.where(NextAction.responsible_member_id == actor.member_id)
        rows = await self._session.scalars(
            query.order_by(NextAction.due_at).limit(limit)
        )
        return list(rows)

    async def due_with_contacts(
        self,
        actor: Actor,
        *,
        now: datetime | None = None,
        overdue_only: bool = False,
        limit: int = 200,
    ) -> list[DueAction]:
        """Pending work already labelled for an operator surface."""
        moment = now or _now()
        query = (
            select(NextAction, Contact.display_name)
            .join(Opportunity, Opportunity.id == NextAction.opportunity_id)
            .join(Contact, Contact.id == Opportunity.contact_id)
            .where(NextAction.organization_id == actor.organization_id)
            .where(NextAction.status == NextActionStatus.PENDING.value)
        )
        if overdue_only:
            query = query.where(NextAction.due_at <= moment)
        if not actor.sees_whole_operation:
            query = query.where(NextAction.responsible_member_id == actor.member_id)
        rows = await self._session.execute(
            query.order_by(NextAction.due_at).limit(limit)
        )
        return [DueAction(action=action, contact_name=name) for action, name in rows]

    @staticmethod
    def is_overdue(action: NextAction | None, *, now: datetime | None = None) -> bool:
        """One definition of overdue, shared by the metric and every surface.

        ``None`` is accepted and answers ``False``: an Opportunity that owes
        nothing is not overdue, it is uncovered — a different gap, counted
        separately. Callers hold "the Pending action, if there is one", so
        making them each guard first is how the three copies of this rule
        drifted apart and lost the status check.
        """
        if action is None or action.status != NextActionStatus.PENDING.value:
            return False
        return action.due_at <= (now or _now())

    # -- internals ---------------------------------------------------------

    async def _by_command_key(self, command_key: str) -> NextAction | None:
        found: NextAction | None = await self._session.scalar(
            select(NextAction).where(NextAction.command_key == command_key)
        )
        return found

    async def _locked_opportunity(
        self, actor: Actor, opportunity_id: uuid.UUID
    ) -> Opportunity:
        return await visible_opportunity(
            self._session, actor, opportunity_id, lock=True
        )

    async def _locked_action(
        self, actor: Actor, next_action_id: uuid.UUID, *, lock: bool = True
    ) -> NextAction:
        query = select(NextAction).where(NextAction.id == next_action_id)
        if lock:
            query = query.with_for_update()
        action = await self._session.scalar(query)
        if action is None:
            raise NotFound("No encontramos esa acción.")
        actor.require_same_organization(action.organization_id)
        actor.require_owns(action.responsible_member_id, "No encontramos esa acción.")
        return action

    async def _responsible(
        self,
        actor: Actor,
        opportunity: Opportunity,
        command: ScheduleNextAction,
    ) -> OrganizationMember:
        """Who owes the action, defaulting to the Responsible Advisor.

        An unassigned Opportunity has nobody to owe it. Refusing here rather
        than storing a NULL is what keeps the coverage metric meaningful: an
        action with no owner is not coverage.
        """
        member_id = command.responsible_member_id or opportunity.responsible_advisor_id
        if member_id is None:
            raise NotAuthorized(
                "Asigna un asesor responsable antes de agendar la siguiente acción."
            )
        member = await self._session.get(OrganizationMember, member_id)
        if (
            member is None
            or member.organization_id != opportunity.organization_id
            or not member.active
        ):
            raise NotFound("Ese integrante no está disponible en la organización.")
        if not actor.sees_whole_operation and member.id != actor.member_id:
            raise NotAuthorized(
                "Sólo un administrador puede asignar una acción a otra persona."
            )
        return member

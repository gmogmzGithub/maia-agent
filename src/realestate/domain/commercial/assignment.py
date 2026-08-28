"""Who is responsible for this Opportunity — and what happens when nobody is.

The rule is deterministic and short (PROJECT_MEMORY): preserve an existing
Responsible Advisor; otherwise use the configured default Advisor; otherwise
place the Opportunity in the Assignment Queue for an Administrator. No
round-robin, no load scoring, no acceptance deadline: those need real
operational data to be anything other than a guess.

The Property Expert branch of that rule is deliberately absent rather than
approximated. The designation itself belongs to the human-operation stage, and
:class:`AssignmentBasis` already names the basis so adding the branch later does
not rewrite what has been recorded.

Two failure modes shape the implementation. **Silence** is the one that matters:
an Opportunity nobody owns must become visible work, not a null column, which
is what the queue is for. **Duplication** is the other: two concurrent
assignments must produce one Responsible Advisor, which the partial unique index
``uq_assignment_open`` guarantees even if the row lock is somehow bypassed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ACTIVE_STAGES,
    AssignmentBasis,
    AssignmentQueueEntry,
    AssignmentQueueReason,
    Contact,
    Opportunity,
    OpportunityExceptionReason,
    OpportunityAssignment,
    OrganizationMember,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, NotAuthorized, NotFound
from realestate.domain.commercial.records import visible_opportunity

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


# Spanish for this module's own enums. Beside the behaviour rather than in the
# router, so adding a basis or a queue reason gives one obvious place to put its
# wording — and so a value can never reach an operator's screen as an English
# identifier.
BASIS_LABELS: dict[str, str] = {
    AssignmentBasis.PRESERVED.value: "Se conservó el asesor existente",
    AssignmentBasis.PROPERTY_EXPERT.value: "Especialista de la propiedad",
    AssignmentBasis.DEFAULT_ADVISOR.value: "Asesor predeterminado",
    AssignmentBasis.MANUAL_ADMIN.value: "Asignación manual del administrador",
}

QUEUE_REASON_LABELS: dict[str, str] = {
    AssignmentQueueReason.NO_ELIGIBLE_ADVISOR.value: (
        "No hay un asesor elegible configurado"
    ),
    AssignmentQueueReason.DEFAULT_ADVISOR_INACTIVE.value: (
        "El asesor predeterminado está inactivo"
    ),
}

# What the Administrator has to do about each, in the queue's own words. The
# two cases are different actions — add a login to the configuration, or
# reactivate somebody — which is the whole reason they are separate reasons.
QUEUE_REASON_DETAIL: dict[str, str] = {
    AssignmentQueueReason.NO_ELIGIBLE_ADVISOR.value: (
        "No hay un asesor predeterminado activo configurado para la organización."
    ),
    AssignmentQueueReason.DEFAULT_ADVISOR_INACTIVE.value: (
        "El asesor predeterminado está dado de baja; reactívalo o configura otro."
    ),
}


@dataclass(frozen=True)
class AssignmentOutcome:
    """The result of asking for a Responsible Advisor.

    ``queued`` and ``advisor_id`` are mutually exclusive by construction: either
    somebody owns it, or an Administrator has been given the work of deciding.
    A caller cannot read an advisor off a queued outcome.
    """

    opportunity_id: uuid.UUID
    advisor_id: uuid.UUID | None
    basis: AssignmentBasis | None
    queued: bool
    #: False when the Opportunity already had this Advisor, which makes
    #: repeated assignment a no-op rather than a new period of responsibility.
    created: bool
    queue_reason: AssignmentQueueReason | None = None


@dataclass(frozen=True)
class QueuedOpportunity:
    """One row of the Administrator's Assignment Queue surface."""

    opportunity: Opportunity
    contact_name: str | None
    reason: AssignmentQueueReason | None
    detail: str | None
    since: datetime


class Assignment:
    """The assignment module.

    Hides: the deterministic candidate rule, row locking, the queue, resolving
    a queue entry when somebody finally owns the work, the denormalised
    ``responsible_advisor_id`` column, idempotency, and the audit trail.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def assign(
        self, actor: Actor, opportunity_id: uuid.UUID
    ) -> AssignmentOutcome:
        """Apply the deterministic rule. Never commits.

        Idempotent: an Opportunity that already has an open assignment keeps it
        and reports ``Preserved``. That is not a special case bolted on for
        retries — preserving an existing owner is the first clause of the rule.
        """
        opportunity = await self._locked(actor, opportunity_id)
        open_assignment = await self._open_assignment(opportunity_id)
        if open_assignment is not None:
            await self._resolve_queue_entry(opportunity_id, actor.label)
            await self._sync_column(opportunity, open_assignment.advisor_id)
            return AssignmentOutcome(
                opportunity_id=opportunity_id,
                advisor_id=open_assignment.advisor_id,
                basis=AssignmentBasis.PRESERVED,
                queued=False,
                created=False,
            )

        candidate, why = await self._default_advisor(opportunity.organization_id)
        if candidate is None:
            assert why is not None
            entry = await self._enqueue(
                opportunity, reason=why, detail=QUEUE_REASON_DETAIL[why.value]
            )
            return AssignmentOutcome(
                opportunity_id=opportunity_id,
                advisor_id=None,
                basis=None,
                queued=True,
                created=False,
                queue_reason=AssignmentQueueReason(entry.reason),
            )

        return await self._attach(
            actor,
            opportunity,
            advisor=candidate,
            basis=AssignmentBasis.DEFAULT_ADVISOR,
        )

    async def assign_manually(
        self, actor: Actor, opportunity_id: uuid.UUID, advisor_id: uuid.UUID
    ) -> AssignmentOutcome:
        """An Administrator naming the Responsible Advisor. Never commits.

        Reserved to an Administrator: an Advisor moving an Opportunity to
        themselves or to a colleague is a team decision, and the MVP has one
        person authorised to make it.
        """
        actor.require_administrator()
        opportunity = await self._locked(actor, opportunity_id)
        advisor = await self._session.get(OrganizationMember, advisor_id)
        if (
            advisor is None
            or advisor.organization_id != opportunity.organization_id
            or not advisor.active
        ):
            raise NotFound("Ese asesor no está disponible en la organización.")
        if not advisor.advises:
            raise NotAuthorized(
                f"{advisor.display_name} no puede ser asesor responsable."
            )

        open_assignment = await self._open_assignment(opportunity_id)
        if open_assignment is not None:
            if open_assignment.advisor_id == advisor_id:
                await self._resolve_queue_entry(opportunity_id, actor.label)
                return AssignmentOutcome(
                    opportunity_id=opportunity_id,
                    advisor_id=advisor_id,
                    basis=AssignmentBasis.PRESERVED,
                    queued=False,
                    created=False,
                )
            # Closed rather than replaced: "who owned this in March" is an
            # attribution question the operation will ask.
            open_assignment.unassigned_at = _now()
            await self._session.flush()

        return await self._attach(
            actor, opportunity, advisor=advisor, basis=AssignmentBasis.MANUAL_ADMIN
        )

    async def release(self, actor: Actor, opportunity_id: uuid.UUID) -> bool:
        """Remove the Responsible Advisor and re-queue the work. Never commits.

        An Opportunity with nobody responsible must be visible, so releasing
        one enqueues it in the same step. Administrator only.
        """
        actor.require_administrator()
        opportunity = await self._locked(actor, opportunity_id)
        open_assignment = await self._open_assignment(opportunity_id)
        if open_assignment is None:
            return False
        open_assignment.unassigned_at = _now()
        opportunity.responsible_advisor_id = None
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ReleaseOpportunityAssignment",
            subject_type="Opportunity",
            subject_id=str(opportunity_id),
            details={"advisor_id": str(open_assignment.advisor_id)},
            commit=False,
        )
        if opportunity.stage in ACTIVE_STAGES:
            await self._enqueue(
                opportunity,
                reason=AssignmentQueueReason.NO_ELIGIBLE_ADVISOR,
                detail="Un administrador liberó la asignación.",
            )
            if opportunity.stage in {
                "Qualified",
                "Searching",
                "Visiting",
                "Negotiating",
            }:
                # Local import avoids a module cycle: OpportunityManagement
                # delegates assignment here, while release needs its canonical
                # exception operation to preserve the coverage invariant.
                from realestate.domain.commercial.opportunities import (
                    OpportunityManagement,
                )

                await OpportunityManagement(self._session).record_exception(
                    actor,
                    opportunity_id,
                    reason=OpportunityExceptionReason.ADMIN_REVIEW,
                    detail="La asignación se liberó y requiere revisión administrativa.",
                    command_key=f"release-assignment:{open_assignment.id}",
                )
        await self._session.flush()
        return True

    async def queue(self, actor: Actor) -> list[QueuedOpportunity]:
        """The Assignment Queue: active Opportunities nobody is responsible for.

        Derived from the assignment state rather than read from the queue table,
        so the Administrator's list cannot drift out of step with reality. The
        table supplies the *reason*, which a derived set cannot know.
        """
        actor.require_administrator()
        rows = await self._session.execute(
            select(Opportunity, Contact.display_name)
            .join(Contact, Contact.id == Opportunity.contact_id)
            .where(Opportunity.organization_id == actor.organization_id)
            .where(Opportunity.stage.in_(ACTIVE_STAGES))
            .where(Opportunity.responsible_advisor_id.is_(None))
            .order_by(Opportunity.created_at)
        )
        opportunities = list(rows.all())
        if not opportunities:
            return []
        entries = {
            entry.opportunity_id: entry
            for entry in await self._session.scalars(
                select(AssignmentQueueEntry)
                .where(
                    AssignmentQueueEntry.opportunity_id.in_(
                        [item[0].id for item in opportunities]
                    )
                )
                .where(AssignmentQueueEntry.resolved_at.is_(None))
            )
        }
        queued: list[QueuedOpportunity] = []
        for opportunity, contact_name in opportunities:
            entry = entries.get(opportunity.id)
            queued.append(
                QueuedOpportunity(
                    opportunity=opportunity,
                    contact_name=contact_name,
                    reason=(AssignmentQueueReason(entry.reason) if entry else None),
                    detail=entry.detail if entry else None,
                    since=entry.created_at if entry else opportunity.created_at,
                )
            )
        return queued

    async def history(self, opportunity_id: uuid.UUID) -> list[OpportunityAssignment]:
        rows = await self._session.scalars(
            select(OpportunityAssignment)
            .where(OpportunityAssignment.opportunity_id == opportunity_id)
            .order_by(OpportunityAssignment.assigned_at.desc())
        )
        return list(rows)

    # -- internals ---------------------------------------------------------

    async def _locked(self, actor: Actor, opportunity_id: uuid.UUID) -> Opportunity:
        """The Opportunity row, locked, inside the Actor's Organization.

        Deliberately not filtered by the caller's own assignments: an
        Administrator assigning work they do not own is the normal case, and
        Product's own deterministic assignment owns nothing at all.
        """
        return await visible_opportunity(
            self._session, actor, opportunity_id, lock=True
        )

    async def _open_assignment(
        self, opportunity_id: uuid.UUID
    ) -> OpportunityAssignment | None:
        found: OpportunityAssignment | None = await self._session.scalar(
            select(OpportunityAssignment)
            .where(OpportunityAssignment.opportunity_id == opportunity_id)
            .where(OpportunityAssignment.unassigned_at.is_(None))
            .limit(1)
        )
        return found

    async def _default_advisor(
        self, organization_id: uuid.UUID
    ) -> tuple[OrganizationMember | None, AssignmentQueueReason | None]:
        """The configured fallback, and — when there is none — why not.

        Inactive means ineligible: returning an unusable Advisor would satisfy
        the column and defeat the promise, which is the exact failure the queue
        exists to make visible.

        The reason is returned rather than assumed because the Administrator's
        two remedies differ. "Nobody is configured" needs a login added to the
        configuration; "the configured Advisor is inactive" needs that person
        reactivated. Collapsing both into one message would put one sentence in
        front of two different actions.
        """
        designated: OrganizationMember | None = await self._session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.is_default_advisor.is_(True))
            .limit(1)
        )
        if designated is None:
            return None, AssignmentQueueReason.NO_ELIGIBLE_ADVISOR
        if not designated.active:
            return None, AssignmentQueueReason.DEFAULT_ADVISOR_INACTIVE
        # ``advises`` is not re-checked: ``ck_organization_members_default_advises``
        # makes "designated but cannot own work" impossible to store, so a check
        # here would be a branch the schema forbids.
        return designated, None

    async def _attach(
        self,
        actor: Actor,
        opportunity: Opportunity,
        *,
        advisor: OrganizationMember,
        basis: AssignmentBasis,
    ) -> AssignmentOutcome:
        try:
            # The row lock above already serialises the ordinary case. This
            # savepoint covers the one it cannot: a caller that reached here
            # without the lock, or a lock acquired on a stale snapshot. The
            # unique index is the final authority on "one open assignment".
            #
            # The row is constructed *inside* the savepoint on purpose: an
            # object added before it would survive the rollback still pending
            # and be flushed again by the caller's own commit.
            async with self._session.begin_nested():
                self._session.add(
                    OpportunityAssignment(
                        organization_id=opportunity.organization_id,
                        opportunity_id=opportunity.id,
                        advisor_id=advisor.id,
                        basis=basis.value,
                        assigned_by=actor.label,
                    )
                )
                await self._session.flush()
        except IntegrityError:
            winner = await self._open_assignment(opportunity.id)
            if winner is None:  # pragma: no cover - the index is the only writer
                raise
            await self._sync_column(opportunity, winner.advisor_id)
            logger.info(
                "Lost the assignment race for Opportunity %s; %s owns it",
                opportunity.id,
                winner.advisor_id,
            )
            return AssignmentOutcome(
                opportunity_id=opportunity.id,
                advisor_id=winner.advisor_id,
                basis=AssignmentBasis.PRESERVED,
                queued=False,
                created=False,
            )

        await self._sync_column(opportunity, advisor.id)
        await self._resolve_queue_entry(opportunity.id, actor.label)
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="AssignOpportunity",
            subject_type="Opportunity",
            subject_id=str(opportunity.id),
            details={"advisor_id": str(advisor.id), "basis": basis.value},
            commit=False,
        )
        await self._session.flush()
        logger.info(
            "Assigned Opportunity %s to %s (%s)",
            opportunity.id,
            advisor.login,
            basis.value,
        )
        return AssignmentOutcome(
            opportunity_id=opportunity.id,
            advisor_id=advisor.id,
            basis=basis,
            queued=False,
            created=True,
        )

    async def _sync_column(
        self, opportunity: Opportunity, advisor_id: uuid.UUID | None
    ) -> None:
        if opportunity.responsible_advisor_id != advisor_id:
            opportunity.responsible_advisor_id = advisor_id

    async def _enqueue(
        self,
        opportunity: Opportunity,
        *,
        reason: AssignmentQueueReason,
        detail: str,
    ) -> AssignmentQueueEntry:
        """Record why the rule produced nobody. Idempotent per Opportunity."""
        existing = await self._session.scalar(
            select(AssignmentQueueEntry)
            .where(AssignmentQueueEntry.opportunity_id == opportunity.id)
            .where(AssignmentQueueEntry.resolved_at.is_(None))
            .limit(1)
        )
        if existing is not None:
            return existing
        entry = AssignmentQueueEntry(
            organization_id=opportunity.organization_id,
            opportunity_id=opportunity.id,
            reason=reason.value,
            detail=detail,
        )
        self._session.add(entry)
        await record_audit(
            self._session,
            actor_type="Product",
            actor_id="Assignment",
            action="EnqueueForAssignment",
            subject_type="Opportunity",
            subject_id=str(opportunity.id),
            details={"reason": reason.value, "detail": detail},
            commit=False,
        )
        await self._session.flush()
        logger.info(
            "Opportunity %s needs manual assignment: %s",
            opportunity.id,
            reason.value,
        )
        return entry

    async def _resolve_queue_entry(
        self, opportunity_id: uuid.UUID, resolved_by: str
    ) -> None:
        entry = await self._session.scalar(
            select(AssignmentQueueEntry)
            .where(AssignmentQueueEntry.opportunity_id == opportunity_id)
            .where(AssignmentQueueEntry.resolved_at.is_(None))
            .limit(1)
        )
        if entry is not None:
            entry.resolved_at = _now()
            entry.resolved_by = resolved_by

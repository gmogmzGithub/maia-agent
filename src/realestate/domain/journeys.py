"""Versioned, human-confirmed buyer Transaction Journeys (ADR-0056).

The module is intentionally deeper than the CRM forms that call it. It owns the
template approval gate, frozen-plan instantiation, Organization scope, ownership
and every legal milestone transition. Hermes receives a read-only projection
elsewhere; there is no Product/Model command that advances a milestone.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ACTIVE_STAGES,
    MarketSaleRecord,
    Opportunity,
    OpportunityKind,
    PurchaseProfile,
    TransactionJourney,
    TransactionJourneyTemplateVersion,
    TransactionMilestone,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    InvalidTransition,
    MissingEvidence,
    NotAuthorized,
    NotFound,
)
from realestate.domain.commercial.records import visible_opportunity


def _now() -> datetime:
    return datetime.now(tz=UTC)


class JourneyState(str, enum.Enum):
    ACTIVE = "Active"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class MilestoneState(str, enum.Enum):
    PENDING = "Pending"
    IN_PROGRESS = "InProgress"
    BLOCKED = "Blocked"
    COMPLETED = "Completed"
    SKIPPED = "Skipped"
    CANCELLED = "Cancelled"


MILESTONE_STATE_LABELS: dict[str, str] = {
    MilestoneState.PENDING.value: "Pendiente",
    MilestoneState.IN_PROGRESS.value: "En curso",
    MilestoneState.BLOCKED.value: "Bloqueado",
    MilestoneState.COMPLETED.value: "Completado",
    MilestoneState.SKIPPED.value: "Omitido",
    MilestoneState.CANCELLED.value: "Cancelado",
}


# Santiago must approve this before it can instantiate customer work. Keeping
# it in code makes the proposed first plan reviewable and deterministic without
# pretending it is already operational configuration.
DEFAULT_BUYER_PLAN: tuple[dict[str, Any], ...] = (
    {"code": "operation-agreed", "name": "Operación acordada", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "payment-path", "name": "Ruta de pago establecida", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "preparatory-agreement", "name": "Acuerdo preparatorio aplicable registrado", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "buyer-file", "name": "Expediente del comprador integrado", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "property-file", "name": "Expediente de la propiedad integrado", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "legal-review", "name": "Revisión legal registrada por la persona responsable", "responsibility": "Responsable legal", "required_evidence": True},
    {"code": "appraisal-review", "name": "Avalúo y revisión técnica aplicable", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "financing-approval", "name": "Aprobación y condiciones de financiamiento", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "notarial-preparation", "name": "Preparación notarial", "responsibility": "Notaría", "required_evidence": True},
    {"code": "signature-scheduled", "name": "Firma programada", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "deed-and-settlement", "name": "Firma de escritura y liquidación", "responsibility": "Notaría", "required_evidence": True},
    {"code": "possession-handover", "name": "Posesión y entrega", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "registration-delivery", "name": "Registro y entrega documental", "responsibility": "Asesor responsable", "required_evidence": True},
    {"code": "aftercare", "name": "Acompañamiento posterior", "responsibility": "Asesor responsable", "required_evidence": False},
)


@dataclass(frozen=True)
class JourneyWorkspace:
    journey: TransactionJourney
    milestones: tuple[TransactionMilestone, ...]
    profile: PurchaseProfile
    sale: MarketSaleRecord


def _validate_plan(plan: tuple[dict[str, Any], ...]) -> None:
    if not plan:
        raise MissingEvidence("El template debe contener al menos un hito.")
    seen: set[str] = set()
    for item in plan:
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        responsibility = str(item.get("responsibility", "")).strip()
        if not code or not name or not responsibility:
            raise MissingEvidence(
                "Cada hito necesita código, nombre y responsable explícitos."
            )
        if code in seen:
            raise InvalidTransition(f"El código de hito «{code}» está repetido.")
        seen.add(code)


class JourneyTemplates:
    """Draft and approval lifecycle for Organization-owned buyer templates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(self, actor: Actor) -> TransactionJourneyTemplateVersion | None:
        found: TransactionJourneyTemplateVersion | None = await self._session.scalar(
            select(TransactionJourneyTemplateVersion)
            .where(
                TransactionJourneyTemplateVersion.organization_id
                == actor.organization_id
            )
            .order_by(TransactionJourneyTemplateVersion.version.desc())
            .limit(1)
        )
        return found

    async def approved(
        self, actor: Actor
    ) -> TransactionJourneyTemplateVersion | None:
        found: TransactionJourneyTemplateVersion | None = await self._session.scalar(
            select(TransactionJourneyTemplateVersion)
            .where(
                TransactionJourneyTemplateVersion.organization_id
                == actor.organization_id,
                TransactionJourneyTemplateVersion.state == "Approved",
            )
            .order_by(TransactionJourneyTemplateVersion.version.desc())
            .limit(1)
        )
        return found

    async def create_draft(
        self,
        actor: Actor,
        *,
        plan: tuple[dict[str, Any], ...] = DEFAULT_BUYER_PLAN,
        name: str = "Compra residencial",
    ) -> TransactionJourneyTemplateVersion:
        actor.require_administrator()
        actor.require_writable()
        if actor.member_id is None:  # defensive: administrator is always human
            raise NotAuthorized()
        _validate_plan(plan)
        latest = await self.latest(actor)
        if latest is not None and latest.state == "Draft":
            return latest
        row = TransactionJourneyTemplateVersion(
            organization_id=actor.organization_id,
            version=1 if latest is None else latest.version + 1,
            name=name.strip() or "Compra residencial",
            state="Draft",
            plan=[dict(item) for item in plan],
            created_by=actor.member_id,
        )
        self._session.add(row)
        await self._session.flush()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="CreateTransactionJourneyTemplateDraft",
            subject_type="TransactionJourneyTemplateVersion",
            subject_id=str(row.id),
            details={"version": row.version, "milestones": len(plan)},
            commit=False,
        )
        return row

    async def approve(
        self, actor: Actor, template_id: uuid.UUID
    ) -> TransactionJourneyTemplateVersion:
        actor.require_administrator()
        actor.require_writable()
        if actor.member_id is None:
            raise NotAuthorized()
        row = await self._session.scalar(
            select(TransactionJourneyTemplateVersion)
            .where(
                TransactionJourneyTemplateVersion.organization_id
                == actor.organization_id,
                TransactionJourneyTemplateVersion.id == template_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFound()
        if row.state == "Approved":
            return row
        if row.state != "Draft":
            raise InvalidTransition("Sólo un borrador puede aprobarse.")
        current = await self.approved(actor)
        if current is not None:
            current.state = "Superseded"
        row.state = "Approved"
        row.approved_by = actor.member_id
        row.approved_at = _now()
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ApproveTransactionJourneyTemplate",
            subject_type="TransactionJourneyTemplateVersion",
            subject_id=str(row.id),
            details={"version": row.version},
            commit=False,
        )
        await self._session.flush()
        return row


class TransactionJourneys:
    """Start, read and human-confirm one Organization's buyer journeys."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_opportunity(
        self, actor: Actor, opportunity_id: uuid.UUID
    ) -> JourneyWorkspace | None:
        opportunity = await visible_opportunity(self._session, actor, opportunity_id)
        journey = await self._session.scalar(
            select(TransactionJourney).where(
                TransactionJourney.organization_id == actor.organization_id,
                TransactionJourney.opportunity_id == opportunity.id,
            )
        )
        if journey is None:
            return None
        milestones = tuple(
            await self._session.scalars(
                select(TransactionMilestone)
                .where(
                    TransactionMilestone.organization_id == actor.organization_id,
                    TransactionMilestone.journey_id == journey.id,
                )
                .order_by(TransactionMilestone.sequence)
            )
        )
        profile = await self._session.scalar(
            select(PurchaseProfile).where(
                PurchaseProfile.organization_id == actor.organization_id,
                PurchaseProfile.journey_id == journey.id,
            )
        )
        sale = await self._session.scalar(
            select(MarketSaleRecord).where(
                MarketSaleRecord.organization_id == actor.organization_id,
                MarketSaleRecord.journey_id == journey.id,
            )
        )
        if profile is None or sale is None:  # schema invariant, not a user state
            raise RuntimeError("Transaction Journey has incomplete analytical records")
        return JourneyWorkspace(journey, milestones, profile, sale)

    async def start(
        self, actor: Actor, opportunity_id: uuid.UUID
    ) -> JourneyWorkspace:
        actor.require_writable()
        if actor.is_product or actor.member_id is None:
            raise NotAuthorized(
                "Sólo un miembro autorizado puede iniciar el trámite de compra."
            )
        existing = await self.for_opportunity(actor, opportunity_id)
        if existing is not None:
            return existing
        opportunity: Opportunity = await visible_opportunity(
            self._session, actor, opportunity_id, lock=True
        )
        if opportunity.kind != OpportunityKind.DEMAND.value:
            raise InvalidTransition(
                "La primera Jornada sólo está disponible para una oportunidad de compra."
            )
        if opportunity.stage not in ACTIVE_STAGES:
            raise InvalidTransition(
                "No se puede iniciar un trámite desde una oportunidad concluida o en pausa."
            )
        if opportunity.responsible_advisor_id is None:
            raise MissingEvidence(
                "Asigna una persona asesora responsable antes de iniciar el trámite."
            )
        actor.require_owns(
            opportunity.responsible_advisor_id,
            "No encontramos esa oportunidad dentro de tu trabajo asignado.",
        )
        template = await JourneyTemplates(self._session).approved(actor)
        if template is None:
            raise MissingEvidence(
                "Un administrador debe revisar y aprobar el template de compra antes de usarlo."
            )
        moment = _now()
        journey = TransactionJourney(
            organization_id=actor.organization_id,
            opportunity_id=opportunity.id,
            template_version_id=template.id,
            responsible_advisor_id=opportunity.responsible_advisor_id,
            state=JourneyState.ACTIVE.value,
            frozen_plan=[dict(item) for item in template.plan],
            started_by=actor.member_id,
            started_at=moment,
            updated_at=moment,
        )
        self._session.add(journey)
        await self._session.flush()
        milestones: list[TransactionMilestone] = []
        for sequence, item in enumerate(template.plan, start=1):
            milestone = TransactionMilestone(
                organization_id=actor.organization_id,
                journey_id=journey.id,
                sequence=sequence,
                code=str(item["code"]),
                name=str(item["name"]),
                responsibility=str(item["responsibility"]),
                required_evidence=bool(item.get("required_evidence", True)),
                state=MilestoneState.PENDING.value,
            )
            self._session.add(milestone)
            milestones.append(milestone)
        profile = PurchaseProfile(
            organization_id=actor.organization_id,
            opportunity_id=opportunity.id,
            journey_id=journey.id,
            recorded_by=actor.member_id,
            recorded_at=moment,
            updated_at=moment,
            field_states={},
            source_version=1,
        )
        self._session.add(profile)
        await self._session.flush()
        sale = MarketSaleRecord(
            organization_id=actor.organization_id,
            opportunity_id=opportunity.id,
            journey_id=journey.id,
            purchase_profile_id=profile.id,
            recorded_by=actor.member_id,
            state="Preparation",
            outcome="InProgress",
            field_states={},
            source_version=1,
            created_at=moment,
            updated_at=moment,
        )
        self._session.add(sale)
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="StartTransactionJourney",
            subject_type="TransactionJourney",
            subject_id=str(journey.id),
            details={
                "opportunity_id": str(opportunity.id),
                "template_version": template.version,
            },
            commit=False,
        )
        await self._session.flush()
        return JourneyWorkspace(journey, tuple(milestones), profile, sale)

    async def update_milestone(
        self,
        actor: Actor,
        milestone_id: uuid.UUID,
        *,
        state: MilestoneState,
        evidence: str | None = None,
        reason: str | None = None,
        due_at: datetime | None = None,
    ) -> TransactionMilestone:
        actor.require_writable()
        if actor.is_product or actor.member_id is None:
            raise NotAuthorized("Maia no puede avanzar un hito.")
        milestone = await self._session.scalar(
            select(TransactionMilestone)
            .where(
                TransactionMilestone.organization_id == actor.organization_id,
                TransactionMilestone.id == milestone_id,
            )
            .with_for_update()
        )
        if milestone is None:
            raise NotFound()
        journey = await self._session.get(TransactionJourney, milestone.journey_id)
        if journey is None or journey.organization_id != actor.organization_id:
            raise NotFound()
        actor.require_owns(
            journey.responsible_advisor_id,
            "No encontramos ese hito dentro de tu trabajo asignado.",
        )
        if journey.state != JourneyState.ACTIVE.value:
            raise InvalidTransition("La Jornada ya no está activa.")
        clean_evidence = (evidence or "").strip() or None
        clean_reason = (reason or "").strip() or None
        if state in {
            MilestoneState.BLOCKED,
            MilestoneState.SKIPPED,
            MilestoneState.CANCELLED,
        } and clean_reason is None:
            raise MissingEvidence("Indica el motivo de este estado.")
        if (
            state is MilestoneState.COMPLETED
            and milestone.required_evidence
            and clean_evidence is None
        ):
            raise MissingEvidence("Registra la evidencia antes de completar el hito.")
        moment = _now()
        previous = milestone.state
        milestone.state = state.value
        milestone.evidence = clean_evidence
        milestone.reason = clean_reason
        milestone.due_at = due_at
        milestone.confirmed_by = actor.member_id
        milestone.confirmed_at = moment
        milestone.updated_at = moment
        journey.updated_at = moment
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ConfirmTransactionMilestone",
            subject_type="TransactionMilestone",
            subject_id=str(milestone.id),
            details={"from": previous, "to": state.value},
            commit=False,
        )
        await self._session.flush()
        return milestone

    async def conclude(
        self,
        actor: Actor,
        journey_id: uuid.UUID,
        *,
        state: JourneyState,
        reason: str | None = None,
    ) -> TransactionJourney:
        actor.require_administrator()
        actor.require_writable()
        if actor.member_id is None or state is JourneyState.ACTIVE:
            raise InvalidTransition()
        journey = await self._session.scalar(
            select(TransactionJourney)
            .where(
                TransactionJourney.organization_id == actor.organization_id,
                TransactionJourney.id == journey_id,
            )
            .with_for_update()
        )
        if journey is None:
            raise NotFound()
        if journey.state != JourneyState.ACTIVE.value:
            if journey.state == state.value:
                return journey
            raise InvalidTransition("La Jornada ya fue concluida.")
        moment = _now()
        if state is JourneyState.CANCELLED:
            clean_reason = (reason or "").strip()
            if not clean_reason:
                raise MissingEvidence("Indica por qué se cancela el trámite.")
            journey.state = state.value
            journey.cancellation_reason = clean_reason
            journey.cancelled_at = moment
            sale = await self._session.scalar(
                select(MarketSaleRecord).where(
                    MarketSaleRecord.organization_id == actor.organization_id,
                    MarketSaleRecord.journey_id == journey.id,
                )
            )
            if sale is not None and sale.state != "Completed":
                sale.state = "Cancelled"
                sale.outcome = "Cancelled"
        else:
            incomplete = await self._session.scalar(
                select(TransactionMilestone.id)
                .where(
                    TransactionMilestone.organization_id == actor.organization_id,
                    TransactionMilestone.journey_id == journey.id,
                    TransactionMilestone.state.not_in(
                        [MilestoneState.COMPLETED.value, MilestoneState.SKIPPED.value]
                    ),
                )
                .limit(1)
            )
            if incomplete is not None:
                raise MissingEvidence(
                    "Completa u omite con motivo todos los hitos antes de cerrar la Jornada."
                )
            journey.state = state.value
            journey.completed_by = actor.member_id
            journey.completed_at = moment
        journey.updated_at = moment
        await record_audit(
            self._session,
            organization_id=actor.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action="ConcludeTransactionJourney",
            subject_type="TransactionJourney",
            subject_id=str(journey.id),
            details={"state": state.value, "reason": reason},
            commit=False,
        )
        await self._session.flush()
        return journey

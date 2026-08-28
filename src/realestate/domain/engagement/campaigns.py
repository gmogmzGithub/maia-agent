"""Administrator-planned Development campaigns with bounded execution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.clock import utc_now
from realestate.db.models import (
    CampaignAudienceMember,
    ConsentCategory,
    Development,
    DevelopmentCampaign,
    DevelopmentCampaignStatus,
    FactsReviewState,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotFound,
)
from realestate.domain.engagement.audience import (
    AUDIENCE_RULE_VERSION,
    Audience,
    AudienceMemberView,
)
from realestate.domain.engagement.templates import TemplateRegistry


class CampaignDenied(CommercialError):
    message = "La campaña no cumple las condiciones para activarse."


@dataclass(frozen=True)
class PlanCampaign:
    development_id: uuid.UUID
    name: str
    property_need_ids: tuple[uuid.UUID, ...]
    template_name: str
    template_language: str
    content_preview: str
    exclude_property_need_ids: tuple[uuid.UUID, ...] = ()
    transaction_intents: tuple[str, ...] = ("Buy",)
    service_area_contains: str = ""
    quiet_hours_start: int = 20
    quiet_hours_end: int = 9
    timezone: str = "America/Mexico_City"
    frequency_cap: int = 1
    frequency_window_days: int = 30
    max_recipients: int = 50
    criteria_version: str = AUDIENCE_RULE_VERSION


@dataclass(frozen=True)
class ActivateCampaign:
    campaign_id: uuid.UUID


@dataclass(frozen=True)
class PauseCampaign:
    campaign_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class CancelCampaign:
    campaign_id: uuid.UUID
    reason: str


@dataclass(frozen=True)
class CampaignPlan:
    campaign_id: uuid.UUID
    status: str
    audience: tuple[AudienceMemberView, ...]


class Campaigns:
    """Plan, activate, pause and cancel; never writes Outbox directly."""

    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        *,
        activation_approved: bool = False,
    ) -> None:
        self._session = session
        self._actor = actor
        self._activation_approved = activation_approved

    async def plan(
        self, command: PlanCampaign, *, at: datetime | None = None
    ) -> CampaignPlan:
        self._actor.require_administrator()
        moment = at or utc_now()
        development = await self._session.get(Development, command.development_id)
        if development is None:
            raise NotFound("No encontramos ese desarrollo.")
        self._actor.require_same_organization(development.organization_id)
        if development.facts_review_state != FactsReviewState.APPROVED.value:
            raise CampaignDenied("Los datos del desarrollo todavía no están aprobados.")
        if development.facts.get("marketing_authority_confirmed") is not True:
            raise CampaignDenied(
                "El desarrollo no tiene autoridad de difusión comercial confirmada."
            )
        unique_needs = tuple(dict.fromkeys(command.property_need_ids))
        if not unique_needs:
            raise CampaignDenied("La audiencia debe nombrar necesidades concretas.")
        if len(unique_needs) > 500:
            raise CampaignDenied("La audiencia explícita excede el límite de 500.")
        if command.criteria_version != AUDIENCE_RULE_VERSION:
            raise CampaignDenied("La versión de criterios no es la vigente.")
        if (
            not 0 <= command.quiet_hours_start <= 23
            or not 0 <= command.quiet_hours_end <= 23
        ):
            raise CampaignDenied("Las horas de silencio deben estar entre 0 y 23.")
        if not 0 < command.max_recipients <= 500:
            raise CampaignDenied("El límite de destinatarios debe estar entre 1 y 500.")
        if command.frequency_cap <= 0 or command.frequency_window_days <= 0:
            raise CampaignDenied("El límite de frecuencia debe ser positivo.")
        template = await TemplateRegistry(self._session).approved(
            organization_id=self._actor.organization_id,
            name=command.template_name,
            language=command.template_language,
            category=ConsentCategory.MARKETING,
            at=moment,
        )
        if template is None:
            raise CampaignDenied(
                "Meta no reporta esa plantilla de Marketing como aprobada y vigente."
            )
        if template.body_text.strip() != command.content_preview.strip():
            raise CampaignDenied(
                "El contenido debe coincidir exactamente con la plantilla observada."
            )

        row = DevelopmentCampaign(
            organization_id=self._actor.organization_id,
            development_id=development.id,
            name=command.name.strip() or f"Campaña {development.name}",
            status=DevelopmentCampaignStatus.DRAFT.value,
            criteria_version=command.criteria_version,
            audience_criteria={
                "property_need_ids": [str(value) for value in unique_needs],
                "exclude_property_need_ids": [
                    str(value)
                    for value in dict.fromkeys(command.exclude_property_need_ids)
                ],
                "transaction_intents": list(command.transaction_intents),
                "service_area_contains": command.service_area_contains.strip(),
            },
            exclusions=["suppression", "opt_out", "stale_need", "frequency_cap"],
            template_name=command.template_name,
            template_language=command.template_language,
            content_preview=template.body_text,
            quiet_hours_start=command.quiet_hours_start,
            quiet_hours_end=command.quiet_hours_end,
            timezone=command.timezone,
            frequency_cap=command.frequency_cap,
            frequency_window_days=command.frequency_window_days,
            max_recipients=command.max_recipients,
            created_at=moment,
            updated_at=moment,
        )
        self._session.add(row)
        await self._session.flush()
        audience = await Audience(self._session, self._actor).resolve(
            row.id, moment, persist=True
        )
        await self._audit(
            "PlanDevelopmentCampaign",
            row,
            {
                "criteria_version": row.criteria_version,
                "included": sum(item.status == "Included" for item in audience),
                "excluded": sum(item.status == "Excluded" for item in audience),
                "max_recipients": row.max_recipients,
            },
        )
        return CampaignPlan(row.id, row.status, audience)

    async def preview(
        self, campaign_id: uuid.UUID, *, at: datetime | None = None
    ) -> tuple[AudienceMemberView, ...]:
        self._actor.require_administrator()
        return await Audience(self._session, self._actor).resolve(
            campaign_id, at or utc_now(), persist=False
        )

    async def activate(
        self, command: ActivateCampaign, *, at: datetime | None = None
    ) -> CampaignPlan:
        self._actor.require_administrator()
        moment = at or utc_now()
        if not self._activation_approved:
            raise CampaignDenied(
                "La activación real sigue Denied hasta aprobar los gates legales, "
                "operativos y del proveedor."
            )
        row = await self._locked(command.campaign_id)
        if row.status not in {
            DevelopmentCampaignStatus.DRAFT.value,
            DevelopmentCampaignStatus.PAUSED.value,
        }:
            raise InvalidTransition(
                "Sólo una campaña en borrador o pausada puede activarse."
            )
        template = await TemplateRegistry(self._session).approved(
            organization_id=self._actor.organization_id,
            name=row.template_name,
            language=row.template_language,
            category=ConsentCategory.MARKETING,
            at=moment,
        )
        if (
            template is None
            or template.body_text.strip() != row.content_preview.strip()
        ):
            raise CampaignDenied(
                "La plantilla cambió o dejó de estar aprobada; la campaña sigue detenida."
            )
        previous = {
            member.audience_reference: (member.status, tuple(member.reasons))
            for member in await self._session.scalars(
                select(CampaignAudienceMember).where(
                    CampaignAudienceMember.campaign_id == row.id
                )
            )
        }
        audience = await Audience(self._session, self._actor).resolve(
            row.id, moment, persist=True
        )
        if not any(item.status == "Included" for item in audience):
            raise CampaignDenied("La campaña no tiene destinatarios elegibles.")
        row.status = DevelopmentCampaignStatus.ACTIVE.value
        row.authorized_by = self._actor.member_id
        row.activated_at = moment
        row.paused_at = None
        row.updated_at = moment
        await self._audit(
            "ActivateDevelopmentCampaign",
            row,
            {
                "eligible": sum(item.status == "Included" for item in audience),
                "audience_changes": [
                    {
                        "reference": item.reference,
                        "before_status": previous.get(item.reference, (None, ()))[0],
                        "after_status": item.status,
                        "before_reasons": previous.get(item.reference, (None, ()))[1],
                        "after_reasons": item.reasons,
                    }
                    for item in audience
                    if previous.get(item.reference) != (item.status, item.reasons)
                ],
            },
        )
        await self._session.flush()
        return CampaignPlan(row.id, row.status, audience)

    async def pause(
        self, command: PauseCampaign, *, at: datetime | None = None
    ) -> DevelopmentCampaign:
        self._actor.require_administrator()
        moment = at or utc_now()
        row = await self._locked(command.campaign_id)
        if row.status != DevelopmentCampaignStatus.ACTIVE.value:
            raise InvalidTransition("Sólo una campaña activa puede pausarse.")
        row.status = DevelopmentCampaignStatus.PAUSED.value
        row.paused_at = moment
        row.updated_at = moment
        await self._audit("PauseDevelopmentCampaign", row, {"reason": command.reason})
        await self._session.flush()
        return row

    async def cancel(
        self, command: CancelCampaign, *, at: datetime | None = None
    ) -> DevelopmentCampaign:
        self._actor.require_administrator()
        moment = at or utc_now()
        row = await self._locked(command.campaign_id)
        if row.status == DevelopmentCampaignStatus.CANCELLED.value:
            return row
        row.status = DevelopmentCampaignStatus.CANCELLED.value
        row.cancelled_at = moment
        row.updated_at = moment
        await self._audit("CancelDevelopmentCampaign", row, {"reason": command.reason})
        await self._session.flush()
        return row

    async def _locked(self, campaign_id: uuid.UUID) -> DevelopmentCampaign:
        row = await self._session.scalar(
            select(DevelopmentCampaign)
            .where(DevelopmentCampaign.id == campaign_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa campaña.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def _audit(
        self,
        action: str,
        row: DevelopmentCampaign,
        details: dict[str, object],
    ) -> None:
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action=action,
            subject_type="DevelopmentCampaign",
            subject_id=str(row.id),
            details=details,
            commit=False,
        )

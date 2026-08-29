"""Use-time authority gate for external Listing candidates."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ExternalCandidateState,
    ExternalInventoryScope,
    ExternalListingCandidate,
    ExternalOfferCandidate,
    FactsReviewState,
    ListingAvailability,
    ListingRevalidationRecord,
    OfferAvailability,
    RevalidationOutcome,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.external_inventory.ports import InventorySourceError
from realestate.domain.service_area import SERVICE_AREA
from realestate.domain.external_inventory.types import (
    IntendedAction,
    RevalidationDecision,
)


class ListingRevalidation:
    """The only seam allowed to approve recommend/share/appointment use."""

    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        inventory: ExternalInventory,
    ) -> None:
        self._session = session
        self._actor = actor
        self._inventory = inventory

    async def evaluate(
        self,
        listing_id: uuid.UUID,
        intended_action: IntendedAction,
        at: datetime,
    ) -> RevalidationDecision:
        candidate = await self._session.scalar(
            select(ExternalListingCandidate).where(
                ExternalListingCandidate.id == listing_id,
                ExternalListingCandidate.organization_id
                == self._actor.organization_id,
            )
        )
        if candidate is None:
            raise NotFound("No encontramos ese candidato de inventario externo.")
        refresh_error: InventorySourceError | None = None
        try:
            candidate = await self._inventory.refresh_for_use(
                candidate.source_listing_id, at=at
            )
        except InventorySourceError as exc:
            refresh_error = exc
            candidate = await self._session.scalar(
                select(ExternalListingCandidate)
                .where(
                    ExternalListingCandidate.id == listing_id,
                    ExternalListingCandidate.organization_id
                    == self._actor.organization_id,
                )
                .with_for_update()
            )
            if candidate is None:
                raise NotFound() from exc

        offers = list(
            await self._session.scalars(
                select(ExternalOfferCandidate).where(
                    ExternalOfferCandidate.listing_candidate_id == candidate.id
                )
            )
        )
        denied: list[str] = []
        pending: list[str] = []
        if candidate.withdrawn_at is not None:
            denied.append("la fuente retiró la publicación")
        if candidate.municipality not in SERVICE_AREA:
            denied.append("la publicación está fuera de la zona de servicio")
        if candidate.authority_state == ExternalCandidateState.DENIED.value:
            denied.append("la autoridad de uso está denegada")
        if candidate.collaboration_authorized is False:
            denied.append("la colaboración fue revocada o denegada")

        if refresh_error is not None:
            pending.append(f"no fue posible revalidar la fuente ({refresh_error.code})")
        if candidate.freshness_deadline <= at:
            pending.append("la verificación de la fuente está vencida")
        if "offers" in candidate.changed_fields:
            pending.append("cambió el precio o la oferta y requiere revisión")
        if candidate.authority_state != ExternalCandidateState.AUTHORIZED.value:
            pending.append("la autoridad de uso no está confirmada")
        if not (candidate.authority_evidence or "").strip():
            pending.append("falta evidencia de autoridad")
        if not (candidate.attribution or "").strip():
            pending.append("falta atribución")
        if candidate.title is None:
            pending.append("falta el título de la publicación")
        if candidate.availability != ListingAvailability.AVAILABLE.value:
            pending.append("la disponibilidad no está confirmada")
        active_offers = [
            offer
            for offer in offers
            if offer.availability == OfferAvailability.AVAILABLE.value
            and offer.operation is not None
            and offer.price_amount is not None
            and offer.price_currency is not None
        ]
        if not active_offers:
            pending.append("no hay una oferta completa y disponible")
        if candidate.commercial_review_state != FactsReviewState.APPROVED.value:
            pending.append("los términos comerciales requieren revisión")
        if candidate.source_scope == ExternalInventoryScope.COLLABORATOR.value:
            if candidate.collaboration_authorized is not True:
                pending.append("la colaboración no está confirmada")
            if not candidate.commission_known or candidate.commission is None:
                pending.append("la comisión compartida no es conocida")

        if denied:
            outcome = RevalidationOutcome.DENIED.value
            reasons = tuple(dict.fromkeys(denied + pending))
        elif pending:
            outcome = RevalidationOutcome.PENDING.value
            reasons = tuple(dict.fromkeys(pending))
        else:
            outcome = RevalidationOutcome.ELIGIBLE.value
            reasons = ()
        record = ListingRevalidationRecord(
            organization_id=self._actor.organization_id,
            listing_candidate_id=candidate.id,
            intended_action=intended_action.value,
            outcome=outcome,
            reasons=list(reasons),
            snapshot_checksum=candidate.payload_checksum,
            evaluated_at=at,
        )
        self._session.add(record)
        await record_audit(
            self._session,
            organization_id=self._actor.organization_id,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action="ExternalListingRevalidated",
            subject_type="ExternalListingCandidate",
            subject_id=str(candidate.id),
            details={
                "source": candidate.source,
                "source_listing_id": candidate.source_listing_id,
                "intended_action": intended_action.value,
                "outcome": outcome,
                "reasons": list(reasons),
                "snapshot_checksum": candidate.payload_checksum,
            },
            commit=False,
        )
        await self._session.commit()
        return RevalidationDecision(
            listing_id=candidate.id,
            intended_action=intended_action,
            outcome=outcome,
            reasons=reasons,
            evaluated_at=at,
            snapshot_checksum=candidate.payload_checksum,
        )

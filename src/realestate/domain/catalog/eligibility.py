"""Purpose-specific eligibility and deterministic Presentation Readiness.

Every customer-facing catalog consumer asks this module.  Availability,
publication and authority remain separate inputs so no caller can equate one
with another accidentally (ADR-0030).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CatalogListing,
    FactsReviewState,
    ListingAuthority,
    ListingAvailability,
    ListingMedia,
    ListingOffer,
    ListingPublicationState,
    ListingSourceKind,
    OfferAvailability,
    Property,
    UnitModel,
)
from realestate.domain.commercial.actors import Actor, NotFound


class EligibilityPurpose(str, enum.Enum):
    PUBLISH = "Publish"
    PUBLIC_SHARE = "PublicShare"
    RECOMMEND = "Recommend"
    APPOINTMENT = "Appointment"
    AGENT_DISCLOSURE = "AgentDisclosure"


@dataclass(frozen=True)
class PresentationReadiness:
    ready: bool
    overridden: bool
    reasons: tuple[str, ...]
    tier: str | None


@dataclass(frozen=True)
class EligibilityDecision:
    listing_id: uuid.UUID
    purpose: EligibilityPurpose
    eligible: bool
    reasons: tuple[str, ...]
    readiness: PresentationReadiness


class ListingEligibility:
    """The sole policy seam for using a Listing for a named purpose."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def evaluate(
        self,
        listing_id: uuid.UUID,
        purpose: EligibilityPurpose,
        at: datetime,
    ) -> EligibilityDecision:
        listing = await self._session.get(CatalogListing, listing_id)
        if listing is None:
            raise NotFound()
        self._actor.require_same_organization(listing.organization_id)

        offers = list(
            await self._session.scalars(
                select(ListingOffer).where(ListingOffer.listing_id == listing.id)
            )
        )
        media = list(
            await self._session.scalars(
                select(ListingMedia).where(ListingMedia.listing_id == listing.id)
            )
        )
        readiness = await self._readiness(listing, offers, media)
        reasons: list[str] = []

        if listing.authority != ListingAuthority.AUTHORIZED.value:
            reasons.append("la autoridad de la publicación no está vigente")
        if not (listing.authority_evidence or "").strip():
            reasons.append("falta evidencia de autoridad")
        if listing.availability != ListingAvailability.AVAILABLE.value:
            reasons.append("la publicación no está disponible")
        active = [
            offer
            for offer in offers
            if offer.availability == OfferAvailability.AVAILABLE.value
        ]
        if not active:
            reasons.append("no existe una oferta disponible")
        if any(
            offer.terms_review_state != FactsReviewState.APPROVED.value
            for offer in active
        ):
            reasons.append("hay términos comerciales pendientes de revisión")

        if listing.source_kind == ListingSourceKind.COLLABORATOR.value:
            if listing.freshness_checked_at is None:
                reasons.append("la fuente colaboradora no se ha revalidado")
            if listing.revalidate_by is None or listing.revalidate_by <= at:
                reasons.append("la revalidación de la fuente colaboradora venció")

        if purpose is EligibilityPurpose.PUBLIC_SHARE and (
            listing.publication_state != ListingPublicationState.PUBLISHED.value
        ):
            reasons.append("la publicación no está publicada")
        if purpose in {EligibilityPurpose.PUBLISH, EligibilityPurpose.PUBLIC_SHARE}:
            if not readiness.ready:
                reasons.extend(readiness.reasons)

        # Publication is a transition into Published; every other purpose reads
        # the current state.  Private recommendation and appointment may use an
        # authorized Organization Listing that is deliberately not public.
        return EligibilityDecision(
            listing_id=listing.id,
            purpose=purpose,
            eligible=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
            readiness=readiness,
        )

    async def _readiness(
        self,
        listing: CatalogListing,
        offers: list[ListingOffer],
        media: list[ListingMedia],
    ) -> PresentationReadiness:
        tier = listing.tier_override or listing.automatic_tier
        failures: list[str] = []
        if listing.facts_review_state != FactsReviewState.APPROVED.value:
            failures.append("los datos de la publicación no están aprobados")

        subject_state = await self._subject_review_state(listing)
        if subject_state != FactsReviewState.APPROVED.value:
            failures.append("los datos físicos o del modelo no están aprobados")
        if not offers:
            failures.append("falta al menos una oferta")
        if tier is None:
            failures.append("falta una regla u override de nivel de presentación")

        approved = [
            row
            for row in media
            if row.authority == ListingAuthority.AUTHORIZED.value
            and row.revoked_at is None
        ]
        cover = next((row for row in approved if row.is_cover), None)
        if cover is None:
            failures.append("falta una fotografía de portada autorizada")

        required_count = {"Larevia": 6, "Premium": 12, "SuperPremium": 20}.get(
            tier or "", 0
        )
        if required_count and len(approved) < required_count:
            failures.append(
                f"se requieren {required_count} fotografías autorizadas"
            )
        required_groups = {"Premium": 4, "SuperPremium": 6}.get(tier or "", 0)
        groups = {row.space_group for row in approved if row.space_group}
        if required_groups and len(groups) < required_groups:
            failures.append(f"se requieren {required_groups} grupos fotográficos")
        if tier in {"Premium", "SuperPremium"} and cover is not None:
            if not cover.high_resolution:
                failures.append("la portada debe estar confirmada en alta resolución")

        overridden = bool(listing.readiness_override)
        return PresentationReadiness(
            ready=not failures or overridden,
            overridden=overridden,
            reasons=tuple(failures),
            tier=tier,
        )

    async def _subject_review_state(self, listing: CatalogListing) -> str:
        if listing.property_uuid is not None:
            prop = await self._session.get(Property, listing.property_uuid)
            return prop.facts_review_state if prop is not None else "Missing"
        model = await self._session.get(UnitModel, listing.unit_model_id)
        return model.facts_review_state if model is not None else "Missing"

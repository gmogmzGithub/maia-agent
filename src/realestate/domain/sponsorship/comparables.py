"""Presale comparables that admit when they have nothing to compare.

ADR-0044 groups comparable campaigns by operation, municipality, property type,
Commercial Price Band, Presentation Tier and sponsored surface, and requires the
period, sample size, median and range to be disclosed. The requirement that
matters most is the last one: below the versioned minimum sample the answer is
``Estimación inicial sin historial suficiente`` and there is no number at all.

That refusal is the product's honesty, not a gap in it. A median of one campaign
is that campaign, and presenting it as a comparable to a buyer is a forecast
dressed up as evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    CatalogListing,
    ListingOffer,
    OfferAvailability,
    Property,
    SponsorshipCampaign,
    TrafficClass,
    UnitModel,
)
from realestate.domain.analytics.definitions import Definition
from realestate.domain.analytics.metrics import median
from realestate.domain.commercial.actors import Actor
from realestate.domain.sponsorship.labels import INSUFFICIENT_HISTORY

#: Commercial Price Bands in MXN. An analytics grouping of the Listing's asking
#: price — never a statement about the Contact (CONTEXT.md).
PRICE_BANDS: tuple[tuple[str, Decimal | None], ...] = (
    ("Hasta 2 M", Decimal("2000000")),
    ("2 a 4 M", Decimal("4000000")),
    ("4 a 7 M", Decimal("7000000")),
    ("7 a 12 M", Decimal("12000000")),
    ("Más de 12 M", None),
)


def price_band(amount: Decimal | None) -> str:
    """The band one asking price falls in, or an explicit unknown."""
    if amount is None:
        return "Sin precio registrado"
    for label, ceiling in PRICE_BANDS:
        if ceiling is None or amount <= ceiling:
            return label
    return PRICE_BANDS[-1][0]  # pragma: no cover - the open band ends the loop


@dataclass(frozen=True)
class CohortKey:
    """What makes two campaigns comparable."""

    operation: str
    municipality: str
    property_type: str
    price_band: str
    presentation_tier: str
    surface: str

    @property
    def text(self) -> str:
        return (
            f"{self.operation} · {self.municipality} · {self.property_type} · "
            f"{self.price_band} · {self.presentation_tier} · {self.surface}"
        )


@dataclass(frozen=True)
class Comparable:
    """One cohort's disclosed evidence, or its explicit absence."""

    key: CohortKey
    period_start: datetime
    period_end: datetime
    sample_size: int
    minimum_sample: int
    median_visible_impressions: Decimal | None
    lowest: int | None
    highest: int | None

    @property
    def sufficient(self) -> bool:
        return self.sample_size >= self.minimum_sample

    @property
    def text(self) -> str:
        """The sentence a presale conversation may actually use."""
        if not self.sufficient:
            return INSUFFICIENT_HISTORY
        assert self.median_visible_impressions is not None
        return (
            f"Mediana {int(self.median_visible_impressions)} impresiones "
            f"visibles, rango {self.lowest}–{self.highest}, "
            f"{self.sample_size} campañas comparables"
        )


class SponsorshipComparables:
    """Build one cohort's aggregate evidence from the stored events."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def cohort_key(
        self, campaign: SponsorshipCampaign, surface: str
    ) -> CohortKey:
        listing = await self._session.get(CatalogListing, campaign.listing_id)
        assert listing is not None
        offer = await self._session.scalar(
            select(ListingOffer)
            .where(
                ListingOffer.listing_id == listing.id,
                ListingOffer.availability == OfferAvailability.AVAILABLE.value,
            )
            .order_by(ListingOffer.price_amount)
        )
        return CohortKey(
            operation=offer.operation if offer else "Sin operación",
            municipality=_municipality(listing.public_location),
            property_type=await self._property_type(listing),
            price_band=price_band(offer.price_amount if offer else None),
            presentation_tier=listing.tier_override
            or listing.automatic_tier
            or "Larevia",
            surface=surface,
        )

    async def describe(
        self,
        key: CohortKey,
        definition: Definition,
        *,
        period_start: datetime,
        period_end: datetime,
        exclude_campaign_id: uuid.UUID | None = None,
    ) -> Comparable:
        """The cohort's median and range, with its own campaign excluded.

        Excluding the subject campaign is what makes the comparable a
        *comparison*. Leaving it in would let a strong campaign quote itself as
        evidence that campaigns like it do well.
        """
        campaign_ids = await self._cohort_campaigns(key, exclude_campaign_id)
        if not campaign_ids:
            return Comparable(
                key=key,
                period_start=period_start,
                period_end=period_end,
                sample_size=0,
                minimum_sample=definition.comparable_minimum_sample,
                median_visible_impressions=None,
                lowest=None,
                highest=None,
            )
        rows = await self._session.execute(
            select(
                AnalyticsDomainEvent.campaign_id,
                func.count(AnalyticsDomainEvent.id),
            )
            .where(
                AnalyticsDomainEvent.organization_id == self._actor.organization_id,
                AnalyticsDomainEvent.definition_version == definition.version,
                AnalyticsDomainEvent.campaign_id.in_(campaign_ids),
                AnalyticsDomainEvent.event_name
                == AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value,
                AnalyticsDomainEvent.traffic_class == TrafficClass.VALID.value,
                AnalyticsDomainEvent.surface == key.surface,
                AnalyticsDomainEvent.occurred_at >= period_start,
                AnalyticsDomainEvent.occurred_at < period_end,
            )
            .group_by(AnalyticsDomainEvent.campaign_id)
        )
        counts = [int(count) for _, count in rows]
        if not counts:
            return Comparable(
                key=key,
                period_start=period_start,
                period_end=period_end,
                sample_size=0,
                minimum_sample=definition.comparable_minimum_sample,
                median_visible_impressions=None,
                lowest=None,
                highest=None,
            )
        middle = median([Decimal(value) for value in counts])
        return Comparable(
            key=key,
            period_start=period_start,
            period_end=period_end,
            sample_size=len(counts),
            minimum_sample=definition.comparable_minimum_sample,
            median_visible_impressions=middle,
            lowest=min(counts),
            highest=max(counts),
        )

    async def _property_type(self, listing: CatalogListing) -> str:
        """The physical subject's type, from the Property or the Unit Model.

        A Listing has no type of its own — ADR-0025 keeps physical truth on the
        Property — so the cohort reads it from whichever subject the Listing
        points at, and names the absence rather than guessing.
        """
        if listing.property_uuid is not None:
            physical = await self._session.get(Property, listing.property_uuid)
            return physical.property_type if physical is not None else "Sin tipo"
        if listing.unit_model_id is not None:
            model = await self._session.get(UnitModel, listing.unit_model_id)
            if model is not None:
                return str(model.facts.get("property_type") or "Development")
        return "Sin tipo"

    async def _cohort_campaigns(
        self, key: CohortKey, exclude: uuid.UUID | None
    ) -> list[uuid.UUID]:
        rows = await self._session.execute(
            select(SponsorshipCampaign, CatalogListing)
            .join(CatalogListing, CatalogListing.id == SponsorshipCampaign.listing_id)
            .where(
                SponsorshipCampaign.organization_id == self._actor.organization_id,
            )
        )
        matched: list[uuid.UUID] = []
        for campaign, listing in rows:
            if exclude is not None and campaign.id == exclude:
                continue
            candidate = await self.cohort_key(campaign, key.surface)
            if candidate == key:
                matched.append(campaign.id)
        return matched


def _municipality(public_location: str | None) -> str:
    """The municipality part of a public location, or an explicit unknown.

    Public Location is Administrator-entered text like ``"Zapopan, Jalisco"``, so
    the municipality is the part before the first comma. A blank value becomes a
    named unknown rather than an empty cohort key that would silently merge
    every unlabelled Listing into one comparable group.
    """
    if not public_location or not public_location.strip():
        return "Sin municipio registrado"
    return public_location.split(",", 1)[0].strip()

"""Deterministic Listing presentation policy (ADR-0039).

The thresholds are the accepted initial product policy, still labelled for
six-month review and Santiago validation.  They never estimate value, convert
currency, or infer anything about a Contact.

This module is the only writer of ``CatalogListing.automatic_tier``, so the
tier and the ``presentation_policy_version`` that decided it are always stamped
together.  An earlier shape recalculated the tier in two catalog modules and
only one of them recorded the version, which left the audit trail partial for
exactly the rows a policy review would want to re-examine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CatalogListing,
    CatalogPresentationTier,
    ListingOffer,
    OfferAvailability,
    Property,
    UnitModel,
)
from realestate.domain.clock import utc_now

PRESENTATION_POLICY_VERSION = "initial-2026-08-pending-san-058"

#: Property types whose presentation rules are validated. Land and Development
#: remain open (SAN-057/058), so Product returns no automatic tier for them
#: rather than applying house thresholds.
_RATED_TYPES = frozenset({"House", "Apartment"})


@dataclass(frozen=True)
class OfferPresentation:
    operation: str
    price: Decimal
    currency: str


_TIER_ORDER = {
    CatalogPresentationTier.LAREVIA: 0,
    CatalogPresentationTier.PREMIUM: 1,
    CatalogPresentationTier.SUPER_PREMIUM: 2,
}

#: MXN thresholds per operation: above the first is SuperPremium, at or above
#: the second is Premium. Only MXN has thresholds; a USD amount is Premium by
#: currency alone, which is why the numbers live in one table rather than in a
#: branch per operation.
_MXN_THRESHOLDS = {
    "Sale": (Decimal("20000000"), Decimal("12000000")),
    "Presale": (Decimal("20000000"), Decimal("12000000")),
    "Rental": (Decimal("85000"), Decimal("50000")),
}

#: The tier an Offer reaches on its currency alone, before any threshold.
_CURRENCY_FLOOR = {
    "USD": CatalogPresentationTier.PREMIUM,
    "MXN": CatalogPresentationTier.LAREVIA,
}


def _offer_tier(offer: OfferPresentation) -> CatalogPresentationTier | None:
    floor = _CURRENCY_FLOOR.get(offer.currency)
    thresholds = _MXN_THRESHOLDS.get(offer.operation)
    if floor is None or thresholds is None:
        return None
    if offer.currency != "MXN":
        return floor
    super_premium, premium = thresholds
    if offer.price > super_premium:
        return CatalogPresentationTier.SUPER_PREMIUM
    if offer.price >= premium:
        return CatalogPresentationTier.PREMIUM
    return floor


def automatic_presentation_tier(
    property_type: str, offers: list[OfferPresentation]
) -> CatalogPresentationTier | None:
    """Return the highest tier contributed by active Offers."""
    if property_type not in _RATED_TYPES:
        return None
    tiers = [tier for offer in offers if (tier := _offer_tier(offer)) is not None]
    return max(tiers, key=_TIER_ORDER.__getitem__) if tiers else None


async def recalculate_automatic_tier(
    session: AsyncSession,
    listing: CatalogListing,
    *,
    offers: Iterable[ListingOffer] | None = None,
) -> None:
    """Restamp this Listing's automatic tier and the policy version behind it.

    ``offers`` is the Listing's offers when the caller already holds them —
    a cascade that has just locked every offer for a Property should not
    re-read them once per Listing.
    """
    if offers is None:
        offers = await session.scalars(
            select(ListingOffer).where(ListingOffer.listing_id == listing.id)
        )
    active = [
        row
        for row in offers
        if row.listing_id == listing.id
        and row.availability == OfferAvailability.AVAILABLE.value
    ]
    tier = automatic_presentation_tier(
        await _property_type(session, listing),
        [
            OfferPresentation(row.operation, row.price_amount, row.price_currency)
            for row in active
        ],
    )
    listing.automatic_tier = tier.value if tier is not None else None
    listing.presentation_policy_version = PRESENTATION_POLICY_VERSION
    listing.updated_at = utc_now()


async def _property_type(session: AsyncSession, listing: CatalogListing) -> str:
    if listing.property_uuid is not None:
        prop = await session.get(Property, listing.property_uuid)
        return prop.property_type if prop is not None else "Other"
    model = await session.get(UnitModel, listing.unit_model_id)
    return str(model.facts.get("property_type", "Other")) if model else "Other"

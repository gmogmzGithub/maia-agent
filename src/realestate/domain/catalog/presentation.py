"""Deterministic Listing presentation policy (ADR-0039).

The thresholds are the accepted initial product policy, still labelled for
six-month review and Santiago validation.  They never estimate value, convert
currency, or infer anything about a Contact.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal


class PresentationTier(str, enum.Enum):
    LAREVIA = "Larevia"
    PREMIUM = "Premium"
    SUPER_PREMIUM = "SuperPremium"


@dataclass(frozen=True)
class OfferPresentation:
    operation: str
    price: Decimal
    currency: str


_TIER_ORDER = {
    PresentationTier.LAREVIA: 0,
    PresentationTier.PREMIUM: 1,
    PresentationTier.SUPER_PREMIUM: 2,
}


def _offer_tier(offer: OfferPresentation) -> PresentationTier | None:
    if offer.currency == "USD":
        minimum = PresentationTier.PREMIUM
    elif offer.currency == "MXN":
        minimum = PresentationTier.LAREVIA
    else:
        return None

    if offer.operation in {"Sale", "Presale"}:
        if offer.currency == "MXN" and offer.price > Decimal("20000000"):
            return PresentationTier.SUPER_PREMIUM
        if offer.currency == "MXN" and offer.price >= Decimal("12000000"):
            return PresentationTier.PREMIUM
        return minimum
    if offer.operation == "Rental":
        if offer.currency == "MXN" and offer.price > Decimal("85000"):
            return PresentationTier.SUPER_PREMIUM
        if offer.currency == "MXN" and offer.price >= Decimal("50000"):
            return PresentationTier.PREMIUM
        return minimum
    return None


def automatic_presentation_tier(
    property_type: str, offers: list[OfferPresentation]
) -> PresentationTier | None:
    """Return the highest tier contributed by active Offers.

    Land and Development presentation rules remain unvalidated (SAN-057/058),
    so Product returns no automatic tier instead of applying house thresholds.
    """
    if property_type not in {"House", "Apartment"}:
        return None
    tiers = [tier for offer in offers if (tier := _offer_tier(offer)) is not None]
    return max(tiers, key=_TIER_ORDER.__getitem__) if tiers else None

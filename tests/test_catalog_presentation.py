"""Presentation rules through the catalog's public calculation seam."""

from decimal import Decimal

from realestate.db.models import CatalogPresentationTier
from realestate.domain.catalog.presentation import (
    OfferPresentation,
    automatic_presentation_tier,
)


def test_sale_tier_has_exact_mxn_boundaries() -> None:
    assert automatic_presentation_tier(
        "House", [OfferPresentation("Sale", Decimal("11999999.99"), "MXN")]
    ) is CatalogPresentationTier.LAREVIA
    assert automatic_presentation_tier(
        "House", [OfferPresentation("Sale", Decimal("12000000"), "MXN")]
    ) is CatalogPresentationTier.PREMIUM
    assert automatic_presentation_tier(
        "House", [OfferPresentation("Sale", Decimal("20000000"), "MXN")]
    ) is CatalogPresentationTier.PREMIUM
    assert automatic_presentation_tier(
        "House", [OfferPresentation("Sale", Decimal("20000000.01"), "MXN")]
    ) is CatalogPresentationTier.SUPER_PREMIUM


def test_rental_tier_has_exact_mxn_boundaries() -> None:
    assert automatic_presentation_tier(
        "Apartment", [OfferPresentation("Rental", Decimal("49999.99"), "MXN")]
    ) is CatalogPresentationTier.LAREVIA
    assert automatic_presentation_tier(
        "Apartment", [OfferPresentation("Rental", Decimal("50000"), "MXN")]
    ) is CatalogPresentationTier.PREMIUM
    assert automatic_presentation_tier(
        "Apartment", [OfferPresentation("Rental", Decimal("85000"), "MXN")]
    ) is CatalogPresentationTier.PREMIUM
    assert automatic_presentation_tier(
        "Apartment", [OfferPresentation("Rental", Decimal("85000.01"), "MXN")]
    ) is CatalogPresentationTier.SUPER_PREMIUM


def test_usd_is_at_least_premium_and_the_highest_offer_wins() -> None:
    assert automatic_presentation_tier(
        "House", [OfferPresentation("Sale", Decimal("1"), "USD")]
    ) is CatalogPresentationTier.PREMIUM
    assert automatic_presentation_tier(
        "House",
        [
            OfferPresentation("Rental", Decimal("5000"), "USD"),
            OfferPresentation("Sale", Decimal("25000000"), "MXN"),
        ],
    ) is CatalogPresentationTier.SUPER_PREMIUM


def test_unvalidated_property_types_have_no_automatic_tier() -> None:
    assert automatic_presentation_tier(
        "Land", [OfferPresentation("Sale", Decimal("25000000"), "MXN")]
    ) is None

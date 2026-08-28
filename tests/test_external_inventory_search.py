"""Pure match-contract branches for organization-first inventory search."""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest

from realestate.domain.catalog.projection import AuthorizedListing, AuthorizedOffer
from realestate.domain.external_inventory.search import _own_match
from realestate.domain.external_inventory.types import InventorySearchCriteria, MatchQuality


def _listing() -> AuthorizedListing:
    return AuthorizedListing(
        listing_id=uuid.uuid4(),
        listing_key="own-1",
        property_uuid=uuid.uuid4(),
        unit_model_id=None,
        physical_key="property-1",
        physical_name="Casa propia",
        property_type="House",
        source_kind="Organization",
        source_name="Larevia",
        attribution="Fuente: Larevia",
        provenance={"kind": "Test"},
        title="Casa propia",
        public_location="Zapopan, Jalisco",
        physical_facts={"bedrooms": 3},
        listing_facts={},
        availability="Available",
        publication_state="Published",
        authority="Authorized",
        freshness_checked_at=None,
        revalidate_by=None,
        presentation_tier="Larevia",
        readiness_overridden=False,
        gallery_path="/gallery",
        technical_sheet_path="/sheet",
        offers=(
            AuthorizedOffer(
                offer_id=uuid.uuid4(),
                operation="Sale",
                price_amount=Decimal("5000000"),
                price_currency="MXN",
                price_visibility="Visible",
                consultation_copy=None,
                terms={},
                availability="Available",
            ),
        ),
        media=(),
    )


@pytest.mark.parametrize(
    ("listing", "criteria", "expected"),
    [
        (_listing(), InventorySearchCriteria(municipality="Guadalajara"), None),
        (
            replace(_listing(), property_type=""),
            InventorySearchCriteria(municipality="Zapopan", property_type="House"),
            MatchQuality.APPROXIMATE,
        ),
        (
            _listing(),
            InventorySearchCriteria(municipality="Zapopan", property_type="Apartment"),
            None,
        ),
        (
            _listing(),
            InventorySearchCriteria(municipality="Zapopan", operation="Rental"),
            None,
        ),
        (
            _listing(),
            InventorySearchCriteria(
                municipality="Zapopan", operation="Sale", min_price=Decimal("4000000")
            ),
            MatchQuality.EXACT,
        ),
        (
            replace(
                _listing(),
                offers=(replace(_listing().offers[0], price_amount=None),),
            ),
            InventorySearchCriteria(
                municipality="Zapopan", min_price=Decimal("4000000")
            ),
            MatchQuality.APPROXIMATE,
        ),
        (
            _listing(),
            InventorySearchCriteria(
                municipality="Zapopan", max_price=Decimal("4000000")
            ),
            None,
        ),
        (
            replace(_listing(), physical_facts={}),
            InventorySearchCriteria(municipality="Zapopan", min_bedrooms=2),
            MatchQuality.APPROXIMATE,
        ),
        (
            _listing(),
            InventorySearchCriteria(municipality="Zapopan", min_bedrooms=4),
            None,
        ),
    ],
)
def test_organization_match_is_exact_approximate_or_excluded(
    listing: AuthorizedListing,
    criteria: InventorySearchCriteria,
    expected: MatchQuality | None,
) -> None:
    assert _own_match(listing, criteria) == expected

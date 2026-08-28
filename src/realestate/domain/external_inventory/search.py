"""Organization-first authorized inventory search for Maia and operators."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import ListingSourceKind
from realestate.domain.catalog.eligibility import EligibilityPurpose
from realestate.domain.catalog.projection import AuthorizedListing, CatalogProjection
from realestate.domain.commercial.actors import Actor
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.external_inventory.types import (
    CandidateOfferView,
    InventorySearchCriteria,
    InventorySearchHit,
    MatchQuality,
)


class AuthorizedInventorySearch:
    """Return Organization Listings first; external candidates are fallback only."""

    def __init__(
        self,
        session: AsyncSession,
        actor: Actor,
        external: ExternalInventory,
    ) -> None:
        self._catalog = CatalogProjection(session, actor)
        self._external = external

    async def search(
        self, criteria: InventorySearchCriteria, *, at: datetime
    ) -> tuple[InventorySearchHit, ...]:
        own: list[InventorySearchHit] = []
        for listing in await self._catalog.list_authorized(
            EligibilityPurpose.RECOMMEND, at
        ):
            if listing.source_kind != ListingSourceKind.ORGANIZATION.value:
                continue
            quality = _own_match(listing, criteria)
            if quality is None:
                continue
            own.append(
                InventorySearchHit(
                    listing_id=listing.listing_id,
                    source_kind=listing.source_kind,
                    source_name=listing.source_name,
                    source_listing_id=None,
                    title=listing.title,
                    municipality=criteria.municipality,
                    public_location=listing.public_location,
                    match_quality=quality,
                    attribution=listing.attribution,
                    provenance=listing.provenance,
                    offers=tuple(
                        CandidateOfferView(
                            source_offer_key=str(offer.offer_id),
                            operation=offer.operation,
                            price_amount=offer.price_amount,
                            price_currency=offer.price_currency,
                            price_unit=None,
                            availability=offer.availability,
                            terms=offer.terms,
                        )
                        for offer in listing.offers
                    ),
                    requires_use_time_revalidation=False,
                )
            )
            if len(own) >= criteria.limit:
                break
        if own:
            return tuple(own)

        external = await self._external.search(replace(criteria, at=at))
        return tuple(
            InventorySearchHit(
                listing_id=row.listing_id,
                source_kind=row.source_scope,
                source_name=row.source,
                source_listing_id=row.source_listing_id,
                title=row.title,
                municipality=row.municipality,
                public_location=row.public_location,
                match_quality=row.match_quality,
                attribution=row.attribution or "",
                provenance=row.provenance,
                offers=row.offers,
                requires_use_time_revalidation=True,
            )
            for row in external
        )


def _own_match(
    listing: AuthorizedListing, criteria: InventorySearchCriteria
) -> MatchQuality | None:
    location = listing.public_location or ""
    tokens = {part.strip().casefold() for part in location.split(",")}
    if criteria.municipality.casefold() not in tokens:
        return None
    approximate = False
    if criteria.property_type:
        if not listing.property_type:
            approximate = True
        elif listing.property_type.casefold() != criteria.property_type.casefold():
            return None
    relevant = list(listing.offers)
    if criteria.operation:
        matches = [offer for offer in relevant if offer.operation == criteria.operation]
        if not matches:
            return None
        relevant = matches
    if criteria.min_price is not None or criteria.max_price is not None:
        prices = [offer.price_amount for offer in relevant if offer.price_amount is not None]
        if not prices:
            approximate = True
        elif not any(_in_range(price, criteria) for price in prices):
            return None
    if criteria.min_bedrooms is not None:
        value = listing.listing_facts.get(
            "bedrooms", listing.physical_facts.get("bedrooms")
        )
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            approximate = True
        elif value < criteria.min_bedrooms:
            return None
    return MatchQuality.APPROXIMATE if approximate else MatchQuality.EXACT


def _in_range(price: Decimal, criteria: InventorySearchCriteria) -> bool:
    if criteria.min_price is not None and price < criteria.min_price:
        return False
    return criteria.max_price is None or price <= criteria.max_price

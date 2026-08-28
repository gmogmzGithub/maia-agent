"""Explicit, shareable search over the authorized Product catalog (ADR-0042)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import ListingOffer, OfferAvailability
from realestate.domain.catalog.eligibility import EligibilityPurpose
from realestate.domain.catalog.projection import AuthorizedListing, CatalogProjection
from realestate.domain.commercial.actors import Actor
from realestate.domain.service_area import SERVICE_AREA

ALLOWED_OPERATIONS = frozenset({"Sale", "Rental", "Presale"})
ALLOWED_SORTS = frozenset({"relevance", "recent", "price_asc", "price_desc"})


@dataclass(frozen=True)
class SearchQuery:
    operation: str | None = None
    zone: str | None = None
    property_type: str | None = None
    minimum_price: Decimal | None = None
    maximum_price: Decimal | None = None
    sort: str = "relevance"
    page: int = 1
    page_size: int = 12

    def normalized(self) -> SearchQuery:
        operation = (self.operation or "").strip() or None
        zone = (self.zone or "").strip() or None
        property_type = (self.property_type or "").strip() or None
        if operation is not None and operation not in ALLOWED_OPERATIONS:
            raise ValueError("La operación no es válida.")
        if zone is not None and zone not in SERVICE_AREA:
            raise ValueError("La zona está fuera del área de servicio.")
        if self.sort not in ALLOWED_SORTS:
            raise ValueError("El orden no es válido.")
        if self.minimum_price is not None and self.minimum_price < 0:
            raise ValueError("El precio mínimo no puede ser negativo.")
        if self.maximum_price is not None and self.maximum_price < 0:
            raise ValueError("El precio máximo no puede ser negativo.")
        if (
            self.minimum_price is not None
            and self.maximum_price is not None
            and self.minimum_price > self.maximum_price
        ):
            raise ValueError("El precio mínimo no puede superar el máximo.")
        return SearchQuery(
            operation=operation,
            zone=zone,
            property_type=property_type,
            minimum_price=self.minimum_price,
            maximum_price=self.maximum_price,
            sort=self.sort,
            page=max(1, self.page),
            page_size=min(24, max(1, self.page_size)),
        )


@dataclass(frozen=True)
class PublicOfferView:
    offer_id: uuid.UUID
    operation: str
    price_amount: Decimal | None
    price_currency: str
    price_visibility: str
    consultation_copy: str | None
    terms: dict[str, Any]


@dataclass(frozen=True)
class PublicMediaView:
    media_id: uuid.UUID
    url: str
    is_cover: bool
    sort_order: int
    space_group: str | None


@dataclass(frozen=True)
class PublicListingView:
    listing_id: uuid.UUID
    slug: str
    property_id: uuid.UUID | None
    title: str
    physical_name: str
    public_location: str | None
    property_type: str
    physical_facts: dict[str, Any]
    listing_facts: dict[str, Any]
    source_kind: str
    source_name: str
    attribution: str
    presentation_tier: str
    gallery_url: str
    technical_sheet_url: str
    offers: tuple[PublicOfferView, ...]
    media: tuple[PublicMediaView, ...]
    updated_at: datetime | None

    @property
    def cover(self) -> PublicMediaView | None:
        return next((item for item in self.media if item.is_cover), None)


@dataclass(frozen=True)
class SearchResult:
    query: SearchQuery
    listings: tuple[PublicListingView, ...]
    total: int
    has_more: bool


def listing_view(listing: AuthorizedListing) -> PublicListingView:
    return PublicListingView(
        listing_id=listing.listing_id,
        slug=listing.listing_key,
        property_id=listing.property_uuid,
        title=listing.title,
        physical_name=listing.physical_name,
        public_location=listing.public_location,
        property_type=listing.property_type,
        physical_facts=dict(listing.physical_facts),
        listing_facts=dict(listing.listing_facts),
        source_kind=listing.source_kind,
        source_name=listing.source_name,
        attribution=listing.attribution,
        presentation_tier=listing.presentation_tier or "Larevia",
        gallery_url=f"/propiedades/{listing.listing_key}/galeria",
        technical_sheet_url=f"/propiedades/{listing.listing_key}",
        offers=tuple(
            PublicOfferView(
                offer_id=offer.offer_id,
                operation=offer.operation,
                price_amount=offer.price_amount,
                price_currency=offer.price_currency,
                price_visibility=offer.price_visibility,
                consultation_copy=offer.consultation_copy,
                terms=dict(offer.terms),
            )
            for offer in listing.offers
        ),
        media=tuple(
            PublicMediaView(
                media_id=item.media_id,
                url=f"/media/{item.media_id}",
                is_cover=item.is_cover,
                sort_order=item.sort_order,
                space_group=item.space_group,
            )
            for item in listing.media
        ),
        updated_at=listing.freshness_checked_at,
    )


class PublicCatalog:
    """A deep module for eligibility, hidden-price filtering and deduplication."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def search(self, query: SearchQuery, *, at: datetime) -> SearchResult:
        criteria = query.normalized()
        authorized = list(
            await CatalogProjection(self._session, self._actor).list_authorized(
                EligibilityPurpose.PUBLIC_SHARE, at
            )
        )
        offer_prices = await self._offer_prices([item.listing_id for item in authorized])
        filtered = [
            item
            for item in authorized
            if self._matches(item, criteria, offer_prices.get(item.listing_id, ()))
        ]
        deduplicated = self._deduplicate(filtered)
        ordered = self._order(deduplicated, criteria, offer_prices)
        start = (criteria.page - 1) * criteria.page_size
        end = start + criteria.page_size
        return SearchResult(
            query=criteria,
            listings=tuple(listing_view(item) for item in ordered[start:end]),
            total=len(ordered),
            has_more=end < len(ordered),
        )

    async def _offer_prices(
        self, listing_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[tuple[str, Decimal], ...]]:
        if not listing_ids:
            return {}
        result: dict[uuid.UUID, list[tuple[str, Decimal]]] = {}
        rows = await self._session.scalars(
            select(ListingOffer).where(
                ListingOffer.listing_id.in_(listing_ids),
                ListingOffer.availability == OfferAvailability.AVAILABLE.value,
            )
        )
        for row in rows:
            result.setdefault(row.listing_id, []).append((row.operation, row.price_amount))
        return {key: tuple(value) for key, value in result.items()}

    @staticmethod
    def _matches(
        listing: AuthorizedListing,
        query: SearchQuery,
        prices: tuple[tuple[str, Decimal], ...],
    ) -> bool:
        selected = tuple(price for operation, price in prices if query.operation in (None, operation))
        if query.operation is not None and not selected:
            return False
        if query.zone is not None and query.zone.casefold() not in (
            listing.public_location or ""
        ).casefold():
            return False
        if query.property_type is not None and (
            listing.property_type.casefold() != query.property_type.casefold()
        ):
            return False
        relevant_prices = selected or tuple(price for _, price in prices)
        if query.minimum_price is not None and not any(
            price >= query.minimum_price for price in relevant_prices
        ):
            return False
        if query.maximum_price is not None and not any(
            price <= query.maximum_price for price in relevant_prices
        ):
            return False
        return True

    @staticmethod
    def _deduplicate(listings: list[AuthorizedListing]) -> list[AuthorizedListing]:
        by_physical: dict[str, AuthorizedListing] = {}
        for listing in listings:
            key = str(listing.property_uuid or listing.unit_model_id or listing.listing_id)
            current = by_physical.get(key)
            if current is None or (
                current.source_kind != "Organization"
                and listing.source_kind == "Organization"
            ):
                by_physical[key] = listing
        return list(by_physical.values())

    @staticmethod
    def _order(
        listings: list[AuthorizedListing],
        query: SearchQuery,
        prices: dict[uuid.UUID, tuple[tuple[str, Decimal], ...]],
    ) -> list[AuthorizedListing]:
        def price(item: AuthorizedListing) -> Decimal:
            values = [
                amount
                for operation, amount in prices.get(item.listing_id, ())
                if query.operation in (None, operation)
            ]
            return min(values) if values else Decimal("Infinity")

        if query.sort == "price_asc":
            return sorted(listings, key=lambda item: (price(item), item.listing_key))
        if query.sort == "price_desc":
            return sorted(listings, key=lambda item: (price(item), item.listing_key), reverse=True)
        if query.sort == "recent":
            return sorted(
                listings,
                key=lambda item: (
                    item.freshness_checked_at or datetime.min.replace(tzinfo=UTC),
                    item.listing_key,
                ),
                reverse=True,
            )
        return sorted(
            listings,
            key=lambda item: (
                0 if item.source_kind == "Organization" else 1,
                -(item.freshness_checked_at.timestamp() if item.freshness_checked_at else 0),
                item.listing_key,
            ),
        )

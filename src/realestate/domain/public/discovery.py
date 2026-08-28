"""Coherent visible, canonical and machine-readable publication projection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.commercial.actors import Actor
from realestate.domain.public.listing import PublicListing


@dataclass(frozen=True)
class DiscoveryProjection:
    status_code: int
    canonical_path: str
    indexable: bool
    title: str
    description: str
    structured_data: dict[str, Any] | None
    primary_image_path: str | None


class DiscoveryPublication:
    """Project one Listing without a second SEO or assistant-search catalog."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._listings = PublicListing(session, actor)

    async def project(
        self, listing_id: uuid.UUID, *, at: datetime
    ) -> DiscoveryProjection:
        result = await self._listings.read_by_id(listing_id, at=at)
        canonical = f"/propiedades/{result.slug}"
        if result.listing is None:
            return DiscoveryProjection(
                status_code=result.status_code,
                canonical_path=canonical,
                indexable=False,
                title="Propiedad no disponible · Larevia",
                description="Esta publicación ya no está disponible en Larevia.",
                structured_data=None,
                primary_image_path=None,
            )
        listing = result.listing
        offers = [self._offer_schema(offer) for offer in listing.offers]
        images = [item.url for item in listing.media]
        data: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "RealEstateListing",
            "name": listing.title,
            "url": canonical,
            "image": images,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": listing.public_location or "Área Metropolitana de Guadalajara",
                "addressCountry": "MX",
            },
            "offers": offers,
        }
        return DiscoveryProjection(
            status_code=200,
            canonical_path=canonical,
            indexable=True,
            title=f"{listing.title} · Larevia",
            description=self._description(listing.title, listing.public_location),
            structured_data=data,
            primary_image_path=listing.cover.url if listing.cover else None,
        )

    @staticmethod
    def _offer_schema(offer: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "@type": "Offer",
            "availability": "https://schema.org/InStock",
        }
        if isinstance(offer.price_amount, Decimal):
            data["price"] = str(offer.price_amount)
            data["priceCurrency"] = offer.price_currency
        return data

    @staticmethod
    def _description(title: str, location: str | None) -> str:
        where = f" en {location}" if location else ""
        return f"Consulta la ficha autorizada de {title}{where} y conversa con Maia."

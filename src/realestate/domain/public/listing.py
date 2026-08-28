"""One honest public Listing read, including withdrawal semantics."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import CatalogListing, ListingMedia, ListingPublicationState
from realestate.domain.catalog.eligibility import EligibilityPurpose
from realestate.domain.catalog.projection import (
    AuthorizedListingQuery,
    CatalogProjection,
    ListingNotEligible,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.public.catalog import PublicListingView, listing_view


@dataclass(frozen=True)
class PublicListingResult:
    status_code: int
    listing: PublicListingView | None
    slug: str
    indexable: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class PublicMediaResult:
    storage_key: str
    content_type: str
    checksum: str


class PublicListing:
    """The single Listing visibility seam for pages, media, saves and handoff."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def read(self, slug: str, *, at: datetime) -> PublicListingResult:
        key = slug.strip()
        row = await self._session.scalar(
            select(CatalogListing).where(
                CatalogListing.organization_id == self._actor.organization_id,
                CatalogListing.listing_key == key,
            )
        )
        if row is None:
            raise NotFound("No encontramos esa propiedad.")
        try:
            authorized = await CatalogProjection(
                self._session, self._actor
            ).get_authorized_listing(
                AuthorizedListingQuery(
                    purpose=EligibilityPurpose.PUBLIC_SHARE,
                    at=at,
                    listing_id=row.id,
                )
            )
        except ListingNotEligible as exc:
            # Drafts have never been public. Revealing even their title would
            # turn an administrative work-in-progress into a public catalog.
            if row.publication_state == ListingPublicationState.DRAFT.value:
                raise NotFound("No encontramos esa propiedad.") from exc
            return PublicListingResult(
                status_code=410,
                listing=None,
                slug=key,
                indexable=False,
                unavailable_reason="Esta propiedad ya no está disponible.",
            )
        return PublicListingResult(
            status_code=200,
            listing=listing_view(authorized),
            slug=key,
            indexable=True,
        )

    async def read_by_id(
        self, listing_id: uuid.UUID, *, at: datetime
    ) -> PublicListingResult:
        row = await self._session.get(CatalogListing, listing_id)
        if row is None or row.organization_id != self._actor.organization_id:
            raise NotFound("No encontramos esa propiedad.")
        return await self.read(row.listing_key, at=at)

    async def media(
        self, media_id: uuid.UUID, *, at: datetime
    ) -> PublicMediaResult:
        row = await self._session.get(ListingMedia, media_id)
        if row is None or row.organization_id != self._actor.organization_id:
            raise NotFound("No encontramos esa fotografía.")
        publication = await self.read_by_id(row.listing_id, at=at)
        if publication.listing is None or not any(
            item.media_id == media_id for item in publication.listing.media
        ):
            raise NotFound("No encontramos esa fotografía.")
        return PublicMediaResult(row.storage_key, row.content_type, row.checksum)

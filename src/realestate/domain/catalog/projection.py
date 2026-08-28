"""Authorized catalog read model for Maia, public-site and future adapters."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CatalogListing,
    ListingAuthority,
    ListingMedia,
    ListingOffer,
    ListingSourceKind,
    OfferAvailability,
    Property,
    PropertyExpert,
    PublicPriceVisibility,
    UnitModel,
)
from realestate.domain.catalog.eligibility import (
    EligibilityDecision,
    EligibilityPurpose,
    ListingEligibility,
)
from realestate.domain.commercial.actors import Actor, CommercialError, NotFound


class ListingNotEligible(CommercialError):
    def __init__(self, decision: EligibilityDecision) -> None:
        self.decision = decision
        detail = "; ".join(decision.reasons)
        super().__init__(f"La publicación no es elegible para esta acción: {detail}.")


@dataclass(frozen=True)
class AuthorizedListingQuery:
    purpose: EligibilityPurpose
    at: datetime
    listing_id: uuid.UUID | None = None
    listing_key: str | None = None
    property_uuid: uuid.UUID | None = None


@dataclass(frozen=True)
class AuthorizedOffer:
    offer_id: uuid.UUID
    operation: str
    price_amount: Decimal | None
    price_currency: str
    price_visibility: str
    consultation_copy: str | None
    terms: dict[str, Any]
    availability: str


@dataclass(frozen=True)
class AuthorizedMedia:
    media_id: uuid.UUID
    is_cover: bool
    sort_order: int
    space_group: str | None


@dataclass(frozen=True)
class AuthorizedListing:
    listing_id: uuid.UUID
    listing_key: str
    property_uuid: uuid.UUID | None
    unit_model_id: uuid.UUID | None
    physical_key: str
    physical_name: str
    source_kind: str
    source_name: str
    attribution: str
    provenance: dict[str, Any]
    title: str
    public_location: str | None
    physical_facts: dict[str, Any]
    listing_facts: dict[str, Any]
    availability: str
    publication_state: str
    authority: str
    freshness_checked_at: datetime | None
    revalidate_by: datetime | None
    presentation_tier: str | None
    readiness_overridden: bool
    gallery_path: str
    technical_sheet_path: str
    offers: tuple[AuthorizedOffer, ...]
    media: tuple[AuthorizedMedia, ...]


@dataclass(frozen=True)
class AdministrationOffer:
    offer_id: uuid.UUID
    operation: str
    price_amount: Decimal
    price_currency: str
    price_visibility: str
    terms_review_state: str
    availability: str


@dataclass(frozen=True)
class AdministrationMedia:
    media_id: uuid.UUID
    original_filename: str
    authority: str
    is_cover: bool
    sort_order: int
    space_group: str | None
    high_resolution: bool
    revoked_at: datetime | None
    cleanup_complete: bool


@dataclass(frozen=True)
class AdministrationListing:
    listing_id: uuid.UUID
    listing_key: str
    property_uuid: uuid.UUID | None
    unit_model_id: uuid.UUID | None
    physical_name: str
    physical_key: str
    title: str
    source_kind: str
    source_name: str
    attribution: str
    provenance: dict[str, Any]
    physical_facts: dict[str, Any]
    physical_facts_review_state: str
    listing_facts: dict[str, Any]
    listing_facts_review_state: str
    availability: str
    publication_state: str
    authority: str
    authority_evidence: str | None
    freshness_checked_at: datetime | None
    revalidate_by: datetime | None
    presentation_tier: str | None
    automatic_tier: str | None
    tier_override: str | None
    readiness_ready: bool
    readiness_overridden: bool
    action_reasons: tuple[str, ...]
    gallery_path: str
    technical_sheet_path: str
    offers: tuple[AdministrationOffer, ...]
    media: tuple[AdministrationMedia, ...]


class CatalogProjection:
    """Return only a purpose-authorized Listing, never a raw catalog row."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor
        self._eligibility = ListingEligibility(session, actor)

    async def get_authorized_listing(
        self, query: AuthorizedListingQuery
    ) -> AuthorizedListing:
        candidates = await self._candidates(query)
        if not candidates:
            raise NotFound("No encontramos una publicación autorizada.")
        last_refusal: EligibilityDecision | None = None
        for listing in candidates:
            decision = await self._eligibility.evaluate(
                listing.id, query.purpose, query.at
            )
            if decision.eligible:
                return await self._project(listing, query.purpose, decision)
            last_refusal = decision
            # An explicit source Listing must never silently fall through to a
            # different source publication.
            if query.listing_id is not None or query.listing_key is not None:
                break
        assert last_refusal is not None
        raise ListingNotEligible(last_refusal)

    async def list_authorized(
        self, purpose: EligibilityPurpose, at: datetime
    ) -> tuple[AuthorizedListing, ...]:
        """All eligible Listings for a customer-facing catalog use.

        Each row still travels through ``get_authorized_listing`` with its
        explicit source identity. A failed row is omitted; it can never cause a
        caller to substitute another source publication silently.
        """
        listing_ids = tuple(
            await self._session.scalars(
                select(CatalogListing.id)
                .where(CatalogListing.organization_id == self._actor.organization_id)
                .order_by(CatalogListing.listing_key)
            )
        )
        projected: list[AuthorizedListing] = []
        for listing_id in listing_ids:
            try:
                row = await self.get_authorized_listing(
                    AuthorizedListingQuery(
                        purpose=purpose,
                        at=at,
                        listing_id=listing_id,
                    )
                )
            except ListingNotEligible:
                continue
            projected.append(row)
        return tuple(projected)

    async def list_for_administration(
        self, at: datetime
    ) -> tuple[AdministrationListing, ...]:
        """Catalog rows visible to this operator, with readiness explained.

        Administrators see their whole Organization. Advisors see only Listings
        for physical Properties where they have a live expert designation;
        expertise is deliberately not inferred from Opportunity ownership.
        """
        statement = self._administration_scope(select(CatalogListing)).order_by(
            CatalogListing.updated_at.desc(), CatalogListing.listing_key
        )
        return tuple(
            [
                await self._project_for_administration(row, at)
                for row in await self._session.scalars(statement)
            ]
        )

    async def get_for_administration(
        self, listing_id: uuid.UUID, at: datetime
    ) -> AdministrationListing:
        statement = self._administration_scope(select(CatalogListing)).where(
            CatalogListing.id == listing_id
        )
        listing = await self._session.scalar(statement)
        if listing is None:
            raise NotFound()
        return await self._project_for_administration(listing, at)

    def _administration_scope(self, statement: Any) -> Any:
        statement = statement.where(
            CatalogListing.organization_id == self._actor.organization_id
        )
        if self._actor.sees_whole_operation:
            return statement
        if self._actor.member_id is None:
            raise NotFound()
        expert_properties = select(PropertyExpert.property_uuid).where(
            PropertyExpert.organization_id == self._actor.organization_id,
            PropertyExpert.advisor_id == self._actor.member_id,
            PropertyExpert.revoked_at.is_(None),
        )
        return statement.where(CatalogListing.property_uuid.in_(expert_properties))

    async def _project_for_administration(
        self, listing: CatalogListing, at: datetime
    ) -> AdministrationListing:
        offers = tuple(
            AdministrationOffer(
                offer_id=row.id,
                operation=row.operation,
                price_amount=row.price_amount,
                price_currency=row.price_currency,
                price_visibility=row.price_visibility,
                terms_review_state=row.terms_review_state,
                availability=row.availability,
            )
            for row in await self._session.scalars(
                select(ListingOffer)
                .where(ListingOffer.listing_id == listing.id)
                .order_by(ListingOffer.operation)
            )
        )
        media = tuple(
            AdministrationMedia(
                media_id=row.id,
                original_filename=row.original_filename,
                authority=row.authority,
                is_cover=row.is_cover,
                sort_order=row.sort_order,
                space_group=row.space_group,
                high_resolution=row.high_resolution,
                revoked_at=row.revoked_at,
                cleanup_complete=(
                    row.revoked_at is None
                    or (
                        row.storage_deleted_at is not None
                        and row.cache_purged_at is not None
                    )
                ),
            )
            for row in await self._session.scalars(
                select(ListingMedia)
                .where(ListingMedia.listing_id == listing.id)
                .order_by(ListingMedia.revoked_at.nullsfirst(), ListingMedia.sort_order)
            )
        )
        if listing.property_uuid is not None:
            subject = await self._session.get(Property, listing.property_uuid)
            if subject is None:
                raise NotFound()
            physical_name = subject.name
            physical_key = subject.property_key
            physical_facts = dict(subject.physical_facts)
            physical_state = subject.facts_review_state
        else:
            subject_model = await self._session.get(UnitModel, listing.unit_model_id)
            if subject_model is None:
                raise NotFound()
            physical_name = subject_model.name
            physical_key = subject_model.model_key
            physical_facts = dict(subject_model.facts)
            physical_state = subject_model.facts_review_state
        decision = await self._eligibility.evaluate(
            listing.id, EligibilityPurpose.PUBLISH, at
        )
        return AdministrationListing(
            listing_id=listing.id,
            listing_key=listing.listing_key,
            property_uuid=listing.property_uuid,
            unit_model_id=listing.unit_model_id,
            physical_name=physical_name,
            physical_key=physical_key,
            title=listing.title,
            source_kind=listing.source_kind,
            source_name=listing.source_name,
            attribution=listing.attribution,
            provenance=dict(listing.provenance),
            physical_facts=physical_facts,
            physical_facts_review_state=physical_state,
            listing_facts=dict(listing.facts),
            listing_facts_review_state=listing.facts_review_state,
            availability=listing.availability,
            publication_state=listing.publication_state,
            authority=listing.authority,
            authority_evidence=listing.authority_evidence,
            freshness_checked_at=listing.freshness_checked_at,
            revalidate_by=listing.revalidate_by,
            presentation_tier=decision.readiness.tier,
            automatic_tier=listing.automatic_tier,
            tier_override=listing.tier_override,
            readiness_ready=decision.readiness.ready,
            readiness_overridden=decision.readiness.overridden,
            action_reasons=decision.reasons,
            gallery_path=listing.gallery_path,
            technical_sheet_path=listing.technical_sheet_path,
            offers=offers,
            media=media,
        )

    async def _candidates(
        self, query: AuthorizedListingQuery
    ) -> list[CatalogListing]:
        selectors = [
            query.listing_id is not None,
            query.listing_key is not None,
            query.property_uuid is not None,
        ]
        if sum(selectors) != 1:
            raise ValueError(
                "Exactly one of listing_id, listing_key or property_uuid is required."
            )
        statement = select(CatalogListing).where(
            CatalogListing.organization_id == self._actor.organization_id
        )
        if query.listing_id is not None:
            statement = statement.where(CatalogListing.id == query.listing_id)
        elif query.listing_key is not None:
            statement = statement.where(
                CatalogListing.listing_key == query.listing_key.strip()
            )
        else:
            statement = statement.where(
                CatalogListing.property_uuid == query.property_uuid
            ).order_by(
                case(
                    (
                        CatalogListing.source_kind
                        == ListingSourceKind.ORGANIZATION.value,
                        0,
                    ),
                    else_=1,
                ),
                CatalogListing.created_at,
            )
        return list(await self._session.scalars(statement))

    async def _project(
        self,
        listing: CatalogListing,
        purpose: EligibilityPurpose,
        decision: EligibilityDecision,
    ) -> AuthorizedListing:
        offers = list(
            await self._session.scalars(
                select(ListingOffer)
                .where(
                    ListingOffer.listing_id == listing.id,
                    ListingOffer.availability == OfferAvailability.AVAILABLE.value,
                )
                .order_by(ListingOffer.operation)
            )
        )
        media = list(
            await self._session.scalars(
                select(ListingMedia)
                .where(
                    ListingMedia.listing_id == listing.id,
                    ListingMedia.authority == ListingAuthority.AUTHORIZED.value,
                    ListingMedia.revoked_at.is_(None),
                )
                .order_by(ListingMedia.sort_order)
            )
        )
        # Every AuthorizedListing projection is customer-facing. Internal
        # administration uses the separate AdministrationListing model, so a
        # hidden amount must never leak through recommendation, appointment or
        # Maia disclosure merely because the public site is not the caller.
        hide_manual_price = True
        projected_offers = tuple(
            AuthorizedOffer(
                offer_id=row.id,
                operation=row.operation,
                price_amount=(
                    None
                    if hide_manual_price
                    and row.price_visibility == PublicPriceVisibility.HIDDEN.value
                    else row.price_amount
                ),
                price_currency=row.price_currency,
                price_visibility=row.price_visibility,
                consultation_copy=(
                    row.hidden_price_copy
                    if row.price_visibility == PublicPriceVisibility.HIDDEN.value
                    else None
                ),
                terms=dict(row.terms),
                availability=row.availability,
            )
            for row in offers
        )
        physical_key, physical_name, physical_facts = await self._physical_subject(
            listing
        )
        return AuthorizedListing(
            listing_id=listing.id,
            listing_key=listing.listing_key,
            property_uuid=listing.property_uuid,
            unit_model_id=listing.unit_model_id,
            physical_key=physical_key,
            physical_name=physical_name,
            source_kind=listing.source_kind,
            source_name=listing.source_name,
            attribution=listing.attribution,
            provenance=dict(listing.provenance),
            title=listing.title,
            public_location=listing.public_location,
            physical_facts=physical_facts,
            listing_facts=dict(listing.facts),
            availability=listing.availability,
            publication_state=listing.publication_state,
            authority=listing.authority,
            freshness_checked_at=listing.freshness_checked_at,
            revalidate_by=listing.revalidate_by,
            presentation_tier=decision.readiness.tier,
            readiness_overridden=decision.readiness.overridden,
            gallery_path=listing.gallery_path,
            technical_sheet_path=listing.technical_sheet_path,
            offers=projected_offers,
            media=tuple(
                AuthorizedMedia(
                    media_id=row.id,
                    is_cover=row.is_cover,
                    sort_order=row.sort_order,
                    space_group=row.space_group,
                )
                for row in media
            ),
        )

    async def _physical_subject(
        self, listing: CatalogListing
    ) -> tuple[str, str, dict[str, Any]]:
        if listing.property_uuid is not None:
            prop = await self._session.get(Property, listing.property_uuid)
            if prop is None:
                raise NotFound()
            return prop.property_key, prop.name, dict(prop.physical_facts)
        model = await self._session.get(UnitModel, listing.unit_model_id)
        if model is None:
            raise NotFound()
        return model.model_key, model.name, dict(model.facts)

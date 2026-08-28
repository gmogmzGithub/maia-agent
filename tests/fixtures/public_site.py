"""Stage 5 catalog fixtures built through Product's authority modules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    FactsReviewState,
    ListingAuthority,
    ListingAvailability,
    ListingPublicationState,
)
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateListing,
    CreateProperty,
    ReviewListingFacts,
    ReviewPropertyFacts,
    SetListingAuthority,
    SetListingAvailability,
    SetPublicationState,
    SetReadinessOverride,
    SetTierOverride,
)
from realestate.domain.catalog.media import AddMedia, MediaAdministration
from realestate.domain.catalog.offers import OfferManagement, RecordOffer
from realestate.domain.commercial.actors import Actor
from tests.fixtures.media import InMemoryMediaStorage


@dataclass(frozen=True)
class PublishedListing:
    property_id: uuid.UUID
    listing_id: uuid.UUID
    media_id: uuid.UUID
    slug: str


async def publish_listing(
    session: AsyncSession,
    actor: Actor,
    suffix: str,
    *,
    property_id: uuid.UUID | None = None,
    source_kind: str = "Organization",
    source_name: str = "Larevia",
    zone: str = "Zapopan",
    operation: str = "Sale",
    price: Decimal = Decimal("5000000"),
    hidden_price: bool = False,
    tier: str = "Larevia",
    storage: InMemoryMediaStorage | None = None,
) -> PublishedListing:
    """Create one fully eligible public Listing without bypassing Product."""
    catalog = CatalogAdministration(session)
    if property_id is None:
        physical = await catalog.record(
            actor,
            CreateProperty(
                property_key=f"casa-{suffix}",
                name=f"Casa {suffix.title()}",
                property_type="House",
                facts={"city": zone, "bedrooms": 3, "construction_m2": 180},
                provenance={"kind": "Test"},
                command_key=f"stage5:property:{suffix}",
            ),
        )
        property_id = physical.subject_id
        await catalog.record(
            actor,
            ReviewPropertyFacts(
                property_uuid=property_id,
                review_state=FactsReviewState.APPROVED,
                facts={"city": zone, "bedrooms": 3, "construction_m2": 180},
                command_key=f"stage5:property-review:{suffix}",
            ),
        )
    listing = await catalog.record(
        actor,
        CreateListing(
            listing_key=f"casa-{suffix}-{source_kind.casefold()}",
            property_uuid=property_id,
            source_kind=source_kind,
            source_name=source_name,
            attribution=f"Fuente: {source_name}",
            title=f"Casa {suffix.title()}",
            public_location=f"{zone}, Jalisco",
            provenance={"kind": "Test"},
            command_key=f"stage5:listing:{suffix}:{source_kind}",
        ),
    )
    listing_id = listing.subject_id
    await catalog.record(
        actor,
        ReviewListingFacts(
            listing_id=listing_id,
            review_state=FactsReviewState.APPROVED,
            facts={"public_location": f"{zone}, Jalisco"},
            command_key=f"stage5:listing-review:{suffix}:{source_kind}",
        ),
    )
    await catalog.record(
        actor,
        SetListingAuthority(
            listing_id=listing_id,
            authority=ListingAuthority.AUTHORIZED,
            evidence="Autorización sintética de prueba",
            checked_at=datetime(2026, 8, 28, tzinfo=UTC),
            revalidate_by=(
                datetime(2027, 8, 28, tzinfo=UTC)
                if source_kind != "Organization"
                else None
            ),
            command_key=f"stage5:authority:{suffix}:{source_kind}",
        ),
    )
    await catalog.record(
        actor,
        SetListingAvailability(
            listing_id=listing_id,
            availability=ListingAvailability.AVAILABLE,
            command_key=f"stage5:availability:{suffix}:{source_kind}",
        ),
    )
    await OfferManagement(session).record(
        actor,
        RecordOffer(
            listing_id=listing_id,
            operation=operation,
            price_amount=price,
            price_currency="MXN",
            price_visibility="Hidden" if hidden_price else "Visible",
            terms={"condition": "Precio de lista"},
            terms_review_state="Approved",
            availability="Available",
            command_key=f"stage5:offer:{suffix}:{source_kind}",
        ),
    )
    media_store = storage or InMemoryMediaStorage()
    recorded = await MediaAdministration(session, media_store).record(
        actor,
        AddMedia(
            listing_id=listing_id,
            original_filename=f"{suffix}.jpg",
            content_type="image/jpeg",
            content=b"\xff\xd8\xff\xe0stage-five-image",
            provenance="Fotografía sintética de prueba",
            authority=ListingAuthority.AUTHORIZED,
            authority_evidence="Autorización sintética de prueba",
            is_cover=True,
            sort_order=0,
            space_group="Fachada",
            high_resolution=True,
            cache_keys=(),
            command_key=f"stage5:media:{suffix}:{source_kind}",
        ),
    )
    await catalog.record(
        actor,
        SetReadinessOverride(
            listing_id=listing_id,
            enabled=True,
            command_key=f"stage5:readiness:{suffix}:{source_kind}",
        ),
    )
    if tier != "Larevia":
        await catalog.record(
            actor,
            SetTierOverride(
                listing_id=listing_id,
                tier=tier,
                command_key=f"stage5:tier:{suffix}:{source_kind}",
            ),
        )
    await catalog.record(
        actor,
        SetPublicationState(
            listing_id=listing_id,
            state=ListingPublicationState.PUBLISHED,
            command_key=f"stage5:publish:{suffix}:{source_kind}",
        ),
    )
    await session.flush()
    return PublishedListing(property_id, listing_id, recorded.media_id, f"casa-{suffix}-{source_kind.casefold()}")

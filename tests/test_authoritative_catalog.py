"""Authoritative catalog behavior through its public module interfaces."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from realestate.db.engine import Database
from realestate.db.models import (
    CatalogListing,
    AuditEvent,
    Development,
    FactsReviewState,
    ListingAuthority,
    ListingAvailability,
    ListingMedia,
    ListingOffer,
    ListingPublicationState,
    MemberProvisioning,
    MemberRole,
    OpportunityKind,
    Organization,
    OrganizationMember,
    Property,
    UnitModel,
)
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateListing,
    CreateProperty,
    CreateDevelopment,
    CreateUnitModel,
    ImportLegacyDocument,
    ReviewListingFacts,
    ReviewDevelopmentFacts,
    ReviewPropertyFacts,
    ReviewUnitModelFacts,
    SetListingAuthority,
    SetListingAvailability,
    SetPublicationState,
    SetReadinessOverride,
    SetTierOverride,
    SyncLegacyPropertyStatus,
)
from realestate.domain.catalog.eligibility import (
    EligibilityPurpose,
    ListingEligibility,
)
from realestate.domain.catalog.offers import (
    CompleteOperation,
    OfferManagement,
    RecordOffer,
)
from realestate.domain.catalog.media import (
    AddMedia,
    ArrangeMedia,
    MediaAdministration,
    MediaCleanupPending,
    MediaPlacement,
    RevokeMedia,
)
from realestate.domain.catalog.storage import MediaStorageError
from tests.fixtures.media import InMemoryMediaStorage
from realestate.domain.catalog.projection import (
    AuthorizedListingQuery,
    CatalogProjection,
    ListingNotEligible,
)
from realestate.domain.commercial.actors import (
    Actor,
    Authority,
    InvalidTransition,
    NotAuthorized,
    NotFound,
)
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    ADVISOR_LOGIN,
    actor_for,
    make_contact,
    open_opportunity,
    provision,
    product_actor,
    reset,
)

pytestmark = requires_postgres


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await session.commit()
        await reset(session, members=True)
        await session.execute(text("DELETE FROM organizations WHERE slug <> 'larevia'"))
        await session.commit()
        await provision(session)
    yield db


async def test_admin_records_a_physical_property_and_two_source_listings(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        physical = await catalog.record(
            admin,
            CreateProperty(
                property_key="casa-fresno",
                name="Casa Fresno",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "AdministratorStatement"},
                command_key="catalog:property:fresno",
            ),
        )
        own = await catalog.record(
            admin,
            CreateListing(
                listing_key="fresno-larevia",
                property_uuid=physical.subject_id,
                source_kind="Organization",
                source_name="Larevia",
                attribution="Inventario propio",
                title="Casa Fresno",
                public_location="Zapopan, Jalisco",
                provenance={"kind": "AdministratorStatement"},
                command_key="catalog:listing:fresno-own",
            ),
        )
        collaborator = await catalog.record(
            admin,
            CreateListing(
                listing_key="fresno-colaborador",
                property_uuid=physical.subject_id,
                source_kind="Collaborator",
                source_name="Inmobiliaria colaboradora",
                attribution="Fuente colaboradora; autorización por validar",
                title="Casa Fresno",
                public_location="Zapopan, Jalisco",
                provenance={"kind": "ManualExternalReference"},
                command_key="catalog:listing:fresno-collab",
            ),
        )
        await session.commit()

        assert physical.subject_id != own.subject_id != collaborator.subject_id
        assert await session.get(Property, physical.subject_id) is not None
        own_row = await session.get(CatalogListing, own.subject_id)
        collaborator_row = await session.get(CatalogListing, collaborator.subject_id)
        assert own_row is not None and own_row.property_uuid == physical.subject_id
        assert collaborator_row is not None
        assert collaborator_row.property_uuid == physical.subject_id
        assert collaborator_row.authority == "Pending"
        assert collaborator_row.publication_state == "Draft"


async def test_advisor_cannot_mutate_the_catalog(database) -> None:
    async with database.session_scope() as session:
        advisor = await actor_for(session, ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized):
            await CatalogAdministration(session).record(
                advisor,
                CreateProperty(
                    property_key="sin-permiso",
                    name="Sin permiso",
                    property_type="House",
                    facts={},
                    provenance={"kind": "Untrusted"},
                    command_key=f"catalog:forbidden:{uuid.uuid4().hex}",
                ),
            )


async def _listing(database, suffix: str = "offers") -> tuple[object, uuid.UUID, uuid.UUID]:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        physical = await catalog.record(
            admin,
            CreateProperty(
                property_key=f"casa-{suffix}",
                name=f"Casa {suffix}",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "Test"},
                command_key=f"catalog:property:{suffix}",
            ),
        )
        listing = await catalog.record(
            admin,
            CreateListing(
                listing_key=f"listing-{suffix}",
                property_uuid=physical.subject_id,
                source_kind="Organization",
                source_name="Larevia",
                attribution="Inventario propio",
                title=f"Casa {suffix}",
                public_location="Zapopan, Jalisco",
                provenance={"kind": "Test"},
                command_key=f"catalog:listing:{suffix}",
            ),
        )
        await session.commit()
        return admin, physical.subject_id, listing.subject_id


async def test_one_listing_has_sale_and_rental_offers_and_uses_the_highest_tier(
    database, monkeypatch,
) -> None:
    _admin, _property_id, listing_id = await _listing(database)
    changed_at = datetime(2026, 8, 28, 19, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "realestate.domain.catalog.presentation.utc_now", lambda: changed_at
    )
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        offers = OfferManagement(session)
        sale = await offers.record(
            admin,
            RecordOffer(
                listing_id=listing_id,
                operation="Sale",
                price_amount=Decimal("9000000"),
                price_currency="MXN",
                price_visibility="Visible",
                terms={"condition": "Precio de lista"},
                terms_review_state="Approved",
                availability="Available",
                command_key="offer:sale:offers",
            ),
        )
        rental = await offers.record(
            admin,
            RecordOffer(
                listing_id=listing_id,
                operation="Rental",
                price_amount=Decimal("90000"),
                price_currency="MXN",
                price_visibility="Hidden",
                terms={"period": "Mensual"},
                terms_review_state="Approved",
                availability="Available",
                command_key="offer:rental:offers",
            ),
        )
        await session.commit()

        assert sale.offer_id != rental.offer_id
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None and listing.automatic_tier == "SuperPremium"
        assert listing.updated_at == changed_at
        rental_row = await session.get(ListingOffer, rental.offer_id)
        assert rental_row is not None
        assert rental_row.hidden_price_copy == "Precio disponible previa consulta"
        assert rental_row.price_amount == Decimal("90000.00")


async def test_completed_sale_disables_sale_and_rental_without_deleting_them(
    database,
) -> None:
    _admin, property_id, listing_id = await _listing(database, "completed")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        offers = OfferManagement(session)
        for operation, price in (("Sale", "8000000"), ("Rental", "35000")):
            await offers.record(
                admin,
                RecordOffer(
                    listing_id=listing_id,
                    operation=operation,
                    price_amount=Decimal(price),
                    price_currency="MXN",
                    price_visibility="Visible",
                    terms={},
                    terms_review_state="Approved",
                    availability="Available",
                    command_key=f"offer:{operation}:completed",
                ),
            )
        await offers.record(
            admin,
            CompleteOperation(
                listing_id=listing_id,
                operation="Sale",
                command_key="offer:complete-sale",
            ),
        )
        await session.commit()

        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None
        assert listing.property_uuid == property_id
        assert listing.availability == "Sold"
        rows = list(
            await session.scalars(
                select(ListingOffer).where(ListingOffer.listing_id == listing_id)
            )
        )
        assert {row.operation for row in rows} == {"Sale", "Rental"}
        assert {row.availability for row in rows} == {"Completed"}
        assert {row.unavailable_reason for row in rows} == {"Sold"}


async def _approve_for_private_use(
    session, admin, property_id: uuid.UUID, listing_id: uuid.UUID
) -> None:
    catalog = CatalogAdministration(session)
    await catalog.record(
        admin,
        ReviewPropertyFacts(
            property_uuid=property_id,
            review_state=FactsReviewState.APPROVED,
            facts={"city": "Zapopan", "bedrooms": 3},
            command_key=f"review:property:{property_id}",
        ),
    )
    await catalog.record(
        admin,
        ReviewListingFacts(
            listing_id=listing_id,
            review_state=FactsReviewState.APPROVED,
            facts={"public_location": "Zapopan, Jalisco"},
            command_key=f"review:listing:{listing_id}",
        ),
    )
    await catalog.record(
        admin,
        SetListingAuthority(
            listing_id=listing_id,
            authority=ListingAuthority.AUTHORIZED,
            evidence="Autorización administrativa documentada",
            checked_at=datetime(2026, 8, 28, tzinfo=UTC),
            revalidate_by=None,
            command_key=f"authority:{listing_id}",
        ),
    )
    await catalog.record(
        admin,
        SetListingAvailability(
            listing_id=listing_id,
            availability=ListingAvailability.AVAILABLE,
            command_key=f"availability:{listing_id}",
        ),
    )
    await OfferManagement(session).record(
        admin,
        RecordOffer(
            listing_id=listing_id,
            operation="Sale",
            price_amount=Decimal("5000000"),
            price_currency="MXN",
            price_visibility="Visible",
            terms={},
            terms_review_state="Approved",
            availability="Available",
            command_key=f"offer:approved:{listing_id}",
        ),
    )


async def test_availability_publication_and_authority_are_independent(
    database,
) -> None:
    _admin, property_id, listing_id = await _listing(database, "matrix")
    moment = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await _approve_for_private_use(session, admin, property_id, listing_id)
        eligibility = ListingEligibility(session, admin)

        private = await eligibility.evaluate(
            listing_id, EligibilityPurpose.APPOINTMENT, moment
        )
        assert private.eligible is True
        current = await session.get(CatalogListing, listing_id)
        assert current is not None and current.publication_state == "Draft"

        public = await eligibility.evaluate(
            listing_id, EligibilityPurpose.PUBLIC_SHARE, moment
        )
        assert public.eligible is False
        assert "la publicación no está publicada" in public.reasons

        await CatalogAdministration(session).record(
            admin,
            SetListingAvailability(
                listing_id=listing_id,
                availability=ListingAvailability.RESERVED,
                command_key="matrix:reserved",
            ),
        )
        reserved = await eligibility.evaluate(
            listing_id, EligibilityPurpose.APPOINTMENT, moment
        )
        assert reserved.eligible is False
        assert "la publicación no está disponible" in reserved.reasons

        await CatalogAdministration(session).record(
            admin,
            SetListingAvailability(
                listing_id=listing_id,
                availability=ListingAvailability.AVAILABLE,
                command_key="matrix:available-again",
            ),
        )
        await CatalogAdministration(session).record(
            admin,
            SetListingAuthority(
                listing_id=listing_id,
                authority=ListingAuthority.REVOKED,
                evidence="Revocada por el titular",
                checked_at=moment,
                revalidate_by=None,
                command_key="matrix:revoked",
            ),
        )
        revoked = await eligibility.evaluate(
            listing_id, EligibilityPurpose.APPOINTMENT, moment
        )
        assert revoked.eligible is False
        assert "la autoridad de la publicación no está vigente" in revoked.reasons


async def test_incomplete_readiness_blocks_publication_without_destroying_data(
    database,
) -> None:
    _admin, property_id, listing_id = await _listing(database, "readiness")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await _approve_for_private_use(session, admin, property_id, listing_id)
        catalog = CatalogAdministration(session)
        with pytest.raises(InvalidTransition, match="no está lista"):
            await catalog.record(
                admin,
                SetPublicationState(
                    listing_id=listing_id,
                    state=ListingPublicationState.PUBLISHED,
                    command_key="publish:not-ready",
                ),
            )
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None
        assert listing.publication_state == "Draft"
        rows = list(
            await session.scalars(
                select(ListingOffer).where(ListingOffer.listing_id == listing_id)
            )
        )
        assert len(rows) == 1


async def test_admin_readiness_override_is_explicit_and_auditable(database) -> None:
    _admin, property_id, listing_id = await _listing(database, "override")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await _approve_for_private_use(session, admin, property_id, listing_id)
        catalog = CatalogAdministration(session)
        await catalog.record(
            admin,
            SetReadinessOverride(
                listing_id=listing_id,
                enabled=True,
                command_key="readiness:override",
            ),
        )
        await catalog.record(
            admin,
            SetPublicationState(
                listing_id=listing_id,
                state=ListingPublicationState.PUBLISHED,
                command_key="publish:override",
            ),
        )
        await session.commit()
        decision = await ListingEligibility(session, admin).evaluate(
            listing_id,
            EligibilityPurpose.PUBLIC_SHARE,
            datetime.now(tz=UTC) + timedelta(minutes=1),
        )
        assert decision.eligible is True
        assert decision.readiness.overridden is True
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None
        assert listing.readiness_override_by == admin.member_id


async def test_admin_tier_override_and_its_removal_are_auditable(database) -> None:
    _admin, _property_id, listing_id = await _listing(database, "tier-override")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        await catalog.record(
            admin,
            SetTierOverride(
                listing_id=listing_id,
                tier="SuperPremium",
                command_key="tier:override:set",
            ),
        )
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None
        assert listing.tier_override == "SuperPremium"
        assert listing.tier_override_by == admin.member_id
        assert listing.tier_override_at is not None

        await catalog.record(
            admin,
            SetTierOverride(
                listing_id=listing_id,
                tier=None,
                command_key="tier:override:clear",
            ),
        )
        await session.commit()
        assert listing.tier_override is None
        assert listing.tier_override_by is None
        events = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "SetTierOverride",
                    AuditEvent.subject_id == str(listing_id),
                )
            )
        )
        assert [event.details["after"]["tier_override"] for event in events] == [
            "SuperPremium",
            None,
        ]


async def _add_larevia_gallery(
    session,
    admin,
    listing_id: uuid.UUID,
    storage: InMemoryMediaStorage,
) -> list[uuid.UUID]:
    media = MediaAdministration(session, storage)
    ids: list[uuid.UUID] = []
    for index in range(6):
        recorded = await media.record(
            admin,
            AddMedia(
                listing_id=listing_id,
                original_filename=f"espacio-{index}.jpg",
                content_type="image/jpeg",
                content=b"\xff\xd8\xff" + bytes([index]),
                provenance=f"Fotografía sintética {index}",
                authority=ListingAuthority.AUTHORIZED,
                authority_evidence="Autorización sintética para prueba",
                is_cover=index == 0,
                sort_order=index,
                space_group="Interiores" if index else "Fachada",
                high_resolution=index == 0,
                cache_keys=(f"thumb/{listing_id}/{index}.jpg",),
                command_key=f"media:add:{listing_id}:{index}",
            ),
        )
        ids.append(recorded.media_id)
    return ids


async def test_complete_larevia_readiness_allows_publication_and_media_revocation_deletes_storage_and_cache(
    database,
) -> None:
    _admin, property_id, listing_id = await _listing(database, "media")
    storage = InMemoryMediaStorage()
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await _approve_for_private_use(session, admin, property_id, listing_id)
        await session.commit()
        media_ids = await _add_larevia_gallery(session, admin, listing_id, storage)
        for index in range(6):
            storage.cache_objects.add(f"thumb/{listing_id}/{index}.jpg")

        await CatalogAdministration(session).record(
            admin,
            SetPublicationState(
                listing_id=listing_id,
                state=ListingPublicationState.PUBLISHED,
                command_key="publish:media-ready",
            ),
        )
        await session.commit()
        decision = await ListingEligibility(session, admin).evaluate(
            listing_id, EligibilityPurpose.PUBLIC_SHARE, datetime.now(tz=UTC)
        )
        assert decision.eligible is True

        cover = await session.get(ListingMedia, media_ids[0])
        assert cover is not None and cover.storage_key in storage.objects
        await MediaAdministration(session, storage).record(
            admin,
            RevokeMedia(
                media_id=media_ids[0],
                command_key="media:revoke:cover",
            ),
        )
        assert cover.storage_key not in storage.objects
        assert f"thumb/{listing_id}/0.jpg" not in storage.cache_objects
        assert cover.storage_deleted_at is not None
        assert cover.cache_purged_at is not None
        after = await ListingEligibility(session, admin).evaluate(
            listing_id, EligibilityPurpose.PUBLIC_SHARE, datetime.now(tz=UTC)
        )
        assert after.eligible is False
        assert "falta una fotografía de portada autorizada" in after.reasons


async def test_revoked_media_cleanup_resumes_idempotently_after_restart(database) -> None:
    _admin, property_id, listing_id = await _listing(database, "media-restart")
    storage = InMemoryMediaStorage()
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await _approve_for_private_use(session, admin, property_id, listing_id)
        await session.commit()
        media_id = (
            await MediaAdministration(session, storage).record(
                admin,
                AddMedia(
                    listing_id=listing_id,
                    original_filename="portada.png",
                    content_type="image/png",
                    content=b"\x89PNG\r\n\x1a\nsynthetic",
                    provenance="Fotografía sintética",
                    authority=ListingAuthority.AUTHORIZED,
                    authority_evidence="Autorización sintética",
                    is_cover=True,
                    sort_order=0,
                    space_group="Fachada",
                    high_resolution=True,
                    cache_keys=("cache/portada.png",),
                    command_key="media:add:restart",
                ),
            )
        ).media_id
        storage.cache_objects.add("cache/portada.png")
        storage.fail_delete_once = True
        command = RevokeMedia(media_id=media_id, command_key="media:revoke:restart")
        with pytest.raises(MediaCleanupPending):
            await MediaAdministration(session, storage).record(admin, command)

    async with database.session_scope() as restarted:
        admin = await actor_for(restarted, ADMIN_LOGIN)
        result = await MediaAdministration(restarted, storage).record(admin, command)
        assert result.replayed is True
        row = await restarted.get(ListingMedia, media_id)
        assert row is not None
        assert row.authority == "Revoked"
        assert row.storage_deleted_at is not None
        assert row.cache_purged_at is not None
        assert not storage.objects
        assert not storage.cache_objects


async def test_authorized_projection_keeps_source_and_hides_public_price(database) -> None:
    _admin, property_id, listing_id = await _listing(database, "projection")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await _approve_for_private_use(session, admin, property_id, listing_id)
        await OfferManagement(session).record(
            admin,
            RecordOffer(
                listing_id=listing_id,
                operation="Sale",
                price_amount=Decimal("5000000"),
                price_currency="MXN",
                price_visibility="Hidden",
                terms={},
                terms_review_state="Approved",
                availability="Available",
                command_key="offer:hidden:projection",
            ),
        )
        catalog = CatalogAdministration(session)
        await catalog.record(
            admin,
            SetReadinessOverride(
                listing_id=listing_id,
                enabled=True,
                command_key="readiness:projection",
            ),
        )
        await catalog.record(
            admin,
            SetPublicationState(
                listing_id=listing_id,
                state=ListingPublicationState.PUBLISHED,
                command_key="publish:projection",
            ),
        )
        await session.commit()

        projected = await CatalogProjection(session, admin).get_authorized_listing(
            AuthorizedListingQuery(
                listing_id=listing_id,
                purpose=EligibilityPurpose.PUBLIC_SHARE,
                at=datetime.now(tz=UTC),
            )
        )
        assert projected.source_kind == "Organization"
        assert projected.attribution == "Inventario propio"
        assert projected.gallery_path.endswith("/galeria")
        assert projected.technical_sheet_path.endswith("/ficha-tecnica")
        assert len(projected.offers) == 1
        assert projected.offers[0].price_amount is None
        assert (
            projected.offers[0].consultation_copy
            == "Precio disponible previa consulta"
        )


async def test_external_listing_without_current_authority_has_no_projection(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        prop = await catalog.record(
            admin,
            CreateProperty(
                property_key="externa-pendiente",
                name="Externa pendiente",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "CollaboratorClaim"},
                command_key="external:property",
            ),
        )
        listing = await catalog.record(
            admin,
            CreateListing(
                listing_key="externa-pendiente",
                property_uuid=prop.subject_id,
                source_kind="Collaborator",
                source_name="Colaborador externo",
                attribution="Pendiente de validar",
                title="Externa pendiente",
                public_location="Zapopan, Jalisco",
                provenance={"kind": "ManualExternalReference"},
                command_key="external:listing",
            ),
        )
        await session.commit()
        with pytest.raises(ListingNotEligible) as refusal:
            await CatalogProjection(session, admin).get_authorized_listing(
                AuthorizedListingQuery(
                    listing_id=listing.subject_id,
                    purpose=EligibilityPurpose.RECOMMEND,
                    at=datetime.now(tz=UTC),
                )
            )
        assert "autoridad" in refusal.value.message


async def test_external_listing_must_be_revalidated_before_recommendation(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        prop = await catalog.record(
            admin,
            CreateProperty(
                property_key="externa-vencida",
                name="Externa vencida",
                property_type="House",
                facts={},
                provenance={"kind": "CollaboratorClaim"},
                command_key="expired:property",
            ),
        )
        listing = await catalog.record(
            admin,
            CreateListing(
                listing_key="externa-vencida",
                property_uuid=prop.subject_id,
                source_kind="Collaborator",
                source_name="Colaborador",
                attribution="Colaborador identificado",
                title="Externa vencida",
                public_location="Zapopan",
                provenance={"kind": "ExternalReference"},
                command_key="expired:listing",
            ),
        )
        await _approve_for_private_use(
            session, admin, prop.subject_id, listing.subject_id
        )
        checked = datetime.now(tz=UTC) - timedelta(days=2)
        await catalog.record(
            admin,
            SetListingAuthority(
                listing_id=listing.subject_id,
                authority=ListingAuthority.AUTHORIZED,
                evidence="Permiso del colaborador",
                checked_at=checked,
                revalidate_by=checked + timedelta(days=1),
                command_key="expired:authority",
            ),
        )
        await session.commit()
        with pytest.raises(ListingNotEligible) as refusal:
            await CatalogProjection(session, admin).get_authorized_listing(
                AuthorizedListingQuery(
                    listing_id=listing.subject_id,
                    purpose=EligibilityPurpose.RECOMMEND,
                    at=datetime.now(tz=UTC),
                )
            )
        assert "revalidación" in refusal.value.message


async def test_development_and_unit_model_create_no_fictitious_property(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        development = await catalog.record(
            admin,
            CreateDevelopment(
                development_key="torres-del-valle",
                name="Torres del Valle",
                facts={"stage": "Pending"},
                provenance={"kind": "AdministratorStatement"},
                command_key="development:create",
            ),
        )
        model = await catalog.record(
            admin,
            CreateUnitModel(
                development_id=development.subject_id,
                model_key="modelo-a",
                name="Modelo A",
                facts={"property_type": "Apartment", "bedrooms": 2},
                provenance={"kind": "DeveloperMaterialPendingReview"},
                command_key="unit-model:create",
            ),
        )
        listing = await catalog.record(
            admin,
            CreateListing(
                listing_key="torres-modelo-a",
                unit_model_id=model.subject_id,
                source_kind="Organization",
                source_name="Larevia",
                attribution="Desarrollo administrado",
                title="Torres del Valle — Modelo A",
                public_location="Zapopan",
                provenance={"kind": "DeveloperMaterialPendingReview"},
                command_key="unit-model:listing",
            ),
        )
        await session.commit()
        assert await session.get(Development, development.subject_id) is not None
        assert await session.scalar(select(Property.id).limit(1)) is None
        row = await session.get(CatalogListing, listing.subject_id)
        assert row is not None
        assert row.property_uuid is None
        assert row.unit_model_id == model.subject_id
        assert row.authority == "Pending"


async def test_listing_acquisition_opportunity_never_creates_a_listing(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        contact_id, _lead = await make_contact(session, "5213300000444")
        await open_opportunity(
            session,
            admin,
            contact_id,
            kind=OpportunityKind.LISTING_ACQUISITION,
        )
        await session.commit()
        assert await session.scalar(select(CatalogListing.id).limit(1)) is None


async def test_catalog_records_are_isolated_between_organizations(database) -> None:
    _admin, _property_id, listing_id = await _listing(database, "org-scope")
    async with database.session_scope() as session:
        other_org = Organization(
            slug="otra-inmobiliaria", display_name="Otra inmobiliaria"
        )
        session.add(other_org)
        await session.flush()
        other_member = OrganizationMember(
            organization_id=other_org.id,
            login="admin@otra.test",
            display_name="Admin otra",
            role=MemberRole.ADMINISTRATOR.value,
            advises=False,
            is_default_advisor=False,
            active=True,
            provisioned_by=MemberProvisioning.ADMINISTRATOR.value,
        )
        session.add(other_member)
        await session.commit()
        other_actor = await actor_for(session, "admin@otra.test")
        with pytest.raises(NotFound):
            await CatalogProjection(session, other_actor).get_authorized_listing(
                AuthorizedListingQuery(
                    listing_id=listing_id,
                    purpose=EligibilityPurpose.RECOMMEND,
                    at=datetime.now(tz=UTC),
                )
            )


async def test_legacy_status_write_through_covers_every_compatibility_state(
    database,
) -> None:
    _admin, property_id, listing_id = await _listing(database, "legacy-status")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        for operation, price in (("Sale", "7000000"), ("Rental", "45000")):
            await OfferManagement(session).record(
                admin,
                RecordOffer(
                    listing_id,
                    operation,
                    Decimal(price),
                    "MXN",
                    "Visible",
                    {},
                    "Approved",
                    "Available",
                    f"legacy-status:offer:{operation}",
                ),
            )
        await session.commit()

    states = (
        ("Inactive", "Reserved", "Reserved", {"Reserved"}),
        (
            "Inactive",
            "TemporarilyUnavailable",
            "TemporarilyUnavailable",
            {"TemporarilyUnavailable"},
        ),
        ("Inactive", "Withdrawn", "TemporarilyUnavailable", {"Withdrawn"}),
        (
            "Inactive",
            "Rented",
            "Rented",
            {"Completed", "TemporarilyUnavailable"},
        ),
        ("Inactive", "Unspecified", "Unknown", {"Unknown"}),
        ("Active", None, "Available", {"Available"}),
        ("Inactive", "Sold", "Sold", {"Completed"}),
    )
    for index, (status, reason, listing_state, offer_states) in enumerate(states):
        async with database.session_scope() as session:
            product = await product_actor(session)
            command = SyncLegacyPropertyStatus(
                property_id,
                status,
                reason,
                f"legacy-status:{index}",
            )
            result = await CatalogAdministration(session).record(product, command)
            await session.commit()
            listing = await session.get(CatalogListing, listing_id)
            rows = list(
                await session.scalars(
                    select(ListingOffer).where(ListingOffer.listing_id == listing_id)
                )
            )
            assert listing is not None and listing.availability == listing_state
            assert {row.availability for row in rows} == offer_states
            if index == 0:
                replay = await CatalogAdministration(session).record(product, command)
                assert result.replayed is False and replay.replayed is True


async def test_catalog_commands_refuse_missing_or_invalid_evidence(database) -> None:
    _admin, property_id, listing_id = await _listing(database, "refusals")
    invalid_commands = (
        CreateProperty("Bad Key", "Nombre", "House", {}, {}, "bad:key"),
        CreateListing(
            "bad-subject",
            "Organization",
            "Larevia",
            "Propia",
            "Mala",
            None,
            {},
            "bad:subject",
        ),
        CreateListing(
            "bad-source",
            "Scraped",
            "Internet",
            "Desconocida",
            "Mala",
            None,
            {},
            "bad:source",
            property_uuid=property_id,
        ),
        SetListingAuthority(
            listing_id,
            ListingAuthority.AUTHORIZED,
            None,
            datetime.now(tz=UTC),
            None,
            "bad:authority",
        ),
        SetTierOverride(listing_id, "Diamond", "bad:tier"),
    )
    for command in invalid_commands:
        async with database.session_scope() as session:
            admin = await actor_for(session, ADMIN_LOGIN)
            with pytest.raises(InvalidTransition):
                await CatalogAdministration(session).record(admin, command)

    moment = datetime.now(tz=UTC)
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(InvalidTransition, match="después"):
            await CatalogAdministration(session).record(
                admin,
                SetListingAuthority(
                    listing_id,
                    ListingAuthority.PENDING,
                    "Pendiente",
                    moment,
                    moment - timedelta(minutes=1),
                    "bad:revalidation",
                ),
            )

    async with database.session_scope() as session:
        product = await product_actor(session)
        with pytest.raises(NotFound):
            await CatalogAdministration(session).record(
                product,
                SyncLegacyPropertyStatus(
                    uuid.uuid4(), "Active", None, "missing:legacy-status"
                ),
            )
        with pytest.raises(NotFound):
            await CatalogAdministration(session).record(
                product,
                ImportLegacyDocument(
                    uuid.uuid4(), uuid.uuid4(), {}, "missing:legacy-import"
                ),
            )


async def test_offer_refusals_replay_and_rental_completion(database) -> None:
    _admin, _property_id, listing_id = await _listing(database, "offer-refusals")
    base = RecordOffer(
        listing_id,
        "Sale",
        Decimal("5000000"),
        "MXN",
        "Visible",
        {},
        "Approved",
        "Available",
        "offer:valid",
    )
    for command in (
        replace(base, operation="Swap", command_key="offer:bad-operation"),
        replace(base, price_amount=Decimal("0"), command_key="offer:bad-price"),
        replace(base, price_currency="EUR", command_key="offer:bad-currency"),
    ):
        async with database.session_scope() as session:
            admin = await actor_for(session, ADMIN_LOGIN)
            with pytest.raises(InvalidTransition):
                await OfferManagement(session).record(admin, command)

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        recorded = await OfferManagement(session).record(admin, base)
        await session.commit()
        replay = await OfferManagement(session).record(admin, base)
        assert replay.offer_id == recorded.offer_id and replay.replayed
        with pytest.raises(InvalidTransition):
            await OfferManagement(session).record(
                admin, CompleteOperation(listing_id, "Swap", "complete:bad")
            )
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(NotFound):
            await OfferManagement(session).record(
                admin, CompleteOperation(listing_id, "Rental", "complete:missing")
            )
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        offers = OfferManagement(session)
        await offers.record(
            admin,
            replace(
                base,
                operation="Rental",
                price_amount=Decimal("40000"),
                command_key="offer:rental:complete",
            ),
        )
        await offers.record(
            admin, CompleteOperation(listing_id, "Rental", "complete:rental")
        )
        await session.commit()
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None and listing.availability == "Available"


async def test_media_refusals_replay_and_arrangement_validation(database) -> None:
    _admin, _property_id, listing_id = await _listing(database, "media-refusals")
    storage = InMemoryMediaStorage()
    base = AddMedia(
        listing_id,
        "portada.jpg",
        "image/jpeg",
        b"\xff\xd8\xffsynthetic",
        "Fotografía del propietario",
        ListingAuthority.AUTHORIZED,
        "Autorización escrita",
        True,
        0,
        "Fachada",
        True,
        (),
        "media:refusal:valid",
    )
    invalid = (
        replace(base, content_type="image/gif", command_key="media:bad-type"),
        replace(base, original_filename="portada.png", command_key="media:bad-ext"),
        replace(base, content=b"", command_key="media:empty"),
        replace(base, content=b"not-jpeg", command_key="media:signature"),
        replace(base, authority_evidence=None, command_key="media:evidence"),
        replace(base, sort_order=-1, command_key="media:order"),
        replace(base, provenance=" ", command_key="media:provenance"),
    )
    for command in invalid:
        async with database.session_scope() as session:
            admin = await actor_for(session, ADMIN_LOGIN)
            with pytest.raises(InvalidTransition):
                await MediaAdministration(session, storage).record(admin, command)

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        recorded = await MediaAdministration(session, storage).record(admin, base)
        replay = await MediaAdministration(session, storage).record(admin, base)
        assert replay.media_id == recorded.media_id and replay.replayed
        with pytest.raises(InvalidTransition, match="exactamente"):
            await MediaAdministration(session, storage).record(
                admin,
                ArrangeMedia(listing_id, uuid.uuid4(), (), "arrange:incomplete"),
            )
        with pytest.raises(InvalidTransition, match="orden único"):
            await MediaAdministration(session, storage).record(
                admin,
                ArrangeMedia(
                    listing_id,
                    recorded.media_id,
                    (
                        MediaPlacement(recorded.media_id, 0, "Fachada"),
                        MediaPlacement(recorded.media_id, 0, "Sala"),
                    ),
                    "arrange:duplicate-order",
                ),
            )
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(NotFound):
            await MediaAdministration(session, storage).record(
                admin, RevokeMedia(uuid.uuid4(), "media:missing")
            )


class _FailingPutStorage(InMemoryMediaStorage):
    async def put(self, key: str, content: bytes) -> None:
        raise MediaStorageError("Falla sintética al guardar.")


async def test_media_storage_failure_never_creates_a_database_row(database) -> None:
    _admin, _property_id, listing_id = await _listing(database, "media-put-fails")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(MediaStorageError):
            await MediaAdministration(session, _FailingPutStorage()).record(
                admin,
                AddMedia(
                    listing_id,
                    "foto.webp",
                    "image/webp",
                    b"RIFFxxxxWEBPsynthetic",
                    "Propietario",
                    ListingAuthority.AUTHORIZED,
                    "Autorización escrita",
                    True,
                    0,
                    None,
                    True,
                    (),
                    "media:put:fails",
                ),
            )
        assert list(await session.scalars(select(ListingMedia))) == []


async def test_development_and_unit_model_review_projection_and_completion_boundary(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        development_command = CreateDevelopment(
            "desarrollo-revisado",
            "Desarrollo revisado",
            {"city": "Zapopan"},
            {"kind": "DeveloperMaterial"},
            "development:reviewed",
        )
        development = await catalog.record(admin, development_command)
        assert (await catalog.record(admin, development_command)).replayed
        unit_command = CreateUnitModel(
            development.subject_id,
            "modelo-revisado",
            "Modelo revisado",
            {"property_type": "Apartment", "bedrooms": 2},
            {"kind": "DeveloperMaterial"},
            "unit:reviewed",
        )
        unit = await catalog.record(admin, unit_command)
        assert (await catalog.record(admin, unit_command)).replayed
        review_development = ReviewDevelopmentFacts(
            development.subject_id,
            FactsReviewState.APPROVED,
            {"city": "Zapopan", "stage": "Validated"},
            "development:review",
        )
        await catalog.record(admin, review_development)
        assert (await catalog.record(admin, review_development)).replayed
        review_unit = ReviewUnitModelFacts(
            unit.subject_id,
            FactsReviewState.APPROVED,
            {"property_type": "Apartment", "bedrooms": 2},
            "unit:review",
        )
        await catalog.record(admin, review_unit)
        listing = await catalog.record(
            admin,
            CreateListing(
                "modelo-revisado-larevia",
                "Organization",
                "Larevia",
                "Material del desarrollo",
                "Modelo revisado",
                "Zapopan",
                {"kind": "DeveloperMaterial"},
                "unit:listing",
                unit_model_id=unit.subject_id,
            ),
        )
        await catalog.record(
            admin,
            ReviewListingFacts(
                listing.subject_id,
                FactsReviewState.APPROVED,
                {"public_location": "Zapopan"},
                "unit:listing:review",
            ),
        )
        await catalog.record(
            admin,
            SetListingAuthority(
                listing.subject_id,
                ListingAuthority.AUTHORIZED,
                "Contrato del desarrollo",
                datetime.now(tz=UTC),
                None,
                "unit:authority",
            ),
        )
        await catalog.record(
            admin,
            SetListingAvailability(
                listing.subject_id,
                ListingAvailability.AVAILABLE,
                "unit:available",
            ),
        )
        offers = OfferManagement(session)
        await offers.record(
            admin,
            RecordOffer(
                listing.subject_id,
                "Presale",
                Decimal("250000"),
                "USD",
                "Visible",
                {},
                "Approved",
                "Available",
                "unit:presale",
            ),
        )
        with pytest.raises(InvalidTransition, match="propiedad física"):
            await offers.record(
                admin,
                CompleteOperation(
                    listing.subject_id,
                    "Presale",
                    "unit:presale:complete",
                ),
            )
        await session.commit()

        row = await CatalogProjection(session, admin).get_for_administration(
            listing.subject_id,
            datetime.now(tz=UTC),
        )
        assert row.unit_model_id == unit.subject_id
        assert row.physical_name == "Modelo revisado"
        projected = await CatalogProjection(session, admin).get_authorized_listing(
            AuthorizedListingQuery(
                purpose=EligibilityPurpose.RECOMMEND,
                at=datetime.now(tz=UTC),
                listing_key="modelo-revisado-larevia",
            )
        )
        assert projected.unit_model_id == unit.subject_id
        assert projected.presentation_tier == "Premium"
        assert await session.get(Property, unit.subject_id) is None
        model = await session.get(UnitModel, unit.subject_id)
        assert model is not None and model.facts_review_state == "Approved"


async def test_catalog_identity_replays_duplicates_missing_rows_and_query_shape(
    database,
) -> None:
    admin, property_id, listing_id = await _listing(database, "identity")
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        property_command = CreateProperty(
            "casa-identity-two",
            "Casa identity",
            "House",
            {},
            {"kind": "Test"},
            "identity:property",
        )
        prop = await catalog.record(admin, property_command)
        assert (await catalog.record(admin, property_command)).replayed
        with pytest.raises(InvalidTransition, match="clave"):
            await catalog.record(
                admin,
                replace(property_command, command_key="identity:property:duplicate"),
            )
        listing_command = CreateListing(
            "identity-listing-two",
            "Organization",
            "Larevia",
            "Inventario propio",
            "Casa identity",
            None,
            {"kind": "Test"},
            "identity:listing",
            property_uuid=prop.subject_id,
        )
        created = await catalog.record(admin, listing_command)
        assert (await catalog.record(admin, listing_command)).replayed
        with pytest.raises(InvalidTransition, match="clave"):
            await catalog.record(
                admin,
                replace(listing_command, command_key="identity:listing:duplicate"),
            )
        with pytest.raises(NotFound):
            await catalog.record(
                admin,
                ReviewPropertyFacts(
                    uuid.uuid4(), FactsReviewState.APPROVED, {}, "identity:missing-review"
                ),
            )
        with pytest.raises(NotFound):
            await CatalogAdministration(session).record(
                admin,
                SetListingAvailability(
                    uuid.uuid4(), ListingAvailability.AVAILABLE, "identity:missing-listing"
                ),
            )
        with pytest.raises(NotFound):
            await ListingEligibility(session, admin).evaluate(
                uuid.uuid4(), EligibilityPurpose.RECOMMEND, datetime.now(tz=UTC)
            )
        projection = CatalogProjection(session, admin)
        with pytest.raises(ValueError, match="Exactly one"):
            await projection.get_authorized_listing(
                AuthorizedListingQuery(
                    purpose=EligibilityPurpose.RECOMMEND,
                    at=datetime.now(tz=UTC),
                )
            )
        with pytest.raises(ValueError, match="Exactly one"):
            await projection.get_authorized_listing(
                AuthorizedListingQuery(
                    purpose=EligibilityPurpose.RECOMMEND,
                    at=datetime.now(tz=UTC),
                    listing_id=listing_id,
                    property_uuid=property_id,
                )
            )
        actor_without_member = Actor(
            organization_id=admin.organization_id,
            authority=Authority.ADVISOR,
            member_id=None,
            label="advisor-without-member",
            display_name="Advisor sin miembro",
        )
        with pytest.raises(NotFound):
            await CatalogProjection(session, actor_without_member).list_for_administration(
                datetime.now(tz=UTC)
            )
        assert created.subject_id != listing_id


async def test_media_duplicate_cleanup_and_cache_retry_are_recoverable(database) -> None:
    _admin, _property_id, listing_id = await _listing(database, "media-duplicate")
    storage = InMemoryMediaStorage()
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        base = AddMedia(
            listing_id,
            "uno.jpg",
            "image/jpeg",
            b"\xff\xd8\xffone",
            "Propietario",
            ListingAuthority.AUTHORIZED,
            "Autorización escrita",
            True,
            0,
            "Fachada",
            True,
            ("cache/uno.jpg",),
            "media:duplicate:first",
        )
        media_id = (
            await MediaAdministration(session, storage).record(admin, base)
        ).media_id
        with pytest.raises(InvalidTransition, match="duplica"):
            await MediaAdministration(session, storage).record(
                admin,
                replace(
                    base,
                    original_filename="dos.jpg",
                    content=b"\xff\xd8\xfftwo",
                    command_key="media:duplicate:second",
                ),
            )
        assert len(storage.objects) == 1
        storage.cache_objects.add("cache/uno.jpg")
        storage.fail_cache_once = True
        command = RevokeMedia(media_id, "media:cache-retry")
        with pytest.raises(MediaCleanupPending):
            await MediaAdministration(session, storage).record(admin, command)

    async with database.session_scope() as restarted:
        admin = await actor_for(restarted, ADMIN_LOGIN)
        result = await MediaAdministration(restarted, storage).record(admin, command)
        assert result.replayed
        assert not storage.cache_objects
        assert not storage.objects


async def test_presale_completion_replay_missing_listing_and_readiness_reasons(
    database,
) -> None:
    _admin, property_id, listing_id = await _listing(database, "presale-readiness")
    storage = InMemoryMediaStorage()
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        offers = OfferManagement(session)
        with pytest.raises(NotFound):
            await offers.record(
                admin,
                RecordOffer(
                    uuid.uuid4(),
                    "Sale",
                    Decimal("1"),
                    "MXN",
                    "Visible",
                    {},
                    "Approved",
                    "Available",
                    "offer:missing-listing",
                ),
            )
        await _approve_for_private_use(session, admin, property_id, listing_id)
        await offers.record(
            admin,
            RecordOffer(
                listing_id,
                "Sale",
                Decimal("100000"),
                "USD",
                "Visible",
                {},
                "Pending",
                "Available",
                "offer:pending-terms",
            ),
        )
        await MediaAdministration(session, storage).record(
            admin,
            AddMedia(
                listing_id,
                "portada.webp",
                "image/webp",
                b"RIFFxxxxWEBPsynthetic",
                "Propietario",
                ListingAuthority.AUTHORIZED,
                "Autorización escrita",
                True,
                0,
                "Fachada",
                False,
                (),
                "media:low-resolution-cover",
            ),
        )
        decision = await ListingEligibility(session, admin).evaluate(
            listing_id,
            EligibilityPurpose.PUBLISH,
            datetime.now(tz=UTC),
        )
        assert "hay términos comerciales pendientes de revisión" in decision.reasons
        assert (
            "la portada debe estar confirmada en alta resolución"
            in decision.readiness.reasons
        )

        await offers.record(
            admin,
            RecordOffer(
                listing_id,
                "Presale",
                Decimal("13000000"),
                "MXN",
                "Visible",
                {},
                "Approved",
                "Available",
                "offer:presale:physical",
            ),
        )
        command = CompleteOperation(
            listing_id,
            "Presale",
            "offer:presale:physical:complete",
        )
        completed = await offers.record(admin, command)
        await session.commit()
        replay = await offers.record(admin, command)
        assert completed.offer_id == replay.offer_id
        assert replay.replayed
        presale = await session.get(ListingOffer, completed.offer_id)
        assert presale is not None
        assert presale.availability == "Completed"
        assert presale.unavailable_reason == "CompletedPresale"

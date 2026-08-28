"""Authoritative Property, Development, Unit Model and Listing commands.

One ``record`` interface owns organization scope, authorization, idempotency,
state transitions and audit.  Routers and future import adapters submit facts;
they do not recreate catalog policy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CatalogListing,
    Development,
    FactsReviewState,
    ListingAuthority,
    ListingAvailability,
    ListingPublicationState,
    ListingSourceKind,
    ListingOffer,
    OfferAvailability,
    Property,
    PropertyStatus,
    UnitModel,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import Actor, InvalidTransition, NotFound
from realestate.domain.commercial.idempotency import CommercialCommands
from realestate.domain.property_document import PROPERTY_KEY_PATTERN, normalize_name
from realestate.domain.catalog.presentation import (
    OfferPresentation,
    automatic_presentation_tier,
)

PRESENTATION_POLICY_VERSION = "initial-2026-08-pending-san-058"


@dataclass(frozen=True)
class CreateProperty:
    property_key: str
    name: str
    property_type: str
    facts: dict[str, Any]
    provenance: dict[str, Any]
    command_key: str
    development_id: uuid.UUID | None = None
    unit_model_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CreateDevelopment:
    development_key: str
    name: str
    facts: dict[str, Any]
    provenance: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class CreateUnitModel:
    development_id: uuid.UUID
    model_key: str
    name: str
    facts: dict[str, Any]
    provenance: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class CreateListing:
    listing_key: str
    source_kind: str
    source_name: str
    attribution: str
    title: str
    public_location: str | None
    provenance: dict[str, Any]
    command_key: str
    property_uuid: uuid.UUID | None = None
    unit_model_id: uuid.UUID | None = None
    source_reference: str | None = None
    facts: dict[str, Any] | None = None


@dataclass(frozen=True)
class ImportLegacyDocument:
    """One-way compatibility cut from an accepted Property Document.

    Only Product may issue it.  It creates a Draft Organization Listing and
    Offer once; later document versions remain provenance and physical facts,
    never a second editable price or publication truth.
    """

    property_uuid: uuid.UUID
    document_version_id: uuid.UUID
    metadata: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class SyncLegacyPropertyStatus:
    """Temporary write-through while the Stage 0 status surface is removed."""

    property_uuid: uuid.UUID
    status: str
    inactive_reason: str | None
    command_key: str


@dataclass(frozen=True)
class ReviewPropertyFacts:
    property_uuid: uuid.UUID
    review_state: FactsReviewState
    facts: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class ReviewDevelopmentFacts:
    development_id: uuid.UUID
    review_state: FactsReviewState
    facts: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class ReviewUnitModelFacts:
    unit_model_id: uuid.UUID
    review_state: FactsReviewState
    facts: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class SetListingAuthority:
    listing_id: uuid.UUID
    authority: ListingAuthority
    evidence: str | None
    checked_at: datetime
    revalidate_by: datetime | None
    command_key: str


@dataclass(frozen=True)
class SetListingAvailability:
    listing_id: uuid.UUID
    availability: ListingAvailability
    command_key: str


@dataclass(frozen=True)
class ReviewListingFacts:
    listing_id: uuid.UUID
    review_state: FactsReviewState
    facts: dict[str, Any]
    command_key: str


@dataclass(frozen=True)
class SetTierOverride:
    listing_id: uuid.UUID
    tier: str | None
    command_key: str


@dataclass(frozen=True)
class SetReadinessOverride:
    listing_id: uuid.UUID
    enabled: bool
    command_key: str


@dataclass(frozen=True)
class SetPublicationState:
    listing_id: uuid.UUID
    state: ListingPublicationState
    command_key: str


Command = (
    CreateProperty
    | CreateDevelopment
    | CreateUnitModel
    | CreateListing
    | ImportLegacyDocument
    | SyncLegacyPropertyStatus
    | ReviewPropertyFacts
    | ReviewDevelopmentFacts
    | ReviewUnitModelFacts
    | SetListingAuthority
    | SetListingAvailability
    | ReviewListingFacts
    | SetTierOverride
    | SetReadinessOverride
    | SetPublicationState
)


@dataclass(frozen=True)
class CatalogRecorded:
    subject_type: str
    subject_id: uuid.UUID
    replayed: bool


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _required(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidTransition(f"{label} es obligatorio.")
    return cleaned


def _key(value: str, label: str) -> str:
    cleaned = _required(value, label)
    if len(cleaned) > 140 or not PROPERTY_KEY_PATTERN.fullmatch(cleaned):
        raise InvalidTransition(
            f"{label} debe usar minúsculas, números y guiones simples."
        )
    return cleaned


class CatalogAdministration:
    """The catalog write module.  One entry point, all invariants inside."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._commands = CommercialCommands(session)

    async def record(self, actor: Actor, command: Command) -> CatalogRecorded:
        if isinstance(command, (ImportLegacyDocument, SyncLegacyPropertyStatus)):
            if not actor.is_product:
                actor.require_administrator()
            if isinstance(command, ImportLegacyDocument):
                return await self._import_legacy(actor, command)
            return await self._sync_legacy_status(actor, command)
        actor.require_administrator()
        if isinstance(command, CreateProperty):
            return await self._create_property(actor, command)
        if isinstance(command, CreateDevelopment):
            return await self._create_development(actor, command)
        if isinstance(command, CreateUnitModel):
            return await self._create_unit_model(actor, command)
        if isinstance(command, CreateListing):
            return await self._create_listing(actor, command)
        if isinstance(command, ReviewPropertyFacts):
            return await self._review_property(actor, command)
        if isinstance(command, ReviewDevelopmentFacts):
            return await self._review_development(actor, command)
        if isinstance(command, ReviewUnitModelFacts):
            return await self._review_unit_model(actor, command)
        return await self._mutate_listing(actor, command)

    async def _sync_legacy_status(
        self, actor: Actor, command: SyncLegacyPropertyStatus
    ) -> CatalogRecorded:
        prop = await self._session.get(Property, command.property_uuid)
        if prop is None:
            raise NotFound("No encontramos esa propiedad física.")
        actor.require_same_organization(prop.organization_id)
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="SyncLegacyPropertyStatus",
            subject_type="Property",
            subject_id=str(prop.id),
            payload={
                "status": command.status,
                "inactive_reason": command.inactive_reason,
            },
        )
        listings = list(
            await self._session.scalars(
                select(CatalogListing)
                .where(CatalogListing.property_uuid == prop.id)
                .with_for_update()
            )
        )
        if replayed:
            return CatalogRecorded("Property", prop.id, True)
        mapping = {
            None: ListingAvailability.AVAILABLE,
            "Sold": ListingAvailability.SOLD,
            "Rented": ListingAvailability.RENTED,
            "Reserved": ListingAvailability.RESERVED,
            "TemporarilyUnavailable": ListingAvailability.TEMPORARILY_UNAVAILABLE,
            "Withdrawn": ListingAvailability.TEMPORARILY_UNAVAILABLE,
            "Unspecified": ListingAvailability.UNKNOWN,
        }
        target = (
            ListingAvailability.AVAILABLE
            if command.status == PropertyStatus.ACTIVE.value
            else mapping.get(command.inactive_reason, ListingAvailability.UNKNOWN)
        )
        listing_ids = [row.id for row in listings]
        offers = list(
            await self._session.scalars(
                select(ListingOffer)
                .where(ListingOffer.listing_id.in_(listing_ids))
                .with_for_update()
            )
        ) if listing_ids else []
        for listing in listings:
            listing.availability = target.value
            listing.updated_at = _now()
        for offer in offers:
            if command.status == PropertyStatus.ACTIVE.value:
                offer.availability = OfferAvailability.AVAILABLE.value
                offer.unavailable_reason = None
            elif command.inactive_reason == "Sold":
                offer.availability = OfferAvailability.COMPLETED.value
                offer.unavailable_reason = "Sold"
            elif command.inactive_reason == "Rented":
                offer.availability = (
                    OfferAvailability.COMPLETED.value
                    if offer.operation == "Rental"
                    else OfferAvailability.TEMPORARILY_UNAVAILABLE.value
                )
                offer.unavailable_reason = "Rented"
            elif command.inactive_reason == "Reserved":
                offer.availability = OfferAvailability.RESERVED.value
                offer.unavailable_reason = "Reserved"
            elif command.inactive_reason == "Withdrawn":
                offer.availability = OfferAvailability.WITHDRAWN.value
                offer.unavailable_reason = "Withdrawn"
            elif command.inactive_reason == "TemporarilyUnavailable":
                offer.availability = OfferAvailability.TEMPORARILY_UNAVAILABLE.value
                offer.unavailable_reason = "TemporarilyUnavailable"
            else:
                offer.availability = OfferAvailability.UNKNOWN.value
                offer.unavailable_reason = "Unspecified"
            offer.updated_at = _now()
        for listing in listings:
            active_presentations = [
                OfferPresentation(
                    operation=offer.operation,
                    price=offer.price_amount,
                    currency=offer.price_currency,
                )
                for offer in offers
                if offer.listing_id == listing.id
                and offer.availability == OfferAvailability.AVAILABLE.value
            ]
            tier = automatic_presentation_tier(
                prop.property_type,
                active_presentations,
            )
            listing.automatic_tier = tier.value if tier is not None else None
            listing.presentation_policy_version = PRESENTATION_POLICY_VERSION
        await self._audit(
            actor,
            "SyncLegacyPropertyStatus",
            "Property",
            prop.id,
            {
                "legacy_status": command.status,
                "legacy_inactive_reason": command.inactive_reason,
                "listing_ids": [str(row.id) for row in listings],
            },
        )
        await self._session.flush()
        return CatalogRecorded("Property", prop.id, False)

    async def _import_legacy(
        self, actor: Actor, command: ImportLegacyDocument
    ) -> CatalogRecorded:
        prop = await self._session.get(Property, command.property_uuid)
        if prop is None:
            raise NotFound("No encontramos esa propiedad física.")
        actor.require_same_organization(prop.organization_id)
        listing_key = f"{prop.property_key}-legacy"
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="ImportLegacyPropertyDocument",
            subject_type="CatalogListing",
            subject_id=listing_key,
            payload={
                "property_uuid": prop.id,
                "document_version_id": command.document_version_id,
                "metadata": command.metadata,
            },
        )
        existing = await self._session.scalar(
            select(CatalogListing).where(
                CatalogListing.organization_id == actor.organization_id,
                CatalogListing.listing_key == listing_key,
            )
        )
        if replayed:
            if existing is None:
                raise InvalidTransition(
                    "La importación existe pero su publicación no está disponible."
                )
            return CatalogRecorded("CatalogListing", existing.id, True)
        if existing is not None:
            # A later immutable document version is provenance for physical
            # facts.  The already-cut Listing/Offer remain the only editable
            # commercial truth.
            return CatalogRecorded("CatalogListing", existing.id, False)

        metadata = command.metadata
        operation = str(metadata.get("operation", ""))
        currency = str(metadata.get("price_currency", ""))
        try:
            price = Decimal(str(metadata.get("price_amount", "")))
        except Exception as exc:
            raise InvalidTransition(
                "El documento aceptado no tiene un precio compatible."
            ) from exc
        if operation not in {"Sale", "Rental"} or currency not in {"MXN", "USD"}:
            raise InvalidTransition(
                "El documento aceptado no tiene una operación o moneda compatible."
            )
        tier = automatic_presentation_tier(
            prop.property_type,
            [OfferPresentation(operation, price, currency)],
        )
        location = ", ".join(
            str(metadata.get(key, "")).strip()
            for key in ("neighborhood", "city", "state")
            if str(metadata.get(key, "")).strip()
        )
        listing = CatalogListing(
            organization_id=actor.organization_id,
            listing_key=listing_key,
            property_uuid=prop.id,
            source_kind=ListingSourceKind.ORGANIZATION.value,
            source_name="Catálogo Larevia",
            attribution="Inventario propio de Larevia",
            provenance={
                "kind": "LegacyPropertyDocument",
                "document_version_id": str(command.document_version_id),
            },
            title=prop.name,
            public_location=location or None,
            facts=dict(prop.physical_facts),
            facts_review_state=prop.facts_review_state,
            availability=ListingAvailability.AVAILABLE.value,
            publication_state=ListingPublicationState.DRAFT.value,
            authority=ListingAuthority.AUTHORIZED.value,
            authority_evidence=(
                "Aceptación administrativa legacy del documento de propiedad"
            ),
            freshness_checked_at=_now(),
            automatic_tier=tier.value if tier is not None else None,
            presentation_policy_version=PRESENTATION_POLICY_VERSION,
            gallery_path=f"/catalogo/{listing_key}/galeria",
            technical_sheet_path=f"/catalogo/{listing_key}/ficha-tecnica",
            legacy_document_version_id=command.document_version_id,
            created_by=actor.label,
        )
        self._session.add(listing)
        await self._session.flush()
        offer = ListingOffer(
            organization_id=actor.organization_id,
            listing_id=listing.id,
            operation=operation,
            price_amount=price,
            price_currency=currency,
            price_visibility="Visible",
            terms={},
            terms_review_state=FactsReviewState.APPROVED.value,
            availability=OfferAvailability.AVAILABLE.value,
            legacy_document_version_id=command.document_version_id,
        )
        self._session.add(offer)
        await self._session.flush()
        await self._audit(
            actor,
            "ImportLegacyPropertyDocument",
            "CatalogListing",
            listing.id,
            {
                "property_uuid": str(prop.id),
                "document_version_id": str(command.document_version_id),
                "publication_state": listing.publication_state,
                "offer_id": str(offer.id),
            },
        )
        return CatalogRecorded("CatalogListing", listing.id, False)

    async def _review_property(
        self, actor: Actor, command: ReviewPropertyFacts
    ) -> CatalogRecorded:
        row = await self._session.scalar(
            select(Property)
            .where(Property.id == command.property_uuid)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa propiedad física.")
        actor.require_same_organization(row.organization_id)
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="ReviewPhysicalPropertyFacts",
            subject_type="Property",
            subject_id=str(row.id),
            payload={
                "review_state": command.review_state.value,
                "facts": command.facts,
            },
        )
        if replayed:
            return CatalogRecorded("Property", row.id, True)
        before = row.facts_review_state
        row.physical_facts = dict(command.facts)
        row.facts_review_state = command.review_state.value
        row.facts_reviewed_by = actor.member_id
        row.facts_reviewed_at = _now()
        row.updated_at = _now()
        await self._audit(
            actor,
            "ReviewPhysicalPropertyFacts",
            "Property",
            row.id,
            {"before": before, "after": row.facts_review_state},
        )
        await self._session.flush()
        return CatalogRecorded("Property", row.id, False)

    async def _review_development(
        self, actor: Actor, command: ReviewDevelopmentFacts
    ) -> CatalogRecorded:
        row = await self._development(actor, command.development_id)
        return await self._review_subject_facts(
            actor,
            row,
            command.review_state,
            command.facts,
            command.command_key,
            operation="ReviewDevelopmentFacts",
            subject_type="Development",
        )

    async def _review_unit_model(
        self, actor: Actor, command: ReviewUnitModelFacts
    ) -> CatalogRecorded:
        row = await self._session.get(UnitModel, command.unit_model_id)
        if row is None:
            raise NotFound("No encontramos ese modelo.")
        actor.require_same_organization(row.organization_id)
        return await self._review_subject_facts(
            actor,
            row,
            command.review_state,
            command.facts,
            command.command_key,
            operation="ReviewUnitModelFacts",
            subject_type="UnitModel",
        )

    async def _review_subject_facts(
        self,
        actor: Actor,
        row: Development | UnitModel,
        review_state: FactsReviewState,
        facts: dict[str, Any],
        command_key: str,
        *,
        operation: str,
        subject_type: str,
    ) -> CatalogRecorded:
        replayed = await self._commands.claim(
            actor,
            command_key=command_key,
            operation=operation,
            subject_type=subject_type,
            subject_id=str(row.id),
            payload={"review_state": review_state.value, "facts": facts},
        )
        if replayed:
            return CatalogRecorded(subject_type, row.id, True)
        before = row.facts_review_state
        row.facts = dict(facts)
        row.facts_review_state = review_state.value
        row.reviewed_by = actor.member_id
        row.reviewed_at = _now()
        row.updated_at = _now()
        await self._audit(
            actor,
            operation,
            subject_type,
            row.id,
            {"before": before, "after": row.facts_review_state},
        )
        await self._session.flush()
        return CatalogRecorded(subject_type, row.id, False)

    async def _create_property(
        self, actor: Actor, command: CreateProperty
    ) -> CatalogRecorded:
        key = _key(command.property_key, "La clave de la propiedad")
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="CreatePhysicalProperty",
            subject_type="Property",
            subject_id=key,
            payload={
                "name": command.name,
                "property_type": command.property_type,
                "facts": command.facts,
                "provenance": command.provenance,
                "development_id": command.development_id,
                "unit_model_id": command.unit_model_id,
            },
        )
        if replayed:
            row = await self._session.scalar(
                select(Property).where(
                    Property.organization_id == actor.organization_id,
                    Property.property_key == key,
                )
            )
            if row is None:
                raise InvalidTransition(
                    "La operación existe pero su propiedad no está disponible."
                )
            return CatalogRecorded("Property", row.id, True)

        await self._validate_development_links(
            actor, command.development_id, command.unit_model_id
        )
        existing = await self._session.scalar(
            select(Property).where(Property.property_key == key)
        )
        if existing is not None:
            raise InvalidTransition("Ya existe una propiedad con esa clave.")
        row = Property(
            organization_id=actor.organization_id,
            property_key=key,
            name=_required(command.name, "El nombre"),
            normalized_name=normalize_name(command.name),
            status=PropertyStatus.ACTIVE.value,
            inactive_reason=None,
            property_type=_required(command.property_type, "El tipo de propiedad"),
            physical_facts=dict(command.facts),
            facts_review_state=FactsReviewState.PENDING.value,
            provenance=dict(command.provenance),
            development_id=command.development_id,
            unit_model_id=command.unit_model_id,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit(actor, "CreatePhysicalProperty", "Property", row.id, {
            "property_key": key,
            "facts_review_state": row.facts_review_state,
        })
        return CatalogRecorded("Property", row.id, False)

    async def _create_development(
        self, actor: Actor, command: CreateDevelopment
    ) -> CatalogRecorded:
        key = _key(command.development_key, "La clave del desarrollo")
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="CreateDevelopment",
            subject_type="Development",
            subject_id=key,
            payload={"name": command.name, "facts": command.facts, "provenance": command.provenance},
        )
        existing = await self._session.scalar(
            select(Development).where(
                Development.organization_id == actor.organization_id,
                Development.development_key == key,
            )
        )
        if replayed:
            if existing is None:
                raise InvalidTransition(
                    "La operación existe pero su desarrollo no está disponible."
                )
            return CatalogRecorded("Development", existing.id, True)
        if existing is not None:
            raise InvalidTransition("Ya existe un desarrollo con esa clave.")
        row = Development(
            organization_id=actor.organization_id,
            development_key=key,
            name=_required(command.name, "El nombre"),
            facts=dict(command.facts),
            facts_review_state=FactsReviewState.PENDING.value,
            provenance=dict(command.provenance),
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit(actor, "CreateDevelopment", "Development", row.id, {})
        return CatalogRecorded("Development", row.id, False)

    async def _create_unit_model(
        self, actor: Actor, command: CreateUnitModel
    ) -> CatalogRecorded:
        key = _key(command.model_key, "La clave del modelo")
        development = await self._development(actor, command.development_id)
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="CreateUnitModel",
            subject_type="UnitModel",
            subject_id=f"{development.id}:{key}",
            payload={"name": command.name, "facts": command.facts, "provenance": command.provenance},
        )
        existing = await self._session.scalar(
            select(UnitModel).where(
                UnitModel.development_id == development.id,
                UnitModel.model_key == key,
            )
        )
        if replayed:
            if existing is None:
                raise InvalidTransition(
                    "La operación existe pero su modelo no está disponible."
                )
            return CatalogRecorded("UnitModel", existing.id, True)
        if existing is not None:
            raise InvalidTransition("Ya existe un modelo con esa clave.")
        row = UnitModel(
            organization_id=actor.organization_id,
            development_id=development.id,
            model_key=key,
            name=_required(command.name, "El nombre"),
            facts=dict(command.facts),
            facts_review_state=FactsReviewState.PENDING.value,
            provenance=dict(command.provenance),
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit(actor, "CreateUnitModel", "UnitModel", row.id, {})
        return CatalogRecorded("UnitModel", row.id, False)

    async def _create_listing(
        self, actor: Actor, command: CreateListing
    ) -> CatalogRecorded:
        key = _key(command.listing_key, "La clave de la publicación")
        if (command.property_uuid is None) == (command.unit_model_id is None):
            raise InvalidTransition(
                "La publicación debe corresponder a una propiedad física o a un "
                "modelo, pero no a ambos."
            )
        await self._listing_subject(actor, command.property_uuid, command.unit_model_id)
        try:
            source_kind = ListingSourceKind(command.source_kind)
        except ValueError as exc:
            raise InvalidTransition(
                "La fuente debe ser inventario propio o de colaborador."
            ) from exc
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="CreateCatalogListing",
            subject_type="CatalogListing",
            subject_id=key,
            payload={
                "property_uuid": command.property_uuid,
                "unit_model_id": command.unit_model_id,
                "source_kind": source_kind.value,
                "source_name": command.source_name,
                "source_reference": command.source_reference,
                "attribution": command.attribution,
                "title": command.title,
                "public_location": command.public_location,
                "facts": command.facts or {},
                "provenance": command.provenance,
            },
        )
        existing = await self._session.scalar(
            select(CatalogListing).where(
                CatalogListing.organization_id == actor.organization_id,
                CatalogListing.listing_key == key,
            )
        )
        if replayed:
            if existing is None:
                raise InvalidTransition(
                    "La operación existe pero su publicación no está disponible."
                )
            return CatalogRecorded("CatalogListing", existing.id, True)
        if existing is not None:
            raise InvalidTransition("Ya existe una publicación con esa clave.")
        row = CatalogListing(
            organization_id=actor.organization_id,
            listing_key=key,
            property_uuid=command.property_uuid,
            unit_model_id=command.unit_model_id,
            source_kind=source_kind.value,
            source_name=_required(command.source_name, "La fuente"),
            source_reference=(command.source_reference or "").strip() or None,
            attribution=_required(command.attribution, "La atribución"),
            provenance=dict(command.provenance),
            title=_required(command.title, "El título"),
            public_location=(command.public_location or "").strip() or None,
            facts=dict(command.facts or {}),
            facts_review_state=FactsReviewState.PENDING.value,
            availability=ListingAvailability.UNKNOWN.value,
            publication_state=ListingPublicationState.DRAFT.value,
            authority=ListingAuthority.PENDING.value,
            automatic_tier=None,
            presentation_policy_version=PRESENTATION_POLICY_VERSION,
            gallery_path=f"/catalogo/{key}/galeria",
            technical_sheet_path=f"/catalogo/{key}/ficha-tecnica",
            created_by=actor.label,
        )
        self._session.add(row)
        await self._session.flush()
        await self._audit(actor, "CreateCatalogListing", "CatalogListing", row.id, {
            "source_kind": source_kind.value,
            "authority": row.authority,
            "publication_state": row.publication_state,
        })
        return CatalogRecorded("CatalogListing", row.id, False)

    async def _mutate_listing(
        self,
        actor: Actor,
        command: SetListingAuthority
        | SetListingAvailability
        | ReviewListingFacts
        | SetTierOverride
        | SetReadinessOverride
        | SetPublicationState,
    ) -> CatalogRecorded:
        listing = await self._listing(actor, command.listing_id, lock=True)
        operation = type(command).__name__
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation=operation,
            subject_type="CatalogListing",
            subject_id=str(listing.id),
            payload=command.__dict__,
        )
        if replayed:
            return CatalogRecorded("CatalogListing", listing.id, True)

        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        moment = _now()
        if isinstance(command, SetListingAuthority):
            if command.authority is ListingAuthority.AUTHORIZED and not (
                command.evidence or ""
            ).strip():
                raise InvalidTransition(
                    "Registra la evidencia antes de autorizar la publicación."
                )
            if command.revalidate_by is not None and command.revalidate_by <= command.checked_at:
                raise InvalidTransition(
                    "La revalidación debe vencer después de la fecha de revisión."
                )
            before = {"authority": listing.authority}
            listing.authority = command.authority.value
            listing.authority_evidence = (command.evidence or "").strip() or None
            listing.freshness_checked_at = command.checked_at
            listing.revalidate_by = command.revalidate_by
            after = {"authority": listing.authority}
        elif isinstance(command, SetListingAvailability):
            before = {"availability": listing.availability}
            listing.availability = command.availability.value
            after = {"availability": listing.availability}
        elif isinstance(command, ReviewListingFacts):
            before = {"facts_review_state": listing.facts_review_state}
            listing.facts = dict(command.facts)
            listing.facts_review_state = command.review_state.value
            after = {"facts_review_state": listing.facts_review_state}
        elif isinstance(command, SetTierOverride):
            allowed = {None, "Larevia", "Premium", "SuperPremium"}
            if command.tier not in allowed:
                raise InvalidTransition("El nivel de presentación no es válido.")
            before = {"tier_override": listing.tier_override}
            listing.tier_override = command.tier
            listing.tier_override_by = actor.member_id if command.tier else None
            listing.tier_override_at = moment if command.tier else None
            after = {"tier_override": listing.tier_override}
        elif isinstance(command, SetReadinessOverride):
            before = {"readiness_override": listing.readiness_override}
            listing.readiness_override = command.enabled
            listing.readiness_override_by = actor.member_id if command.enabled else None
            listing.readiness_override_at = moment if command.enabled else None
            after = {"readiness_override": listing.readiness_override}
        else:
            if command.state is ListingPublicationState.PUBLISHED:
                # Imported lazily to keep the administration module independent
                # from the read-side implementation except at this invariant.
                from realestate.domain.catalog.eligibility import (
                    EligibilityPurpose,
                    ListingEligibility,
                )

                decision = await ListingEligibility(self._session, actor).evaluate(
                    listing.id, EligibilityPurpose.PUBLISH, moment
                )
                if not decision.eligible:
                    raise InvalidTransition(
                        "La publicación no está lista: " + "; ".join(decision.reasons)
                    )
            before = {"publication_state": listing.publication_state}
            listing.publication_state = command.state.value
            after = {"publication_state": listing.publication_state}
        listing.updated_at = moment
        await self._audit(actor, operation, "CatalogListing", listing.id, {
            "before": before,
            "after": after,
        })
        await self._session.flush()
        return CatalogRecorded("CatalogListing", listing.id, False)

    async def _listing(
        self, actor: Actor, listing_id: uuid.UUID, *, lock: bool = False
    ) -> CatalogListing:
        statement = select(CatalogListing).where(CatalogListing.id == listing_id)
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise NotFound()
        actor.require_same_organization(row.organization_id)
        return row

    async def _development(self, actor: Actor, development_id: uuid.UUID) -> Development:
        row = await self._session.get(Development, development_id)
        if row is None:
            raise NotFound("No encontramos ese desarrollo.")
        actor.require_same_organization(row.organization_id)
        return row

    async def _validate_development_links(
        self,
        actor: Actor,
        development_id: uuid.UUID | None,
        unit_model_id: uuid.UUID | None,
    ) -> None:
        if unit_model_id is None:
            if development_id is not None:
                await self._development(actor, development_id)
            return
        model = await self._session.get(UnitModel, unit_model_id)
        if model is None:
            raise NotFound("No encontramos ese modelo.")
        actor.require_same_organization(model.organization_id)
        if development_id != model.development_id:
            raise InvalidTransition(
                "El modelo no pertenece al desarrollo indicado."
            )

    async def _listing_subject(
        self,
        actor: Actor,
        property_uuid: uuid.UUID | None,
        unit_model_id: uuid.UUID | None,
    ) -> None:
        if property_uuid is not None:
            row = await self._session.get(Property, property_uuid)
            if row is None:
                raise NotFound("No encontramos esa propiedad física.")
            actor.require_same_organization(row.organization_id)
            return
        assert unit_model_id is not None
        model = await self._session.get(UnitModel, unit_model_id)
        if model is None:
            raise NotFound("No encontramos ese modelo.")
        actor.require_same_organization(model.organization_id)

    async def _audit(
        self,
        actor: Actor,
        action: str,
        subject_type: str,
        subject_id: uuid.UUID,
        details: dict[str, Any],
    ) -> None:
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action=action,
            subject_type=subject_type,
            subject_id=str(subject_id),
            details=details,
            commit=False,
        )

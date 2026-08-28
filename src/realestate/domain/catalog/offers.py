"""Listing Offer commands and cross-Offer completion policy (ADR-0025)."""

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
    FactsReviewState,
    ListingAvailability,
    ListingOffer,
    ListingOfferOperation,
    OfferAvailability,
    Property,
    PublicPriceVisibility,
    UnitModel,
)
from realestate.domain.audit import record_audit
from realestate.domain.catalog.presentation import (
    OfferPresentation,
    automatic_presentation_tier,
)
from realestate.domain.commercial.actors import Actor, InvalidTransition, NotFound
from realestate.domain.commercial.idempotency import CommercialCommands

HIDDEN_PRICE_COPY = "Precio disponible previa consulta"


@dataclass(frozen=True)
class RecordOffer:
    listing_id: uuid.UUID
    operation: str
    price_amount: Decimal
    price_currency: str
    price_visibility: str
    terms: dict[str, Any]
    terms_review_state: str
    availability: str
    command_key: str


@dataclass(frozen=True)
class CompleteOperation:
    listing_id: uuid.UUID
    operation: str
    command_key: str


Command = RecordOffer | CompleteOperation


@dataclass(frozen=True)
class OfferRecorded:
    offer_id: uuid.UUID
    listing_id: uuid.UUID
    replayed: bool


def _now() -> datetime:
    return datetime.now(tz=UTC)


class OfferManagement:
    """One write interface for prices, terms, availability and completion."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._commands = CommercialCommands(session)

    async def record(self, actor: Actor, command: Command) -> OfferRecorded:
        actor.require_administrator()
        listing = await self._listing(actor, command.listing_id, lock=True)
        if isinstance(command, CompleteOperation):
            return await self._complete(actor, listing, command)
        return await self._upsert(actor, listing, command)

    async def _upsert(
        self, actor: Actor, listing: CatalogListing, command: RecordOffer
    ) -> OfferRecorded:
        try:
            operation = ListingOfferOperation(command.operation)
            visibility = PublicPriceVisibility(command.price_visibility)
            availability = OfferAvailability(command.availability)
            review = FactsReviewState(command.terms_review_state)
        except ValueError as exc:
            raise InvalidTransition(
                "La operación, visibilidad, disponibilidad o revisión no es válida."
            ) from exc
        if command.price_amount <= 0:
            raise InvalidTransition("El precio debe ser mayor que cero.")
        if command.price_currency not in {"MXN", "USD"}:
            raise InvalidTransition("La moneda debe ser MXN o USD.")

        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="RecordListingOffer",
            subject_type="ListingOffer",
            subject_id=f"{listing.id}:{operation.value}",
            payload={
                "listing_id": listing.id,
                "operation": operation.value,
                "price_amount": command.price_amount,
                "price_currency": command.price_currency,
                "price_visibility": visibility.value,
                "terms": command.terms,
                "terms_review_state": review.value,
                "availability": availability.value,
            },
        )
        row = await self._session.scalar(
            select(ListingOffer)
            .where(
                ListingOffer.listing_id == listing.id,
                ListingOffer.operation == operation.value,
            )
            .with_for_update()
        )
        if replayed:
            if row is None:
                raise InvalidTransition(
                    "La operación existe pero su oferta no está disponible."
                )
            return OfferRecorded(row.id, listing.id, True)

        before = None
        if row is None:
            row = ListingOffer(
                organization_id=actor.organization_id,
                listing_id=listing.id,
                operation=operation.value,
                price_amount=command.price_amount,
                price_currency=command.price_currency,
                price_visibility=visibility.value,
                hidden_price_copy=(
                    HIDDEN_PRICE_COPY
                    if visibility is PublicPriceVisibility.HIDDEN
                    else None
                ),
                terms=dict(command.terms),
                terms_review_state=review.value,
                availability=availability.value,
            )
            self._session.add(row)
        else:
            before = {
                "price_amount": str(row.price_amount),
                "price_currency": row.price_currency,
                "price_visibility": row.price_visibility,
                "availability": row.availability,
            }
            row.price_amount = command.price_amount
            row.price_currency = command.price_currency
            row.price_visibility = visibility.value
            row.hidden_price_copy = (
                HIDDEN_PRICE_COPY
                if visibility is PublicPriceVisibility.HIDDEN
                else None
            )
            row.terms = dict(command.terms)
            row.terms_review_state = review.value
            row.availability = availability.value
            row.unavailable_reason = None
            row.updated_at = _now()
        await self._session.flush()
        await self._recalculate_tier(listing)
        await self._audit(
            actor,
            "RecordListingOffer",
            row,
            {
                "before": before,
                "after": {
                    "operation": row.operation,
                    "price_amount": str(row.price_amount),
                    "price_currency": row.price_currency,
                    "price_visibility": row.price_visibility,
                    "availability": row.availability,
                },
            },
        )
        return OfferRecorded(row.id, listing.id, False)

    async def _complete(
        self, actor: Actor, listing: CatalogListing, command: CompleteOperation
    ) -> OfferRecorded:
        try:
            operation = ListingOfferOperation(command.operation)
        except ValueError as exc:
            raise InvalidTransition("La operación concluida no es válida.") from exc
        replayed = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="CompleteListingOperation",
            subject_type="CatalogListing",
            subject_id=f"{listing.id}:{operation.value}",
            payload={"listing_id": listing.id, "operation": operation.value},
        )
        selected = await self._session.scalar(
            select(ListingOffer).where(
                ListingOffer.listing_id == listing.id,
                ListingOffer.operation == operation.value,
            )
        )
        if selected is None:
            raise NotFound("No encontramos esa oferta.")
        if replayed:
            return OfferRecorded(selected.id, listing.id, True)
        if listing.property_uuid is None:
            raise InvalidTransition(
                "Un modelo de desarrollo no puede concluir una operación sin una "
                "propiedad física identificada."
            )

        related = list(
            await self._session.scalars(
                select(CatalogListing)
                .where(CatalogListing.property_uuid == listing.property_uuid)
                .with_for_update()
            )
        )
        related_ids = [row.id for row in related]
        offers = list(
            await self._session.scalars(
                select(ListingOffer)
                .where(ListingOffer.listing_id.in_(related_ids))
                .with_for_update()
            )
        )
        if operation is ListingOfferOperation.SALE:
            affected = offers
            for row in related:
                row.availability = ListingAvailability.SOLD.value
            reason = "Sold"
        elif operation is ListingOfferOperation.RENTAL:
            affected = [
                row
                for row in offers
                if row.operation == ListingOfferOperation.RENTAL.value
            ]
            reason = "Rented"
        else:
            affected = [row for row in offers if row.id == selected.id]
            reason = "CompletedPresale"

        moment = _now()
        for offer in affected:
            offer.availability = OfferAvailability.COMPLETED.value
            offer.unavailable_reason = reason
            offer.updated_at = moment

        if operation is ListingOfferOperation.RENTAL:
            active_by_listing = {
                row.listing_id
                for row in offers
                if row.operation != ListingOfferOperation.RENTAL.value
                and row.availability == OfferAvailability.AVAILABLE.value
            }
            for row in related:
                row.availability = (
                    ListingAvailability.AVAILABLE.value
                    if row.id in active_by_listing
                    else ListingAvailability.RENTED.value
                )
        for row in related:
            row.updated_at = moment
            await self._recalculate_tier(row)
        await self._audit(
            actor,
            "CompleteListingOperation",
            selected,
            {
                "operation": operation.value,
                "physical_property_id": str(listing.property_uuid),
                "affected_listing_ids": [str(row.id) for row in related],
                "affected_offer_ids": [str(row.id) for row in affected],
            },
        )
        await self._session.flush()
        return OfferRecorded(selected.id, listing.id, False)

    async def _recalculate_tier(self, listing: CatalogListing) -> None:
        offers = list(
            await self._session.scalars(
                select(ListingOffer).where(
                    ListingOffer.listing_id == listing.id,
                    ListingOffer.availability == OfferAvailability.AVAILABLE.value,
                )
            )
        )
        property_type = await self._property_type(listing)
        tier = automatic_presentation_tier(
            property_type,
            [
                OfferPresentation(row.operation, row.price_amount, row.price_currency)
                for row in offers
            ],
        )
        listing.automatic_tier = tier.value if tier is not None else None
        listing.updated_at = _now()

    async def _property_type(self, listing: CatalogListing) -> str:
        if listing.property_uuid is not None:
            prop = await self._session.get(Property, listing.property_uuid)
            return prop.property_type if prop is not None else "Other"
        model = await self._session.get(UnitModel, listing.unit_model_id)
        return str(model.facts.get("property_type", "Other")) if model else "Other"

    async def _listing(
        self, actor: Actor, listing_id: uuid.UUID, *, lock: bool
    ) -> CatalogListing:
        statement = select(CatalogListing).where(CatalogListing.id == listing_id)
        if lock:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise NotFound()
        actor.require_same_organization(row.organization_id)
        return row

    async def _audit(
        self,
        actor: Actor,
        action: str,
        offer: ListingOffer,
        details: dict[str, Any],
    ) -> None:
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action=action,
            subject_type="ListingOffer",
            subject_id=str(offer.id),
            details=details,
            commit=False,
        )

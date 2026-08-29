"""``SponsorshipQuoting.quote`` — a seven-day offer that holds nothing.

Three rules, each one the answer to a way quoting usually goes wrong:

**A quote preserves its catalog version.** The stored version and the amounts are
copied onto the row. When the Administrator publishes new prices tomorrow, the
quote a buyer is still considering does not silently change under them, and
accepting it charges what it said.

**A discount needs a reason.** Enforced here and by a check constraint, because
"we gave them a break" with nobody's name on it is how a price list stops meaning
anything. The reason is free text on purpose: it is written for a human reading
the campaign later, not for a report.

**Issuing reserves nothing.** Capacity is held only when the quote is accepted.
ADR-0043 lets a quote expire in seven days, and a stalled negotiation must not be
able to make a surface look sold out.

Accepting is where money would appear in a different product. Here it records a
reservation and a collection state somebody observed elsewhere; Product issues no
invoice and moves nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipQuote,
    SponsorshipQuoteStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotFound,
)
from realestate.domain.sponsorship.capacity import SponsorshipCapacity, SurfaceForecast
from realestate.domain.sponsorship.eligibility import SponsoredEligibility
from realestate.domain.sponsorship.labels import (
    NON_CAUSAL_DISCLAIMER,
    SPONSORED_DISCLOSURE,
)
from realestate.domain.sponsorship.pricing import (
    DEFAULT_DURATION_DAYS,
    PACKAGE_SURFACES,
    PackageUnpriced,
    SponsorshipPricing,
)

#: ADR-0043: a quote expires after seven days without reserving capacity.
QUOTE_VALID_DAYS = 7


class QuoteRefused(CommercialError):
    """The quote cannot be issued or accepted as asked."""

    message = "No se puede emitir la cotización con esos datos."


class QuoteExpired(CommercialError):
    """The quote's seven days have passed."""

    message = "La cotización venció. Emite una nueva con el catálogo vigente."


@dataclass(frozen=True)
class QuoteCommand:
    """One quote request. ``command_key`` makes a double submission one quote."""

    campaign_id: uuid.UUID
    command_key: str
    duration_days: int = DEFAULT_DURATION_DAYS
    discount_amount: Decimal = Decimal("0")
    discount_reason: str = ""


@dataclass(frozen=True)
class AcceptQuote:
    quote_id: uuid.UUID
    starts_on: datetime


@dataclass(frozen=True)
class QuoteView:
    """Everything a presale conversation needs, and nothing it must not claim."""

    quote_id: uuid.UUID
    campaign_id: uuid.UUID
    catalog_version: str
    package: str
    surfaces: tuple[str, ...]
    duration_days: int
    list_amount: Decimal
    discount_amount: Decimal
    discount_reason: str | None
    total_amount: Decimal
    currency: str
    status: str
    issued_at: datetime
    expires_at: datetime
    capacity: tuple[SurfaceForecast, ...] = ()
    #: The label and the two sentences that must travel with any price.
    disclosure: str = SPONSORED_DISCLOSURE
    disclaimer: str = NON_CAUSAL_DISCLAIMER

    def expired(self, at: datetime) -> bool:
        return at >= self.expires_at


def view_of(
    row: SponsorshipQuote,
    surfaces: tuple[str, ...],
    capacity: tuple[SurfaceForecast, ...] = (),
) -> QuoteView:
    return QuoteView(
        quote_id=row.id,
        campaign_id=row.campaign_id,
        catalog_version=row.catalog_version,
        package=row.package,
        surfaces=surfaces,
        duration_days=row.duration_days,
        list_amount=row.list_amount,
        discount_amount=row.discount_amount,
        discount_reason=row.discount_reason,
        total_amount=row.total_amount,
        currency=row.currency,
        status=row.status,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        capacity=capacity,
    )


class SponsorshipQuoting:
    """Issue, expire and accept quotes against the published price catalog."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def quote(self, command: QuoteCommand, *, at: datetime) -> QuoteView:
        self._actor.require_administrator()
        if not command.command_key.strip():
            raise QuoteRefused("La cotización requiere una clave de operación.")
        if command.duration_days <= 0:
            raise QuoteRefused("La duración debe ser positiva.")
        if command.discount_amount < 0:
            raise QuoteRefused("El descuento no puede ser negativo.")
        if command.discount_amount > 0 and len(command.discount_reason.strip()) < 4:
            raise QuoteRefused(
                "Un descuento requiere una razón escrita registrada con la "
                "cotización."
            )

        existing = await self._session.scalar(
            select(SponsorshipQuote).where(
                SponsorshipQuote.organization_id == self._actor.organization_id,
                SponsorshipQuote.command_key == command.command_key,
            )
        )
        if existing is not None:
            return await self._view(existing, at=at)

        campaign = await self._campaign(command.campaign_id)
        if campaign.status not in {
            SponsorshipCampaignStatus.DRAFT.value,
            SponsorshipCampaignStatus.QUOTED.value,
        }:
            raise InvalidTransition(
                "Sólo una campaña en borrador o cotizada admite una cotización nueva."
            )
        # The Listing has to be sellable before a price is put on it. Quoting an
        # ineligible Listing is how a buyer ends up paying for days Product was
        # always going to pause.
        decision = await SponsoredEligibility(self._session, self._actor).evaluate(
            campaign.listing_id, None, at, campaign=campaign
        )
        structural = tuple(
            reason
            for reason in decision.reasons
            if "no está programada" not in reason
            and "no ha iniciado" not in reason
            and "validación comercial" not in reason
        )
        if structural:
            raise QuoteRefused(
                "La publicación no es elegible para patrocinio: "
                + "; ".join(structural)
                + "."
            )

        catalog = await SponsorshipPricing(self._session, self._actor).published()
        amount = catalog.amount_for(campaign.package, command.duration_days)
        if amount is None:
            raise PackageUnpriced(
                f"El catálogo «{catalog.version}» no incluye el paquete "
                f"«{campaign.package}» a {command.duration_days} días."
            )
        if command.discount_amount > amount:
            raise QuoteRefused("El descuento no puede superar el precio de lista.")

        row = SponsorshipQuote(
            organization_id=self._actor.organization_id,
            campaign_id=campaign.id,
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            package=campaign.package,
            duration_days=command.duration_days,
            list_amount=amount,
            discount_amount=command.discount_amount,
            discount_reason=command.discount_reason.strip() or None,
            total_amount=amount - command.discount_amount,
            currency=catalog.currency,
            status=SponsorshipQuoteStatus.ISSUED.value,
            issued_by=self._actor.member_id,
            issued_at=at,
            expires_at=at + timedelta(days=QUOTE_VALID_DAYS),
            command_key=command.command_key,
        )
        self._session.add(row)
        campaign.status = SponsorshipCampaignStatus.QUOTED.value
        campaign.paid_days = command.duration_days
        campaign.updated_at = at
        await self._session.flush()
        await self._audit(
            "QuoteSponsorship",
            row,
            {
                "catalog_version": row.catalog_version,
                "package": row.package,
                "discounted": row.discount_amount > 0,
            },
        )
        return await self._view(row, at=at)

    async def accept(self, command: AcceptQuote, *, at: datetime) -> QuoteView:
        """Accept one quote and take the capacity it needs, or refuse.

        The capacity check happens here rather than at issue time, and the
        campaign only becomes Reserved once every surface in its package is
        held. That ordering is what makes "no oversell" a property of the
        product rather than a hope about timing.
        """
        self._actor.require_administrator()
        row = await self._locked(command.quote_id)
        if row.status == SponsorshipQuoteStatus.RESERVED.value:
            return await self._view(row, at=at)
        if row.status != SponsorshipQuoteStatus.ISSUED.value:
            raise InvalidTransition("Sólo una cotización vigente puede aceptarse.")
        if at >= row.expires_at:
            row.status = SponsorshipQuoteStatus.EXPIRED.value
            await self._session.flush()
            raise QuoteExpired()
        campaign = await self._campaign(row.campaign_id)
        forecasts = await SponsorshipCapacity(self._session, self._actor).reserve(
            campaign, starts_on=command.starts_on, days=row.duration_days, at=at
        )
        row.status = SponsorshipQuoteStatus.RESERVED.value
        row.reserved_at = at
        campaign.status = SponsorshipCampaignStatus.RESERVED.value
        campaign.paid_days = row.duration_days
        campaign.price_amount = row.total_amount
        campaign.price_currency = row.currency
        campaign.catalog_id = row.catalog_id
        campaign.updated_at = at
        await self._session.flush()
        await self._audit(
            "AcceptSponsorshipQuote",
            row,
            {"starts_on": command.starts_on.isoformat(), "surfaces": len(forecasts)},
        )
        return view_of(row, tuple(item.surface for item in forecasts), forecasts)

    async def expire_due(self, *, at: datetime) -> int:
        """Mark every quote past its seventh day as Expired.

        Run by the worker rather than computed on read: a quote whose status
        still says Issued a month later is a quote somebody will honour by
        accident.
        """
        rows = list(
            await self._session.scalars(
                select(SponsorshipQuote).where(
                    SponsorshipQuote.organization_id == self._actor.organization_id,
                    SponsorshipQuote.status == SponsorshipQuoteStatus.ISSUED.value,
                    SponsorshipQuote.expires_at <= at,
                )
            )
        )
        for row in rows:
            row.status = SponsorshipQuoteStatus.EXPIRED.value
        await self._session.flush()
        return len(rows)

    async def quotes(self, campaign_id: uuid.UUID) -> tuple[QuoteView, ...]:
        rows = await self._session.scalars(
            select(SponsorshipQuote)
            .where(SponsorshipQuote.campaign_id == campaign_id)
            .order_by(SponsorshipQuote.issued_at.desc())
        )
        return tuple([await self._view(row, at=None) for row in rows])

    async def _view(
        self, row: SponsorshipQuote, *, at: datetime | None
    ) -> QuoteView:
        surfaces = PACKAGE_SURFACES.get(row.package, ())
        if at is None:
            return view_of(row, surfaces)
        capacity = SponsorshipCapacity(self._session, self._actor)
        window_end = at + timedelta(days=row.duration_days)
        forecasts = tuple(
            [
                await capacity.forecast(surface, at, window_end)
                for surface in surfaces
            ]
        )
        return view_of(row, surfaces, forecasts)

    async def _campaign(self, campaign_id: uuid.UUID) -> SponsorshipCampaign:
        row = await self._session.scalar(
            select(SponsorshipCampaign)
            .where(SponsorshipCampaign.id == campaign_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa campaña de patrocinio.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def _locked(self, quote_id: uuid.UUID) -> SponsorshipQuote:
        row = await self._session.scalar(
            select(SponsorshipQuote)
            .where(SponsorshipQuote.id == quote_id)
            .with_for_update()
        )
        if row is None:
            raise NotFound("No encontramos esa cotización.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def _audit(
        self, action: str, row: SponsorshipQuote, details: dict[str, object]
    ) -> None:
        await record_audit(
            self._session,
            actor_type=self._actor.actor_type,
            actor_id=self._actor.label,
            action=action,
            subject_type="SponsorshipQuote",
            subject_id=str(row.id),
            details=details,
            commit=False,
        )

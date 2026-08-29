"""Synthetic Stage 8 setup, built through Product's own seams.

Every helper here goes through the real modules — publish a catalog, open a
campaign, quote it, accept it, schedule it, activate it — because a fixture that
inserted a ``sponsorship_campaigns`` row directly would not exercise the
invariants these suites exist to prove. The data is entirely synthetic: no real
buyer, no real property, no real contact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.domain.analytics.definitions import CURRENT_DEFINITION_VERSION
from realestate.domain.commercial.actors import Actor
from realestate.domain.sponsorship.campaigns import (
    OpenCampaign,
    ScheduleCampaign,
    SponsorshipCampaigns,
)
from realestate.domain.sponsorship.pricing import (
    DraftCatalog,
    PriceLine,
    PublishCatalog,
    SponsorshipPricing,
)
from realestate.domain.sponsorship.quoting import (
    AcceptQuote,
    QuoteCommand,
    SponsorshipQuoting,
)
from tests.fixtures.public_site import PublishedListing, publish_listing

#: The synthetic reference every suite works from, so timestamps are stable.
MOMENT = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)

#: Pilot evidence text. Deliberately explicit that it is synthetic: publishing a
#: catalog requires evidence, and the suites must not look like they invented a
#: defensible market price.
PILOT_EVIDENCE = (
    "Evidencia sintética de prueba: tráfico medido del piloto en el periodo de "
    "referencia."
)

CLEARANCE = (
    "Validación comercial sintética: ficha, precio, disponibilidad, fotografía y "
    "relación con el propietario revisadas."
)


@dataclass(frozen=True)
class ActiveCampaign:
    """One campaign taken all the way to Active, with its Listing."""

    campaign_id: uuid.UUID
    listing: PublishedListing
    quote_id: uuid.UUID


#: Durations the synthetic catalog prices. The product sells 30 days; the extra
#: entries exist so a suite can drive a two- or five-day campaign to completion
#: without simulating a month of ticks. Pricing them here rather than relaxing
#: the product rule keeps "an unpriced package is refused" under test.
FIXTURE_DURATIONS: tuple[int, ...] = (2, 5, 10, 30)


async def published_catalog(
    session: AsyncSession,
    admin: Actor,
    *,
    version: str = "precios-piloto-1",
    search: Decimal = Decimal("4000"),
    homepage: Decimal = Decimal("7000"),
    both: Decimal = Decimal("9500"),
    durations: tuple[int, ...] = FIXTURE_DURATIONS,
    at: datetime = MOMENT,
) -> uuid.UUID:
    """A published price catalog version with all three packages priced."""
    pricing = SponsorshipPricing(session, admin)
    catalog = await pricing.draft(
        DraftCatalog(
            version=version,
            currency="MXN",
            lines=tuple(
                PriceLine(package, days, amount)
                for package, amount in (
                    ("Search", search),
                    ("Homepage", homepage),
                    ("Both", both),
                )
                for days in durations
            ),
            command_key=f"catalog:{version}",
        ),
        at=at,
    )
    await pricing.publish(
        PublishCatalog(catalog.catalog_id, PILOT_EVIDENCE), at=at
    )
    return catalog.catalog_id


async def active_campaign(
    session: AsyncSession,
    admin: Actor,
    suffix: str,
    *,
    package: str = "Search",
    paid_days: int = 30,
    at: datetime = MOMENT,
    listing: PublishedListing | None = None,
    property_id: uuid.UUID | None = None,
) -> ActiveCampaign:
    """A campaign through every accepted transition to Active.

    Deliberately the whole path. A test that needs an Active campaign also needs
    the reservation, the collection state and the delivery-day row that only the
    real transitions create.
    """
    published = listing or await publish_listing(
        session, admin, suffix, property_id=property_id
    )
    campaigns = SponsorshipCampaigns(session, admin)
    view = await campaigns.open(
        OpenCampaign(
            listing_id=published.listing_id,
            buyer_kind="Owner",
            buyer_label=f"Propietario sintético {suffix}",
            package=package,
            paid_days=paid_days,
        ),
        at=at,
    )
    await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=at)
    quoting = SponsorshipQuoting(session, admin)
    quote = await quoting.quote(
        QuoteCommand(
            campaign_id=view.campaign_id,
            command_key=f"quote:{suffix}",
            duration_days=paid_days,
        ),
        at=at,
    )
    await quoting.accept(AcceptQuote(quote.quote_id, at), at=at)
    await campaigns.schedule(ScheduleCampaign(view.campaign_id, at), at=at)
    await campaigns.activate(view.campaign_id, at=at)
    await session.flush()
    return ActiveCampaign(
        campaign_id=view.campaign_id,
        listing=published,
        quote_id=quote.quote_id,
    )


def days_after(count: int, *, base: datetime = MOMENT) -> datetime:
    return base + timedelta(days=count)


DEFINITION_VERSION = CURRENT_DEFINITION_VERSION

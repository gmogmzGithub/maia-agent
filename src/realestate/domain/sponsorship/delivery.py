"""``SponsoredDelivery.select`` — which paid slots this page render gets.

The single most important property of this module is what it does *not* touch.
The organic result list arrives already ordered by
:class:`~realestate.domain.public.catalog.PublicCatalog`, which knows nothing
about sponsorship, and it leaves unchanged. Sponsored placements are returned as
a separate, labelled list of slots. Payment buys positions; it cannot buy
relevance (ADR-0043), and the way to guarantee that is for the ranking code and
the money code to have no connection at all.

What it does decide, in order:

* **How many slots exist.** One per six visible results in search, two on the
  homepage, from the versioned definition rather than a literal here.
* **Who is eligible right now.** Per-exposure, through
  :class:`~realestate.domain.sponsorship.eligibility.SponsoredEligibility`, so a
  Listing that lost its authority five minutes ago stops being shown for money
  five minutes ago.
* **Who is over their cap.** Three paid Visible Impressions per Listing per
  anonymous session per day, counted durably.
* **Whose turn it is.** Rotation by delivery deficit: the campaign furthest
  behind the share of its paid days goes first. That is what "equitable" has to
  mean when several campaigns share one slot — not a fixed order, and not random.
* **Never a listing already visible organically on this very page**: a buyer
  paying for reach should not pay for a second copy of a card the visitor can
  already see.

One rule that is deliberately *not* repeated here is one sponsored position per
confirmed Property. ``SponsoredEligibility`` already refuses every campaign that
competes with a live one over the same Property, and it refuses them
symmetrically — so a second check in this module could never fire, and a branch
that cannot fire is a branch nobody can trust.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CatalogListing,
    SponsoredExposureCounter,
    SponsoredSurface,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
)
from realestate.domain.analytics.definitions import (
    Definition,
    MeasurementDefinitions,
)
from realestate.domain.analytics.projection import day_of
from realestate.domain.commercial.actors import Actor
from realestate.domain.sponsorship.eligibility import SponsoredEligibility
from realestate.domain.sponsorship.labels import (
    SPONSORED_ARIA_LABEL,
    SPONSORED_LABEL,
)
from realestate.domain.sponsorship.pricing import PACKAGE_SURFACES

#: Why a campaign that could have been shown was not. Reported to the
#: Administrator so "we sold it and never delivered it" cannot happen quietly.
CAP_REACHED = "SessionDailyCapReached"
ALREADY_ORGANIC = "AlreadyVisibleOrganically"
NOT_ELIGIBLE = "NotEligible"
NO_SLOT = "NoSlotAvailable"


@dataclass(frozen=True)
class DeliveryContext:
    """Everything one page render can tell delivery about itself.

    ``session_reference`` is already pseudonymous — the caller resolved it
    through :class:`~realestate.domain.analytics.pseudonyms.Pseudonyms` — so this
    module never holds a raw browser identifier. ``organic_listing_ids`` is the
    page's own ordered result list, read only to avoid duplicating a card.
    """

    surface: str
    visible_results: int
    session_reference: str
    at: datetime
    organic_listing_ids: tuple[uuid.UUID, ...] = ()
    definition_version: str | None = None
    #: A crawler or an operator preview. Slots are still selected so the page
    #: looks the same, but nothing is counted against a cap.
    countable: bool = True


@dataclass(frozen=True)
class SponsoredSlot:
    """One paid position, already labelled."""

    position: int
    campaign_id: uuid.UUID
    listing_id: uuid.UUID
    surface: str
    label: str = SPONSORED_LABEL
    accessible_label: str = SPONSORED_ARIA_LABEL


@dataclass(frozen=True)
class SkippedCampaign:
    campaign_id: uuid.UUID
    listing_id: uuid.UUID
    reason: str
    detail: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliveryPlan:
    """The paid part of one page. The organic part is not in here at all."""

    surface: str
    slots: tuple[SponsoredSlot, ...]
    available_slots: int
    skipped: tuple[SkippedCampaign, ...] = field(default_factory=tuple)

    @property
    def sponsored_listing_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(slot.listing_id for slot in self.slots)


class SponsoredDelivery:
    """Select, cap and rotate the sponsored placements for one render."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def select(self, context: DeliveryContext) -> DeliveryPlan:
        if context.surface not in {item.value for item in SponsoredSurface}:
            raise ValueError("La superficie patrocinada no es válida.")
        definition = await MeasurementDefinitions(self._session).resolve(
            context.definition_version
        )
        slots = definition.sponsored_slots(
            surface=context.surface, visible_results=context.visible_results
        )
        if slots <= 0:
            return DeliveryPlan(context.surface, (), 0)

        candidates = await self._candidates(context.surface)
        eligibility = SponsoredEligibility(self._session, self._actor)
        chosen: list[SponsoredSlot] = []
        skipped: list[SkippedCampaign] = []

        for campaign, listing, _deficit in candidates:
            if len(chosen) >= slots:
                skipped.append(
                    SkippedCampaign(campaign.id, listing.id, NO_SLOT)
                )
                continue
            if listing.id in context.organic_listing_ids:
                skipped.append(
                    SkippedCampaign(campaign.id, listing.id, ALREADY_ORGANIC)
                )
                continue
            decision = await eligibility.evaluate(
                listing, context.surface, context.at, campaign=campaign
            )
            if not decision.eligible:
                await eligibility.record_exposure(
                    campaign.id, decision, at=context.at
                )
                skipped.append(
                    SkippedCampaign(
                        campaign.id, listing.id, NOT_ELIGIBLE, decision.reasons
                    )
                )
                continue
            if context.countable and await self._capped(
                definition, listing.id, context
            ):
                skipped.append(
                    SkippedCampaign(campaign.id, listing.id, CAP_REACHED)
                )
                continue
            chosen.append(
                SponsoredSlot(
                    position=len(chosen) + 1,
                    campaign_id=campaign.id,
                    listing_id=listing.id,
                    surface=context.surface,
                )
            )
        return DeliveryPlan(
            surface=context.surface,
            slots=tuple(chosen),
            available_slots=slots,
            skipped=tuple(skipped),
        )

    async def count_visible(
        self,
        *,
        listing_id: uuid.UUID,
        session_reference: str,
        at: datetime,
    ) -> int:
        """Count one paid Visible Impression against the session's daily cap.

        Written durably rather than derived from the analytics store: the cap is
        enforced while the page is being built, and the projection may not have
        run yet. Returns the running count so a caller can log the cap being
        approached.
        """
        if not session_reference:
            return 0
        service_date = day_of(at)
        savepoint = await self._session.begin_nested()
        try:
            row = SponsoredExposureCounter(
                organization_id=self._actor.organization_id,
                listing_id=listing_id,
                session_reference=session_reference,
                service_date=service_date,
                visible_impressions=1,
            )
            self._session.add(row)
            await self._session.flush()
        except IntegrityError:
            await savepoint.rollback()
            existing = await self._session.scalar(
                select(SponsoredExposureCounter)
                .where(
                    SponsoredExposureCounter.listing_id == listing_id,
                    SponsoredExposureCounter.session_reference == session_reference,
                    SponsoredExposureCounter.service_date == service_date,
                )
                .with_for_update()
            )
            if existing is None:  # pragma: no cover - the constraint guarantees it
                raise
            existing.visible_impressions += 1
            await self._session.flush()
            return existing.visible_impressions
        await savepoint.commit()
        return row.visible_impressions

    async def _capped(
        self,
        definition: Definition,
        listing_id: uuid.UUID,
        context: DeliveryContext,
    ) -> bool:
        if not context.session_reference:
            return False
        current = await self._session.scalar(
            select(SponsoredExposureCounter.visible_impressions).where(
                SponsoredExposureCounter.listing_id == listing_id,
                SponsoredExposureCounter.session_reference
                == context.session_reference,
                SponsoredExposureCounter.service_date == day_of(context.at),
            )
        )
        return (current or 0) >= definition.session_daily_visible_impression_cap

    async def _candidates(
        self, surface: str
    ) -> list[tuple[SponsorshipCampaign, CatalogListing, Decimal]]:
        """Live campaigns for this surface, furthest behind first.

        The deficit is ``delivered_days / paid_days``: a campaign that has had
        two of thirty days is behind one that has had twenty of thirty, and the
        one behind gets the slot. Ties break on the campaign's activation time
        and then its id, so the order is deterministic and a test can assert on
        it rather than on a coin flip.
        """
        rows = await self._session.execute(
            select(SponsorshipCampaign, CatalogListing)
            .join(CatalogListing, CatalogListing.id == SponsorshipCampaign.listing_id)
            .where(
                SponsorshipCampaign.organization_id == self._actor.organization_id,
                SponsorshipCampaign.status == SponsorshipCampaignStatus.ACTIVE.value,
            )
        )
        candidates: list[tuple[SponsorshipCampaign, CatalogListing, Decimal]] = []
        for campaign, listing in rows:
            if surface not in PACKAGE_SURFACES.get(campaign.package, ()):
                continue
            share = Decimal(campaign.delivered_days) / Decimal(campaign.paid_days)
            candidates.append((campaign, listing, share))
        candidates.sort(
            key=lambda item: (
                item[2],
                item[0].activated_at or item[0].created_at,
                str(item[0].id),
            )
        )
        return candidates

"""``SponsoredEligibility.evaluate`` — may this Listing be shown for money?

Paying changes one thing: which position a Listing may occupy. It changes
nothing about whether the Listing is fit to be shown at all. So this module does
not re-implement any customer-facing rule; it asks
:class:`~realestate.domain.catalog.eligibility.ListingEligibility` for the same
``PublicShare`` decision the unpaid site gets, and then adds only what is
specific to money changing hands:

* a written commercial clearance, because SAN-065 — which defects of file,
  price, availability, photography or owner relationship block accepting payment
  — is still Pending and must not be silently assumed away;
* one sponsored position per confirmed physical Property, so a buyer cannot
  occupy the surface twice through two Listings of the same house;
* the campaign's own state and remaining paid days.

The decision is recorded, daily and per exposure, because a buyer asking why
five days were not delivered deserves an answer that does not depend on somebody
remembering.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    CatalogListing,
    SponsoredEligibilityRecord,
    SponsoredSurface,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
)
from realestate.domain.analytics.projection import day_of
from realestate.domain.catalog.eligibility import (
    EligibilityPurpose,
    ListingEligibility,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.sponsorship.pricing import PACKAGE_SURFACES

#: Campaign states in which a placement may actually be delivered.
DELIVERABLE_STATES: frozenset[str] = frozenset(
    {SponsorshipCampaignStatus.ACTIVE.value}
)

#: States a daily check may legitimately find and resume from.
PAUSABLE_STATES: frozenset[str] = frozenset(
    {
        SponsorshipCampaignStatus.ACTIVE.value,
        SponsorshipCampaignStatus.PAUSED.value,
    }
)


@dataclass(frozen=True)
class SponsoredDecision:
    """Whether one campaign may occupy one surface right now, and why not."""

    campaign_id: uuid.UUID
    listing_id: uuid.UUID
    surface: str | None
    eligible: bool
    reasons: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return not self.eligible


class SponsoredEligibility:
    """The one policy seam for paid placement of a Listing."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def evaluate(
        self,
        listing: uuid.UUID | CatalogListing,
        placement: str | None,
        at: datetime,
        *,
        campaign: SponsorshipCampaign | None = None,
    ) -> SponsoredDecision:
        """The decision for one Listing on one placement surface.

        ``listing`` accepts an id or the row a caller already holds, and
        ``campaign`` likewise: the delivery path evaluates several campaigns per
        page render and must not re-read the same Listing for each of them.
        """
        # Validated before any read. An unknown surface is a programming error
        # in the caller, and answering it with "we could not find that Listing"
        # would send whoever is debugging it in the wrong direction.
        if placement is not None and placement not in {
            item.value for item in SponsoredSurface
        }:
            raise ValueError("La superficie patrocinada no es válida.")

        row = await self._listing(listing)
        if campaign is None:
            campaign = await self._campaign_for(row.id)
        reasons: list[str] = []

        public = await ListingEligibility(self._session, self._actor).evaluate(
            row.id, EligibilityPurpose.PUBLIC_SHARE, at
        )
        if not public.eligible:
            reasons.extend(public.reasons)

        if campaign is None:
            reasons.append("no existe una campaña de patrocinio para la publicación")
            return await self._decision(None, row.id, placement, reasons)

        if not (campaign.commercial_clearance or "").strip():
            reasons.append(
                "falta la validación comercial escrita para aceptar pago (SAN-065)"
            )
        if campaign.status == SponsorshipCampaignStatus.CANCELLED.value:
            reasons.append("la campaña está cancelada")
        elif campaign.status == SponsorshipCampaignStatus.COMPLETED.value:
            reasons.append("la campaña ya se completó")
        elif campaign.status not in PAUSABLE_STATES | {
            SponsorshipCampaignStatus.SCHEDULED.value
        }:
            reasons.append("la campaña todavía no está programada")
        if campaign.delivered_days >= campaign.paid_days:
            reasons.append("no quedan días pagados por entregar")
        if campaign.starts_on is not None and campaign.starts_on > at:
            reasons.append("la campaña no ha iniciado")
        if placement is not None and placement not in PACKAGE_SURFACES.get(
            campaign.package, ()
        ):
            reasons.append("el paquete contratado no incluye esa superficie")

        if row.property_uuid is not None:
            competitor = await self._other_property_campaign(campaign, row)
            if competitor is not None:
                reasons.append(
                    "otra campaña activa ya ocupa una posición patrocinada para "
                    "esa propiedad confirmada"
                )
        return await self._decision(campaign.id, row.id, placement, reasons)

    async def record_daily(
        self, campaign_id: uuid.UUID, decision: SponsoredDecision, *, at: datetime
    ) -> None:
        """Store today's decision once, so a re-run does not duplicate it."""
        service_date = day_of(at)
        existing = await self._session.scalar(
            select(SponsoredEligibilityRecord).where(
                SponsoredEligibilityRecord.campaign_id == campaign_id,
                SponsoredEligibilityRecord.scope == "Daily",
                SponsoredEligibilityRecord.service_date == service_date,
            )
        )
        if existing is not None:
            existing.eligible = decision.eligible
            existing.reasons = list(decision.reasons)
            existing.decided_at = at
            return
        self._session.add(
            SponsoredEligibilityRecord(
                organization_id=self._actor.organization_id,
                campaign_id=campaign_id,
                scope="Daily",
                surface=decision.surface,
                eligible=decision.eligible,
                reasons=list(decision.reasons),
                service_date=service_date,
                decided_at=at,
            )
        )

    async def record_exposure(
        self, campaign_id: uuid.UUID, decision: SponsoredDecision, *, at: datetime
    ) -> None:
        """Store one refused exposure decision.

        Only refusals: an accepted exposure is already evidenced by its Served
        Impression event, and storing a row per rendered placement would put a
        write on the read path of every search page.
        """
        if decision.eligible:
            return
        self._session.add(
            SponsoredEligibilityRecord(
                organization_id=self._actor.organization_id,
                campaign_id=campaign_id,
                scope="Exposure",
                surface=decision.surface,
                eligible=False,
                reasons=list(decision.reasons),
                service_date=None,
                decided_at=at,
            )
        )

    async def _decision(
        self,
        campaign_id: uuid.UUID | None,
        listing_id: uuid.UUID,
        placement: str | None,
        reasons: list[str],
    ) -> SponsoredDecision:
        return SponsoredDecision(
            campaign_id=campaign_id or uuid.UUID(int=0),
            listing_id=listing_id,
            surface=placement,
            eligible=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    async def _listing(
        self, listing: uuid.UUID | CatalogListing
    ) -> CatalogListing:
        if isinstance(listing, CatalogListing):
            self._actor.require_same_organization(listing.organization_id)
            return listing
        row = await self._session.get(CatalogListing, listing)
        if row is None:
            raise NotFound("No encontramos esa publicación.")
        self._actor.require_same_organization(row.organization_id)
        return row

    async def _campaign_for(
        self, listing_id: uuid.UUID
    ) -> SponsorshipCampaign | None:
        row: SponsorshipCampaign | None = await self._session.scalar(
            select(SponsorshipCampaign)
            .where(
                SponsorshipCampaign.organization_id == self._actor.organization_id,
                SponsorshipCampaign.listing_id == listing_id,
                SponsorshipCampaign.status.notin_(
                    (
                        SponsorshipCampaignStatus.CANCELLED.value,
                        SponsorshipCampaignStatus.COMPLETED.value,
                    )
                ),
            )
            .order_by(SponsorshipCampaign.created_at.desc())
        )
        return row

    async def _other_property_campaign(
        self, campaign: SponsorshipCampaign, listing: CatalogListing
    ) -> SponsorshipCampaign | None:
        """Another live campaign over a different Listing of the same Property.

        Attribution stays on the paying Listing (ADR-0043), so the loser here is
        the campaign that did not get the position — not a merged record.
        """
        row: SponsorshipCampaign | None = await self._session.scalar(
            select(SponsorshipCampaign)
            .join(CatalogListing, CatalogListing.id == SponsorshipCampaign.listing_id)
            .where(
                SponsorshipCampaign.organization_id == self._actor.organization_id,
                SponsorshipCampaign.id != campaign.id,
                SponsorshipCampaign.status.in_(tuple(DELIVERABLE_STATES)),
                CatalogListing.property_uuid == listing.property_uuid,
            )
            .order_by(SponsorshipCampaign.activated_at)
        )
        return row

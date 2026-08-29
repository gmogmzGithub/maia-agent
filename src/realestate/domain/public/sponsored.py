"""The public read of paid placements, already labelled and already measured.

This is the seam between "who may occupy a slot" and "what the browser is
handed". It composes three things that must not be composed anywhere else:

* :class:`~realestate.domain.sponsorship.delivery.SponsoredDelivery` decides the
  slots;
* :class:`~realestate.domain.public.listing.PublicListing` renders each one
  through the *same* public projection an organic card goes through, so a paid
  card cannot show a field an unpaid card would not;
* :class:`~realestate.domain.analytics.emission.AnalyticsEmission` records the
  Served Impression as the response is built.

Recording at build time rather than from the browser is deliberate. Serving is
Product's own fact — it put the placement in the response — and a served count
that depended on a script running would under-report exactly the visitors whose
devices are slowest. Visibility is the opposite: only the browser can know
whether half the card was on screen for a second, so that event arrives from the
page.

The raw session identifier is pseudonymised here and never held beyond this
call, which is what lets the cap be per-session without the analytics schema
knowing what a session is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AnalyticsEventName
from realestate.domain.analytics.definitions import MeasurementDefinitions
from realestate.domain.analytics.emission import AnalyticsEmission
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.pseudonyms import Pseudonyms, Purpose
from realestate.domain.commercial.actors import Actor
from realestate.domain.public.catalog import PublicListingView
from realestate.domain.public.listing import PublicListing
from realestate.domain.sponsorship.delivery import (
    DeliveryContext,
    SponsoredDelivery,
)
from realestate.domain.sponsorship.labels import (
    SPONSORED_ARIA_LABEL,
    SPONSORED_DISCLOSURE,
    SPONSORED_LABEL,
)


@dataclass(frozen=True)
class SponsoredCard:
    """One paid card. The label is not optional and has no "off" value."""

    position: int
    campaign_id: uuid.UUID
    listing: PublicListingView
    label: str = SPONSORED_LABEL
    accessible_label: str = SPONSORED_ARIA_LABEL


@dataclass(frozen=True)
class SponsoredSurfaceResult:
    """What one surface's paid section contains."""

    surface: str
    cards: tuple[SponsoredCard, ...]
    available_slots: int
    disclosure: str = SPONSORED_DISCLOSURE


class PublicSponsored:
    """Build the labelled paid section of one public surface."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def for_surface(
        self,
        *,
        surface: str,
        at: datetime,
        visible_results: int,
        organic_listing_ids: tuple[uuid.UUID, ...] = (),
        session_value: str = "",
        bot: bool = False,
        internal: bool = False,
        definition_version: str | None = None,
    ) -> SponsoredSurfaceResult:
        reference = await Pseudonyms(
            self._session, self._actor.organization_id
        ).reference(Purpose.SESSION, session_value)
        plan = await SponsoredDelivery(self._session, self._actor).select(
            DeliveryContext(
                surface=surface,
                visible_results=visible_results,
                session_reference=reference,
                at=at,
                organic_listing_ids=organic_listing_ids,
                definition_version=definition_version,
                # A crawler still sees the same page, but nothing it does
                # consumes a buyer's cap or counts toward delivery.
                countable=not (bot or internal),
            )
        )
        if not plan.slots:
            return SponsoredSurfaceResult(surface, (), plan.available_slots)

        reader = PublicListing(self._session, self._actor)
        emission = AnalyticsEmission(self._session, self._actor)
        cards: list[SponsoredCard] = []
        for slot in plan.slots:
            publication = await reader.read_by_id(slot.listing_id, at=at)
            if publication.listing is None:
                # Withdrawn between the eligibility check and the render. The
                # slot is dropped rather than filled from further down the
                # rotation: an empty paid section is honest, a substituted one
                # would bill the wrong campaign for this impression.
                continue
            await emission.emit_sponsored_exposure(
                campaign_id=slot.campaign_id,
                listing_id=slot.listing_id,
                surface=surface,
                position=slot.position,
                session_value=session_value,
                session_reference=reference,
                occurred_at=at,
                bot=bot,
                internal=internal,
            )
            cards.append(
                SponsoredCard(
                    position=slot.position,
                    campaign_id=slot.campaign_id,
                    listing=publication.listing,
                )
            )
        return SponsoredSurfaceResult(
            surface=surface,
            cards=tuple(cards),
            available_slots=plan.available_slots,
        )

    async def count_visible(
        self,
        *,
        campaign_id: uuid.UUID,
        listing_id: uuid.UUID,
        surface: str,
        visible_fraction: float,
        continuous_milliseconds: int,
        session_value: str,
        at: datetime,
        bot: bool = False,
        internal: bool = False,
        definition_version: str | None = None,
    ) -> bool:
        """Record one browser-reported Visible Impression, if it qualifies.

        The threshold is applied here, against the stored definition, rather
        than trusted from the page: a browser that claimed visibility it did not
        have would otherwise be able to inflate a buyer's report and exhaust
        another buyer's rotation.
        """
        definition = await MeasurementDefinitions(self._session).resolve(
            definition_version
        )
        if not definition.visible(
            visible_fraction=visible_fraction,
            continuous_milliseconds=continuous_milliseconds,
        ):
            return False
        reference = await Pseudonyms(
            self._session, self._actor.organization_id
        ).reference(Purpose.SESSION, session_value)
        day = at.date().isoformat()
        recorded = await AnalyticsEvents(self._session, self._actor).record(
            AnalyticsEvent(
                event_key=f"visible:{campaign_id}:{reference or 'anon'}:{day}",
                name=AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION,
                occurred_at=at,
                listing_id=listing_id,
                campaign_id=campaign_id,
                session_value=session_value,
                attributes={
                    "surface": surface,
                    "visible_fraction": visible_fraction,
                    "continuous_milliseconds": continuous_milliseconds,
                },
                bot=bot,
                internal=internal,
            )
        )
        if recorded.created and not (bot or internal):
            await SponsoredDelivery(self._session, self._actor).count_visible(
                listing_id=listing_id, session_reference=reference, at=at
            )
        return recorded.created

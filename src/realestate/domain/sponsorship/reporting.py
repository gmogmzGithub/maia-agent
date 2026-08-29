"""``SponsorshipReporting.generate`` — one report, two audiences, one truth.

The buyer report and the internal report are the *same* computation with
different fields exposed. That is deliberate: two separate implementations would
eventually disagree, and a buyer noticing that their report and the
Administrator's do not add up is a trust problem no explanation fixes.

What separates the audiences is what a buyer must never receive (ADR-0043,
ADR-0044): Contact identity, phone numbers, conversation content, individual
searches, Saved Collections, and any per-person row at all. A buyer gets
aggregate delivery, aggregate interaction, aggregate outcomes, their own price
and their own unit economics. The Administrator additionally gets commercial
terms, collection state, capacity, invalid traffic and Follow-up Data
Completeness.

Three honesty rules run through the whole module:

* an unknown outcome is ``Sin registrar``, never zero and never a loss;
* a ratio with no denominator is ``No calculable``, never zero;
* nothing anywhere claims the campaign *caused* what followed it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    CatalogListing,
    ReportAudience,
    SponsorshipCampaign,
    SponsorshipQuote,
    TrafficClass,
)
from realestate.domain.analytics.definitions import (
    Definition,
    MeasurementDefinitions,
)
from realestate.domain.analytics.metrics import (
    Measure,
    OperationMetrics,
    ratio,
)
from realestate.domain.analytics.projection import day_of
from realestate.domain.commercial.actors import Actor, NotAuthorized, NotFound
from realestate.domain.sponsorship.campaigns import CampaignView, view_of
from realestate.domain.sponsorship.capacity import SponsorshipCapacity
from realestate.domain.sponsorship.comparables import (
    Comparable,
    SponsorshipComparables,
)
from realestate.domain.sponsorship.labels import (
    NON_CAUSAL_DISCLAIMER,
    SPONSORED_DISCLOSURE,
    SPONSORED_LABEL,
)
from realestate.domain.sponsorship.pricing import PACKAGE_SURFACES

#: The reporting window when the caller does not name one.
DEFAULT_PERIOD_DAYS = 30

ENGAGEMENT_EVENTS: tuple[str, ...] = (
    AnalyticsEventName.LISTING_OPENED.value,
    AnalyticsEventName.GALLERY_OPENED.value,
    AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION.value,
    AnalyticsEventName.LISTING_SAVED.value,
    AnalyticsEventName.MAIA_STARTED.value,
    AnalyticsEventName.WHATSAPP_HANDOFF.value,
    AnalyticsEventName.APPOINTMENT_REQUESTED.value,
)

#: Funnel steps in the order ADR-0044 fixes them, paired with the readable
#: Mexican Spanish label a report shows. One list, so the buyer report, the
#: internal dashboard and the PDF cannot disagree about the order or the words.
FUNNEL_LABELS: tuple[tuple[str, str], ...] = (
    ("SponsoredServedImpression", "Impresiones entregadas"),
    ("SponsoredVisibleImpression", "Impresiones visibles"),
    ("ListingOpened", "Aperturas de la publicación"),
    ("GalleryOpened", "Aperturas de galería"),
    ("SignificantGalleryExploration", "Exploración significativa de galería"),
    ("SavedOrShared", "Guardadas o compartidas"),
    ("MaiaStarted", "Conversaciones iniciadas con Maia"),
    ("WhatsAppHandoff", "Continuaciones por WhatsApp"),
    ("AppointmentRequested", "Solicitudes de cita"),
    ("AppointmentVerified", "Citas verificadas"),
    ("AppointmentAttended", "Citas atendidas"),
    ("OpportunityOutcomeKnown", "Resultados conocidos"),
)

#: The events each funnel step counts. ``SavedOrShared`` is one step reached by
#: two events, which is why this is not the identity mapping.
_STEP_EVENTS: dict[str, tuple[str, ...]] = {
    "SponsoredServedImpression": (
        AnalyticsEventName.SPONSORED_SERVED_IMPRESSION.value,
    ),
    "SponsoredVisibleImpression": (
        AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value,
    ),
    "ListingOpened": (AnalyticsEventName.LISTING_OPENED.value,),
    "GalleryOpened": (AnalyticsEventName.GALLERY_OPENED.value,),
    "SignificantGalleryExploration": (
        AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION.value,
    ),
    "SavedOrShared": (
        AnalyticsEventName.LISTING_SAVED.value,
        AnalyticsEventName.SELECTION_SHARED.value,
    ),
    "MaiaStarted": (AnalyticsEventName.MAIA_STARTED.value,),
    "WhatsAppHandoff": (AnalyticsEventName.WHATSAPP_HANDOFF.value,),
    "AppointmentRequested": (AnalyticsEventName.APPOINTMENT_REQUESTED.value,),
    "AppointmentVerified": (AnalyticsEventName.APPOINTMENT_VERIFIED.value,),
    "AppointmentAttended": (AnalyticsEventName.APPOINTMENT_ATTENDED.value,),
    "OpportunityOutcomeKnown": (
        AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN.value,
    ),
}


@dataclass(frozen=True)
class FunnelRow:
    """One funnel step, with the conversion from the step above it."""

    step: str
    label: str
    count: int | None
    from_previous: Measure


@dataclass(frozen=True)
class UnitEconomics:
    """What the buyer paid, per delivered thing.

    Every field is a :class:`Measure`, so "no appointments were requested" is
    ``No calculable`` rather than a division by zero pretending to be free.
    """

    price: Decimal | None
    currency: str
    cost_per_visible_impression: Measure
    cost_per_listing_open: Measure
    cost_per_appointment_request: Measure


@dataclass(frozen=True)
class Attribution:
    """Outcomes observed inside the declared windows. Never a causal claim."""

    view_through_days: int
    engaged_days: int
    view_through_outcomes: int | None
    engaged_outcomes: int | None
    disclaimer: str = NON_CAUSAL_DISCLAIMER


@dataclass(frozen=True)
class TrendPoint:
    period_start: datetime
    visible_impressions: int | None
    listing_opens: int | None
    interest_actions: int | None


@dataclass(frozen=True)
class InternalDetail:
    """The half of the report a buyer never receives."""

    collection_state: str
    collection_reference: str | None
    catalog_version: str | None
    discount_amount: Decimal
    discount_reason: str | None
    capacity_available: dict[str, int]
    invalid_events: dict[str, int]
    duplicate_suppressed: int
    follow_up_data_completeness: Measure
    outcome_completeness: Measure


@dataclass(frozen=True)
class SponsorshipReport:
    """One campaign's evidence, scoped to one audience."""

    campaign: CampaignView
    audience: str
    label: str
    definition_version: str
    period_start: datetime
    period_end: datetime
    listing_title: str
    surfaces: tuple[str, ...]
    funnel: tuple[FunnelRow, ...]
    outcomes: dict[str, int | None]
    unrecorded_outcomes: Measure
    economics: UnitEconomics
    attribution: Attribution
    trend: tuple[TrendPoint, ...]
    definitions: tuple[str, ...]
    comparables: tuple[Comparable, ...]
    disclosure: str = SPONSORED_DISCLOSURE
    disclaimer: str = NON_CAUSAL_DISCLAIMER
    internal: InternalDetail | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_buyer_view(self) -> bool:
        return self.audience == ReportAudience.BUYER.value


class SponsorshipReporting:
    """Generate the one report, exposed at the requested audience's level."""

    def __init__(self, session: AsyncSession, actor: Actor) -> None:
        self._session = session
        self._actor = actor

    async def generate(
        self,
        campaign_id: uuid.UUID,
        audience: ReportAudience,
        *,
        at: datetime,
        period_start: datetime | None = None,
        definition_version: str | None = None,
    ) -> SponsorshipReport:
        """Build the report, refusing an internal view to a non-Administrator.

        The authorization check is here rather than in the router because the
        buyer link reaches this method too, through a Product actor. A router
        that forgot the check would be handing out commercial terms.
        """
        if audience is ReportAudience.ADMINISTRATOR and not (
            self._actor.is_administrator or self._actor.is_product
        ):
            raise NotAuthorized(
                "Sólo un administrador puede ver el reporte interno."
            )
        campaign = await self._session.get(SponsorshipCampaign, campaign_id)
        if campaign is None:
            raise NotFound("No encontramos esa campaña de patrocinio.")
        self._actor.require_same_organization(campaign.organization_id)
        definition = await MeasurementDefinitions(self._session).resolve(
            definition_version
        )
        start = period_start or (at - timedelta(days=DEFAULT_PERIOD_DAYS))
        listing = await self._session.get(CatalogListing, campaign.listing_id)
        assert listing is not None

        counts = await self._step_counts(campaign, definition, start, at)
        funnel = self._funnel(counts)
        outcomes = await self._outcomes(campaign, definition, start, at)
        display_outcomes: dict[str, int | None] = dict(outcomes)
        if audience is ReportAudience.BUYER:
            display_outcomes = self._protect_counts(
                outcomes, definition.comparable_minimum_sample
            )
        surfaces = PACKAGE_SURFACES.get(campaign.package, ())
        report = SponsorshipReport(
            campaign=view_of(campaign),
            audience=audience.value,
            label=SPONSORED_LABEL,
            definition_version=definition.version,
            period_start=start,
            period_end=at,
            listing_title=listing.title,
            surfaces=surfaces,
            funnel=(
                self._protect_funnel(funnel, definition.comparable_minimum_sample)
                if audience is ReportAudience.BUYER
                else funnel
            ),
            outcomes=display_outcomes,
            unrecorded_outcomes=self._protect_measure(
                self._unrecorded_outcomes(counts, outcomes),
                definition.comparable_minimum_sample,
                audience,
            ),
            economics=self._protected_economics(
                self._economics(campaign, counts),
                definition.comparable_minimum_sample,
                audience,
            ),
            attribution=self._protect_attribution(
                await self._attribution(campaign, definition, at),
                definition.comparable_minimum_sample,
                audience,
            ),
            trend=self._protect_trend(
                await self._trend(campaign, definition, start, at),
                definition.comparable_minimum_sample,
                audience,
            ),
            definitions=(
                "Entregada: Product incluyó la posición pagada en una superficie.",
                (
                    "Visible: al menos "
                    f"{definition.minimum_visible_fraction * 100:g} % de la tarjeta "
                    f"durante {definition.minimum_continuous_milliseconds / 1000:g} "
                    + (
                        "segundo continuo."
                        if definition.minimum_continuous_milliseconds == 1000
                        else "segundos continuos."
                    )
                ),
                (
                    "Exploración significativa: "
                    f"{definition.minimum_photographs} fotografías o "
                    f"{definition.minimum_gallery_fraction * 100:g} % de la galería."
                ),
                "Muestra protegida: menos de 3 casos; la cifra no se muestra.",
            ),
            comparables=await self._comparables(campaign, definition, start, at),
            internal=(
                await self._internal(campaign, definition, start, at)
                if audience is ReportAudience.ADMINISTRATOR
                else None
            ),
            notes=self._notes(campaign, counts),
        )
        return report

    # -- the funnel --------------------------------------------------------

    async def _step_counts(
        self,
        campaign: SponsorshipCampaign,
        definition: Definition,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        rows = await self._session.scalars(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.organization_id == campaign.organization_id,
                AnalyticsDomainEvent.definition_version == definition.version,
                AnalyticsDomainEvent.campaign_id == campaign.id,
                AnalyticsDomainEvent.traffic_class == TrafficClass.VALID.value,
                AnalyticsDomainEvent.occurred_at >= start,
                AnalyticsDomainEvent.occurred_at < end,
            )
        )
        per_event: dict[str, int] = {}
        for row in rows:
            if (
                row.event_name
                == AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION.value
            ):
                continue
            per_event[row.event_name] = per_event.get(row.event_name, 0) + 1
            if (
                row.event_name == AnalyticsEventName.GALLERY_DEPTH_REACHED.value
                and definition.significant_exploration(
                    photographs=int(row.attributes.get("photographs") or 0),
                    gallery_fraction=float(
                        row.attributes.get("gallery_fraction") or 0
                    ),
                )
            ):
                name = AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION.value
                per_event[name] = per_event.get(name, 0) + 1
        return {
            step: sum(per_event.get(name, 0) for name in names)
            for step, names in _STEP_EVENTS.items()
        }

    async def _trend(
        self,
        campaign: SponsorshipCampaign,
        definition: Definition,
        start: datetime,
        end: datetime,
    ) -> tuple[TrendPoint, ...]:
        rows = await self._session.scalars(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.organization_id == campaign.organization_id,
                AnalyticsDomainEvent.definition_version == definition.version,
                AnalyticsDomainEvent.campaign_id == campaign.id,
                AnalyticsDomainEvent.traffic_class == TrafficClass.VALID.value,
                AnalyticsDomainEvent.occurred_at >= start,
                AnalyticsDomainEvent.occurred_at < end,
            )
        )
        buckets: dict[datetime, list[int]] = {}
        interest_names = {
            AnalyticsEventName.LISTING_SAVED.value,
            AnalyticsEventName.SELECTION_SHARED.value,
            AnalyticsEventName.MAIA_STARTED.value,
            AnalyticsEventName.WHATSAPP_HANDOFF.value,
        }
        for row in rows:
            bucket = buckets.setdefault(day_of(row.occurred_at), [0, 0, 0])
            if row.event_name == AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value:
                bucket[0] += 1
            if row.event_name == AnalyticsEventName.LISTING_OPENED.value:
                bucket[1] += 1
            if row.event_name in interest_names:
                bucket[2] += 1
        return tuple(
            TrendPoint(day, values[0], values[1], values[2])
            for day, values in sorted(buckets.items())
        )

    @staticmethod
    def _funnel(counts: dict[str, int]) -> tuple[FunnelRow, ...]:
        """The steps in fixed order, each with its conversion from the previous.

        Conversion from the step above rather than from the top: a buyer asking
        "why so much gallery exploration and no appointments" (SAN-067) is asking
        about one step boundary, and a report that only shows the overall rate
        cannot answer it.
        """
        out: list[FunnelRow] = []
        previous: int | None = None
        for step, label in FUNNEL_LABELS:
            count = counts.get(step, 0)
            out.append(
                FunnelRow(
                    step=step,
                    label=label,
                    count=count,
                    from_previous=(
                        Measure.not_computable(unit="%")
                        if previous is None
                        else ratio(count, previous)
                    ),
                )
            )
            previous = count
        return tuple(out)

    @staticmethod
    def _protect_counts(
        counts: dict[str, int], minimum: int
    ) -> dict[str, int | None]:
        return {
            name: None if 0 < count < minimum else count
            for name, count in counts.items()
        }

    @staticmethod
    def _protect_funnel(
        rows: tuple[FunnelRow, ...], minimum: int
    ) -> tuple[FunnelRow, ...]:
        protected: list[FunnelRow] = []
        previous_hidden = False
        for index, row in enumerate(rows):
            # Delivery volumes describe placements, not people. Interaction and
            # outcome cells can expose an individual when their sample is tiny.
            hidden = index >= 2 and row.count is not None and 0 < row.count < minimum
            conversion = (
                Measure.protected(sample=row.count or 0, unit="%")
                if hidden or previous_hidden
                else row.from_previous
            )
            protected.append(
                FunnelRow(
                    step=row.step,
                    label=row.label,
                    count=None if hidden else row.count,
                    from_previous=conversion,
                )
            )
            previous_hidden = hidden
        return tuple(protected)

    # -- outcomes ----------------------------------------------------------

    async def _outcomes(
        self,
        campaign: SponsorshipCampaign,
        definition: Definition,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        rows = await self._session.scalars(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.organization_id == campaign.organization_id,
                AnalyticsDomainEvent.definition_version == definition.version,
                AnalyticsDomainEvent.campaign_id == campaign.id,
                AnalyticsDomainEvent.traffic_class == TrafficClass.VALID.value,
                AnalyticsDomainEvent.event_name
                == AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN.value,
                AnalyticsDomainEvent.occurred_at >= start,
                AnalyticsDomainEvent.occurred_at < end,
            )
        )
        counted = {"Won": 0, "Lost": 0, "Dormant": 0}
        for row in rows:
            outcome = str(row.attributes.get("outcome") or "")
            if outcome in counted:
                counted[outcome] += 1
        return counted

    @staticmethod
    def _unrecorded_outcomes(
        counts: dict[str, int], outcomes: dict[str, int]
    ) -> Measure:
        """Appointments attended whose Opportunity outcome is not recorded.

        Reported as its own number so nobody has to subtract two totals and
        guess. ``Sin registrar`` when every attended visit is still open — which
        is normal early in a pilot and is not a loss.
        """
        attended = counts.get("AppointmentAttended", 0)
        known = sum(outcomes.values())
        if attended == 0:
            return Measure.not_computable(unit="%")
        if known == 0:
            return Measure.unrecorded_only(sample=attended, unit="%")
        return ratio(known, attended, unrecorded=max(0, attended - known))

    # -- money -------------------------------------------------------------

    @staticmethod
    def _economics(
        campaign: SponsorshipCampaign, counts: dict[str, int]
    ) -> UnitEconomics:
        price = campaign.price_amount

        def per(step: str) -> Measure:
            volume = counts.get(step, 0)
            if price is None or volume <= 0:
                return Measure.not_computable(unit=campaign.price_currency)
            return Measure.of(
                price / Decimal(volume), unit=campaign.price_currency, sample=volume
            )

        return UnitEconomics(
            price=price,
            currency=campaign.price_currency,
            cost_per_visible_impression=per("SponsoredVisibleImpression"),
            cost_per_listing_open=per("ListingOpened"),
            cost_per_appointment_request=per("AppointmentRequested"),
        )

    @staticmethod
    def _protect_measure(
        measure: Measure, minimum: int, audience: ReportAudience
    ) -> Measure:
        if (
            audience is ReportAudience.BUYER
            and 0 < measure.sample < minimum
        ):
            return Measure.protected(sample=measure.sample, unit=measure.unit)
        return measure

    @classmethod
    def _protected_economics(
        cls,
        economics: UnitEconomics,
        minimum: int,
        audience: ReportAudience,
    ) -> UnitEconomics:
        return UnitEconomics(
            price=economics.price,
            currency=economics.currency,
            cost_per_visible_impression=economics.cost_per_visible_impression,
            cost_per_listing_open=cls._protect_measure(
                economics.cost_per_listing_open, minimum, audience
            ),
            cost_per_appointment_request=cls._protect_measure(
                economics.cost_per_appointment_request, minimum, audience
            ),
        )

    @staticmethod
    def _protect_attribution(
        attribution: Attribution, minimum: int, audience: ReportAudience
    ) -> Attribution:
        if audience is not ReportAudience.BUYER:
            return attribution

        def protect(value: int) -> int | None:
            return None if 0 < value < minimum else value

        return Attribution(
            view_through_days=attribution.view_through_days,
            engaged_days=attribution.engaged_days,
            view_through_outcomes=protect(attribution.view_through_outcomes or 0),
            engaged_outcomes=protect(attribution.engaged_outcomes or 0),
        )

    @staticmethod
    def _protect_trend(
        points: tuple[TrendPoint, ...],
        minimum: int,
        audience: ReportAudience,
    ) -> tuple[TrendPoint, ...]:
        if audience is not ReportAudience.BUYER:
            return points

        def protect(value: int | None) -> int | None:
            return None if value is not None and 0 < value < minimum else value

        return tuple(
            TrendPoint(
                period_start=point.period_start,
                visible_impressions=protect(point.visible_impressions),
                listing_opens=protect(point.listing_opens),
                interest_actions=protect(point.interest_actions),
            )
            for point in points
        )

    # -- attribution -------------------------------------------------------

    async def _attribution(
        self, campaign: SponsorshipCampaign, definition: Definition, at: datetime
    ) -> Attribution:
        """Outcomes inside the two declared windows, counted from the exposure.

        View-through counts outcomes within seven days of *any* visible
        impression for this campaign; engaged counts within ninety days of an
        engagement event. Neither overwrites the Opportunity's first origin and
        neither is described as lift.
        """
        view_through = await self._outcomes_within(
            campaign,
            definition,
            at,
            (AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION.value,),
            definition.attribution.view_through_days,
        )
        engaged = await self._outcomes_within(
            campaign,
            definition,
            at,
            ENGAGEMENT_EVENTS,
            definition.attribution.engaged_days,
        )
        return Attribution(
            view_through_days=definition.attribution.view_through_days,
            engaged_days=definition.attribution.engaged_days,
            view_through_outcomes=view_through,
            engaged_outcomes=engaged,
        )

    async def _outcomes_within(
        self,
        campaign: SponsorshipCampaign,
        definition: Definition,
        at: datetime,
        anchor_names: tuple[str, ...],
        days: int,
    ) -> int:
        outcome = aliased(AnalyticsDomainEvent)
        anchor = aliased(AnalyticsDomainEvent)
        has_anchor = (
            select(anchor.id)
            .where(
                anchor.organization_id == outcome.organization_id,
                anchor.campaign_id == outcome.campaign_id,
                anchor.definition_version == outcome.definition_version,
                anchor.event_name.in_(anchor_names),
                anchor.traffic_class == TrafficClass.VALID.value,
                anchor.occurred_at <= outcome.occurred_at,
                anchor.occurred_at
                >= outcome.occurred_at - timedelta(days=days),
            )
            .exists()
        )
        total = await self._session.scalar(
            select(func.count(outcome.id)).where(
                outcome.organization_id == campaign.organization_id,
                outcome.campaign_id == campaign.id,
                outcome.definition_version == definition.version,
                outcome.event_name
                == AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN.value,
                outcome.traffic_class == TrafficClass.VALID.value,
                outcome.occurred_at <= at,
                has_anchor,
            )
        )
        return total or 0

    # -- comparables -------------------------------------------------------

    async def _comparables(
        self,
        campaign: SponsorshipCampaign,
        definition: Definition,
        start: datetime,
        end: datetime,
    ) -> tuple[Comparable, ...]:
        module = SponsorshipComparables(self._session, self._actor)
        out: list[Comparable] = []
        for surface in PACKAGE_SURFACES.get(campaign.package, ()):
            key = await module.cohort_key(campaign, surface)
            out.append(
                await module.describe(
                    key,
                    definition,
                    period_start=start,
                    period_end=end,
                    exclude_campaign_id=campaign.id,
                )
            )
        return tuple(out)

    # -- internal only -----------------------------------------------------

    async def _internal(
        self,
        campaign: SponsorshipCampaign,
        definition: Definition,
        start: datetime,
        end: datetime,
    ) -> InternalDetail:
        quote = await self._session.scalar(
            select(SponsorshipQuote)
            .where(SponsorshipQuote.campaign_id == campaign.id)
            .order_by(SponsorshipQuote.issued_at.desc())
        )
        invalid = await self._session.execute(
            select(
                AnalyticsDomainEvent.traffic_class,
                func.count(AnalyticsDomainEvent.id),
            )
            .where(
                AnalyticsDomainEvent.campaign_id == campaign.id,
                AnalyticsDomainEvent.definition_version == definition.version,
                AnalyticsDomainEvent.traffic_class != TrafficClass.VALID.value,
                AnalyticsDomainEvent.occurred_at >= start,
                AnalyticsDomainEvent.occurred_at < end,
            )
            .group_by(AnalyticsDomainEvent.traffic_class)
        )
        capacity = SponsorshipCapacity(self._session, self._actor)
        available: dict[str, int] = {}
        for surface in PACKAGE_SURFACES.get(campaign.package, ()):
            forecast = await capacity.forecast(surface, start, end)
            available[surface] = forecast.available
        metrics = OperationMetrics(self._session, self._actor)
        scorecard = await metrics.scorecard(
            period_start=start, period_end=end, definition_version=definition.version
        )
        return InternalDetail(
            collection_state=campaign.collection_state,
            collection_reference=campaign.collection_reference,
            catalog_version=quote.catalog_version if quote else None,
            discount_amount=quote.discount_amount if quote else Decimal("0"),
            discount_reason=quote.discount_reason if quote else None,
            capacity_available=available,
            invalid_events={
                traffic_class: int(count) for traffic_class, count in invalid
            },
            duplicate_suppressed=await self._duplicate_suppressed(campaign),
            follow_up_data_completeness=scorecard.follow_up_data_completeness,
            outcome_completeness=scorecard.outcome_completeness,
        )

    async def _duplicate_suppressed(self, campaign: SponsorshipCampaign) -> int:
        """How many repeat emissions the Outbox absorbed for this campaign.

        Read from the Outbox rather than the event store: a suppressed duplicate
        by definition never became an event, so the event store cannot count it.
        """
        total = await self._session.scalar(
            select(func.coalesce(func.sum(AnalyticsOutboxEntry.duplicate_attempts), 0))
            .where(
                AnalyticsOutboxEntry.organization_id == campaign.organization_id,
                AnalyticsOutboxEntry.payload["campaign_id"].astext
                == str(campaign.id),
            )
        )
        return int(total or 0)

    @staticmethod
    def _notes(
        campaign: SponsorshipCampaign, counts: dict[str, int]
    ) -> tuple[str, ...]:
        """Sentences the report has earned the right to say.

        SAN-067 asks how a campaign with much exploration and no appointment is
        explained. The answer is a described observation, never a diagnosis: the
        report says what the numbers show and leaves the interpretation to the
        Advisor who knows the property.
        """
        notes: list[str] = []
        if campaign.paused_reason:
            notes.append(
                "La entrega se pausó y los días pagados restantes se conservan: "
                f"{campaign.paused_reason}."
            )
        explored = counts.get("SignificantGalleryExploration", 0)
        requested = counts.get("AppointmentRequested", 0)
        if explored > 0 and requested == 0:
            notes.append(
                "Hubo exploración significativa de galería sin solicitudes de "
                "cita en el periodo. Es una observación del embudo, no un "
                "diagnóstico de la propiedad ni del precio."
            )
        if counts.get("SponsoredServedImpression", 0) > counts.get(
            "SponsoredVisibleImpression", 0
        ):
            notes.append(
                "Las impresiones entregadas superan a las visibles: parte de las "
                "posiciones no alcanzó el umbral de visibilidad de la versión "
                "de medición vigente."
            )
        return tuple(notes)

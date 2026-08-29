"""What a report may say, and the several things it must refuse to say.

The buyer report is the product's main claim about itself, so it is where honesty
is cheapest to lose. Each test here pins one guard:

* a comparable cohort below the versioned sample says
  ``Estimación inicial sin historial suficiente`` and shows no number at all;
* an unknown outcome is ``Sin registrar``, never zero and never a loss;
* unit economics with no denominator are ``No calculable``, not free;
* attribution reports what followed inside the declared 7- and 90-day windows
  and nothing about cause;
* the buyer view contains no identity, no phone, no conversation, no individual
  search and no Saved Collection — in the JSON, in the page lines, and in the PDF.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from realestate.db.engine import Database
from realestate.db.models import AnalyticsEventName, ReportAudience
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.metrics import (
    NOT_COMPUTABLE_TEXT,
    PROTECTED_TEXT,
    UNRECORDED_TEXT,
)
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.commercial.actors import NotAuthorized, NotFound
from realestate.domain.sponsorship.capacity import SponsorshipCapacity
from realestate.domain.sponsorship.comparables import (
    SponsorshipComparables,
    price_band,
)
from realestate.domain.sponsorship.labels import (
    INSUFFICIENT_HISTORY,
    NON_CAUSAL_DISCLAIMER,
    SPONSORED_DISCLOSURE,
    SPONSORED_LABEL,
)
from realestate.domain.sponsorship.reporting import SponsorshipReporting
from realestate.domain.sponsorship.sharing import report_lines, report_pdf
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    ADVISOR_LOGIN,
    actor_for,
    provision,
    reset,
)
from tests.fixtures.sponsorship import MOMENT, active_campaign, published_catalog

pytestmark = requires_postgres

#: Words a report may not use to describe a campaign's effect. Checked over the
#: rendered buyer surface with the two fixed statements removed first: those two
#: sentences use "garantiza" and "causalidad" precisely to *deny* a claim, and a
#: check that could not tell the difference would have to be weakened until it
#: caught nothing.
CAUSAL_WORDS = (
    "garantiza",
    "garantizado",
    "causó",
    "causal",
    "gracias a la campaña",
    "incremento atribuible",
    "aumentó por",
    "provocó",
    "lift",
)


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await provision(session)
        await session.commit()
    yield database
    await database.dispose()


async def funnel_events(session, actor, campaign_id, listing_id, *, at=MOMENT) -> None:
    """One synthetic pass through the whole sponsored funnel."""
    events = AnalyticsEvents(session, actor)
    for index in range(4):
        await events.record(
            AnalyticsEvent(
                event_key=f"served-{campaign_id}-{index}",
                name=AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
                occurred_at=at,
                listing_id=listing_id,
                campaign_id=campaign_id,
                session_value=f"visitor-{index}",
                attributes={"surface": "Search", "position": 1},
            )
        )
    for index in range(3):
        await events.record(
            AnalyticsEvent(
                event_key=f"visible-{campaign_id}-{index}",
                name=AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION,
                occurred_at=at,
                listing_id=listing_id,
                campaign_id=campaign_id,
                session_value=f"visitor-{index}",
                attributes={
                    "surface": "Search",
                    "visible_fraction": 0.6,
                    "continuous_milliseconds": 1400,
                },
            )
        )
    await events.record(
        AnalyticsEvent(
            event_key=f"opened-{campaign_id}",
            name=AnalyticsEventName.LISTING_OPENED,
            occurred_at=at,
            listing_id=listing_id,
            campaign_id=campaign_id,
            session_value="visitor-0",
            attributes={"surface": "TechnicalSheet"},
        )
    )
    await events.record(
        AnalyticsEvent(
            event_key=f"depth-{campaign_id}",
            name=AnalyticsEventName.GALLERY_DEPTH_REACHED,
            occurred_at=at,
            listing_id=listing_id,
            campaign_id=campaign_id,
            session_value="visitor-0",
            attributes={"photographs": 6, "gallery_fraction": 0.5},
        )
    )
    await events.record(
        AnalyticsEvent(
            event_key=f"explored-{campaign_id}",
            name=AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION,
            occurred_at=at,
            listing_id=listing_id,
            campaign_id=campaign_id,
            session_value="visitor-0",
            attributes={"photographs": 6, "gallery_fraction": 0.5},
        )
    )


@pytest.mark.parametrize(
    ("operation", "amount", "band"),
    [
        ("Sale", None, "Sin precio registrado"),
        ("Sale", Decimal("5000000"), "Hasta 5 M"),
        ("Sale", Decimal("5000001"), "5 a 8 M"),
        ("Sale", Decimal("12000000"), "8 a 12 M"),
        ("Sale", Decimal("20000000"), "12 a 20 M"),
        ("Sale", Decimal("20000001"), "Más de 20 M"),
        ("Rental", Decimal("20000"), "Hasta 20 mil"),
        ("Rental", Decimal("20001"), "20 a 35 mil"),
        ("Rental", Decimal("50000"), "35 a 50 mil"),
        ("Rental", Decimal("85000"), "50 a 85 mil"),
        ("Rental", Decimal("85001"), "Más de 85 mil"),
    ],
)
def test_a_price_band_describes_the_listing_and_names_the_unknown(
    operation, amount, band
) -> None:
    """A Commercial Price Band is about the Listing, never about the Contact."""
    assert price_band(amount, operation=operation) == band


async def test_a_cohort_below_the_minimum_sample_shows_no_number(database) -> None:
    """A median of one campaign is that campaign, not a comparable.

    Presenting it to a buyer would be a forecast dressed up as evidence, so the
    report says it has insufficient history and shows nothing.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "sola")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT + timedelta(days=1)
        )
        assert len(report.comparables) == 1
        comparable = report.comparables[0]
        assert comparable.sample_size == 0
        assert comparable.sufficient is False
        assert comparable.text == INSUFFICIENT_HISTORY
        assert comparable.median_visible_impressions is None
        # The cohort key still discloses what it grouped by, so the absence is
        # readable rather than mysterious.
        assert "Venta" in comparable.key.text
        assert "Zapopan" in comparable.key.text


async def test_a_cohort_at_the_minimum_sample_discloses_median_and_range(
    database,
) -> None:
    """Period, sample size, median and range, and the subject excluded.

    Excluding the campaign being reported is what makes the comparable a
    comparison rather than a campaign quoting itself as evidence.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        # Four concurrent campaigns is more than the surface would normally
        # sell; the cohort needs peers, so the Administrator raises the limit
        # explicitly rather than the fixture bypassing it.
        await SponsorshipCapacity(session, admin).set_limit("Search", 8, at=MOMENT)
        subject = await active_campaign(session, admin, "sujeto")
        peers = [
            await active_campaign(session, admin, f"par-{index}")
            for index in range(3)
        ]
        await funnel_events(
            session, admin, subject.campaign_id, subject.listing.listing_id
        )
        events = AnalyticsEvents(session, admin)
        for index, peer in enumerate(peers):
            for repeat in range(index + 1):
                await events.record(
                    AnalyticsEvent(
                        event_key=f"peer-visible-{index}-{repeat}",
                        name=AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION,
                        occurred_at=MOMENT,
                        listing_id=peer.listing.listing_id,
                        campaign_id=peer.campaign_id,
                        session_value=f"peer-visitor-{index}-{repeat}",
                        attributes={
                            "surface": "Search",
                            "visible_fraction": 0.7,
                            "continuous_milliseconds": 1200,
                        },
                    )
                )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            subject.campaign_id,
            ReportAudience.BUYER,
            at=MOMENT + timedelta(days=1),
            period_start=MOMENT - timedelta(days=1),
        )
        comparable = report.comparables[0]
        assert comparable.sample_size == 3
        assert comparable.sufficient is True
        assert comparable.median_visible_impressions == Decimal("2")
        assert (comparable.lowest, comparable.highest) == (1, 3)
        assert "Mediana 2" in comparable.text
        assert "3 campañas comparables" in comparable.text
        assert comparable.period_start == MOMENT - timedelta(days=1)


async def test_the_funnel_is_reported_in_the_published_order_with_step_conversion(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "embudo")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT + timedelta(days=1)
        )
        steps = {row.step: row for row in report.funnel}
        assert [row.step for row in report.funnel][:3] == [
            "SponsoredServedImpression",
            "SponsoredVisibleImpression",
            "ListingOpened",
        ]
        assert steps["SponsoredServedImpression"].count == 4
        assert steps["SponsoredVisibleImpression"].count == 3
        assert steps["ListingOpened"].count is None
        # Conversion from the step above, so "much exploration, no appointment"
        # is answerable at the boundary where it happened (SAN-067).
        assert steps["SponsoredVisibleImpression"].from_previous.text == "75 %"
        assert steps["ListingOpened"].from_previous.text == PROTECTED_TEXT
        # The first row has nothing above it, so its conversion is not a zero.
        assert (
            report.funnel[0].from_previous.text == NOT_COMPUTABLE_TEXT
        )
        # Served above visible is described honestly rather than hidden.
        assert any("umbral de visibilidad" in note for note in report.notes)


async def test_an_unrecorded_outcome_is_sin_registrar_and_not_a_loss(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "resultado")
        events = AnalyticsEvents(session, admin)
        await events.record(
            AnalyticsEvent(
                event_key="attended-without-outcome",
                name=AnalyticsEventName.APPOINTMENT_ATTENDED,
                occurred_at=MOMENT,
                campaign_id=campaign.campaign_id,
                attributes={"attendance": "Attended"},
            )
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id,
            ReportAudience.ADMINISTRATOR,
            at=MOMENT + timedelta(days=1),
        )
        assert report.outcomes == {"Won": 0, "Lost": 0, "Dormant": 0}
        assert report.unrecorded_outcomes.text == UNRECORDED_TEXT
        assert report.unrecorded_outcomes.unrecorded == 1


async def test_unit_economics_without_a_denominator_are_not_computable(
    database,
) -> None:
    """No appointment requests does not make the cost per request zero."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "economia")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id,
            ReportAudience.ADMINISTRATOR,
            at=MOMENT + timedelta(days=1),
        )
        assert report.economics.price == Decimal("4000.00")
        # 4000 over three visible impressions.
        assert report.economics.cost_per_visible_impression.text.startswith("1333.3")
        assert report.economics.cost_per_listing_open.text == "4000 MXN"
        assert (
            report.economics.cost_per_appointment_request.text == NOT_COMPUTABLE_TEXT
        )


async def test_attribution_reports_both_windows_without_claiming_cause(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "atribucion")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        events = AnalyticsEvents(session, admin)
        # Campaign tagging alone is not attribution: this outcome predates every
        # exposure and engagement and must be outside both windows.
        await events.record(
            AnalyticsEvent(
                event_key="outcome-before-campaign-exposure",
                name=AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN,
                occurred_at=MOMENT - timedelta(days=1),
                campaign_id=campaign.campaign_id,
                attributes={"outcome": "Dormant"},
            )
        )
        # Inside seven days of the exposure, and inside ninety.
        await events.record(
            AnalyticsEvent(
                event_key="outcome-within-seven",
                name=AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN,
                occurred_at=MOMENT + timedelta(days=3),
                campaign_id=campaign.campaign_id,
                attributes={"outcome": "Won"},
            )
        )
        # Outside seven days, inside ninety.
        await events.record(
            AnalyticsEvent(
                event_key="outcome-within-ninety",
                name=AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN,
                occurred_at=MOMENT + timedelta(days=40),
                campaign_id=campaign.campaign_id,
                attributes={"outcome": "Lost"},
            )
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id,
            ReportAudience.ADMINISTRATOR,
            at=MOMENT + timedelta(days=95),
        )
        assert report.attribution.view_through_days == 7
        assert report.attribution.engaged_days == 90
        assert report.attribution.view_through_outcomes == 1
        assert report.attribution.engaged_outcomes == 2
        assert report.attribution.disclaimer == NON_CAUSAL_DISCLAIMER


async def test_no_buyer_surface_uses_causal_language(database) -> None:
    """Checked over the rendered lines and the PDF bytes, not one template."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "lenguaje")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT + timedelta(days=1)
        )
        rendered = "\n".join(line.text for line in report_lines(report)).casefold()
        # The two fixed statements are present, and they are the only place the
        # words may appear at all.
        assert SPONSORED_DISCLOSURE.casefold() in rendered
        assert NON_CAUSAL_DISCLAIMER.casefold() in rendered
        assert SPONSORED_LABEL.casefold() in rendered

        body = rendered.replace(SPONSORED_DISCLOSURE.casefold(), "").replace(
            NON_CAUSAL_DISCLAIMER.casefold(), ""
        )
        for word in CAUSAL_WORDS:
            assert word not in body, word

        pdf = report_pdf(report)
        assert pdf.startswith(b"%PDF-1.7")
        assert pdf.rstrip().endswith(b"%%EOF")


async def test_a_paused_campaign_explains_the_preserved_days(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "pausa-reporte")
        from realestate.domain.sponsorship.campaigns import SponsorshipCampaigns

        await SponsorshipCampaigns(session, admin).pause(
            campaign.campaign_id, "La ficha entró en revisión.", at=MOMENT
        )
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT + timedelta(days=1)
        )
        assert any("días pagados restantes se conservan" in note for note in report.notes)
        assert report.campaign.remaining_days == report.campaign.paid_days


async def test_much_exploration_and_no_appointment_is_described_not_diagnosed(
    database,
) -> None:
    """SAN-067's hard conversation, answered as an observation.

    The report says what the funnel shows and leaves the interpretation to the
    Advisor who knows the property — it does not conclude the price is wrong.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "exploracion")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT + timedelta(days=1)
        )
        note = next(
            note for note in report.notes if "exploración significativa" in note
        )
        assert "no un diagnóstico" in note


async def test_the_internal_report_adds_the_commercial_half(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "interno")
        await funnel_events(
            session, admin, campaign.campaign_id, campaign.listing.listing_id
        )
        await session.commit()
        await AnalyticsProjection(session, admin).drain()
        await session.commit()

        internal = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id,
            ReportAudience.ADMINISTRATOR,
            at=MOMENT + timedelta(days=1),
        )
        assert internal.internal is not None
        assert internal.internal.catalog_version == "precios-piloto-1"
        assert internal.internal.collection_state == "NotInvoiced"
        assert "Search" in internal.internal.capacity_available
        assert internal.internal.invalid_events == {}

        buyer = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT + timedelta(days=1)
        )
        assert buyer.internal is None
        assert buyer.is_buyer_view is True
        # Both views use one computation, but the buyer's person-level small
        # cells are suppressed at the presentation boundary.
        assert [row.count for row in buyer.funnel[:2]] == [
            row.count for row in internal.funnel[:2]
        ]
        assert buyer.funnel[2].count is None
        assert internal.funnel[2].count == 1


async def test_an_advisor_may_not_request_the_internal_report(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "autorizacion")
        await session.commit()

        advisor = await actor_for(session, ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized):
            await SponsorshipReporting(session, advisor).generate(
                campaign.campaign_id,
                ReportAudience.ADMINISTRATOR,
                at=MOMENT,
            )


async def test_reporting_an_unknown_campaign_is_a_named_refusal(database) -> None:
    import uuid

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(NotFound):
            await SponsorshipReporting(session, admin).generate(
                uuid.uuid4(), ReportAudience.BUYER, at=MOMENT
            )


async def test_a_cohort_names_a_missing_municipality_rather_than_merging(
    database,
) -> None:
    """An unlabelled Listing gets a named unknown, not an empty group key.

    An empty key would silently merge every Listing with no public location into
    one comparable cohort and report a median across unrelated properties.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "sin-zona")
        row = await SponsorshipCampaigns_read(session, campaign.campaign_id)
        from realestate.db.models import CatalogListing

        listing = await session.get(CatalogListing, row.listing_id)
        assert listing is not None
        listing.public_location = None
        await session.commit()

        key = await SponsorshipComparables(session, admin).cohort_key(row, "Search")
        assert key.municipality == "Sin municipio registrado"


async def SponsorshipCampaigns_read(session, campaign_id):
    from realestate.db.models import SponsorshipCampaign

    row = await session.get(SponsorshipCampaign, campaign_id)
    assert row is not None
    return row

"""The refusals, the guards and the second paths.

Every case here is a branch the happy path never reaches: a state the lifecycle
declines, an argument the module rejects, a race two statements apart, or the
second time a caller does the same thing. They are separated from the main suites
because they read as a list rather than as a story, and because grouping them
makes it obvious when one of them stops being reachable.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    Appointment,
    AppointmentStatus,
    CatalogListing,
    FactsReviewState,
    HarmSignalKind,
    ListingAuthority,
    ListingAvailability,
    ListingPublicationState,
    PublicAnalyticsEventName,
    ReportAudience,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipQuote,
    SponsorshipQuoteStatus,
    UnitModel,
)
from realestate.domain.analytics.definitions import CURRENT_DEFINITION_VERSION
from realestate.domain.analytics.emission import AnalyticsEmission
from realestate.domain.analytics.events import (
    AnalyticsEvent,
    AnalyticsEvents,
    EventRejected,
)
from realestate.domain.analytics.metrics import (
    HarmSignalCommand,
    HarmSignals,
    OperationMetrics,
)
from realestate.domain.analytics.projection import AnalyticsProjection, RefreshReport
from realestate.domain.analytics.pseudonyms import Pseudonyms, Purpose
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    CreateListing,
    CreateProperty,
    ReviewListingFacts,
    SetListingAuthority,
    SetListingAvailability,
    SetPublicationState,
    SetReadinessOverride,
)
from realestate.domain.commercial.actors import InvalidTransition, NotFound
from realestate.domain.commercial.opportunities import (
    OpportunityManagement,
    RecordWon,
    WonEvidence,
)
from realestate.domain.public.analytics import PublicAnalytics, PublicEventCommand
from realestate.domain.public.listing import PublicListing, PublicListingResult
from realestate.domain.public.sponsored import PublicSponsored
from realestate.domain.sponsorship.campaigns import (
    OpenCampaign,
    ScheduleCampaign,
    SponsorshipCampaigns,
)
from realestate.domain.sponsorship.capacity import SponsorshipCapacity
from realestate.domain.sponsorship.comparables import SponsorshipComparables
from realestate.domain.sponsorship.eligibility import SponsoredEligibility
from realestate.domain.sponsorship.pdf import CHARACTERS_PER_LINE, Line, wrapped
from realestate.domain.sponsorship.pricing import (
    DraftCatalog,
    PriceLine,
    PublishCatalog,
    SponsorshipPricing,
)
from realestate.domain.sponsorship.quoting import (
    AcceptQuote,
    QuoteCommand,
    QuoteRefused,
    SponsorshipQuoting,
)
from realestate.domain.sponsorship.reporting import SponsorshipReporting
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    actor_for,
    confirm_minimum_criteria,
    opportunity_for,
    provision,
    reset,
)
from tests.fixtures.public_site import publish_listing
from tests.fixtures.sponsorship import (
    CLEARANCE,
    MOMENT,
    active_campaign,
    published_catalog,
)

pytestmark = requires_postgres


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


# -- pricing ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        (PriceLine("Instagram", 30, Decimal("100")), "paquete"),
        (PriceLine("Search", 0, Decimal("100")), "positivos"),
        (PriceLine("Search", 30, Decimal("-1")), "positivos"),
    ],
)
async def test_a_draft_line_outside_the_sellable_packages_is_refused(
    database, line, fragment
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(ValueError, match=fragment):
            await SponsorshipPricing(session, admin).draft(
                DraftCatalog(
                    version="mala",
                    currency="MXN",
                    lines=(line,),
                    command_key="catalog:mala",
                ),
                at=MOMENT,
            )


async def test_a_retired_catalog_cannot_be_published_again(database) -> None:
    """Republishing a retired version would make its recorded price current again.

    The version is the identity a quote preserved, so bringing it back would
    silently change what an already-accepted quote appears to have charged.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        pricing = SponsorshipPricing(session, admin)
        await published_catalog(session, admin, version="precios-1")
        await published_catalog(session, admin, version="precios-2")
        await session.commit()

        retired = next(
            item for item in await pricing.catalogs() if item.version == "precios-1"
        )
        assert retired.status == "Retired"
        with pytest.raises(InvalidTransition, match="retirado"):
            await pricing.publish(
                PublishCatalog(retired.catalog_id, "Evidencia sintética del piloto."),
                at=MOMENT,
            )

        # And it is still readable by id, with its own preserved prices.
        read_back = await pricing.by_id(retired.catalog_id)
        assert read_back.version == "precios-1"
        assert read_back.amount_for("Search", 30) == Decimal("4000.00")
        assert read_back.amount_for("Search", 45) is None

        with pytest.raises(NotFound):
            await pricing.publish(
                PublishCatalog(uuid.uuid4(), "Evidencia sintética del piloto."),
                at=MOMENT,
            )


# -- quoting ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"command_key": "  "}, "clave de operación"),
        ({"duration_days": 0}, "duración"),
        ({"discount_amount": Decimal("-5")}, "negativo"),
    ],
)
async def test_a_malformed_quote_command_is_refused(
    database, overrides, fragment
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        values: dict[str, object] = {
            "campaign_id": uuid.uuid4(),
            "command_key": "q:malformada",
        }
        values.update(overrides)
        with pytest.raises(QuoteRefused, match=fragment):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(**values),  # type: ignore[arg-type]
                at=MOMENT,
            )


async def test_quoting_an_unknown_campaign_is_a_named_refusal(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        with pytest.raises(NotFound, match="campaña"):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(campaign_id=uuid.uuid4(), command_key="q:fantasma"),
                at=MOMENT,
            )


async def test_a_reserved_campaign_does_not_accept_a_new_quote(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "ya-reservada")
        await session.commit()
        with pytest.raises(InvalidTransition, match="borrador o cotizada"):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(
                    campaign_id=campaign.campaign_id, command_key="q:ya-reservada"
                ),
                at=MOMENT,
            )


async def test_accepting_a_reserved_quote_twice_returns_the_same_reservation(
    database,
) -> None:
    """Idempotent, because a double-clicked acceptance must not reserve twice."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "aceptada-dos-veces")
        await session.commit()

        quoting = SponsorshipQuoting(session, admin)
        again = await quoting.accept(
            AcceptQuote(campaign.quote_id, MOMENT), at=MOMENT
        )
        await session.commit()
        assert again.status == SponsorshipQuoteStatus.RESERVED.value


async def test_an_expired_quote_cannot_be_accepted_afterwards(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        listing = await publish_listing(session, admin, "caduca")
        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.open(
            OpenCampaign(
                listing_id=listing.listing_id,
                buyer_kind="Owner",
                buyer_label="Propietario sintético",
                package="Search",
            ),
            at=MOMENT,
        )
        await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:caduca"),
            at=MOMENT,
        )
        await quoting.expire_due(at=MOMENT + timedelta(days=8))
        await session.commit()

        with pytest.raises(InvalidTransition, match="vigente"):
            await quoting.accept(
                AcceptQuote(quote.quote_id, MOMENT + timedelta(days=9)),
                at=MOMENT + timedelta(days=9),
            )


async def test_cancelling_a_campaign_cancels_its_outstanding_quote(database) -> None:
    """An Issued quote for a cancelled campaign is one somebody could still accept."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        listing = await publish_listing(session, admin, "cancelada-con-cotizacion")
        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.open(
            OpenCampaign(
                listing_id=listing.listing_id,
                buyer_kind="Owner",
                buyer_label="Propietario sintético",
                package="Search",
            ),
            at=MOMENT,
        )
        await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
        quote = await SponsorshipQuoting(session, admin).quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:cancelada"),
            at=MOMENT,
        )
        await session.commit()

        await campaigns.cancel(view.campaign_id, "El comprador se retiró", at=MOMENT)
        await session.commit()

        stored = await session.get(SponsorshipQuote, quote.quote_id)
        assert stored is not None
        assert stored.status == SponsorshipQuoteStatus.CANCELLED.value


# -- campaigns -------------------------------------------------------------


async def test_opening_a_campaign_over_an_unknown_listing_is_refused(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(NotFound, match="publicación"):
            await SponsorshipCampaigns(session, admin).open(
                OpenCampaign(
                    listing_id=uuid.uuid4(),
                    buyer_kind="Owner",
                    buyer_label="Propietario sintético",
                    package="Search",
                ),
                at=MOMENT,
            )


async def test_the_daily_pass_activates_a_scheduled_campaign_on_its_start_date(
    database,
) -> None:
    """Nobody has to press Activate on the morning the campaign begins."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        listing = await publish_listing(session, admin, "programada")
        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.open(
            OpenCampaign(
                listing_id=listing.listing_id,
                buyer_kind="Owner",
                buyer_label="Propietario sintético",
                package="Search",
                paid_days=5,
            ),
            at=MOMENT,
        )
        await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(
                campaign_id=view.campaign_id,
                command_key="q:programada",
                duration_days=5,
            ),
            at=MOMENT,
        )
        start = MOMENT + timedelta(days=2)
        await quoting.accept(AcceptQuote(quote.quote_id, start), at=MOMENT)
        await campaigns.schedule(ScheduleCampaign(view.campaign_id, start), at=MOMENT)
        await session.commit()

        # Before the start date the pass consumes nothing.
        early = await campaigns.run_daily(at=MOMENT)
        await session.commit()
        assert [item.counted for item in early] == [False]
        row = await session.get(SponsorshipCampaign, view.campaign_id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.SCHEDULED.value

        on_time = await campaigns.run_daily(at=start)
        await session.commit()
        assert [item.counted for item in on_time] == [True]
        row = await session.get(SponsorshipCampaign, view.campaign_id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.ACTIVE.value
        assert row.delivered_days == 1

        # The delivery days are readable, including the ones that consumed nothing.
        days = await campaigns.delivery_days(view.campaign_id)
        assert [(day.counted, day.reason) for day in days] == [
            (False, "NotEligible"),
            (True, "Delivered"),
        ]


async def test_campaigns_can_be_listed_by_status(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "activa-listada")
        await publish_listing(session, admin, "borrador-listado")
        campaigns = SponsorshipCampaigns(session, admin)
        draft_listing = await session.scalar(
            select(CatalogListing).where(
                CatalogListing.listing_key == "casa-borrador-listado-organization"
            )
        )
        assert draft_listing is not None
        await campaigns.open(
            OpenCampaign(
                listing_id=draft_listing.id,
                buyer_kind="Owner",
                buyer_label="Propietario sintético",
                package="Homepage",
            ),
            at=MOMENT,
        )
        await session.commit()

        active = await campaigns.campaigns(
            statuses=(SponsorshipCampaignStatus.ACTIVE.value,)
        )
        assert [item.status for item in active] == ["Active"]
        assert len(await campaigns.campaigns()) == 2

        read = await campaigns.read(active[0].campaign_id)
        assert read.status == "Active"
        with pytest.raises(NotFound):
            await campaigns.read(uuid.uuid4())
        with pytest.raises(NotFound):
            await campaigns.pause(uuid.uuid4(), "Fantasma", at=MOMENT)


# -- capacity --------------------------------------------------------------


async def test_a_capacity_limit_can_be_lowered_after_it_was_set(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        capacity = SponsorshipCapacity(session, admin)
        await capacity.set_limit("Search", 5, at=MOMENT)
        await session.commit()
        assert await capacity.limit("Search") == 5

        await capacity.set_limit("Search", 1, at=MOMENT + timedelta(days=1))
        await session.commit()
        assert await capacity.limit("Search") == 1

        with pytest.raises(ValueError, match="negativa"):
            await capacity.set_limit("Search", -1, at=MOMENT)
        with pytest.raises(ValueError, match="superficie"):
            await capacity.set_limit("Instagram", 1, at=MOMENT)


async def test_reserving_the_same_campaign_again_moves_its_window(database) -> None:
    """A rescheduled reservation is the same hold, not a second one."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "reservada-otra-vez")
        await session.commit()

        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        capacity = SponsorshipCapacity(session, admin)
        later = MOMENT + timedelta(days=10)
        await capacity.reserve(row, starts_on=later, days=30, at=MOMENT)
        await session.commit()

        from realestate.db.models import SponsorshipCapacityReservation

        holds = list(
            await session.scalars(
                select(SponsorshipCapacityReservation).where(
                    SponsorshipCapacityReservation.campaign_id == campaign.campaign_id
                )
            )
        )
        assert len(holds) == 1
        assert holds[0].starts_on == later
        assert holds[0].released_at is None


async def test_measured_exposure_appears_once_there_are_seven_days_of_it(
    database,
) -> None:
    """Below a week the forecast says it has no history; at a week it reports one."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "medida")
        events = AnalyticsEvents(session, admin)
        for day in range(7):
            for index in range(2):
                await events.record(
                    AnalyticsEvent(
                        event_key=f"medida-visible-{day}-{index}",
                        name=AnalyticsEventName.SPONSORED_VISIBLE_IMPRESSION,
                        occurred_at=MOMENT + timedelta(days=day),
                        listing_id=campaign.listing.listing_id,
                        campaign_id=campaign.campaign_id,
                        session_value=f"visitante-{day}-{index}",
                        attributes={
                            "surface": "Search",
                            "visible_fraction": 0.8,
                            "continuous_milliseconds": 1500,
                        },
                    )
                )
        await session.commit()
        await AnalyticsProjection(session).drain()
        await session.commit()

        forecast = await SponsorshipCapacity(session, admin).forecast(
            "Search", MOMENT, MOMENT + timedelta(days=30)
        )
        assert forecast.measured_daily_visible == 2
        assert "2 impresiones visibles diarias medidas" in forecast.exposure_note


# -- eligibility -----------------------------------------------------------


async def test_a_listing_with_no_campaign_is_not_eligible_for_paid_placement(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "sin-campana")
        await session.commit()

        decision = await SponsoredEligibility(session, admin).evaluate(
            listing.listing_id, "Search", MOMENT
        )
        assert decision.blocked
        assert "no existe una campaña de patrocinio para la publicación" in (
            decision.reasons
        )
        assert decision.campaign_id == uuid.UUID(int=0)

        with pytest.raises(NotFound, match="publicación"):
            await SponsoredEligibility(session, admin).evaluate(
                uuid.uuid4(), "Search", MOMENT
            )


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        ({"status": SponsorshipCampaignStatus.CANCELLED.value}, "cancelada"),
        ({"status": SponsorshipCampaignStatus.COMPLETED.value}, "ya se completó"),
        ({"delivered_days": 30}, "no quedan días pagados"),
    ],
)
async def test_a_finished_campaign_is_not_eligible(database, mutate, fragment) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "terminada")
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        for name, value in mutate.items():
            setattr(row, name, value)
        await session.flush()

        decision = await SponsoredEligibility(session, admin).evaluate(
            campaign.listing.listing_id, "Search", MOMENT, campaign=row
        )
        assert decision.blocked
        assert any(fragment in reason for reason in decision.reasons)
        await session.rollback()


async def test_a_package_that_excludes_the_surface_is_not_eligible_on_it(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(
            session, admin, "solo-portada", package="Homepage"
        )
        await session.commit()

        decision = await SponsoredEligibility(session, admin).evaluate(
            campaign.listing.listing_id, "Search", MOMENT
        )
        assert decision.blocked
        assert any("no incluye esa superficie" in reason for reason in decision.reasons)


async def test_an_eligible_exposure_decision_is_not_recorded(database) -> None:
    """Only refusals are stored; a Served Impression already evidences the rest.

    A row per rendered placement would put a write on the read path of every
    search page.
    """
    from realestate.db.models import SponsoredEligibilityRecord

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "elegible")
        await session.commit()

        eligibility = SponsoredEligibility(session, admin)
        decision = await eligibility.evaluate(
            campaign.listing.listing_id, "Search", MOMENT
        )
        assert decision.eligible
        await eligibility.record_exposure(campaign.campaign_id, decision, at=MOMENT)
        await session.commit()

        rows = list(
            await session.scalars(
                select(SponsoredEligibilityRecord).where(
                    SponsoredEligibilityRecord.scope == "Exposure"
                )
            )
        )
        assert rows == []


# -- delivery --------------------------------------------------------------


async def test_a_slot_whose_listing_disappears_mid_render_is_dropped(
    database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race between the eligibility check and the public read.

    Two statements apart in production, so it is reproduced by making the read
    answer as it would for a Listing withdrawn in between. Substituting the next
    campaign would bill the wrong buyer for this impression.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "desaparecida")
        await session.commit()

        async def withdrawn(self, listing_id, *, at):  # noqa: ANN001, ANN202
            return PublicListingResult(
                status_code=410,
                listing=None,
                slug="retirada",
                indexable=False,
                unavailable_reason="Esta propiedad ya no está disponible.",
            )

        monkeypatch.setattr(PublicListing, "read_by_id", withdrawn)
        result = await PublicSponsored(session, admin).for_surface(
            surface="Search",
            at=MOMENT,
            visible_results=12,
            session_value="navegador-carrera",
        )
        await session.commit()
        assert result.cards == ()
        assert result.available_slots == 2


# -- comparables -----------------------------------------------------------


async def test_a_cohort_with_peers_but_no_events_reports_no_sample(database) -> None:
    """Comparable campaigns exist; none of them was measured in the period."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await SponsorshipCapacity(session, admin).set_limit("Search", 8, at=MOMENT)
        subject = await active_campaign(session, admin, "sujeto-sin-datos")
        await active_campaign(session, admin, "par-sin-datos")
        await session.commit()

        from realestate.domain.analytics.definitions import MeasurementDefinitions

        definition = await MeasurementDefinitions(session).resolve()
        module = SponsorshipComparables(session, admin)
        row = await session.get(SponsorshipCampaign, subject.campaign_id)
        assert row is not None
        key = await module.cohort_key(row, "Search")
        comparable = await module.describe(
            key,
            definition,
            period_start=MOMENT,
            period_end=MOMENT + timedelta(days=1),
            exclude_campaign_id=subject.campaign_id,
        )
        assert comparable.sample_size == 0
        assert comparable.sufficient is False


async def test_a_unit_model_listing_takes_its_type_from_the_model(database) -> None:
    """A Development Listing has no Property, so the cohort reads the Unit Model."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        from realestate.domain.catalog.administration import (
            CreateDevelopment,
            CreateUnitModel,
            ReviewUnitModelFacts,
        )

        development = await catalog.record(
            admin,
            CreateDevelopment(
                development_key="desarrollo-medicion",
                name="Desarrollo Medición",
                facts={"city": "Zapopan"},
                provenance={"kind": "Test"},
                command_key="edges:development",
            ),
        )
        model = await catalog.record(
            admin,
            CreateUnitModel(
                development_id=development.subject_id,
                model_key="modelo-a",
                name="Modelo A",
                facts={"property_type": "Apartment", "bedrooms": 2},
                provenance={"kind": "Test"},
                command_key="edges:model",
            ),
        )
        await catalog.record(
            admin,
            ReviewUnitModelFacts(
                unit_model_id=model.subject_id,
                review_state=FactsReviewState.APPROVED,
                facts={"property_type": "Apartment", "bedrooms": 2},
                command_key="edges:model-review",
            ),
        )
        listing = await catalog.record(
            admin,
            CreateListing(
                listing_key="modelo-a-listing",
                unit_model_id=model.subject_id,
                source_kind="Organization",
                source_name="Larevia",
                attribution="Fuente: Larevia",
                title="Modelo A",
                public_location="Zapopan, Jalisco",
                provenance={"kind": "Test"},
                command_key="edges:listing",
            ),
        )
        await session.commit()

        row = await session.get(CatalogListing, listing.subject_id)
        assert row is not None
        assert row.property_uuid is None
        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.open(
            OpenCampaign(
                listing_id=row.id,
                buyer_kind="Developer",
                buyer_label="Desarrollador sintético",
                package="Search",
            ),
            at=MOMENT,
        )
        await session.commit()

        campaign = await session.get(SponsorshipCampaign, view.campaign_id)
        assert campaign is not None
        key = await SponsorshipComparables(session, admin).cohort_key(
            campaign, "Search"
        )
        assert key.property_type == "Apartment"

        # And a Unit Model whose facts name no type falls back to Development.
        stored_model = await session.get(UnitModel, model.subject_id)
        assert stored_model is not None
        stored_model.facts = {"bedrooms": 2}
        await session.flush()
        fallback = await SponsorshipComparables(session, admin).cohort_key(
            campaign, "Search"
        )
        assert fallback.property_type == "Development"
        await session.rollback()


# -- reporting -------------------------------------------------------------


async def test_known_outcomes_are_counted_and_completeness_is_a_real_ratio(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "resultados-conocidos")
        events = AnalyticsEvents(session, admin)
        for index in range(2):
            await events.record(
                AnalyticsEvent(
                    event_key=f"asistio-{index}",
                    name=AnalyticsEventName.APPOINTMENT_ATTENDED,
                    occurred_at=MOMENT,
                    campaign_id=campaign.campaign_id,
                    attributes={"attendance": "Attended"},
                )
            )
        await events.record(
            AnalyticsEvent(
                event_key="resultado-ganado",
                name=AnalyticsEventName.OPPORTUNITY_OUTCOME_KNOWN,
                occurred_at=MOMENT,
                campaign_id=campaign.campaign_id,
                attributes={"outcome": "Won"},
            )
        )
        await session.commit()
        await AnalyticsProjection(session).drain()
        await session.commit()

        report = await SponsorshipReporting(session, admin).generate(
            campaign.campaign_id,
            ReportAudience.BUYER,
            at=MOMENT + timedelta(days=1),
            period_start=MOMENT - timedelta(days=1),
        )
        assert report.outcomes == {"Won": 1, "Lost": 0, "Dormant": 0}
        assert report.unrecorded_outcomes.text == "50 %"
        assert report.unrecorded_outcomes.unrecorded == 1


# -- analytics -------------------------------------------------------------


async def test_a_qualified_opportunity_and_a_harm_signal_are_both_emitted(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213355550001", confirm_criteria=True)
        assert state.need_id is not None
        await confirm_minimum_criteria(session, admin, state.need_id, at=MOMENT)
        from realestate.domain.commercial.opportunities import AdvanceStage
        from realestate.db.models import OpportunityStage

        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=state.opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="edges:qualify",
                at=MOMENT,
            ),
        )
        await HarmSignals(session, admin).record(
            HarmSignalCommand(
                kind=HarmSignalKind.WRONG_INFORMATION,
                evidence="Dato sintético incorrecto en la prueba.",
                occurred_at=MOMENT,
                command_key="edges:harm",
            ),
            at=MOMENT,
        )
        await session.commit()

        report = await AnalyticsEmission(session, admin).emit_operational()
        await session.commit()
        assert report.qualifications == 1
        assert report.harm_signals == 1

        keys = {
            key
            for (key,) in await session.execute(select(AnalyticsOutboxEntry.event_key))
        }
        assert f"qualified:{state.opportunity_id}" in keys


async def test_a_won_outcome_counts_toward_completeness(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213355550002", confirm_criteria=True)
        from realestate.db.models import OpportunityStage as Stage
        from realestate.domain.commercial.opportunities import AdvanceStage as Advance

        await OpportunityManagement(session).record(
            admin,
            Advance(
                opportunity_id=state.opportunity_id,
                to_stage=Stage.QUALIFIED,
                command_key="edges:won-qualify",
                at=MOMENT,
            ),
        )
        await OpportunityManagement(session).record(
            admin,
            RecordWon(
                opportunity_id=state.opportunity_id,
                evidence=WonEvidence.COMPLETED_SALE,
                evidence_detail="Escritura sintética de prueba",
                command_key="edges:won",
                at=MOMENT,
            ),
        )
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=MOMENT - timedelta(days=1),
            period_end=MOMENT + timedelta(days=1),
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.outcome_completeness.text == "100 %"


async def test_two_concurrent_sessions_agree_on_one_generated_salt() -> None:
    """The loser of the race re-reads rather than failing the event.

    A measurement event must not be refused because somebody else created the
    salt a microsecond earlier, so the unique constraint decides and the loser
    adopts the winner's value.
    """
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await provision(session)
        await session.commit()
        organization_id = (await actor_for(session, ADMIN_LOGIN)).organization_id

    async def reference() -> str:
        async with database.session_scope() as session:
            value = await Pseudonyms(session, organization_id).reference(
                Purpose.SESSION, "una-sesion"
            )
            await session.commit()
            return value

    first, second = await asyncio.gather(reference(), reference())
    assert first == second
    await database.dispose()


async def test_an_event_that_needs_a_listing_is_refused_without_one(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(EventRejected, match="publicación"):
            await AnalyticsEvents(session, admin).record(
                AnalyticsEvent(
                    event_key="galeria-sin-publicacion",
                    name=AnalyticsEventName.GALLERY_OPENED,
                    occurred_at=MOMENT,
                )
            )


async def test_a_numeric_attribute_is_accepted_as_it_is(database) -> None:
    """Numbers and booleans pass through; only strings must be enumerated."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        recorded = await AnalyticsEvents(session, admin).record(
            AnalyticsEvent(
                event_key="seleccion-compartida",
                name=AnalyticsEventName.SELECTION_SHARED,
                occurred_at=MOMENT,
                attributes={"count": 4},
            )
        )
        await session.commit()
        assert recorded.created is True
        row = await session.scalar(
            select(AnalyticsOutboxEntry).where(
                AnalyticsOutboxEntry.event_key == "seleccion-compartida"
            )
        )
        assert row is not None
        assert row.payload["attributes"] == {"count": 4}


def test_a_refresh_report_knows_whether_it_changed_anything() -> None:
    idle = RefreshReport(
        definition_version=CURRENT_DEFINITION_VERSION,
        from_sequence=0,
        last_sequence=0,
        projected=0,
        excluded=0,
        late=0,
        rebuilt_periods=0,
        drained=True,
    )
    busy = RefreshReport(
        definition_version=CURRENT_DEFINITION_VERSION,
        from_sequence=0,
        last_sequence=4,
        projected=4,
        excluded=1,
        late=1,
        rebuilt_periods=2,
        drained=True,
    )
    assert idle.changed is False
    assert busy.changed is True


async def test_the_stage_five_bridge_skips_an_event_with_no_listing(
    database,
) -> None:
    """A gallery open with no Listing is not a measurable Stage 8 fact.

    It is still recorded on the Stage 5 surface. Inventing a Listing for it, or
    refusing the Stage 5 event because the bridge could not use it, would both be
    worse than dropping it here.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "puente")
        analytics = PublicAnalytics(session, admin)

        assert await analytics.record(
            PublicEventCommand(
                event_key="puente-sin-publicacion",
                name=PublicAnalyticsEventName.GALLERY_OPEN,
                surface="Gallery",
                occurred_at=MOMENT,
            )
        )
        await session.commit()
        assert (
            await session.scalar(
                select(AnalyticsOutboxEntry).where(
                    AnalyticsOutboxEntry.event_key == "public:puente-sin-publicacion"
                )
            )
        ) is None

        # With a Listing it bridges, and the target schema decides which
        # attributes travel: an appointment request accepts no surface at all.
        assert await analytics.record(
            PublicEventCommand(
                event_key="puente-con-publicacion",
                name=PublicAnalyticsEventName.GALLERY_OPEN,
                surface="Gallery",
                occurred_at=MOMENT,
                listing_id=listing.listing_id,
            )
        )
        assert await analytics.record(
            PublicEventCommand(
                event_key="puente-cita",
                name=PublicAnalyticsEventName.APPOINTMENT_REQUESTED,
                surface="TechnicalSheet",
                occurred_at=MOMENT,
            )
        )
        await session.commit()

        bridged = await session.scalar(
            select(AnalyticsOutboxEntry).where(
                AnalyticsOutboxEntry.event_key == "public:puente-con-publicacion"
            )
        )
        appointment = await session.scalar(
            select(AnalyticsOutboxEntry).where(
                AnalyticsOutboxEntry.event_key == "public:puente-cita"
            )
        )
        assert bridged is not None
        assert bridged.payload["attributes"] == {}
        assert appointment is not None
        assert appointment.payload["attributes"] == {}


async def test_a_withdrawn_listing_is_not_measured_on_the_stage_five_surface(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "medicion-retirada")
        await CatalogAdministration(session).record(
            admin,
            SetPublicationState(
                listing_id=listing.listing_id,
                state=ListingPublicationState.UNPUBLISHED,
                command_key="edges:unpublish",
            ),
        )
        await session.commit()

        with pytest.raises(ValueError, match="retirada"):
            await PublicAnalytics(session, admin).record(
                PublicEventCommand(
                    event_key="medicion-de-una-retirada",
                    name=PublicAnalyticsEventName.GALLERY_OPEN,
                    surface="Gallery",
                    occurred_at=MOMENT,
                    listing_id=listing.listing_id,
                )
            )


def test_a_word_longer_than_the_line_is_split_rather_than_overflowing() -> None:
    """PDF text does not wrap, so an unbroken token would run off the page."""
    lines = wrapped([Line("x" * (CHARACTERS_PER_LINE * 2 + 5))])
    assert [len(line.text) for line in lines] == [
        CHARACTERS_PER_LINE,
        CHARACTERS_PER_LINE,
        5,
    ]


# -- the dashboard tile ----------------------------------------------------


async def test_a_measure_with_a_sample_reports_its_sample_and_its_gap(
    database,
) -> None:
    """The tile carries the denominator, because 25 percent of four is not news.

    Asserted through the module the surface uses rather than the page, so the
    hint and the number cannot drift apart.
    """
    from realestate.api.analytics import _stat
    from realestate.domain.analytics.metrics import Measure

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        del admin
    tile = _stat("Asistencia", Measure.of(Decimal("25"), unit="%", sample=4, unrecorded=1))
    assert "25 %" in tile
    assert "4 casos" in tile
    assert "1 sin registrar" in tile

    plain = _stat("Citas", Measure.of(Decimal("3"), unit="", sample=3))
    assert "3 casos" in plain
    assert "sin registrar" not in plain


async def test_the_dashboard_reports_a_recorded_attendance_ratio(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        state = await opportunity_for(session, "5213355550003")
        from tests.fixtures.commercial import make_conversation

        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        physical = await CatalogAdministration(session).record(
            admin,
            CreateProperty(
                property_key="casa-asistencia",
                name="Casa Asistencia",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "Test"},
                command_key="edges:attendance-property",
            ),
        )
        for index, attendance in enumerate(("Attended", "Missed", None)):
            appointment = Appointment(
                organization_id=admin.organization_id,
                reference=f"VIS-EDGES-{index}",
                idempotency_key=f"edges-visit-{index}",
                conversation_id=conversation.id,
                lead_id=state.lead.id,
                property_uuid=physical.subject_id,
                starts_at=MOMENT - timedelta(days=1),
                ends_at=MOMENT - timedelta(days=1) + timedelta(minutes=90),
                status=AppointmentStatus.CONFIRMED.value,
                created_at=MOMENT - timedelta(days=2),
            )
            if attendance is not None:
                appointment.attendance = attendance
                appointment.attendance_recorded_at = MOMENT
                appointment.attendance_recorded_by = admin.member_id
            session.add(appointment)
        await session.commit()

        card = await OperationMetrics(session, admin).scorecard(
            period_start=MOMENT - timedelta(days=2),
            period_end=MOMENT + timedelta(days=1),
            definition_version=CURRENT_DEFINITION_VERSION,
        )
        assert card.appointment_attendance.text == "33.3 %"
        assert card.appointment_attendance.sample == 3
        assert card.appointment_attendance.unrecorded == 1


async def test_a_reviewed_listing_that_is_not_ready_is_refused_for_paid_placement(
    database,
) -> None:
    """Presentation Readiness is not waived by paying. It is the same check.

    The Listing here is authorized and available but has no approved cover, so
    the unpaid site would not show it either — which is the whole point.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog = CatalogAdministration(session)
        physical = await catalog.record(
            admin,
            CreateProperty(
                property_key="casa-sin-portada",
                name="Casa Sin Portada",
                property_type="House",
                facts={"city": "Zapopan"},
                provenance={"kind": "Test"},
                command_key="edges:bare-property",
            ),
        )
        listing = await catalog.record(
            admin,
            CreateListing(
                listing_key="casa-sin-portada-organization",
                property_uuid=physical.subject_id,
                source_kind="Organization",
                source_name="Larevia",
                attribution="Fuente: Larevia",
                title="Casa Sin Portada",
                public_location="Zapopan, Jalisco",
                provenance={"kind": "Test"},
                command_key="edges:bare-listing",
            ),
        )
        await catalog.record(
            admin,
            ReviewListingFacts(
                listing_id=listing.subject_id,
                review_state=FactsReviewState.APPROVED,
                facts={"public_location": "Zapopan, Jalisco"},
                command_key="edges:bare-review",
            ),
        )
        await catalog.record(
            admin,
            SetListingAuthority(
                listing_id=listing.subject_id,
                authority=ListingAuthority.AUTHORIZED,
                evidence="Autorización sintética de prueba",
                checked_at=MOMENT,
                revalidate_by=None,
                command_key="edges:bare-authority",
            ),
        )
        await catalog.record(
            admin,
            SetListingAvailability(
                listing_id=listing.subject_id,
                availability=ListingAvailability.AVAILABLE,
                command_key="edges:bare-availability",
            ),
        )
        await session.commit()

        decision = await SponsoredEligibility(session, admin).evaluate(
            listing.subject_id, "Search", MOMENT
        )
        assert decision.blocked
        assert any("oferta" in reason for reason in decision.reasons)

        # And an override does not conjure the missing campaign either.
        await catalog.record(
            admin,
            SetReadinessOverride(
                listing_id=listing.subject_id,
                enabled=True,
                command_key="edges:bare-readiness",
            ),
        )
        await session.commit()
        again = await SponsoredEligibility(session, admin).evaluate(
            listing.subject_id, "Search", MOMENT
        )
        assert again.blocked

"""Pricing, quoting, reservation and the refusals that keep them honest.

The commercial half of Stage 8 is mostly refusals, and each one exists because
the permissive alternative is how a paid-placement product quietly stops meaning
what it says:

* no published catalog means no quote, because SAN-062 says the first price
  follows measured pilot traffic and an empty field would be filled with a guess;
* a quote preserves its catalog version, so tomorrow's price change does not
  move the offer somebody is still considering;
* a discount without a written reason is refused, at the module and at the
  database;
* a quote expires after seven days and reserves nothing while it lives;
* capacity is reserved under a lock, so a surface cannot be oversold.

Nothing in this module moves money. ``collection_state`` is somebody's record of
what happened elsewhere.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from realestate.db.engine import Database
from realestate.db.models import (
    CollectionState,
    PriceCatalogStatus,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipCapacityReservation,
    SponsorshipPriceCatalog,
    SponsorshipQuote,
    SponsorshipQuoteStatus,
)
from realestate.domain.commercial.actors import (
    InvalidTransition,
    NotAuthorized,
    NotFound,
)
from realestate.domain.sponsorship.campaigns import (
    CampaignRefused,
    OpenCampaign,
    RecordCollection,
    ScheduleCampaign,
    SponsorshipCampaigns,
)
from realestate.domain.sponsorship.capacity import (
    CapacityUnavailable,
    SponsorshipCapacity,
)
from realestate.domain.sponsorship.labels import INSUFFICIENT_HISTORY
from realestate.domain.sponsorship.pricing import (
    DraftCatalog,
    PackageUnpriced,
    PriceLine,
    PricingUnavailable,
    PublishCatalog,
    SponsorshipPricing,
)
from realestate.domain.sponsorship.quoting import (
    QUOTE_VALID_DAYS,
    AcceptQuote,
    QuoteCommand,
    QuoteExpired,
    QuoteRefused,
    SponsorshipQuoting,
)
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    ADVISOR_LOGIN,
    actor_for,
    provision,
    reset,
)
from tests.fixtures.public_site import publish_listing
from tests.fixtures.sponsorship import (
    CLEARANCE,
    MOMENT,
    PILOT_EVIDENCE,
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


async def draft_campaign(session, admin, suffix: str, *, package: str = "Search"):
    listing = await publish_listing(session, admin, suffix)
    campaigns = SponsorshipCampaigns(session, admin)
    view = await campaigns.open(
        OpenCampaign(
            listing_id=listing.listing_id,
            buyer_kind="Developer",
            buyer_label=f"Desarrollador sintético {suffix}",
            package=package,
        ),
        at=MOMENT,
    )
    await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
    return view, listing


async def test_a_draft_catalog_is_not_quotable_and_publishing_needs_evidence(
    database,
) -> None:
    """The first price requires pilot data, and the refusal says so.

    A product that offered an empty price field on day one would have its first
    price chosen by whoever filled it in.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        pricing = SponsorshipPricing(session, admin)
        catalog = await pricing.draft(
            DraftCatalog(
                version="borrador-1",
                currency="MXN",
                lines=(PriceLine("Search", 30, Decimal("4000")),),
                command_key="catalog:borrador-1",
            ),
            at=MOMENT,
        )
        await session.commit()

        with pytest.raises(PricingUnavailable, match="piloto"):
            await pricing.published()

        with pytest.raises(PricingUnavailable, match="piloto"):
            await pricing.publish(
                PublishCatalog(catalog.catalog_id, "corto"), at=MOMENT
            )

        published = await pricing.publish(
            PublishCatalog(catalog.catalog_id, PILOT_EVIDENCE), at=MOMENT
        )
        await session.commit()
        assert published.status == PriceCatalogStatus.PUBLISHED.value
        assert published.pilot_evidence == PILOT_EVIDENCE


async def test_quoting_without_a_published_catalog_is_refused(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        view, _ = await draft_campaign(session, admin, "sin-precio")
        await session.commit()

        with pytest.raises(PricingUnavailable):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(campaign_id=view.campaign_id, command_key="q:sin-precio"),
                at=MOMENT,
            )


async def test_publishing_a_second_version_retires_the_first(database) -> None:
    """Exactly one published version, so "the current price" is unambiguous."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin, version="precios-1")
        await published_catalog(
            session, admin, version="precios-2", search=Decimal("5500")
        )
        await session.commit()

        pricing = SponsorshipPricing(session, admin)
        current = await pricing.published()
        assert current.version == "precios-2"
        assert current.amount_for("Search", 30) == Decimal("5500")
        retired = [
            item
            for item in await pricing.catalogs()
            if item.status == PriceCatalogStatus.RETIRED.value
        ]
        assert [item.version for item in retired] == ["precios-1"]


async def test_a_quote_preserves_its_catalog_version_when_prices_move(
    database,
) -> None:
    """Tomorrow's price change does not move today's offer.

    The quote stores the version and the amounts, so accepting it charges what
    it said rather than what the catalog now says.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin, version="precios-1")
        view, _ = await draft_campaign(session, admin, "version-fija")
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:version-fija"),
            at=MOMENT,
        )
        await session.commit()
        assert quote.catalog_version == "precios-1"
        assert quote.total_amount == Decimal("4000.00")

        await published_catalog(
            session, admin, version="precios-2", search=Decimal("9000")
        )
        await session.commit()

        stored = await session.get(SponsorshipQuote, quote.quote_id)
        assert stored is not None
        assert stored.catalog_version == "precios-1"
        assert stored.list_amount == Decimal("4000.00")

        accepted = await quoting.accept(
            AcceptQuote(quote.quote_id, MOMENT), at=MOMENT
        )
        await session.commit()
        campaign = await session.get(SponsorshipCampaign, view.campaign_id)
        assert campaign is not None
        assert campaign.price_amount == Decimal("4000.00")
        assert accepted.status == SponsorshipQuoteStatus.RESERVED.value


async def test_a_quote_is_idempotent_on_its_command_key(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "doble-clic")
        quoting = SponsorshipQuoting(session, admin)
        command = QuoteCommand(
            campaign_id=view.campaign_id, command_key="q:doble-clic"
        )
        first = await quoting.quote(command, at=MOMENT)
        second = await quoting.quote(command, at=MOMENT)
        await session.commit()
        assert first.quote_id == second.quote_id
        stored = list(await session.scalars(select(SponsorshipQuote)))
        assert len(stored) == 1


async def test_a_discount_requires_a_written_reason(database) -> None:
    """Refused by the module, and by the database if the module were bypassed."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "descuento")
        quoting = SponsorshipQuoting(session, admin)

        with pytest.raises(QuoteRefused, match="razón"):
            await quoting.quote(
                QuoteCommand(
                    campaign_id=view.campaign_id,
                    command_key="q:descuento-sin-razon",
                    discount_amount=Decimal("500"),
                ),
                at=MOMENT,
            )

        reasoned = await quoting.quote(
            QuoteCommand(
                campaign_id=view.campaign_id,
                command_key="q:descuento-con-razon",
                discount_amount=Decimal("500"),
                discount_reason="Cliente piloto fundador",
            ),
            at=MOMENT,
        )
        await session.commit()
        assert reasoned.discount_amount == Decimal("500.00")
        assert reasoned.total_amount == Decimal("3500.00")
        assert reasoned.discount_reason == "Cliente piloto fundador"


async def test_the_database_refuses_a_reasonless_discount_too(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        catalog_id = await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "constraint")
        await session.commit()

        session.add(
            SponsorshipQuote(
                organization_id=admin.organization_id,
                campaign_id=view.campaign_id,
                catalog_id=catalog_id,
                catalog_version="precios-piloto-1",
                package="Search",
                duration_days=30,
                list_amount=Decimal("4000"),
                discount_amount=Decimal("400"),
                discount_reason=None,
                total_amount=Decimal("3600"),
                currency="MXN",
                status=SponsorshipQuoteStatus.ISSUED.value,
                issued_at=MOMENT,
                expires_at=MOMENT + timedelta(days=QUOTE_VALID_DAYS),
                command_key="bypass:constraint",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_a_discount_may_not_exceed_the_list_price(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "regalado")
        with pytest.raises(QuoteRefused, match="superar"):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(
                    campaign_id=view.campaign_id,
                    command_key="q:regalado",
                    discount_amount=Decimal("99999"),
                    discount_reason="Intento de regalar el servicio",
                ),
                at=MOMENT,
            )


async def test_a_quote_expires_after_seven_days_and_cannot_be_accepted(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "vencida")
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:vencida"),
            at=MOMENT,
        )
        await session.commit()
        assert quote.expires_at == MOMENT + timedelta(days=QUOTE_VALID_DAYS)
        assert quote.expired(MOMENT + timedelta(days=QUOTE_VALID_DAYS)) is True
        assert quote.expired(MOMENT + timedelta(days=6)) is False

        with pytest.raises(QuoteExpired):
            await quoting.accept(
                AcceptQuote(quote.quote_id, MOMENT + timedelta(days=8)),
                at=MOMENT + timedelta(days=8),
            )
        await session.commit()
        stored = await session.get(SponsorshipQuote, quote.quote_id)
        assert stored is not None
        assert stored.status == SponsorshipQuoteStatus.EXPIRED.value


async def test_expiring_due_quotes_is_a_pass_not_a_read_time_computation(
    database,
) -> None:
    """A quote still reading Issued a month later is one somebody will honour."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "caducar")
        quoting = SponsorshipQuoting(session, admin)
        await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:caducar"),
            at=MOMENT,
        )
        await session.commit()

        assert await quoting.expire_due(at=MOMENT + timedelta(days=3)) == 0
        assert await quoting.expire_due(at=MOMENT + timedelta(days=8)) == 1
        assert await quoting.expire_due(at=MOMENT + timedelta(days=9)) == 0
        await session.commit()


async def test_issuing_a_quote_reserves_no_capacity(database) -> None:
    """A stalled negotiation must not make a surface look sold out."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "sin-reserva")
        await SponsorshipQuoting(session, admin).quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:sin-reserva"),
            at=MOMENT,
        )
        await session.commit()

        reservations = list(
            await session.scalars(select(SponsorshipCapacityReservation))
        )
        assert reservations == []
        forecast = await SponsorshipCapacity(session, admin).forecast(
            "Search", MOMENT, MOMENT + timedelta(days=30)
        )
        assert forecast.reserved == 0
        assert forecast.available == forecast.concurrent_campaigns


async def test_capacity_refuses_the_sale_that_would_oversell_the_surface(
    database,
) -> None:
    """The surface fills up and the next acceptance is refused, not queued.

    Two campaigns already share every position at one sponsored result per six;
    a third would dilute delivery below what the first two were sold.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        capacity = SponsorshipCapacity(session, admin)
        await capacity.set_limit("Search", 2, at=MOMENT)
        await session.commit()

        for suffix in ("cupo-1", "cupo-2"):
            await active_campaign(session, admin, suffix)
        await session.commit()

        forecast = await capacity.forecast("Search", MOMENT, MOMENT + timedelta(days=30))
        assert (forecast.reserved, forecast.available) == (2, 0)

        view, _ = await draft_campaign(session, admin, "cupo-3")
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:cupo-3"),
            at=MOMENT,
        )
        await session.commit()

        with pytest.raises(CapacityUnavailable, match="Search"):
            await quoting.accept(AcceptQuote(quote.quote_id, MOMENT), at=MOMENT)
        await session.rollback()


async def test_consecutive_campaigns_do_not_compete_for_capacity(database) -> None:
    """The peak overlap decides, not the total.

    Two consecutive fifteen-day campaigns never share a day, and refusing the
    second would decline a sale the surface can actually deliver.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        capacity = SponsorshipCapacity(session, admin)
        await capacity.set_limit("Search", 1, at=MOMENT)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "primera-quincena", paid_days=10)
        await session.commit()

        later = MOMENT + timedelta(days=20)
        forecast = await capacity.forecast("Search", later, later + timedelta(days=10))
        assert (forecast.reserved, forecast.available) == (0, 1)


async def test_cancelling_a_campaign_releases_its_capacity_and_its_quotes(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        capacity = SponsorshipCapacity(session, admin)
        await capacity.set_limit("Search", 1, at=MOMENT)
        campaign = await active_campaign(session, admin, "cancelada")
        await session.commit()

        filled = await capacity.forecast("Search", MOMENT, MOMENT + timedelta(days=30))
        assert filled.available == 0

        campaigns = SponsorshipCampaigns(session, admin)
        await campaigns.cancel(campaign.campaign_id, "Decisión del comprador", at=MOMENT)
        await session.commit()

        freed = await capacity.forecast("Search", MOMENT, MOMENT + timedelta(days=30))
        assert freed.available == 1
        # Cancelling twice is a no-op rather than an error.
        again = await campaigns.cancel(campaign.campaign_id, "Repetida", at=MOMENT)
        assert again.status == SponsorshipCampaignStatus.CANCELLED.value


async def test_capacity_without_measured_history_says_so(database) -> None:
    """A forecast built on two days of traffic is false precision."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        forecast = await SponsorshipCapacity(session, admin).forecast(
            "Homepage", MOMENT, MOMENT + timedelta(days=30)
        )
        assert forecast.measured_daily_visible is None
        assert forecast.exposure_note == INSUFFICIENT_HISTORY


async def test_delivery_requires_the_written_commercial_clearance(database) -> None:
    """SAN-065 is Pending, so Product refuses to assume it away.

    It cannot enumerate the defects that block accepting money. What it can do
    is require a named Administrator to have written down that they checked.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        listing = await publish_listing(session, admin, "sin-validacion")
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
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:sin-validacion"),
            at=MOMENT,
        )
        await quoting.accept(AcceptQuote(quote.quote_id, MOMENT), at=MOMENT)
        await campaigns.schedule(ScheduleCampaign(view.campaign_id, MOMENT), at=MOMENT)
        await session.commit()

        with pytest.raises(CampaignRefused, match="SAN-065"):
            await campaigns.activate(view.campaign_id, at=MOMENT)

        with pytest.raises(CampaignRefused, match="administrador"):
            await campaigns.record_clearance(view.campaign_id, "corto", at=MOMENT)

        await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
        activated = await campaigns.activate(view.campaign_id, at=MOMENT)
        await session.commit()
        assert activated.status == SponsorshipCampaignStatus.ACTIVE.value


async def test_one_listing_may_not_have_two_live_campaigns(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "una-sola")
        campaigns = SponsorshipCampaigns(session, admin)
        command = OpenCampaign(
            listing_id=listing.listing_id,
            buyer_kind="Owner",
            buyer_label="Propietario sintético",
            package="Search",
        )
        await campaigns.open(command, at=MOMENT)
        await session.commit()
        with pytest.raises(CampaignRefused, match="en curso"):
            await campaigns.open(command, at=MOMENT)


async def test_the_accepted_lifecycle_refuses_out_of_order_transitions(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "orden")
        campaigns = SponsorshipCampaigns(session, admin)

        with pytest.raises(InvalidTransition, match="reservada"):
            await campaigns.schedule(ScheduleCampaign(view.campaign_id, MOMENT), at=MOMENT)
        with pytest.raises(InvalidTransition, match="programada o pausada"):
            await campaigns.activate(view.campaign_id, at=MOMENT)
        with pytest.raises(InvalidTransition, match="activa"):
            await campaigns.pause(view.campaign_id, "Sin activar", at=MOMENT)


async def test_a_start_date_in_the_past_is_refused(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        view, _ = await draft_campaign(session, admin, "pasado")
        quoting = SponsorshipQuoting(session, admin)
        quote = await quoting.quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:pasado"),
            at=MOMENT,
        )
        await quoting.accept(AcceptQuote(quote.quote_id, MOMENT), at=MOMENT)
        await session.commit()
        with pytest.raises(CampaignRefused, match="pasado"):
            await SponsorshipCampaigns(session, admin).schedule(
                ScheduleCampaign(view.campaign_id, MOMENT - timedelta(days=5)),
                at=MOMENT,
            )


async def test_collection_state_is_recorded_and_never_charged(database) -> None:
    """Product records what somebody observed outside it. It moves nothing."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "cobro")
        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.record_collection(
            RecordCollection(
                campaign.campaign_id, CollectionState.COLLECTED, "Transferencia 001"
            ),
            at=MOMENT,
        )
        await session.commit()
        assert view.collection_state == CollectionState.COLLECTED.value
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        assert row.collection_reference == "Transferencia 001"


async def test_an_unpriced_package_and_duration_is_refused(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin, durations=(30,))
        view, _ = await draft_campaign(session, admin, "sin-paquete")
        with pytest.raises(PackageUnpriced, match="90 días"):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(
                    campaign_id=view.campaign_id,
                    command_key="q:sin-paquete",
                    duration_days=90,
                ),
                at=MOMENT,
            )


async def test_an_advisor_may_not_price_quote_or_open_a_campaign(database) -> None:
    async with database.session_scope() as session:
        advisor = await actor_for(session, ADVISOR_LOGIN)
        with pytest.raises(NotAuthorized):
            await SponsorshipPricing(session, advisor).draft(
                DraftCatalog(
                    version="intento",
                    currency="MXN",
                    lines=(PriceLine("Search", 30, Decimal("1")),),
                    command_key="catalog:intento",
                ),
                at=MOMENT,
            )
        with pytest.raises(NotAuthorized):
            await SponsorshipCampaigns(session, advisor).open(
                OpenCampaign(
                    listing_id=advisor.organization_id,
                    buyer_kind="Owner",
                    buyer_label="Intento",
                    package="Search",
                ),
                at=MOMENT,
            )


async def test_a_missing_campaign_quote_or_catalog_is_a_named_refusal(
    database,
) -> None:
    import uuid

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        unknown = uuid.uuid4()
        with pytest.raises(NotFound):
            await SponsorshipCampaigns(session, admin).read(unknown)
        with pytest.raises(NotFound):
            await SponsorshipQuoting(session, admin).accept(
                AcceptQuote(unknown, MOMENT), at=MOMENT
            )
        with pytest.raises(NotFound):
            await SponsorshipPricing(session, admin).by_id(unknown)


async def test_a_draft_of_an_existing_version_returns_the_same_catalog(
    database,
) -> None:
    """A version is the identity a quote preserves, so redrafting it is the same."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        pricing = SponsorshipPricing(session, admin)
        command = DraftCatalog(
            version="idempotente",
            currency="MXN",
            lines=(PriceLine("Search", 30, Decimal("4000")),),
            command_key="catalog:idempotente",
        )
        first = await pricing.draft(command, at=MOMENT)
        second = await pricing.draft(command, at=MOMENT)
        await session.commit()
        assert first.catalog_id == second.catalog_id
        rows = list(await session.scalars(select(SponsorshipPriceCatalog)))
        assert len(rows) == 1


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("version", "  ", "nombre"),
        ("lines", (), "al menos un paquete"),
    ],
)
async def test_an_invalid_draft_is_refused(database, field, value, fragment) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        values: dict[str, object] = {
            "version": "invalida",
            "currency": "MXN",
            "lines": (PriceLine("Search", 30, Decimal("4000")),),
            "command_key": "catalog:invalida",
        }
        values[field] = value
        with pytest.raises(ValueError, match=fragment):
            await SponsorshipPricing(session, admin).draft(
                DraftCatalog(**values),  # type: ignore[arg-type]
                at=MOMENT,
            )


@pytest.mark.parametrize(
    ("suffix", "field", "value"),
    [
        ("comprador", "buyer_kind", "Banco"),
        ("paquete", "package", "Instagram"),
        ("dias", "paid_days", 0),
        ("etiqueta", "buyer_label", " "),
    ],
)
async def test_an_invalid_campaign_is_refused(
    database, suffix, field, value
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, f"invalida-{suffix}")
        values: dict[str, object] = {
            "listing_id": listing.listing_id,
            "buyer_kind": "Owner",
            "buyer_label": "Propietario sintético",
            "package": "Search",
            "paid_days": 30,
        }
        values[field] = value
        with pytest.raises(ValueError):
            await SponsorshipCampaigns(session, admin).open(
                OpenCampaign(**values),  # type: ignore[arg-type]
                at=MOMENT,
            )

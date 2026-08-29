"""Caps, equitable rotation, capacity, pause and revoked eligibility.

Delivery is where a sponsorship product either honours what it sold or quietly
does not. The properties asserted here are the ones a buyer would eventually
notice: that their listing is not shown to the same anonymous session all day,
that two campaigns sharing one slot actually share it, that a Listing which
lost its authority stops being shown for money immediately, and that pausing
returns the paid days rather than consuming them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsEventName,
    ListingAuthority,
    ListingAvailability,
    SponsoredEligibilityRecord,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipDeliveryDay,
)
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    SetListingAuthority,
    SetListingAvailability,
)
from realestate.domain.sponsorship.campaigns import (
    OpenCampaign,
    SponsorshipCampaigns,
)
from realestate.domain.sponsorship.delivery import (
    ALREADY_ORGANIC,
    CAP_REACHED,
    NO_SLOT,
    NOT_ELIGIBLE,
    DeliveryContext,
    SponsoredDelivery,
)
from realestate.domain.sponsorship.eligibility import SponsoredEligibility
from realestate.domain.sponsorship.quoting import (
    QuoteCommand,
    QuoteRefused,
    SponsorshipQuoting,
)
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import ADMIN_LOGIN, actor_for, provision, reset
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


def context(**overrides) -> DeliveryContext:
    base = {
        "surface": "Search",
        "visible_results": 12,
        "session_reference": "a" * 32,
        "at": MOMENT,
    }
    base.update(overrides)
    return DeliveryContext(**base)  # type: ignore[arg-type]


async def measured_serve(session, actor, campaign, *, at, suffix: str) -> None:
    await AnalyticsEvents(session, actor).record(
        AnalyticsEvent(
            event_key=f"served-delivery-day-{suffix}",
            name=AnalyticsEventName.SPONSORED_SERVED_IMPRESSION,
            occurred_at=at,
            listing_id=campaign.listing.listing_id,
            campaign_id=campaign.campaign_id,
            session_value=f"browser-{suffix}",
            attributes={"surface": "Search", "position": 1},
        )
    )


async def test_the_page_gets_one_slot_per_six_visible_results(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "uno")
        await session.commit()

        delivery = SponsoredDelivery(session, admin)
        twelve = await delivery.select(context(visible_results=12))
        five = await delivery.select(context(visible_results=5))

        assert twelve.available_slots == 2
        assert len(twelve.slots) == 1  # only one campaign exists
        # A five-result page sells nothing: rounding up would let a nearly empty
        # page be a majority-sponsored page.
        assert (five.available_slots, five.slots) == (0, ())


async def test_a_slot_is_labelled_and_never_reorders_the_organic_list(
    database,
) -> None:
    """The plan carries only paid positions. Organic order is not its business.

    Structural rather than incidental: the delivery module receives the organic
    ids to avoid duplicating a card and returns nothing that could reorder them.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "etiqueta")
        await session.commit()

        plan = await SponsoredDelivery(session, admin).select(context())
        assert [slot.listing_id for slot in plan.slots] == [
            campaign.listing.listing_id
        ]
        slot = plan.slots[0]
        assert slot.label == "Patrocinada"
        assert slot.accessible_label == "Publicación patrocinada, visibilidad pagada"
        assert slot.position == 1
        assert not hasattr(plan, "listings")


async def test_the_third_visible_impression_in_a_session_is_the_last_that_day(
    database,
) -> None:
    """Three paid Visible Impressions per Listing per session per day.

    Counted durably rather than derived from the event store, because the cap is
    enforced while the page is being built and the projection may not have run.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "tope")
        await session.commit()

        delivery = SponsoredDelivery(session, admin)
        reference = "b" * 32
        for expected in (1, 2, 3):
            plan = await delivery.select(
                context(session_reference=reference)
            )
            assert len(plan.slots) == 1
            running = await delivery.count_visible(
                listing_id=campaign.listing.listing_id,
                session_reference=reference,
                at=MOMENT,
            )
            assert running == expected
        await session.commit()

        capped = await delivery.select(context(session_reference=reference))
        assert capped.slots == ()
        assert [item.reason for item in capped.skipped] == [CAP_REACHED]

        # A different session is unaffected, and so is the next day.
        other = await delivery.select(context(session_reference="c" * 32))
        assert len(other.slots) == 1
        tomorrow = await delivery.select(
            context(session_reference=reference, at=MOMENT + timedelta(days=1))
        )
        assert len(tomorrow.slots) == 1


async def test_a_crawler_or_internal_preview_consumes_no_cap(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "robot")
        await session.commit()

        delivery = SponsoredDelivery(session, admin)
        reference = "d" * 32
        for _ in range(10):
            plan = await delivery.select(
                context(session_reference=reference, countable=False)
            )
            assert len(plan.slots) == 1
        await session.commit()


async def test_rotation_gives_the_slot_to_the_campaign_furthest_behind(
    database,
) -> None:
    """Equitable means by delivery deficit, not by a fixed order or a coin flip.

    A campaign that has had two of thirty days goes before one that has had
    twenty of thirty, and the order is deterministic so it can be asserted.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        ahead = await active_campaign(session, admin, "adelantada")
        behind = await active_campaign(session, admin, "atrasada")
        await session.commit()

        row = await session.get(SponsorshipCampaign, ahead.campaign_id)
        assert row is not None
        row.delivered_days = 20
        await session.commit()

        # One slot only, so the two campaigns genuinely compete for it.
        plan = await SponsoredDelivery(session, admin).select(
            context(visible_results=6)
        )
        assert [slot.campaign_id for slot in plan.slots] == [behind.campaign_id]
        assert [item.reason for item in plan.skipped] == [NO_SLOT]

        # With two slots both are delivered, the deficit deciding the order.
        both = await SponsoredDelivery(session, admin).select(
            context(visible_results=12)
        )
        assert [slot.campaign_id for slot in both.slots] == [
            behind.campaign_id,
            ahead.campaign_id,
        ]


async def test_a_listing_already_visible_organically_is_not_also_sold_a_slot(
    database,
) -> None:
    """A buyer should not pay for a second copy of a card already on the page."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "duplicada")
        await session.commit()

        plan = await SponsoredDelivery(session, admin).select(
            context(organic_listing_ids=(campaign.listing.listing_id,))
        )
        assert plan.slots == ()
        assert [item.reason for item in plan.skipped] == [ALREADY_ORGANIC]


async def test_one_confirmed_property_occupies_at_most_one_sponsored_position(
    database,
) -> None:
    """Two Listings of the same house cannot both hold a paid position.

    Campaign ownership and attribution stay on the paying Listing (ADR-0043),
    so what is refused is the second *position*, not the second campaign — and
    it is refused at the earliest gate, quoting, rather than discovered on the
    day the buyer expected delivery.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        first = await active_campaign(session, admin, "misma-a")
        await session.commit()

        # A second Listing over the same confirmed Property.
        rival = await publish_listing(
            session, admin, "misma-b", property_id=first.listing.property_id
        )
        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.open(
            OpenCampaign(
                listing_id=rival.listing_id,
                buyer_kind="Owner",
                buyer_label="Propietario sintético rival",
                package="Search",
            ),
            at=MOMENT,
        )
        await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
        await session.commit()

        decision = await SponsoredEligibility(session, admin).evaluate(
            rival.listing_id, "Search", MOMENT
        )
        assert decision.blocked
        assert any("propiedad confirmada" in reason for reason in decision.reasons)

        with pytest.raises(QuoteRefused, match="propiedad confirmada"):
            await SponsorshipQuoting(session, admin).quote(
                QuoteCommand(
                    campaign_id=view.campaign_id, command_key="quote:misma-b"
                ),
                at=MOMENT,
            )

        plan = await SponsoredDelivery(session, admin).select(
            context(visible_results=12)
        )
        # The rival never became a delivery candidate at all: it was refused at
        # quoting, so it is not Active and delivery never has to consider it.
        assert plan.sponsored_listing_ids == (first.listing.listing_id,)
        assert plan.skipped == ()


async def test_a_listing_that_lost_its_authority_stops_being_shown_for_money(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "revocada")
        await session.commit()

        assert len(
            (await SponsoredDelivery(session, admin).select(context())).slots
        ) == 1

        await CatalogAdministration(session).record(
            admin,
            SetListingAuthority(
                listing_id=campaign.listing.listing_id,
                authority=ListingAuthority.REVOKED,
                evidence="El propietario retiró la autorización.",
                checked_at=MOMENT,
                revalidate_by=None,
                command_key="delivery:withdraw-authority",
            ),
        )
        await session.commit()

        plan = await SponsoredDelivery(session, admin).select(context())
        assert plan.slots == ()
        assert [item.reason for item in plan.skipped] == [NOT_ELIGIBLE]
        # The refusal is recorded, so a buyer asking why can be answered later.
        recorded = list(
            await session.scalars(
                select(SponsoredEligibilityRecord).where(
                    SponsoredEligibilityRecord.scope == "Exposure"
                )
            )
        )
        assert recorded and recorded[0].eligible is False
        await session.commit()


async def test_the_daily_pass_pauses_an_ineligible_campaign_and_keeps_its_days(
    database,
) -> None:
    """Paused days are not consumed, so the buyer gets the week back.

    A day is consumed by being *delivered*, not by passing on a calendar. That
    is the difference between preserving remaining paid days and apologising.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "pausada", paid_days=5)
        await session.commit()

        campaigns = SponsorshipCampaigns(session, admin)
        await measured_serve(session, admin, campaign, at=MOMENT, suffix="pausada-0")
        first = await campaigns.run_daily(at=MOMENT)
        await session.commit()
        assert [item.counted for item in first] == [True]
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None and row.delivered_days == 1

        await CatalogAdministration(session).record(
            admin,
            SetListingAvailability(
                listing_id=campaign.listing.listing_id,
                availability=ListingAvailability.RESERVED,
                command_key="delivery:reserve-listing",
            ),
        )
        await session.commit()

        second = await campaigns.run_daily(at=MOMENT + timedelta(days=1))
        await session.commit()
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.PAUSED.value
        assert row.delivered_days == 1  # unchanged: the day was not delivered
        assert row.paused_reason
        assert [item.counted for item in second] == [False]

        # Eligible again: delivery resumes and the preserved day is used now.
        await CatalogAdministration(session).record(
            admin,
            SetListingAvailability(
                listing_id=campaign.listing.listing_id,
                availability=ListingAvailability.AVAILABLE,
                command_key="delivery:free-listing",
            ),
        )
        await session.commit()
        await measured_serve(
            session,
            admin,
            campaign,
            at=MOMENT + timedelta(days=2),
            suffix="pausada-2",
        )
        await campaigns.run_daily(at=MOMENT + timedelta(days=2))
        await session.commit()
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.ACTIVE.value
        assert row.delivered_days == 2


async def test_the_daily_pass_is_idempotent_within_one_service_date(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "repetida", paid_days=10)
        await session.commit()

        campaigns = SponsorshipCampaigns(session, admin)
        await measured_serve(session, admin, campaign, at=MOMENT, suffix="repetida")
        await campaigns.run_daily(at=MOMENT)
        await campaigns.run_daily(at=MOMENT + timedelta(hours=3))
        await session.commit()

        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None and row.delivered_days == 1
        days = list(
            await session.scalars(
                select(SponsorshipDeliveryDay).where(
                    SponsorshipDeliveryDay.campaign_id == campaign.campaign_id
                )
            )
        )
        assert len(days) == 1


async def test_a_campaign_completes_when_its_paid_days_are_delivered(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "completa", paid_days=2)
        await session.commit()

        campaigns = SponsorshipCampaigns(session, admin)
        for offset in range(2):
            at = MOMENT + timedelta(days=offset)
            await measured_serve(
                session, admin, campaign, at=at, suffix=f"completa-{offset}"
            )
            await campaigns.run_daily(at=at)
            await session.commit()

        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.COMPLETED.value
        assert row.delivered_days == row.paid_days
        assert row.completed_at is not None

        # Completion does not create a successor: campaigns never auto-renew.
        others = list(
            await session.scalars(
                select(SponsorshipCampaign).where(
                    SponsorshipCampaign.id != campaign.campaign_id
                )
            )
        )
        assert others == []

        # And a completed campaign no longer occupies a slot.
        plan = await SponsoredDelivery(session, admin).select(context())
        assert plan.slots == ()


async def test_an_unknown_surface_is_refused_rather_than_defaulted(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        with pytest.raises(ValueError, match="superficie"):
            await SponsoredDelivery(session, admin).select(
                context(surface="Instagram")
            )
        with pytest.raises(ValueError, match="superficie"):
            await SponsoredEligibility(session, admin).evaluate(
                admin.organization_id, "Instagram", MOMENT
            )


async def test_a_homepage_package_does_not_deliver_on_search(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "portada", package="Homepage")
        await session.commit()

        delivery = SponsoredDelivery(session, admin)
        assert (await delivery.select(context(surface="Search"))).slots == ()
        homepage = await delivery.select(
            context(surface="Homepage", visible_results=8)
        )
        assert homepage.available_slots == 2
        assert len(homepage.slots) == 1


async def test_a_both_package_delivers_on_each_surface(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "ambas", package="Both")
        await session.commit()

        delivery = SponsoredDelivery(session, admin)
        assert len((await delivery.select(context(surface="Search"))).slots) == 1
        assert len(
            (
                await delivery.select(
                    context(surface="Homepage", visible_results=8)
                )
            ).slots
        ) == 1


async def test_a_session_without_a_reference_is_never_capped(database) -> None:
    """An anonymous visitor with no cookie still sees the page.

    Refusing to deliver without a reference would make the cap a way to hide
    every paid placement from anybody who blocks cookies.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "sin-sesion")
        await session.commit()

        delivery = SponsoredDelivery(session, admin)
        for _ in range(5):
            plan = await delivery.select(context(session_reference=""))
            assert len(plan.slots) == 1
        assert (
            await delivery.count_visible(
                listing_id=campaign.listing.listing_id,
                session_reference="",
                at=MOMENT,
            )
        ) == 0

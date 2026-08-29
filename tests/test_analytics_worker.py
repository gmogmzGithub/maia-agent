"""The pass that runs measurement and sponsorship on its own clock.

Three things matter about this worker: it is idempotent, it is paced, and it
never touches anything a customer is waiting for. The interval exists as a cost
control — the loop ticks once a second and a daily rule asked 86,400 times a day
is 86,399 wasted scans — and the tests prove that skipping a tick loses nothing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsOutboxEntry,
    AnalyticsOutboxStatus,
    OutboxMessage,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipQuoteStatus,
)
from realestate.domain.sponsorship.quoting import (
    QuoteCommand,
    SponsorshipQuoting,
)
from realestate.worker.analytics import (
    ANALYTICS_INTERVAL_SECONDS,
    AnalyticsWorker,
)
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    actor_for,
    make_conversation,
    make_inbound,
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


async def test_one_pass_emits_projects_and_accounts_for_the_day(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "trabajador", paid_days=5)
        state = await opportunity_for(session, "5213344440001")
        conversation = await make_conversation(session, state.lead, started_at=MOMENT)
        await make_inbound(session, conversation, sent_at=MOMENT)
        session.add(
            OutboxMessage(
                conversation_id=conversation.id,
                idempotency_key="worker-outbox-1",
                to_wa_id=state.lead.wa_id,
                kind="AgentReply",
                body="Con gusto.",
                status="Sent",
                created_at=MOMENT,
                sent_at=MOMENT + timedelta(minutes=4),
            )
        )
        await session.commit()

    worker = AnalyticsWorker(database)
    report = await worker.run(now=MOMENT)

    assert report.emitted >= 1
    assert report.projected >= 1
    assert report.campaigns_examined == 1
    assert report.days_counted == 1
    assert report.campaigns_paused == 0
    assert report.changed is True

    async with database.session_scope() as session:
        pending = await session.scalar(
            select(func.count(AnalyticsOutboxEntry.id)).where(
                AnalyticsOutboxEntry.status == AnalyticsOutboxStatus.PENDING.value
            )
        )
        stored = await session.scalar(select(func.count(AnalyticsDomainEvent.id)))
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert (pending, row.delivered_days if row else None) == (0, 1)
        assert stored is not None and stored >= 1


async def test_running_the_pass_again_the_same_day_changes_nothing(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "idempotente", paid_days=5)
        await session.commit()

    worker = AnalyticsWorker(database)
    await worker.run(now=MOMENT)
    second = await worker.run(now=MOMENT + timedelta(hours=2))

    assert second.emitted == 0
    assert second.projected == 0
    # Examined again, but the day was already accounted for, so nothing changed.
    assert second.campaigns_examined == 1
    assert second.days_counted == 0
    assert second.changed is False

    async with database.session_scope() as session:
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None and row.delivered_days == 1


async def test_the_worker_paces_itself_and_the_first_tick_always_runs(
    database,
) -> None:
    """``None`` means never run, so a process restarted often still gets a pass.

    Without that, a container recycled every few minutes would never reach the
    daily rules at all.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        await active_campaign(session, admin, "pausado-por-reloj", paid_days=5)
        await session.commit()

    worker = AnalyticsWorker(database)
    assert worker.due_at is None
    assert worker.due(MOMENT) is True

    first = await worker.tick(now=MOMENT)
    assert first.campaigns_examined == 1
    assert worker.due_at == MOMENT + timedelta(seconds=ANALYTICS_INTERVAL_SECONDS)

    # Too soon: the tick returns an empty report without touching the database.
    skipped = await worker.tick(now=MOMENT + timedelta(seconds=10))
    assert skipped.campaigns_examined == 0
    assert skipped.changed is False

    later = await worker.tick(
        now=MOMENT + timedelta(seconds=ANALYTICS_INTERVAL_SECONDS + 1)
    )
    assert later.campaigns_examined == 1


async def test_the_pass_expires_a_stale_quote(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        listing = await publish_listing(session, admin, "cotizacion-vieja")
        from realestate.domain.sponsorship.campaigns import (
            OpenCampaign,
            SponsorshipCampaigns,
        )

        campaigns = SponsorshipCampaigns(session, admin)
        view = await campaigns.open(
            OpenCampaign(
                listing_id=listing.listing_id,
                buyer_kind="Collaborator",
                buyer_label="Colaborador sintético",
                package="Homepage",
            ),
            at=MOMENT,
        )
        await campaigns.record_clearance(view.campaign_id, CLEARANCE, at=MOMENT)
        quote = await SponsorshipQuoting(session, admin).quote(
            QuoteCommand(campaign_id=view.campaign_id, command_key="q:worker"),
            at=MOMENT,
        )
        await session.commit()

    report = await AnalyticsWorker(database).run(now=MOMENT + timedelta(days=9))
    assert report.quotes_expired == 1

    async with database.session_scope() as session:
        from realestate.db.models import SponsorshipQuote

        row = await session.get(SponsorshipQuote, quote.quote_id)
        assert row is not None
        assert row.status == SponsorshipQuoteStatus.EXPIRED.value


async def test_the_pass_pauses_a_campaign_whose_listing_became_ineligible(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "pausa-worker", paid_days=5)
        await session.commit()

        from realestate.db.models import ListingAvailability
        from realestate.domain.catalog.administration import (
            CatalogAdministration,
            SetListingAvailability,
        )

        await CatalogAdministration(session).record(
            admin,
            SetListingAvailability(
                listing_id=campaign.listing.listing_id,
                availability=ListingAvailability.SOLD,
                command_key="worker:sold",
            ),
        )
        await session.commit()

    report = await AnalyticsWorker(database).run(now=MOMENT)
    assert report.campaigns_paused == 1

    async with database.session_scope() as session:
        row = await session.get(SponsorshipCampaign, campaign.campaign_id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.PAUSED.value
        assert row.delivered_days == 0


async def test_an_idle_pass_reports_no_change(database) -> None:
    """Nothing to do is reported as nothing, so the log stays readable."""
    report = await AnalyticsWorker(database).run(now=MOMENT)
    assert report.changed is False
    assert (report.emitted, report.projected, report.campaigns_examined) == (0, 0, 0)

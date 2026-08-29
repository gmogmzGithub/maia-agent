"""Pseudonymisation, the expiring buyer link, and no PII anywhere near it.

A sponsorship buyer does not get a CRM account, so the link they do get has to
carry the protections an account would have provided. And the report behind it
has to be safe to hand to a stranger who now has the URL.

These tests go looking for leaks rather than asserting a happy path: the
Contact's phone number, the Contact id, the conversation text and the Saved
Collection are all put into the database first, and then every buyer-facing
surface is searched for them.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    ReportAudience,
    SponsorshipReportLink,
)
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.analytics.pseudonyms import (
    REFERENCE_LENGTH,
    Pseudonyms,
    Purpose,
)
from realestate.domain.commercial.actors import NotAuthorized, NotFound
from realestate.domain.commercial.needs import CriterionStatement, PropertyNeeds
from realestate.domain.public.saved import (
    SavedAction,
    SavedCommand,
    SavedCollections,
)
from realestate.domain.sponsorship.reporting import SponsorshipReporting
from realestate.domain.sponsorship.sharing import (
    MAX_SHARE_DAYS,
    ShareUnavailable,
    SponsorshipSharing,
    digest_of,
    report_lines,
    report_pdf,
)
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    ADVISOR_LOGIN,
    actor_for,
    make_contact,
    provision,
    reset,
)
from tests.fixtures.sponsorship import MOMENT, active_campaign, published_catalog

pytestmark = requires_postgres

#: The synthetic values that must never appear in a buyer surface.
PHONE = "5213399887766"
CONTACT_NOTE = "Quiere una casa en Zapopan con jardín para su perro"


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


async def test_the_same_session_maps_to_one_stable_unreversible_reference(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        pseudonyms = Pseudonyms(session, admin.organization_id)
        first = await pseudonyms.reference(Purpose.SESSION, PHONE)
        second = await pseudonyms.reference(Purpose.SESSION, PHONE)
        await session.commit()

        assert first == second
        assert len(first) == REFERENCE_LENGTH
        assert PHONE not in first
        # Not a plain digest: without the stored salt the mapping cannot be
        # reproduced by anybody holding the analytics rows.
        assert first != hashlib.sha256(PHONE.encode()).hexdigest()[:REFERENCE_LENGTH]


async def test_session_and_subject_references_of_one_value_differ(database) -> None:
    """Separate salts per purpose, so the two tables cannot be joined.

    One salt would let anybody holding both a session reference and a subject
    reference confirm that an anonymous session belongs to a known Contact.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        pseudonyms = Pseudonyms(session, admin.organization_id)
        as_session = await pseudonyms.reference(Purpose.SESSION, PHONE)
        as_subject = await pseudonyms.reference(Purpose.SUBJECT, PHONE)
        await session.commit()
        assert as_session != as_subject


async def test_an_empty_value_produces_no_reference_rather_than_a_shared_one(
    database,
) -> None:
    """A digest of the empty string would make every unidentified event look
    like one very busy session, which is exactly the kind of quiet fabrication a
    funnel must not contain."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        pseudonyms = Pseudonyms(session, admin.organization_id)
        assert await pseudonyms.reference(Purpose.SESSION, "") == ""
        assert await pseudonyms.reference(Purpose.SESSION, "   ") == ""


async def test_a_recorded_event_stores_the_reference_and_not_the_raw_value(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        contact_id, _ = await make_contact(session, PHONE)
        await AnalyticsEvents(session, admin).record(
            AnalyticsEvent(
                event_key="privacy-event-key",
                name=AnalyticsEventName.MAIA_STARTED,
                occurred_at=MOMENT,
                session_value=PHONE,
                subject_value=str(contact_id),
                attributes={"surface": "Maia"},
            )
        )
        await session.commit()
        await AnalyticsProjection(session).drain()
        await session.commit()

        row = await session.scalar(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.event_key == "privacy-event-key"
            )
        )
        assert row is not None
        serialised = repr(
            (
                row.event_key,
                row.session_reference,
                row.subject_reference,
                row.attributes,
            )
        )
        assert PHONE not in serialised
        assert str(contact_id) not in serialised


async def test_a_buyer_link_is_opaque_stored_hashed_and_expiring(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "enlace")
        minted = await SponsorshipSharing(session, admin).share(
            campaign.campaign_id, at=MOMENT, days=14
        )
        await session.commit()

        assert len(minted.token) >= 40
        assert minted.path == f"/reportes/{minted.token}"
        assert minted.expires_at == MOMENT + timedelta(days=14)

        stored = await session.get(SponsorshipReportLink, minted.link_id)
        assert stored is not None
        # Only the digest is at rest, for the same reason a password is not: an
        # operator reading the table must not be able to open the report.
        assert stored.token_digest == digest_of(minted.token)
        assert minted.token not in stored.token_digest


async def test_an_expired_or_revoked_link_gives_the_same_refusal(database) -> None:
    """Telling a holder that a link was withdrawn discloses a relationship."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "revocado")
        sharing = SponsorshipSharing(session, admin)
        expiring = await sharing.share(campaign.campaign_id, at=MOMENT, days=1)
        revoked = await sharing.share(campaign.campaign_id, at=MOMENT, days=30)
        await session.commit()

        report = await sharing.resolve(expiring.token, at=MOMENT)
        assert report.audience == ReportAudience.BUYER.value
        await session.commit()

        with pytest.raises(ShareUnavailable) as expired:
            await sharing.resolve(expiring.token, at=MOMENT + timedelta(days=2))
        await sharing.revoke(revoked.link_id, at=MOMENT)
        await session.commit()
        with pytest.raises(ShareUnavailable) as withdrawn:
            await sharing.resolve(revoked.token, at=MOMENT)
        with pytest.raises(ShareUnavailable) as unknown:
            await sharing.resolve("no-existe-este-token", at=MOMENT)

        assert expired.value.message == withdrawn.value.message == unknown.value.message


async def test_reading_a_link_records_the_view_without_identifying_the_reader(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "vistas")
        sharing = SponsorshipSharing(session, admin)
        minted = await sharing.share(campaign.campaign_id, at=MOMENT, days=7)
        await session.commit()

        await sharing.resolve(minted.token, at=MOMENT)
        await sharing.resolve(minted.token, at=MOMENT + timedelta(hours=1))
        await session.commit()

        statuses = await sharing.shares(campaign.campaign_id)
        assert statuses[0].views == 2
        assert statuses[0].last_viewed_at == MOMENT + timedelta(hours=1)
        assert statuses[0].live(MOMENT) is True
        # Nothing about who read it: no address, no agent, no identity.
        stored = await session.get(SponsorshipReportLink, minted.link_id)
        assert stored is not None
        assert not hasattr(stored, "viewer_ip")


async def test_revoking_twice_is_a_no_op(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "doble-revocacion")
        sharing = SponsorshipSharing(session, admin)
        minted = await sharing.share(campaign.campaign_id, at=MOMENT, days=7)
        await session.commit()
        first = await sharing.revoke(minted.link_id, at=MOMENT)
        second = await sharing.revoke(
            minted.link_id, at=MOMENT + timedelta(days=1)
        )
        await session.commit()
        assert first.revoked_at == second.revoked_at


@pytest.mark.parametrize("days", [0, -1, MAX_SHARE_DAYS + 1])
async def test_an_unbounded_share_is_refused(database, days) -> None:
    """A link with no practical end is an account with extra steps."""
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, f"vigencia-{abs(days)}")
        with pytest.raises(ValueError, match="vigencia"):
            await SponsorshipSharing(session, admin).share(
                campaign.campaign_id, at=MOMENT, days=days
            )


async def test_an_advisor_may_neither_share_nor_revoke(database) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "asesor")
        minted = await SponsorshipSharing(session, admin).share(
            campaign.campaign_id, at=MOMENT, days=7
        )
        await session.commit()

        advisor = await actor_for(session, ADVISOR_LOGIN)
        sharing = SponsorshipSharing(session, advisor)
        with pytest.raises(NotAuthorized):
            await sharing.share(campaign.campaign_id, at=MOMENT)
        with pytest.raises(NotAuthorized):
            await sharing.revoke(minted.link_id, at=MOMENT)


async def test_sharing_an_unknown_campaign_or_link_is_a_named_refusal(
    database,
) -> None:
    import uuid

    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        sharing = SponsorshipSharing(session, admin)
        with pytest.raises(NotFound):
            await sharing.share(uuid.uuid4(), at=MOMENT)
        with pytest.raises(NotFound):
            await sharing.revoke(uuid.uuid4(), at=MOMENT)


async def test_no_buyer_surface_contains_identity_phone_or_conversation(
    database,
) -> None:
    """The leak hunt. Real values are in the database; none may reach the buyer.

    Checked over the report object, the rendered page lines and the PDF bytes,
    because a field that only leaks in one rendering still leaks.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "fuga")
        contact_id, lead = await make_contact(session, PHONE, profile_name="Sintética")

        # A confirmed criterion in the Contact's own words, and a Saved
        # Collection over the sponsored Listing: two things the buyer report sits
        # right next to and must still not expose.
        need = await PropertyNeeds(session).open(admin, contact_id=contact_id)
        await PropertyNeeds(session).record(
            admin,
            need.id,
            [CriterionStatement.stated("essential_requirements", CONTACT_NOTE)],
            now=MOMENT,
        )
        saved = await SavedCollections(session, admin).record(
            SavedCommand(
                action=SavedAction.ADD,
                command_key="privacy-save-1",
                collection_token=None,
                listing_id=campaign.listing.listing_id,
            ),
            at=MOMENT,
        )
        assert saved.collection_token
        await session.commit()

        await AnalyticsProjection(session).drain()
        await session.commit()

        sharing = SponsorshipSharing(session, admin)
        minted = await sharing.share(campaign.campaign_id, at=MOMENT, days=7)
        await session.commit()
        report = await sharing.resolve(minted.token, at=MOMENT)
        await session.commit()

        lines = report_lines(report)
        rendered = "\n".join(line.text for line in lines)
        pdf = report_pdf(report).decode("latin-1", errors="ignore")
        for haystack in (repr(report), rendered, pdf):
            assert PHONE not in haystack
            assert str(contact_id) not in haystack
            assert str(lead.id) not in haystack
            assert CONTACT_NOTE not in haystack
            assert saved.collection_token not in haystack
            assert "Sintética" not in haystack

        # And the buyer report carries no internal block at all.
        assert report.internal is None


async def test_the_internal_report_is_the_only_place_commercial_terms_appear(
    database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "terminos")
        await session.commit()

        reporting = SponsorshipReporting(session, admin)
        buyer = await reporting.generate(
            campaign.campaign_id, ReportAudience.BUYER, at=MOMENT
        )
        internal = await reporting.generate(
            campaign.campaign_id, ReportAudience.ADMINISTRATOR, at=MOMENT
        )
        assert "precios-piloto-1" not in "\n".join(
            line.text for line in report_lines(buyer)
        )
        assert internal.internal is not None
        assert internal.internal.catalog_version == "precios-piloto-1"

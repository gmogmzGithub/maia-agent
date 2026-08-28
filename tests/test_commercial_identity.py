"""Contact resolution: same trusted identity, same person — and nothing else.

The two failures this suite exists to prevent are opposites, and both are
expensive. Creating a second Contact for somebody Product already knows loses
their history. Merging two Contacts because their numbers look alike joins two
strangers' commercial records, and no later report can untangle it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    ChannelIdentityTrust,
    Contact,
    ContactChannelIdentity,
)
from realestate.domain.commercial.identity import (
    ChannelIdentity,
    CommercialIdentity,
    UntrustedIdentity,
    national_digits,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
    yield database
    await database.dispose()


async def test_a_verified_identity_creates_one_contact_and_audits_it(
    database,
) -> None:
    async with database.session_scope() as session:
        contact_id, lead = await commercial.make_contact(
            session, "5213312345678", profile_name="Ana"
        )
        await session.commit()

    async with database.session_scope() as session:
        contact = await session.get(Contact, contact_id)
        assert contact is not None
        assert contact.display_name == "Ana"
        identity = await session.scalar(
            select(ContactChannelIdentity).where(
                ContactChannelIdentity.contact_id == contact_id
            )
        )
        assert identity is not None
        assert identity.identity == "5213312345678"
        assert identity.trust == ChannelIdentityTrust.VERIFIED.value
        assert identity.lead_id == lead.id
        assert identity.organization_id == contact.organization_id

        audited = await session.scalar(
            select(func.count(AuditEvent.id))
            .where(AuditEvent.action == "CreateContact")
            .where(AuditEvent.subject_id == str(contact_id))
        )
        assert audited == 1


async def test_the_audit_event_does_not_copy_the_channel_identity(database) -> None:
    """The audit trail outlives the retention rules for personal data."""
    async with database.session_scope() as session:
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        await session.commit()

    async with database.session_scope() as session:
        event = await session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "CreateContact")
            .where(AuditEvent.subject_id == str(contact_id))
        )
        assert event is not None
        assert "5213312345678" not in str(event.details)


async def test_the_same_identity_resolves_to_the_same_contact(database) -> None:
    async with database.session_scope() as session:
        contact_id, lead = await commercial.make_contact(session, "5213312345678")
        await session.commit()

    async with database.session_scope() as session:
        again = await CommercialIdentity(session).resolve(
            ChannelIdentity.whatsapp(wa_id="5213312345678", lead_id=lead.id),
            organization_id=lead.organization_id,
        )
        await session.commit()
        assert again.contact_id == contact_id
        assert again.created is False
        total = await session.scalar(select(func.count(Contact.id)))
        assert total == 1


async def test_similar_numbers_stay_separate_people(database) -> None:
    """``52`` and ``521`` prefixes are not demonstrably the same person.

    Folding them together is a plausible guess, which is exactly the kind of
    evidence Product refuses to act on for identity.
    """
    async with database.session_scope() as session:
        with_one, _ = await commercial.make_contact(session, "5213312345678")
        without_one, _ = await commercial.make_contact(session, "523312345678")
        await session.commit()

        assert with_one != without_one
        total = await session.scalar(select(func.count(Contact.id)))
        assert total == 2


async def test_a_look_alike_is_reported_to_a_human_not_merged(database) -> None:
    async with database.session_scope() as session:
        first, _ = await commercial.make_contact(session, "5213312345678")
        second, _ = await commercial.make_contact(session, "523312345678")
        await commercial.provision(session)
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)

        candidates = await CommercialIdentity(session).possible_duplicates(
            actor, first
        )

        assert [row.contact_id for row in candidates] == [second]
        # Reporting it changed nothing.
        assert await session.scalar(select(func.count(Contact.id))) == 2


async def test_an_unrelated_number_is_not_reported_as_a_duplicate(database) -> None:
    async with database.session_scope() as session:
        first, _ = await commercial.make_contact(session, "5213312345678")
        await commercial.make_contact(session, "5213399990000")
        await commercial.provision(session)
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)

        assert await CommercialIdentity(session).possible_duplicates(actor, first) == []


async def test_a_contact_with_no_identity_reports_no_duplicates(database) -> None:
    async with database.session_scope() as session:
        await commercial.provision(session)
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        orphan = Contact(organization_id=actor.organization_id, display_name="Sin canal")
        session.add(orphan)
        await session.flush()

        assert (
            await CommercialIdentity(session).possible_duplicates(actor, orphan.id) == []
        )


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ("5213312345678", "523312345678"),
        ("523312345678", "523312345678"),
        ("+52 1 33 1234 5678", "523312345678"),
        ("13125550000", "13125550000"),
        ("5211234", "5211234"),
    ],
)
def test_the_look_alike_key_only_folds_mexicos_optional_one(
    identity: str, expected: str
) -> None:
    assert national_digits(identity) == expected


async def test_an_empty_identity_is_refused(database) -> None:
    async with database.session_scope() as session:
        lead = await commercial.make_lead(session, "5213312345678")
        with pytest.raises(UntrustedIdentity):
            await CommercialIdentity(session).resolve(
                ChannelIdentity.whatsapp(wa_id="   ", lead_id=lead.id),
                organization_id=lead.organization_id,
            )


async def test_an_unsupported_channel_is_refused(database) -> None:
    async with database.session_scope() as session:
        organization = await commercial.organization_id(session)
        with pytest.raises(UntrustedIdentity, match="Telegram"):
            await CommercialIdentity(session).resolve(
                ChannelIdentity(
                    channel="Telegram",
                    identity="12345",
                    trust=ChannelIdentityTrust.ASSERTED,
                    lead_id=uuid.uuid4(),
                ),
                organization_id=organization,
            )


async def test_a_whatsapp_identity_without_its_channel_record_is_refused(
    database,
) -> None:
    """Stage 1's consent and suppression evidence hangs off that record."""
    async with database.session_scope() as session:
        organization = await commercial.organization_id(session)
        with pytest.raises(UntrustedIdentity, match="consent"):
            await CommercialIdentity(session).resolve(
                ChannelIdentity(
                    channel="WhatsApp",
                    identity="5213312345678",
                    trust=ChannelIdentityTrust.VERIFIED,
                    lead_id=None,
                ),
                organization_id=organization,
            )


async def test_a_profile_name_fills_a_blank_but_never_overwrites_one(
    database,
) -> None:
    async with database.session_scope() as session:
        contact_id, lead = await commercial.make_contact(session, "5213312345678")
        await session.commit()

    async with database.session_scope() as session:
        await CommercialIdentity(session).resolve(
            ChannelIdentity.whatsapp(
                wa_id="5213312345678", lead_id=lead.id, profile_name="Ana"
            ),
            organization_id=lead.organization_id,
        )
        await session.commit()
        contact = await session.get(Contact, contact_id)
        assert contact is not None and contact.display_name == "Ana"

    async with database.session_scope() as session:
        # A human corrected the name; the sender's own profile must not win.
        contact = await session.get(Contact, contact_id)
        assert contact is not None
        contact.display_name = "Ana Gómez"
        await session.commit()

    async with database.session_scope() as session:
        await CommercialIdentity(session).resolve(
            ChannelIdentity.whatsapp(
                wa_id="5213312345678", lead_id=lead.id, profile_name="anita123"
            ),
            organization_id=lead.organization_id,
        )
        await session.commit()
        contact = await session.get(Contact, contact_id)
        assert contact is not None and contact.display_name == "Ana Gómez"


async def test_losing_the_contact_creation_race_reads_the_winner(
    database, monkeypatch
) -> None:
    """Forced, so the unique index is proved to be the arbiter.

    ``asyncio.gather`` below shows the ordinary outcome but cannot guarantee the
    two transactions actually collide. Blinding one caller's lookup is the only
    reliable way to reach the branch.
    """
    async with database.session_scope() as session:
        winner_contact_id, lead = await commercial.make_contact(
            session, "5213312345678"
        )
        await session.commit()
        lead_id, organization = lead.id, lead.organization_id

    async with database.session_scope() as session:
        resolver = CommercialIdentity(session)
        real_existing = resolver._existing
        calls = {"n": 0}

        async def blind_first(channel_identity, organization_id):  # noqa: ANN001, ANN202
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_existing(channel_identity, organization_id)

        monkeypatch.setattr(resolver, "_existing", blind_first)

        resolved = await resolver.resolve(
            ChannelIdentity.whatsapp(
                wa_id="5213312345678", lead_id=lead_id, profile_name="Ana"
            ),
            organization_id=organization,
        )
        await session.commit()

        assert resolved.created is False
        assert resolved.contact_id == winner_contact_id
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert await session.scalar(
            select(func.count(ContactChannelIdentity.id))
        ) == 1
        # The loser still contributed the display hint it was carrying.
        contact = await session.get(Contact, winner_contact_id)
        assert contact is not None and contact.display_name == "Ana"


async def test_two_concurrent_first_messages_produce_one_contact(database) -> None:
    """The unique index arbitrates; the loser reads the winner."""
    async with database.session_scope() as session:
        lead = await commercial.make_lead(session, "5213312345678")
        await session.commit()
        lead_id = lead.id
        organization = lead.organization_id

    async def resolve() -> uuid.UUID:
        async with database.session_scope() as session:
            resolved = await CommercialIdentity(session).resolve(
                ChannelIdentity.whatsapp(wa_id="5213312345678", lead_id=lead_id),
                organization_id=organization,
            )
            await session.commit()
            return resolved.contact_id

    first, second = await asyncio.gather(resolve(), resolve())

    assert first == second
    async with database.session_scope() as session:
        assert await session.scalar(select(func.count(Contact.id))) == 1
        assert (
            await session.scalar(select(func.count(ContactChannelIdentity.id))) == 1
        )

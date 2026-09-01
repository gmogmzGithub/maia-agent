"""Stage 5 public experience contracts at Product's authority boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsOutboxEntry,
    Appointment,
    ChannelHandoffPurpose,
    ListingPublicationState,
    PublicAnalyticsEvent,
    PublicAnalyticsEventName,
    SavedCollection,
    SharedSelection,
    SponsorshipContactAttribution,
    WebsiteConversation as WebsiteConversationRow,
    WebsiteMessage,
)
from realestate.domain.catalog.administration import (
    CatalogAdministration,
    SetPublicationState,
)
from realestate.domain.commercial.actors import NotFound
from realestate.domain.public.analytics import PublicAnalytics, PublicEventCommand
from realestate.domain.public.catalog import PublicCatalog, SearchQuery
from realestate.domain.public.discovery import DiscoveryPublication
from realestate.domain.public.handoff import (
    ChannelHandoff,
    CreateHandoff,
    HandoffExpired,
    HandoffIdentityMismatch,
    HandoffReplay,
    extract_handoff_reference,
)
from realestate.domain.public.listing import PublicListing
from realestate.domain.public.responders import HermesWebsiteResponder
from realestate.domain.public.saved import SavedAction, SavedCommand, SavedCollections
from realestate.domain.public.website_conversation import (
    ConversationMessageView,
    WebsiteCommand,
    WebsiteConversation,
    WebsiteReply,
    WebsiteTurn,
)
from realestate.hermes.sessions import TurnResult
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import (
    ADMIN_LOGIN,
    actor_for,
    make_contact,
    make_conversation,
    product_actor,
    provision,
    reset,
)
from tests.fixtures.sponsorship import active_campaign, published_catalog
from tests.fixtures.public_site import publish_listing

pytestmark = requires_postgres
MOMENT = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)


@pytest.fixture
async def database():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await session.commit()
        await reset(session, members=True)
        await provision(session)
    yield database
    await database.dispose()


async def test_public_search_filters_hidden_prices_and_deduplicates_only_confirmed_identity(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        own = await publish_listing(session, admin, "roble")
        collaborator = await publish_listing(
            session,
            admin,
            "roble-colaborador",
            property_id=own.property_id,
            source_kind="Collaborator",
            source_name="Socio autorizado",
        )
        hidden = await publish_listing(
            session,
            admin,
            "loma",
            zone="Guadalajara",
            price=Decimal("7200000"),
            hidden_price=True,
        )
        await session.commit()

        actor = await product_actor(session)
        result = await PublicCatalog(session, actor).search(
            SearchQuery(operation="Sale", minimum_price=Decimal("6000000")),
            at=MOMENT,
        )
        assert [item.listing_id for item in result.listings] == [hidden.listing_id]
        assert result.listings[0].offers[0].price_amount is None
        assert result.listings[0].offers[0].consultation_copy

        all_listings = await PublicCatalog(session, actor).search(
            SearchQuery(page_size=24), at=MOMENT
        )
        ids = {item.listing_id for item in all_listings.listings}
        assert own.listing_id in ids
        assert collaborator.listing_id not in ids
        assert all_listings.total == 2


async def test_listing_withdrawal_returns_410_and_removes_media_immediately(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        published = await publish_listing(session, admin, "retiro")
        await session.commit()
        public = PublicListing(session, await product_actor(session))

        assert (await public.read(published.slug, at=MOMENT)).status_code == 200
        assert (await public.media(published.media_id, at=MOMENT)).storage_key
        await CatalogAdministration(session).record(
            admin,
            SetPublicationState(
                listing_id=published.listing_id,
                state=ListingPublicationState.UNPUBLISHED,
                command_key="stage5:unpublish:retiro",
            ),
        )
        await session.flush()

        withdrawn = await public.read(published.slug, at=MOMENT)
        assert withdrawn.status_code == 410
        assert withdrawn.listing is None
        with pytest.raises(NotFound):
            await public.media(published.media_id, at=MOMENT)
        with pytest.raises(NotFound):
            await public.read("borrador-que-no-existe", at=MOMENT)


async def test_saved_collection_is_idempotent_shareable_and_retains_withdrawn_items(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        published = await publish_listing(session, admin, "guardada")
        await session.commit()
        saved = SavedCollections(session, await product_actor(session))
        add = SavedCommand(
            action=SavedAction.ADD,
            command_key="saved-add-guardada",
            listing_id=published.listing_id,
        )
        first = await saved.record(add, at=MOMENT)
        assert first.changed is True
        assert first.collection_token is not None

        replay = await saved.record(
            SavedCommand(
                action=SavedAction.ADD,
                command_key=add.command_key,
                collection_token=first.collection_token,
                listing_id=published.listing_id,
            ),
            at=MOMENT,
        )
        assert replay.changed is False
        assert len(replay.items) == 1
        shared = await saved.record(
            SavedCommand(
                action=SavedAction.SHARE,
                command_key="saved-share-guardada",
                collection_token=first.collection_token,
            ),
            at=MOMENT,
        )
        assert shared.shared_token is not None

        await CatalogAdministration(session).record(
            admin,
            SetPublicationState(
                listing_id=published.listing_id,
                state=ListingPublicationState.UNPUBLISHED,
                command_key="stage5:unpublish:guardada",
            ),
        )
        current = await saved.read(first.collection_token, at=MOMENT)
        snapshot = await saved.shared(shared.shared_token, at=MOMENT)
        assert current.items[0].available is False
        assert current.items[0].title == "Casa Guardada"
        assert snapshot.items[0].available is False
        assert snapshot.items[0].title == "Casa Guardada"


async def test_saved_collection_protection_merges_devices_without_fingerprinting(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        first_listing = await publish_listing(session, admin, "dispositivo-uno")
        second_listing = await publish_listing(session, admin, "dispositivo-dos")
        contact_id, _lead = await make_contact(session, "5213311111111")
        module = SavedCollections(session, await product_actor(session))
        device_one = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-device-one",
                listing_id=first_listing.listing_id,
            ),
            at=MOMENT,
        )
        device_two = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-device-two",
                listing_id=second_listing.listing_id,
            ),
            at=MOMENT,
        )
        assert device_one.collection_id and device_two.collection_id
        await module.protect(device_one.collection_id, contact_id, at=MOMENT)
        merged = await module.protect(device_two.collection_id, contact_id, at=MOMENT)

        from_first_cookie = await module.read(device_one.collection_token, at=MOMENT)
        from_second_cookie = await module.read(device_two.collection_token, at=MOMENT)
        assert from_first_cookie.collection_id == merged.id
        assert from_second_cookie.collection_id == merged.id
        assert {item.listing_id for item in from_first_cookie.items} == {
            first_listing.listing_id,
            second_listing.listing_id,
        }


async def test_saved_collection_lifecycle_handles_stale_and_duplicate_state(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "ciclo-guardadas")
        contact_id, _lead = await make_contact(session, "5213344444444")
        module = SavedCollections(session, await product_actor(session))

        assert (await module.read(None, at=MOMENT)).items == ()
        assert (await module.read("sc-inexistente", at=MOMENT)).items == ()
        ignored = await module.record(
            SavedCommand(SavedAction.REMOVE, "saved-remove-without-cookie"), at=MOMENT
        )
        assert ignored.collection_id is None and ignored.changed is False

        first = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-cycle-add-first",
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        duplicate = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-cycle-add-duplicate",
                collection_token=first.collection_token,
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        absent_remove = await module.record(
            SavedCommand(
                SavedAction.REMOVE,
                "saved-cycle-remove-absent",
                collection_token=first.collection_token,
                listing_id=uuid.uuid4(),
            ),
            at=MOMENT,
        )
        removed = await module.record(
            SavedCommand(
                SavedAction.REMOVE,
                "saved-cycle-remove-present",
                collection_token=first.collection_token,
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        emptied = await module.record(
            SavedCommand(
                SavedAction.EMPTY,
                "saved-cycle-empty",
                collection_token=first.collection_token,
            ),
            at=MOMENT,
        )
        assert duplicate.changed is False
        assert absent_remove.changed is False
        assert removed.changed is True and removed.items == ()
        assert emptied.changed is False

        restored = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-cycle-restore",
                collection_token=first.collection_token,
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        shared = await module.record(
            SavedCommand(
                SavedAction.SHARE,
                "saved-cycle-share",
                collection_token=first.collection_token,
            ),
            at=MOMENT,
        )
        shared_replay = await module.record(
            SavedCommand(
                SavedAction.SHARE,
                "saved-cycle-share",
                collection_token=first.collection_token,
            ),
            at=MOMENT,
        )
        assert restored.changed is True
        assert shared.shared_token == shared_replay.shared_token
        selection = await session.scalar(
            select(SharedSelection).where(
                SharedSelection.access_token_hash.is_not(None)
            )
        )
        assert selection is not None
        selection.expires_at = MOMENT
        with pytest.raises(NotFound):
            await module.shared(shared.shared_token or "", at=MOMENT)
        with pytest.raises(NotFound):
            await module.shared("ss-inexistente", at=MOMENT)

        protected = await module.protect(first.collection_id, contact_id, at=MOMENT)
        assert (await module.protect(protected.id, contact_id, at=MOMENT)).id == protected.id
        deleted = await module.record(
            SavedCommand(
                SavedAction.DELETE,
                "saved-cycle-delete",
                collection_token=first.collection_token,
            ),
            at=MOMENT,
        )
        assert deleted.changed is True
        assert (await module.read(first.collection_token, at=MOMENT)).collection_id is None
        with pytest.raises(NotFound):
            await module.protect(first.collection_id, contact_id, at=MOMENT)

        expiring = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-cycle-expiring",
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        row = await session.get(SavedCollection, expiring.collection_id)
        assert row is not None
        row.expires_at = MOMENT
        await session.flush()
        assert (await module.read(expiring.collection_token, at=MOMENT)).collection_id is None

        other = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-cycle-other-device",
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        primary = await module.record(
            SavedCommand(
                SavedAction.ADD,
                "saved-cycle-primary-device",
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        await module.protect(primary.collection_id, contact_id, at=MOMENT)
        merged = await module.protect(other.collection_id, contact_id, at=MOMENT)
        assert len((await module.read(other.collection_token, at=MOMENT)).items) == 1
        assert merged.id == primary.collection_id


async def test_channel_handoff_is_opaque_expiring_single_use_and_identity_bound(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        published = await publish_listing(session, admin, "continuidad")
        contact_id, lead = await make_contact(session, "5213322222222")
        other_contact_id, other_lead = await make_contact(session, "5213333333333")
        whatsapp = await make_conversation(session, lead, started_at=MOMENT)
        other_whatsapp = await make_conversation(session, other_lead, started_at=MOMENT)
        module = ChannelHandoff(session, await product_actor(session))
        created = await module.create(
            CreateHandoff(
                purpose=ChannelHandoffPurpose.APPOINTMENT,
                command_key="handoff-appointment-continuidad",
                listing_id=published.listing_id,
                expected_contact_id=contact_id,
            ),
            at=MOMENT,
        )
        assert created.token.startswith("LAR-")
        assert str(contact_id) not in created.token
        assert extract_handoff_reference(f"Referencia {created.token}.") == created.token
        with pytest.raises(HandoffIdentityMismatch):
            await module.resolve(
                created.token,
                verified_contact_id=other_contact_id,
                whatsapp_conversation_id=other_whatsapp.id,
                at=MOMENT,
            )

        resolved = await module.resolve(
            created.token,
            verified_contact_id=contact_id,
            whatsapp_conversation_id=whatsapp.id,
            at=MOMENT,
        )
        assert resolved.listing_id == published.listing_id
        assert whatsapp.property_uuid == published.property_id
        with pytest.raises(HandoffReplay):
            await module.resolve(
                created.token,
                verified_contact_id=contact_id,
                whatsapp_conversation_id=whatsapp.id,
                at=MOMENT,
            )
        expired = await module.create(
            CreateHandoff(
                purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                command_key="handoff-expired-continuidad",
                listing_id=published.listing_id,
            ),
            at=MOMENT,
        )
        with pytest.raises(HandoffExpired):
            await module.resolve(
                expired.token,
                verified_contact_id=contact_id,
                whatsapp_conversation_id=whatsapp.id,
                at=MOMENT + timedelta(minutes=31),
            )
        assert await session.scalar(select(func.count(Appointment.id))) == 0


async def test_channel_handoff_protects_saved_and_website_context(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "continuidad-completa")
        contact_id, _lead = await make_contact(session, "5213355555555")
        actor = await product_actor(session)
        saved = await SavedCollections(session, actor).record(
            SavedCommand(
                SavedAction.ADD,
                "handoff-protection-saved",
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        website = await WebsiteConversation(
            session, actor, RecordingResponder()
        ).handle(
            WebsiteCommand(
                "Mi correo es persona@example.com",
                "handoff-protection-website",
                listing_ids=(listing.listing_id,),
            ),
            at=MOMENT,
        )
        module = ChannelHandoff(session, actor)
        command = CreateHandoff(
            purpose=ChannelHandoffPurpose.SAVED_COLLECTION_PROTECTION,
            command_key="handoff-protection-complete",
            website_conversation_id=website.conversation_id,
            saved_collection_id=saved.collection_id,
            listing_id=listing.listing_id,
            expected_contact_id=contact_id,
        )
        created = await module.create(command, at=MOMENT)
        replay = await module.create(command, at=MOMENT)
        pending = await session.get(WebsiteConversationRow, website.conversation_id)
        assert replay.replayed is True
        assert pending is not None and pending.status == "HandoffPending"

        resolved = await module.resolve(
            created.token,
            verified_contact_id=contact_id,
            whatsapp_conversation_id=None,
            at=MOMENT,
        )
        verified = await session.get(WebsiteConversationRow, website.conversation_id)
        collection = await session.get(SavedCollection, resolved.saved_collection_id)
        assert verified is not None and verified.status == "Verified"
        assert verified.verified_contact_id == contact_id
        assert collection is not None and collection.protected_contact_id == contact_id


async def test_a_sponsored_handoff_links_verified_outcomes_without_rewriting_origin(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "handoff-attribution")
        contact_id, _lead = await make_contact(session, "5213377777777")
        actor = await product_actor(session)
        module = ChannelHandoff(session, actor)
        created = await module.create(
            CreateHandoff(
                purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                command_key="sponsored-handoff-attribution",
                listing_id=campaign.listing.listing_id,
                sponsorship_campaign_id=campaign.campaign_id,
            ),
            at=MOMENT,
        )
        await module.resolve(
            created.token,
            verified_contact_id=contact_id,
            whatsapp_conversation_id=None,
            at=MOMENT,
        )
        await session.flush()

        attribution = await session.scalar(select(SponsorshipContactAttribution))
        assert attribution is not None
        assert attribution.campaign_id == campaign.campaign_id
        assert attribution.contact_id == contact_id
        event = await session.scalar(
            select(AnalyticsOutboxEntry).where(
                AnalyticsOutboxEntry.event_key
                == f"sponsored-handoff:{created.handoff_id}"
            )
        )
        assert event is not None
        assert event.payload["campaign_id"] == str(campaign.campaign_id)


async def test_channel_handoff_rejects_missing_or_withdrawn_context(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(session, admin, "continuidad-invalida")
        contact_id, _lead = await make_contact(session, "5213366666666")
        actor = await product_actor(session)
        module = ChannelHandoff(session, actor)
        valid = await module.create(
            CreateHandoff(
                purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                command_key="handoff-validation-base",
                listing_id=listing.listing_id,
            ),
            at=MOMENT,
        )
        with pytest.raises(NotFound, match="identidad verificada"):
            await module.resolve(
                valid.token,
                verified_contact_id=uuid.uuid4(),
                whatsapp_conversation_id=None,
                at=MOMENT,
            )
        with pytest.raises(NotFound, match="continuidad no existe"):
            await module.resolve(
                "LAR-000000000000000000000000000000000000000000000000",
                verified_contact_id=contact_id,
                whatsapp_conversation_id=None,
                at=MOMENT,
            )
        with pytest.raises(NotFound, match="conversación verificada"):
            await module.resolve(
                valid.token,
                verified_contact_id=contact_id,
                whatsapp_conversation_id=uuid.uuid4(),
                at=MOMENT,
            )

        with pytest.raises(ValueError, match="necesita contexto"):
            await module.create(
                CreateHandoff(
                    purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                    command_key="handoff-validation-empty",
                ),
                at=MOMENT,
            )
        with pytest.raises(NotFound, match="conversación del sitio"):
            await module.create(
                CreateHandoff(
                    purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                    command_key="handoff-validation-website",
                    website_conversation_id=uuid.uuid4(),
                ),
                at=MOMENT,
            )
        with pytest.raises(NotFound, match="colección"):
            await module.create(
                CreateHandoff(
                    purpose=ChannelHandoffPurpose.SAVED_COLLECTION_PROTECTION,
                    command_key="handoff-validation-saved",
                    saved_collection_id=uuid.uuid4(),
                ),
                at=MOMENT,
            )
        with pytest.raises(NotFound, match="identidad esperada"):
            await module.create(
                CreateHandoff(
                    purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                    command_key="handoff-validation-contact",
                    listing_id=listing.listing_id,
                    expected_contact_id=uuid.uuid4(),
                ),
                at=MOMENT,
            )

        await CatalogAdministration(session).record(
            admin,
            SetPublicationState(
                listing_id=listing.listing_id,
                state=ListingPublicationState.UNPUBLISHED,
                command_key="handoff-validation-unpublish",
            ),
        )
        with pytest.raises(NotFound, match="propiedad"):
            await module.create(
                CreateHandoff(
                    purpose=ChannelHandoffPurpose.CONTINUE_WHATSAPP,
                    command_key="handoff-validation-listing",
                    listing_id=listing.listing_id,
                ),
                at=MOMENT,
            )


class RecordingResponder:
    def __init__(self, reply: str = "Puedo ayudarte a comparar esas opciones.") -> None:
        self.reply = reply
        self.turns: list[WebsiteTurn] = []

    async def respond(self, turn: WebsiteTurn) -> WebsiteReply:
        self.turns.append(turn)
        return WebsiteReply(self.reply, turn.hermes_session_id or "hermes-web-1")


async def test_maia_may_point_to_whatsapp_but_not_ask_for_contact_details(
    database: Database,
) -> None:
    """The site prompt tells Maia to hand off to WhatsApp, so saying so must survive.

    The reply guard used to match the bare word, which discarded exactly the
    answers a Website Conversation exists to produce.
    """
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        published = await publish_listing(session, admin, "maia")
        actor = await product_actor(session)

        handoff_reply = (
            "Con gusto. Para agendar una visita, continúa por el WhatsApp oficial."
        )
        allowed = await WebsiteConversation(
            session, actor, RecordingResponder(handoff_reply)
        ).handle(
            WebsiteCommand(
                "¿Puedo agendar una visita?",
                "website-handoff-invite",
                listing_ids=(published.listing_id,),
            ),
            at=MOMENT,
        )
        assert allowed.reply == handoff_reply
        assert allowed.requires_verified_channel is False

        solicited = await WebsiteConversation(
            session, actor, RecordingResponder("Dame tu teléfono y te contacto.")
        ).handle(
            WebsiteCommand(
                "Quiero más información",
                "website-model-solicits-pii",
                listing_ids=(published.listing_id,),
            ),
            at=MOMENT,
        )
        assert solicited.requires_verified_channel is True
        assert "Dame tu teléfono" not in solicited.reply

        echoed = await WebsiteConversation(
            session, actor, RecordingResponder("Marca al 33 1234 5678 directamente.")
        ).handle(
            WebsiteCommand(
                "¿Tienen teléfono?",
                "website-model-echoes-number",
                listing_ids=(published.listing_id,),
            ),
            at=MOMENT,
        )
        assert echoed.requires_verified_channel is True
        assert "33 1234 5678" not in echoed.reply


async def test_website_conversation_rejects_pii_and_uses_only_eligible_context(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        published = await publish_listing(session, admin, "maia")
        responder = RecordingResponder()
        module = WebsiteConversation(session, await product_actor(session), responder)
        blocked = await module.handle(
            WebsiteCommand(
                "Mi correo es persona@example.com",
                "website-pii-attempt",
                listing_ids=(published.listing_id,),
            ),
            at=MOMENT,
        )
        assert blocked.requires_verified_channel is True
        assert "persona@example.com" not in blocked.reply
        assert responder.turns == []
        assert await session.scalar(select(func.count(WebsiteMessage.id))) == 0

        first = await module.handle(
            WebsiteCommand(
                "Busco una casa con tres recámaras",
                "website-safe-message",
                conversation_token=blocked.conversation_token,
                listing_ids=(published.listing_id, uuid.uuid4()),
            ),
            at=MOMENT,
        )
        replay = await module.handle(
            WebsiteCommand(
                "Este texto distinto no debe reemplazar el original",
                "website-safe-message",
                conversation_token=blocked.conversation_token,
            ),
            at=MOMENT,
        )
        assert first.reply == replay.reply
        assert replay.replayed is True
        assert len(responder.turns) == 1
        assert [item.listing_id for item in responder.turns[0].listings] == [
            published.listing_id
        ]
        assert len(first.messages) == 2

        conversation_id, expired_history = await module.read(
            blocked.conversation_token, at=MOMENT + timedelta(days=91)
        )
        assert conversation_id == first.conversation_id
        assert expired_history == ()
        bodies = list(await session.scalars(select(WebsiteMessage.body)))
        assert bodies == ["", ""]


async def test_hermes_website_responder_seeds_only_authorized_context(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_turn(*args: object, **kwargs: object) -> TurnResult:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return TurnResult("Respuesta autorizada", hermes_session_id="hermes-web-next")

    monkeypatch.setattr(
        "realestate.domain.public.responders.run_turn", fake_run_turn
    )
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        published = await publish_listing(session, admin, "responder")
        actor = await product_actor(session)
        publication = await PublicListing(session, actor).read_by_id(
            published.listing_id, at=MOMENT
        )
        assert publication.listing is not None
        turn = WebsiteTurn(
            conversation_id=uuid.uuid4(),
            organization_id=actor.organization_id,
            hermes_session_id="hermes-web-current",
            message="¿Cuál es el precio?",
            history=(
                ConversationMessageView("Customer", "Hola", MOMENT),
                ConversationMessageView("Maia", "Hola, ¿cómo te ayudo?", MOMENT),
            ),
            listings=(publication.listing,),
        )
        result = await HermesWebsiteResponder(
            database, object(), "sales-profile"
        ).respond(turn)

    kwargs = captured["kwargs"]
    args = captured["args"]
    assert isinstance(kwargs, dict) and isinstance(args, tuple)
    assert result == WebsiteReply("Respuesta autorizada", "hermes-web-next")
    assert args[2].endswith("¿Cuál es el precio?")
    assert '"listing_id"' in args[2]
    assert kwargs["profile"] == "sales-profile"
    assert kwargs["required_property_reference"] == publication.listing.physical_name
    assert kwargs["seed"][1:] == [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, ¿cómo te ayudo?"},
    ]


async def test_discovery_and_analytics_share_public_truth_without_behavioral_profiles(
    database: Database,
) -> None:
    async with database.session_scope() as session:
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(
            session,
            admin,
            "descubrimiento",
            hidden_price=True,
            tier="SuperPremium",
        )
        actor = await product_actor(session)
        projection = await DiscoveryPublication(session, actor).project(
            listing.listing_id, at=MOMENT
        )
        offers = projection.structured_data["offers"] if projection.structured_data else []
        assert projection.canonical_path == f"/propiedades/{listing.slug}"
        assert offers and "price" not in offers[0]

        analytics = PublicAnalytics(session, actor)
        command = PublicEventCommand(
            event_key="analytics-impression-one",
            name=PublicAnalyticsEventName.LISTING_IMPRESSION,
            surface="Search",
            occurred_at=MOMENT,
            listing_id=listing.listing_id,
            properties={"operation": "Sale", "depth": 1},
        )
        assert await analytics.record(command) is True
        assert await analytics.record(command) is False
        event = await session.scalar(select(PublicAnalyticsEvent))
        assert event is not None and event.presentation_tier == "SuperPremium"
        with pytest.raises(ValueError, match="propiedades no permitidas"):
            await analytics.record(
                PublicEventCommand(
                    event_key="analytics-private-payload",
                    name=PublicAnalyticsEventName.MAIA_STARTED,
                    surface="Maia",
                    occurred_at=MOMENT,
                    properties={"email": "persona@example.com"},
                )
            )
        with pytest.raises(ValueError, match="valores no permitidos"):
            await analytics.record(
                PublicEventCommand(
                    event_key="analytics-invalid-value",
                    name=PublicAnalyticsEventName.MAIA_STARTED,
                    surface="Maia",
                    occurred_at=MOMENT,
                    properties={"count": []},
                )
            )
        with pytest.raises(ValueError, match="texto libre"):
            await analytics.record(
                PublicEventCommand(
                    event_key="analytics-free-text",
                    name=PublicAnalyticsEventName.MAIA_STARTED,
                    surface="Maia",
                    occurred_at=MOMENT,
                    properties={"source": "x" * 31},
                )
            )

"""Facebook Messenger enters the same durable customer-message pipeline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import delete, func, select

from realestate.api.webhooks import INSTAGRAM_WEBHOOK_PATH, MESSENGER_WEBHOOK_PATH
from realestate.app import create_app
from realestate.channels.messaging import CustomerChannel
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    ConsentRecord,
    ConsentCategory,
    Conversation,
    DeliveryStatus,
    InboxMessage,
    Lead,
    LeadEngagementCycle,
    OutboundDecision,
    OutboxMessage,
    OutboundInitiation,
    OutboxStatus,
    OrganizationChannelBinding,
    SuppressionRecord,
    ChannelBindingKind,
)
from realestate.domain.platform.routing import OrganizationRouting
from realestate.domain.outbound import (
    APPROVED_TEMPLATES,
    ApprovedTemplate,
    DenialReason,
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
    Queued,
)
from realestate.domain.properties import ArtifactStore
from realestate.channels.whatsapp.client import SendOutcome, SendResult
from realestate.domain.availability import WeeklySchedule
from realestate.worker.whatsapp import WhatsAppWorker
from tests.conftest import DATABASE_URL, env, requires_postgres
from tests.fixtures import commercial, instagram, messenger, webhooks

pytestmark = requires_postgres


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.CREDENTIALS_JSON
    )
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)
        await session.execute(
            delete(OrganizationChannelBinding).where(
                OrganizationChannelBinding.kind.in_(
                    (
                        ChannelBindingKind.FACEBOOK_PAGE.value,
                        ChannelBindingKind.INSTAGRAM_ACCOUNT.value,
                    )
                )
            )
        )
        await session.execute(delete(AuditEvent))
        await session.execute(delete(DeliveryStatus))
        await session.execute(delete(OutboundDecision))
        await session.execute(delete(SuppressionRecord))
        await session.execute(delete(ConsentRecord))
        await session.execute(delete(OutboxMessage))
        await session.execute(delete(InboxMessage))
        await session.execute(delete(Conversation))
        await session.execute(delete(LeadEngagementCycle))
        await session.execute(delete(Lead))
        organization_id = await commercial.organization_id(session)
        await OrganizationRouting(session).bind(
            organization_id=organization_id,
            kind=ChannelBindingKind.FACEBOOK_PAGE,
            external_id=messenger.PAGE_ID,
            recorded_by="TestHarness",
        )
        await OrganizationRouting(session).bind(
            organization_id=organization_id,
            kind=ChannelBindingKind.INSTAGRAM_ACCOUNT,
            external_id=instagram.ACCOUNT_ID,
            recorded_by="TestHarness",
        )
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app
    async with database.session_scope() as session:
        await commercial.reset(session)
        await session.execute(
            delete(OrganizationChannelBinding).where(
                OrganizationChannelBinding.kind.in_(
                    (
                        ChannelBindingKind.FACEBOOK_PAGE.value,
                        ChannelBindingKind.INSTAGRAM_ACCOUNT.value,
                    )
                )
            )
        )
        await session.commit()
    await database.dispose()
    get_settings.cache_clear()


async def test_a_signed_page_message_is_persisted_before_acknowledgement(wired) -> None:
    client, app = wired
    body = messenger.text_message(message_id="mid.facebook.1", body="Hola, informes")

    response = await webhooks.post_signed(
        client, MESSENGER_WEBHOOK_PATH, body, env("META_APP_SECRET")
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    async with app.state.database.session_scope() as session:
        inbox = (await session.execute(select(InboxMessage))).scalar_one()
        conversation = (await session.execute(select(Conversation))).scalar_one()
        lead = (await session.execute(select(Lead))).scalar_one()

    assert inbox.channel == CustomerChannel.FACEBOOK_MESSENGER.value
    assert inbox.provider_message_id == "mid.facebook.1"
    assert inbox.sender_id == messenger.SENDER_PSID
    assert conversation.channel == CustomerChannel.FACEBOOK_MESSENGER.value
    assert conversation.channel_account_id == messenger.PAGE_ID
    assert lead.channel == CustomerChannel.FACEBOOK_MESSENGER.value
    assert lead.channel_account_id == messenger.PAGE_ID
    assert lead.provider_user_id == messenger.SENDER_PSID


async def test_a_messenger_conversation_is_visible_as_messenger_in_the_crm(wired) -> None:
    client, app = wired
    body = messenger.text_message(message_id="mid.facebook.crm", body="Hola desde FB")
    response = await webhooks.post_signed(
        client, MESSENGER_WEBHOOK_PATH, body, env("META_APP_SECRET")
    )
    assert response.status_code == 200
    async with app.state.database.session_scope() as session:
        conversation_id = await session.scalar(select(Conversation.id))
    assert conversation_id is not None

    page = await client.get(
        f"/crm/bandeja/{conversation_id}",
        auth=BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
    )

    assert page.status_code == 200
    assert "Facebook Messenger" in page.text
    assert messenger.SENDER_PSID in page.text


async def test_a_signed_instagram_message_enters_the_same_pipeline(wired) -> None:
    client, app = wired
    body = instagram.text_message(message_id="mid.instagram.api", body="¿Precio?")

    response = await webhooks.post_signed(
        client, INSTAGRAM_WEBHOOK_PATH, body, env("META_APP_SECRET")
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    async with app.state.database.session_scope() as session:
        inbox = await session.scalar(
            select(InboxMessage).where(
                InboxMessage.provider_message_id == "mid.instagram.api"
            )
        )
        assert inbox is not None
        conversation = await session.get(Conversation, inbox.conversation_id)
        lead = await session.get(Lead, conversation.lead_id) if conversation else None

    assert inbox.channel == CustomerChannel.INSTAGRAM.value
    assert inbox.sender_id == instagram.SENDER_IGSID
    assert conversation is not None
    assert conversation.channel_account_id == instagram.ACCOUNT_ID
    assert lead is not None
    assert lead.channel == CustomerChannel.INSTAGRAM.value
    assert lead.provider_user_id == instagram.SENDER_IGSID


@pytest.mark.parametrize("path", [MESSENGER_WEBHOOK_PATH, INSTAGRAM_WEBHOOK_PATH])
async def test_meta_customer_channels_share_the_verified_handshake(wired, path) -> None:
    client, _app = wired

    response = await client.get(
        path,
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "meta-customer-channel-ready",
            "hub.verify_token": env("META_VERIFY_TOKEN"),
        },
    )

    assert response.status_code == 200
    assert response.text == "meta-customer-channel-ready"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            MESSENGER_WEBHOOK_PATH,
            messenger.text_message(message_id="mid.facebook.forged", body="Hola"),
        ),
        (
            INSTAGRAM_WEBHOOK_PATH,
            instagram.text_message(message_id="mid.instagram.forged", body="Hola"),
        ),
    ],
)
async def test_a_forged_customer_channel_webhook_persists_nothing(
    wired, path, body
) -> None:
    client, app = wired

    response = await webhooks.post_signed(client, path, body, "forged-app-secret")

    assert response.status_code == 403
    assert response.json() == {"result": "invalid_signature"}
    async with app.state.database.session_scope() as session:
        assert await session.scalar(select(func.count(InboxMessage.id))) == 0


@pytest.mark.parametrize(
    ("path", "body", "setting"),
    [
        (
            MESSENGER_WEBHOOK_PATH,
            messenger.text_message(
                message_id="mid.facebook.dedicated-secret", body="Hola"
            ),
            "meta_messenger_app_secret",
        ),
        (
            INSTAGRAM_WEBHOOK_PATH,
            instagram.text_message(
                message_id="mid.instagram.dedicated-secret", body="Hola"
            ),
            "meta_instagram_app_secret",
        ),
    ],
)
async def test_each_customer_channel_can_verify_with_its_own_app_secret(
    wired, path, body, setting, monkeypatch
) -> None:
    client, _app = wired
    dedicated_secret = "dedicated-customer-channel-secret"
    settings = SimpleNamespace(
        meta_app_secret="shared-secret-that-must-not-be-used",
        meta_messenger_app_secret="",
        meta_instagram_app_secret="",
    )
    setattr(settings, setting, dedicated_secret)
    monkeypatch.setattr("realestate.api.webhooks.get_settings", lambda: settings)

    response = await webhooks.post_signed(client, path, body, dedicated_secret)

    assert response.status_code == 200
    assert response.json()["accepted"] == 1


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            MESSENGER_WEBHOOK_PATH,
            messenger.text_message(
                message_id="mid.facebook.unbound",
                body="Hola",
                page_id="page-not-bound",
            ),
        ),
        (
            INSTAGRAM_WEBHOOK_PATH,
            instagram.text_message(
                message_id="mid.instagram.unbound",
                body="Hola",
                account_id="instagram-not-bound",
            ),
        ),
    ],
)
async def test_an_unbound_customer_channel_account_is_refused_without_guessing(
    wired, path, body
) -> None:
    client, app = wired

    response = await webhooks.post_signed(
        client, path, body, env("META_APP_SECRET")
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 0
    assert response.json()["unroutable"] == 1
    async with app.state.database.session_scope() as session:
        assert await session.scalar(select(func.count(InboxMessage.id))) == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            MESSENGER_WEBHOOK_PATH,
            messenger.text_message(message_id="mid.facebook.duplicate", body="Hola"),
        ),
        (
            INSTAGRAM_WEBHOOK_PATH,
            instagram.text_message(message_id="mid.instagram.duplicate", body="Hola"),
        ),
    ],
)
async def test_a_duplicate_customer_channel_webhook_creates_no_second_record(
    wired, path, body
) -> None:
    client, app = wired

    first = await webhooks.post_signed(client, path, body, env("META_APP_SECRET"))
    second = await webhooks.post_signed(client, path, body, env("META_APP_SECRET"))

    assert first.json()["accepted"] == 1
    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1
    async with app.state.database.session_scope() as session:
        assert await session.scalar(select(func.count(InboxMessage.id))) == 1
        assert await session.scalar(select(func.count(Lead.id))) == 1
        assert await session.scalar(select(func.count(Conversation.id))) == 1


async def test_identical_provider_ids_on_different_channels_never_merge(wired) -> None:
    client, app = wired
    shared_sender = "scoped-user-1"
    shared_message = "scoped-message-1"
    messenger_response = await webhooks.post_signed(
        client,
        MESSENGER_WEBHOOK_PATH,
        messenger.text_message(
            message_id=shared_message,
            body="Messenger",
            sender_id=shared_sender,
        ),
        env("META_APP_SECRET"),
    )
    instagram_response = await webhooks.post_signed(
        client,
        INSTAGRAM_WEBHOOK_PATH,
        instagram.text_message(
            message_id=shared_message,
            body="Instagram",
            sender_id=shared_sender,
        ),
        env("META_APP_SECRET"),
    )

    assert messenger_response.json()["accepted"] == 1
    assert instagram_response.json()["accepted"] == 1
    async with app.state.database.session_scope() as session:
        assert await session.scalar(select(func.count(InboxMessage.id))) == 2
        assert await session.scalar(select(func.count(Lead.id))) == 2


async def test_whatsapp_templates_cannot_escape_through_instagram(
    wired, monkeypatch
) -> None:
    client, app = wired
    monkeypatch.setitem(
        APPROVED_TEMPLATES,
        "whatsapp-only",
        ApprovedTemplate(ConsentCategory.SERVICE, "es_MX"),
    )
    await webhooks.post_signed(
        client,
        INSTAGRAM_WEBHOOK_PATH,
        instagram.text_message(message_id="mid.instagram.template", body="Hola"),
        env("META_APP_SECRET"),
    )

    async with app.state.database.session_scope() as session:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.channel == CustomerChannel.INSTAGRAM.value
            )
        )
        assert conversation is not None
        inbox = await session.scalar(
            select(InboxMessage).where(
                InboxMessage.conversation_id == conversation.id
            )
        )
        assert inbox is not None
        outcome = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body="Seguimiento",
                purpose=Purpose.AGENT_REPLY,
                initiation=OutboundInitiation.REACTIVE,
                idempotency_key="instagram-template-refusal",
                trigger_inbox_ids=(inbox.id,),
                template_id="whatsapp-only",
                template_category=ConsentCategory.SERVICE,
            )
        )

    assert isinstance(outcome, Denied)
    assert outcome.reason is DenialReason.CHANNEL_POLICY_UNSUPPORTED


@pytest.mark.parametrize(
    ("path", "body", "message_id", "channel", "recipient_id", "key"),
    [
        (
            MESSENGER_WEBHOOK_PATH,
            messenger.text_message(message_id="mid.facebook.reply", body="Hola"),
            "mid.facebook.reply",
            CustomerChannel.FACEBOOK_MESSENGER,
            messenger.SENDER_PSID,
            "messenger-reply-1",
        ),
        (
            INSTAGRAM_WEBHOOK_PATH,
            instagram.text_message(message_id="mid.instagram.reply", body="Hola"),
            "mid.instagram.reply",
            CustomerChannel.INSTAGRAM,
            instagram.SENDER_IGSID,
            "instagram-reply-1",
        ),
    ],
)
async def test_an_inbound_can_be_replied_through_its_originating_account(
    wired, path, body, message_id, channel, recipient_id, key
) -> None:
    client, app = wired
    response = await webhooks.post_signed(
        client, path, body, env("META_APP_SECRET")
    )
    assert response.status_code == 200

    async with app.state.database.session_scope() as session:
        inbox = await session.scalar(
            select(InboxMessage).where(
                InboxMessage.provider_message_id == message_id
            )
        )
        assert inbox is not None
        conversation = await session.get(Conversation, inbox.conversation_id)
        assert conversation is not None
        queued = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body="Claro, ¿qué propiedad te interesa?",
                purpose=Purpose.AGENT_REPLY,
                initiation=OutboundInitiation.REACTIVE,
                idempotency_key=key,
                trigger_inbox_ids=(inbox.id,),
            )
        )
        assert isinstance(queued, Queued)
        await session.commit()

    delivered: list[tuple[CustomerChannel, str, str]] = []

    class MessagingClient:
        async def send_text(self, recipient_id: str, text: str) -> SendResult:
            delivered.append((channel, recipient_id, text))
            return SendResult(SendOutcome.SENT, provider_message_id="mid.sent.reply")

    class MessagingDirectory:
        async def for_organization(  # noqa: ANN001, ANN202
            self, session, organization_id, channel, account_id
        ):
            del session, organization_id
            assert channel is channel_under_test
            assert account_id == expected_account_id
            return MessagingClient()

    class WhatsAppMustNotSend:
        async def send_text(self, *_args):  # noqa: ANN002, ANN202
            raise AssertionError("Meta messaging must not use the WhatsApp client")

    channel_under_test = channel
    expected_account_id = (
        messenger.PAGE_ID
        if channel is CustomerChannel.FACEBOOK_MESSENGER
        else instagram.ACCOUNT_ID
    )

    worker = WhatsAppWorker(
        app.state.database,
        object(),  # type: ignore[arg-type]
        WhatsAppMustNotSend(),  # type: ignore[arg-type]
        messaging=MessagingDirectory(),  # type: ignore[arg-type]
        sales_profile="sales",
        schedule=WeeklySchedule.parse(
            "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;"
            "thu=09:00-17:00;fri=09:00-17:00;sat=nada;sun=nada",
            "America/Mexico_City",
        ),
    )
    await worker._drain_outbox()

    assert delivered == [
        (
            channel,
            recipient_id,
            "Claro, ¿qué propiedad te interesa?",
        )
    ]
    async with app.state.database.session_scope() as session:
        row = await session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.idempotency_key == key
            )
        )
        assert row is not None
        assert row.channel == channel.value
        assert row.status == OutboxStatus.SENT.value

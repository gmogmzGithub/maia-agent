"""The public process boundary exposes no Product credential or database."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport

from realestate.app import create_app
from realestate.config import Settings
from realestate.db.engine import Database
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures.commercial import ADMIN_LOGIN, actor_for, provision, reset
from tests.fixtures.media import InMemoryMediaStorage
from tests.fixtures.public_site import publish_listing

pytestmark = requires_postgres


def settings() -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL=DATABASE_URL,
        SITE_PRODUCT_API_TOKEN="site-contract-token",
        WORKER_ENABLED=False,
    )


@pytest.fixture
async def wired():
    database = Database(DATABASE_URL)
    storage = InMemoryMediaStorage()
    async with database.session_scope() as session:
        await reset(session)
        await reset_property_inventory(session)
        await session.commit()
        await reset(session, members=True)
        await provision(session)
        admin = await actor_for(session, ADMIN_LOGIN)
        listing = await publish_listing(
            session,
            admin,
            "boundary",
            price=Decimal("8100000"),
            storage=storage,
        )
        await session.commit()
    app = create_app(settings())
    app.state.database = database
    app.state.media_storage = storage
    app.state.hermes = object()
    yield app, listing
    proxy = getattr(app.state, "public_site_proxy", None)
    if proxy is not None:
        await proxy.aclose()
    await database.dispose()


async def test_internal_contract_requires_dedicated_loopback_credential(wired) -> None:
    app, listing = wired
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        refused = await client.get("/internal/public-site/catalog")
        catalog = await client.get(
            "/internal/public-site/catalog",
            headers={"Authorization": "Bearer site-contract-token"},
        )
        media = await client.get(
            f"/internal/public-site/media/{listing.media_id}",
            headers={"Authorization": "Bearer site-contract-token"},
        )

    assert refused.status_code == 401
    assert catalog.status_code == 200
    assert catalog.json()["listings"][0]["listing_id"] == str(listing.listing_id)
    assert media.status_code == 200
    assert media.content.startswith(b"\xff\xd8\xff")
    assert media.headers["etag"]


async def test_internal_contract_exercises_every_product_owned_operation(wired) -> None:
    app, listing = wired
    authorization = {"Authorization": "Bearer site-contract-token"}
    unknown = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        invalid_price = await client.get(
            "/internal/public-site/catalog?minimum_price=not-a-price",
            headers=authorization,
        )
        invalid_operation = await client.get(
            "/internal/public-site/catalog?operation=Unknown",
            headers=authorization,
        )
        detail = await client.get(
            f"/internal/public-site/listings/{listing.slug}", headers=authorization
        )
        missing_detail = await client.get(
            "/internal/public-site/listings/does-not-exist", headers=authorization
        )
        missing_media = await client.get(
            f"/internal/public-site/media/{unknown}", headers=authorization
        )
        empty = await client.get("/internal/public-site/saved", headers=authorization)
        invalid_save = await client.post(
            "/internal/public-site/saved",
            headers=authorization,
            json={"action": "Add", "command_key": "boundary-invalid-save"},
        )
        added = await client.post(
            "/internal/public-site/saved",
            headers=authorization,
            json={
                "action": "Add",
                "command_key": "boundary-add-listing",
                "listing_id": str(listing.listing_id),
            },
        )
        collection_token = added.json()["collection_token"]
        saved_headers = {
            **authorization,
            "X-Collection-Token": collection_token,
        }
        current = await client.get(
            "/internal/public-site/saved", headers=saved_headers
        )
        shared = await client.post(
            "/internal/public-site/saved",
            headers=saved_headers,
            json={"action": "Share", "command_key": "boundary-share-listing"},
        )
        shared_token = shared.json()["shared_token"]
        selection = await client.get(
            f"/internal/public-site/shared/{shared_token}", headers=authorization
        )
        missing_selection = await client.get(
            "/internal/public-site/shared/ss-does-not-exist", headers=authorization
        )
        pii = await client.post(
            "/internal/public-site/conversation",
            headers=authorization,
            json={
                "message": "Mi correo es persona@example.com",
                "command_key": "boundary-pii-message",
                "listing_ids": [str(listing.listing_id)],
            },
        )
        conversation_token = pii.json()["conversation_token"]
        conversation = await client.get(
            "/internal/public-site/conversation",
            headers={**authorization, "X-Conversation-Token": conversation_token},
        )
        invalid_handoff = await client.post(
            "/internal/public-site/handoffs",
            headers=authorization,
            json={
                "purpose": "ContinueWhatsApp",
                "command_key": "boundary-empty-handoff",
            },
        )
        handoff_body = {
            "purpose": "Appointment",
            "command_key": "boundary-listing-handoff",
            "listing_id": str(listing.listing_id),
        }
        handoff = await client.post(
            "/internal/public-site/handoffs", headers=authorization, json=handoff_body
        )
        replayed_handoff = await client.post(
            "/internal/public-site/handoffs", headers=authorization, json=handoff_body
        )
        event_body = {
            "event_key": "boundary-listing-impression",
            "name": "ListingImpression",
            "surface": "Search",
            "listing_id": str(listing.listing_id),
            "properties": {"operation": "Sale"},
            "occurred_at": "2026-08-28T20:00:00Z",
        }
        event = await client.post(
            "/internal/public-site/events", headers=authorization, json=event_body
        )
        replayed_event = await client.post(
            "/internal/public-site/events", headers=authorization, json=event_body
        )
        invalid_event = await client.post(
            "/internal/public-site/events",
            headers=authorization,
            json={
                **event_body,
                "event_key": "boundary-invalid-surface",
                "surface": "Private",
            },
        )
        discovery = await client.get(
            f"/internal/public-site/discovery/{listing.listing_id}",
            headers=authorization,
        )
        missing_discovery = await client.get(
            f"/internal/public-site/discovery/{unknown}", headers=authorization
        )

    assert invalid_price.status_code == 422
    assert invalid_operation.status_code == 422
    assert detail.status_code == 200 and detail.json()["listing"]["slug"] == listing.slug
    assert missing_detail.status_code == 404
    assert missing_media.status_code == 404
    assert empty.json()["items"] == []
    assert invalid_save.status_code == 409
    assert current.json()["items"][0]["listing_id"] == str(listing.listing_id)
    assert selection.status_code == 200 and len(selection.json()["items"]) == 1
    assert missing_selection.status_code == 410
    assert pii.status_code == 200 and pii.json()["requires_verified_channel"] is True
    assert conversation.status_code == 200 and conversation.json()["messages"] == []
    assert invalid_handoff.status_code == 409
    assert handoff.status_code == 200 and handoff.json()["token"].startswith("LAR-")
    assert replayed_handoff.json()["replayed"] is True
    assert event.status_code == 202 and event.json()["recorded"] is True
    assert replayed_event.status_code == 202 and replayed_event.json()["recorded"] is False
    assert invalid_event.status_code == 422
    assert discovery.status_code == 200
    assert missing_discovery.status_code == 404


async def test_host_proxy_forwards_only_public_headers_and_never_product_auth(wired) -> None:
    app, _listing = wired
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            text="sitio separado",
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Set-Cookie": "larevia_saved=sc-test; Secure; HttpOnly",
                "X-Upstream-Private": "must-not-leak",
            },
        )

    app.state.public_site_proxy = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://site.test"
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        result = await client.get(
            "/propiedades?zone=Zapopan",
            headers={
                "Authorization": "Bearer browser-must-not-cross",
                "Cookie": "larevia_saved=sc-browser",
                "X-Private": "must-not-cross",
            },
        )

    assert result.status_code == 200 and result.text == "sitio separado"
    assert result.headers["set-cookie"].startswith("larevia_saved=")
    assert "x-upstream-private" not in result.headers
    assert len(captured) == 1
    assert captured[0].url.path == "/propiedades"
    assert captured[0].url.params["zone"] == "Zapopan"
    assert "authorization" not in captured[0].headers
    assert "x-private" not in captured[0].headers
    assert captured[0].headers["cookie"] == "larevia_saved=sc-browser"


async def test_public_proxy_fails_honestly_when_site_process_is_unavailable(wired) -> None:
    app, _listing = wired

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("site unavailable", request=request)

    app.state.public_site_proxy = httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable), base_url="http://site.test"
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        result = await client.get("/")

    assert result.status_code == 503
    assert "no está disponible" in result.text

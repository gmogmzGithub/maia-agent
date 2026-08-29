"""Fixture-certified Stage 6 search through the Product plugin boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select, text

from realestate.api.plugin import SESSION_HEADER
from realestate.app import create_app
from realestate.channels.whatsapp.payload import parse_webhook
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import AgentRole, AgentSession, Conversation
from realestate.domain.external_inventory.inventory import ExternalInventory
from realestate.domain.inbox import InboxService
from tests.conftest import DATABASE_URL, env, requires_postgres, reset_property_inventory
from tests.fixtures import commercial, webhooks
from tests.fixtures.external_inventory import FakeInventorySource

pytestmark = requires_postgres
SALES_SESSION = "sess-stage-six-search"


@pytest.fixture
async def wired_external_search():
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    source = FakeInventorySource()
    async with database.session_scope() as session:
        for table_name in (
            "listing_revalidations",
            "external_offer_candidates",
            "external_listing_candidates",
            "inventory_source_health",
        ):
            await session.execute(text(f"DELETE FROM {table_name}"))
        await session.execute(delete(AgentSession))
        await commercial.reset(session)
        await reset_property_inventory(session)
        await commercial.reset(session, members=True)
        await commercial.provision(session)
        message = parse_webhook(
            webhooks.text_message(wamid="w-stage-six-search", body="Busco en Zapopan")
        ).messages[0]
        await InboxService(session).accept(message)

    async with database.session_scope() as session:
        conversation = (await session.execute(select(Conversation))).scalar_one()
        session.add(
            AgentSession(
                organization_id=conversation.organization_id,
                hermes_session_id=SALES_SESSION,
                role=AgentRole.SALES.value,
                cycle_id=conversation.cycle_id,
            )
        )
        actor = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        inventory = ExternalInventory(session, actor, source)
        now = datetime.now(tz=UTC)
        await inventory.synchronize(at=now)
        candidate = (await inventory.list_for_administration())[0]
        await inventory.confirm_evidence(
            candidate.listing_id,
            authority_evidence="Fixture certificado; no es acceso de proveedor",
            attribution="Inmobiliaria Demo · Agente Demo",
            collaboration_authorized=True,
            commission={"kind": "percentage", "value": "50"},
            availability="Available",
            at=now,
        )

    app = create_app(get_settings())
    app.state.database = database
    app.state.easybroker = source
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client
    await database.dispose()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {env('PLUGIN_API_TOKEN')}",
        SESSION_HEADER: SALES_SESSION,
    }


async def test_search_and_revalidation_use_product_with_no_real_provider_access(
    wired_external_search: httpx.AsyncClient,
) -> None:
    search = await wired_external_search.post(
        "/internal/plugin/tools/search_inventory",
        headers=_headers(),
        json={"municipality": "Zapopan", "operation": "Sale"},
    )

    assert search.status_code == 200
    body = search.json()
    assert body["result"] == "found"
    assert body["matches"] == [
        {
            "reference": "EB-FAKE-001",
            "source_kind": "Collaborator",
            "source_name": "EasyBroker",
            "title": "Casa demo en jardín",
            "municipality": "Zapopan",
            "public_location": "Colonia Demo, Zapopan, Jalisco",
            "match_quality": "Exact",
            "attribution": "Inmobiliaria Demo · Agente Demo",
            "offers": [
                {
                    "operation": "Sale",
                    "price_amount": "5750000.00",
                    "price_currency": "MXN",
                    "availability": "Available",
                }
            ],
            "requires_use_time_revalidation": True,
        }
    ]

    revalidated = await wired_external_search.post(
        "/internal/plugin/tools/revalidate_external_listing",
        headers=_headers(),
        json={"reference": "EB-FAKE-001", "intended_action": "Recommend"},
    )

    assert revalidated.status_code == 200
    assert revalidated.json()["result"] == "eligible"

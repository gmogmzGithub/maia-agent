"""`get_property_information` over the plugin boundary (TOOL-CONTRACTS.md, TC-008).

The point of these tests is the authority boundary: Role comes from the session
binding the *product* wrote, so no model argument can widen it, and the tool
refuses every infrastructure-shaped argument.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select

from realestate.api.plugin import SESSION_HEADER, TASK_HEADER
from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import AgentRole, AgentSession, AuditEvent, Property, PropertyStatus
from realestate.domain.properties import ArtifactStore, PropertyService
from tests.conftest import DATABASE_URL, env, requires_postgres, reset_property_inventory

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = requires_postgres

SALES_SESSION = "sess-sales-0001"
ADMIN_SESSION = "sess-admin-0001"
TOOL_PATH = "/internal/plugin/tools/get_property_information"


@pytest.fixture
async def wired(tmp_path: Path):
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset_property_inventory(session)
        await session.execute(delete(AuditEvent))
        await session.execute(delete(AgentSession))
        session.add_all(
            [
                AgentSession(hermes_session_id=SALES_SESSION, role=AgentRole.SALES.value),
                AgentSession(
                    hermes_session_id=ADMIN_SESSION,
                    role=AgentRole.ADMINISTRATIVE.value,
                ),
            ]
        )
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")

    async with database.session_scope() as session:
        await PropertyService(session, app.state.artifacts).accept_upload(
            "casa-roble.md", V1, actor_id="developer"
        )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app
    await database.dispose()


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {env('PLUGIN_API_TOKEN')}"}


async def call(client, reference: str, session_id: str = SALES_SESSION, **extra):
    body = {"reference": reference, **extra}
    return await client.post(
        TOOL_PATH, headers={**auth(), SESSION_HEADER: session_id}, json=body
    )


async def set_inactive(app) -> None:
    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.status = PropertyStatus.INACTIVE.value
        prop.inactive_reason = "Unspecified"
        await session.commit()


# --- Credential and trusted context -----------------------------------------


async def test_the_plugin_credential_is_required(wired) -> None:
    client, _ = wired

    response = await client.post(TOOL_PATH, json={"reference": "casa-roble"})

    assert response.status_code == 401


async def test_an_unbound_session_is_forbidden(wired) -> None:
    client, _ = wired

    response = await call(client, "casa-roble", session_id="sess-not-bound")

    assert response.json() == {"result": "forbidden"}


async def test_a_missing_session_header_is_forbidden(wired) -> None:
    client, _ = wired

    response = await client.post(
        TOOL_PATH, headers=auth(), json={"reference": "casa-roble"}
    )

    assert response.json() == {"result": "forbidden"}


async def test_role_comes_from_the_binding_not_from_the_arguments(wired) -> None:
    client, app = wired
    await set_inactive(app)

    # The Sales session tries to claim the Administrative Role in its arguments.
    response = await call(client, "casa-roble", role="Administrative")

    # Rejected outright: the schema forbids unknown fields, so the attempt
    # cannot even reach the resolver.
    assert response.status_code == 422


async def test_the_sales_role_cannot_read_an_inactive_document(wired) -> None:
    client, app = wired
    await set_inactive(app)

    body = (await call(client, "casa-roble")).json()

    assert body["result"] == "unavailable"
    assert "document_markdown" not in body


async def test_the_administrative_role_can(wired) -> None:
    client, app = wired
    await set_inactive(app)

    body = (await call(client, "casa-roble", session_id=ADMIN_SESSION)).json()

    assert body["result"] == "found"
    assert "Alberca" in body["document_markdown"]


# --- Contract shape ---------------------------------------------------------


async def test_the_found_result_matches_the_contract(wired) -> None:
    client, _ = wired

    body = (await call(client, "casa-roble")).json()

    assert body["result"] == "found"
    assert body["property_id"] == "casa-roble"
    assert body["name"] == "Casa Roble"
    assert body["status"] == "Active"
    assert body["document_version"] == 1
    assert body["document_markdown"].startswith("# Casa Roble")
    assert "Publicación autorizada: `casa-roble-legacy`" in body["document_markdown"]
    assert '"price": "3000000.00"' in body["document_markdown"]
    # The full approved narrative remains, while commercial fields are
    # projected from Offer rather than copied from legacy front matter.
    assert "Alberca" in body["document_markdown"]


async def test_the_name_resolves_as_well_as_the_key(wired) -> None:
    client, _ = wired

    assert (await call(client, "Casa Roble")).json()["result"] == "found"


async def test_an_unknown_reference_is_not_found(wired) -> None:
    client, _ = wired

    assert (await call(client, "casa-fantasma")).json()["result"] == "not_found"


@pytest.mark.parametrize(
    "extra",
    [
        {"lead_id": "521555"},
        {"limit": 1},
        {"offset": 0},
        {"chunk": 2},
        {"sql": "select 1"},
        {"path": "/etc/passwd"},
        {"strategy": "semantic"},
    ],
)
async def test_infrastructure_arguments_are_refused(wired, extra: dict) -> None:
    client, _ = wired

    response = await call(client, "casa-roble", **extra)

    assert response.status_code == 422, extra


async def test_an_empty_reference_is_refused(wired) -> None:
    client, _ = wired

    assert (await call(client, "")).status_code == 422


# --- A replacement is visible on the next call ------------------------------


async def test_a_replacement_is_visible_without_restarting_anything(wired) -> None:
    client, app = wired
    before = (await call(client, "casa-roble")).json()

    v2 = (FIXTURES / "casa-roble-v2.md").read_bytes()
    async with app.state.database.session_scope() as session:
        await PropertyService(session, app.state.artifacts).accept_upload(
            "casa-roble.md", v2, actor_id="developer"
        )

    after = (await call(client, "casa-roble")).json()

    assert before["document_version"] == 1
    assert after["document_version"] == 2
    assert '"price": "3000000.00"' in after["document_markdown"]
    assert "Casa sintética renovada" in after["document_markdown"]
    # Nothing about the tool schema, the session, or the system prompt changed.


# --- Health reports the current tool surface --------------------------------


async def test_health_reports_the_resolved_role(wired) -> None:
    client, _ = wired

    body = (
        await client.get(
            "/internal/plugin/health",
            headers={**auth(), SESSION_HEADER: SALES_SESSION, TASK_HEADER: "task-1"},
        )
    ).json()

    assert body["trusted_context"] == {
        "session_id": SALES_SESSION,
        "task_id": "task-1",
        "role": "Sales",
    }
    import realestate_hermes_plugin as plugin

    assert body["product_tools"] == list(plugin.REGISTERED_TOOLS)

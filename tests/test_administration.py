"""Administrative Property Status and inventory (P-065, P-066, P-017).

The authority boundary is what matters here: a Sales session must never be able
to mutate status, deactivation must never cancel anything, and repeating the
current status must not fabricate a transition.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete, select

from realestate.api.plugin import ORIGIN_HEADER, SESSION_HEADER
from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AgentRole,
    AgentSession,
    AuditEvent,
    Property,
    PropertyStatus,
)
from realestate.domain.administration import AdministrationService, Administrator
from realestate.domain.properties import ArtifactStore, PropertyService
from tests.conftest import DATABASE_URL, env, requires_postgres, reset_property_inventory

FIXTURES = Path(__file__).parent / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()

pytestmark = requires_postgres

ADMIN_SESSION = "sess-admin-cp4"
SALES_SESSION = "sess-sales-cp4"
STATUS_PATH = "/internal/plugin/tools/set_property_status"
LIST_PATH = "/internal/plugin/tools/list_properties"
INFO_PATH = "/internal/plugin/tools/get_property_information"


def second_property() -> bytes:
    return (
        V1.decode("utf-8")
        .replace("property_id: casa-roble", "property_id: casa-encino")
        .replace("name: Casa Roble", "name: Casa Encino")
        .replace("# Casa Roble", "# Casa Encino")
        .encode("utf-8")
    )


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
                AgentSession(
                    hermes_session_id=ADMIN_SESSION,
                    role=AgentRole.ADMINISTRATIVE.value,
                    channel_key="telegram:12345",
                ),
                AgentSession(
                    hermes_session_id=SALES_SESSION, role=AgentRole.SALES.value
                ),
            ]
        )
        await session.commit()

    app = create_app(get_settings())
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")

    async with database.session_scope() as session:
        service = PropertyService(session, app.state.artifacts)
        await service.accept_upload("casa-roble.md", V1, actor_id="developer")
        await service.accept_upload(
            "casa-encino.md", second_property(), actor_id="developer"
        )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app
    await database.dispose()


def headers(session_id: str = ADMIN_SESSION, origin: str | None = None) -> dict[str, str]:
    result = {
        "Authorization": f"Bearer {env('PLUGIN_API_TOKEN')}",
        SESSION_HEADER: session_id,
    }
    if origin:
        result[ORIGIN_HEADER] = origin
    return result


async def set_status(client, reference, status, session_id=ADMIN_SESSION, **extra):
    if status == "Inactive" and "inactive_reason" not in extra:
        extra["inactive_reason"] = "Unspecified"
    return await client.post(
        STATUS_PATH,
        headers=headers(session_id),
        json={"reference": reference, "status": status, **extra},
    )


# --- Authority ---------------------------------------------------------------


async def test_a_sales_session_cannot_change_status(wired) -> None:
    client, app = wired

    body = (await set_status(client, "casa-roble", "Inactive", SALES_SESSION)).json()

    assert body == {"result": "forbidden"}
    async with app.state.database.session_scope() as session:
        prop = (
            await session.execute(
                select(Property).where(Property.property_key == "casa-roble")
            )
        ).scalar_one()
    assert prop.status == PropertyStatus.ACTIVE.value


async def test_a_sales_session_cannot_list_the_inventory(wired) -> None:
    client, _ = wired

    response = await client.post(LIST_PATH, headers=headers(SALES_SESSION), json={})

    assert response.json() == {"result": "forbidden"}


async def test_an_unbound_session_cannot_change_status(wired) -> None:
    client, _ = wired

    body = (await set_status(client, "casa-roble", "Inactive", "sess-unknown")).json()

    assert body == {"result": "forbidden"}


async def test_the_plugin_credential_is_still_required(wired) -> None:
    client, _ = wired

    response = await client.post(
        STATUS_PATH,
        headers={SESSION_HEADER: ADMIN_SESSION},
        json={
            "reference": "casa-roble",
            "status": "Inactive",
            "inactive_reason": "Sold",
        },
    )

    assert response.status_code == 401


# --- Argument surface ---------------------------------------------------------


@pytest.mark.parametrize("status", ["inactive", "INACTIVE", "Paused", "Sold", ""])
async def test_only_the_two_accepted_states_are_allowed(wired, status) -> None:
    client, _ = wired

    response = await set_status(client, "casa-roble", status)

    assert response.status_code == 422, status


@pytest.mark.parametrize(
    "extra",
    [{"actor_id": "someone"}, {"lead_id": "521"}, {"reason": "sold"}, {"sql": "update"}],
)
async def test_extra_arguments_are_refused(wired, extra) -> None:
    client, _ = wired

    response = await set_status(client, "casa-roble", "Inactive", **extra)

    assert response.status_code == 422, extra


async def test_the_inventory_tool_refuses_arguments(wired) -> None:
    client, _ = wired

    response = await client.post(
        LIST_PATH, headers=headers(), json={"status": "Active"}
    )

    assert response.status_code == 422


# --- Behaviour ----------------------------------------------------------------


async def test_a_real_transition_is_persisted_and_reported(wired) -> None:
    client, app = wired

    body = (await set_status(client, "casa-roble", "Inactive")).json()

    assert body["result"] == "updated"
    assert body["previous_status"] == "Active"
    assert body["current_status"] == "Inactive"
    assert body["current_inactive_reason"] == "Unspecified"
    assert body["property_id"] == "casa-roble"
    assert body["name"] == "Casa Roble"

    async with app.state.database.session_scope() as session:
        prop = (
            await session.execute(
                select(Property).where(Property.property_key == "casa-roble")
            )
        ).scalar_one()
    assert prop.status == PropertyStatus.INACTIVE.value
    assert prop.inactive_reason == "Unspecified"


async def test_repeating_the_current_status_is_unchanged_not_updated(wired) -> None:
    client, _ = wired
    await set_status(client, "casa-roble", "Inactive")

    body = (await set_status(client, "casa-roble", "Inactive")).json()

    assert body["result"] == "unchanged"
    assert body["previous_status"] == body["current_status"] == "Inactive"


async def test_an_unknown_property_is_not_found(wired) -> None:
    client, _ = wired

    assert (await set_status(client, "casa-fantasma", "Inactive")).json() == {
        "result": "not_found"
    }


async def test_the_name_resolves_as_well_as_the_key(wired) -> None:
    client, _ = wired

    assert (await set_status(client, "Casa Roble", "Inactive")).json()["result"] == "updated"


async def test_deactivation_reports_appointments_without_cancelling(wired) -> None:
    # P-017: deactivating starts administrative review, never a cancellation.
    client, _ = wired

    body = (await set_status(client, "casa-roble", "Inactive")).json()

    assert "affected_confirmed_appointments" in body
    assert body["affected_confirmed_appointments"] == 0


# --- Audit --------------------------------------------------------------------


async def test_a_transition_is_audited_with_the_trusted_actor(wired) -> None:
    client, app = wired

    await set_status(client, "casa-roble", "Inactive", inactive_reason="Sold")

    async with app.state.database.session_scope() as session:
        event = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "PropertyStatusChanged")
            )
        ).scalars().one()

    # The actor is the Telegram channel from the binding, not a model argument.
    assert event.actor_id == "telegram:12345"
    assert event.actor_type == "Administrative"
    assert event.subject_id == "casa-roble"
    assert event.details["previous_status"] == "Active"
    assert event.details["requested_status"] == "Inactive"
    assert event.details["requested_inactive_reason"] == "Sold"


async def test_the_originating_message_is_recorded(wired) -> None:
    client, app = wired

    await client.post(
        STATUS_PATH,
        headers=headers(origin="admin-message-abc"),
        json={
            "reference": "casa-roble",
            "status": "Inactive",
            "inactive_reason": "Reserved",
        },
    )

    async with app.state.database.session_scope() as session:
        event = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "PropertyStatusChanged")
            )
        ).scalars().one()

    assert event.details["origin_message_id"] == "admin-message-abc"


# --- The enforcement that makes it matter --------------------------------------


async def test_after_deactivation_the_sales_role_gets_no_document(wired) -> None:
    client, _ = wired
    await set_status(client, "casa-roble", "Inactive")

    body = (
        await client.post(
            INFO_PATH, headers=headers(SALES_SESSION), json={"reference": "casa-roble"}
        )
    ).json()

    assert body["result"] == "unavailable"
    assert body["customer_message"] == "La propiedad no está disponible por el momento."
    assert "document_markdown" not in body
    # No promotional fact leaks through any field.
    assert "Alberca" not in str(body)
    assert "3,000,000" not in str(body)


async def test_reactivation_restores_sales_disclosure(wired) -> None:
    client, _ = wired
    await set_status(client, "casa-roble", "Inactive")
    await set_status(client, "casa-roble", "Active")

    body = (
        await client.post(
            INFO_PATH, headers=headers(SALES_SESSION), json={"reference": "casa-roble"}
        )
    ).json()

    assert body["result"] == "found"


async def test_the_administrative_role_still_sees_an_inactive_property(wired) -> None:
    client, _ = wired
    await set_status(client, "casa-roble", "Inactive")

    body = (
        await client.post(
            INFO_PATH, headers=headers(), json={"reference": "casa-roble"}
        )
    ).json()

    assert body["result"] == "found"
    assert body["status"] == "Inactive"


# --- Inventory -----------------------------------------------------------------


async def test_the_inventory_is_compact_and_complete(wired) -> None:
    client, _ = wired

    body = (await client.post(LIST_PATH, headers=headers(), json={})).json()

    assert body["result"] == "found"
    keys = {p["property_id"] for p in body["properties"]}
    assert keys == {"casa-roble", "casa-encino"}
    for entry in body["properties"]:
        assert set(entry) == {
            "property_id",
            "name",
            "status",
            "document_version",
            "confirmed_appointments",
            "inactive_reason",
            "property_type",
            "operation",
            "price_amount",
            "price_currency",
            "updated_at",
        }
        # No document prose in the overview (P-066).
        assert "Alberca" not in str(entry)


async def test_the_inventory_reflects_a_status_change(wired) -> None:
    client, _ = wired
    await set_status(client, "casa-encino", "Inactive")

    body = (await client.post(LIST_PATH, headers=headers(), json={})).json()
    statuses = {p["property_id"]: p["status"] for p in body["properties"]}

    assert statuses == {"casa-roble": "Active", "casa-encino": "Inactive"}


# --- The service directly -------------------------------------------------------


async def test_an_invalid_status_is_refused_at_the_service_too(wired) -> None:
    # The schema blocks this, but the Backend must not depend on that alone.
    _, app = wired

    async with app.state.database.session_scope() as session:
        result = await AdministrationService(session).set_property_status(
            "casa-roble", "Vendida", Administrator(actor_id="t:1")
        )

    assert result["result"] == "ambiguous"


async def test_a_missing_reason_is_answered_not_rejected(wired) -> None:
    """An argument mistake is a result the Agent can act on, not a transport error.

    Deactivation needs a reason. Answering ``ambiguous`` with the accepted values
    lets the Administrative Role ask which one; a rejected request would reach
    the plugin as ``temporarily_unavailable`` and be reported as an outage.
    """
    client, _ = wired

    body = (
        await client.post(
            STATUS_PATH,
            headers=headers(),
            json={"reference": "casa-roble", "status": "Inactive"},
        )
    ).json()

    assert body["result"] == "ambiguous"
    assert "inactive_reason" in body["detail"]


async def test_a_reason_supplied_for_activation_is_answered_too(wired) -> None:
    client, _ = wired

    body = (
        await client.post(
            STATUS_PATH,
            headers=headers(),
            json={
                "reference": "casa-roble",
                "status": "Active",
                "inactive_reason": "Sold",
            },
        )
    ).json()

    assert body["result"] == "ambiguous"
    assert "omitted" in body["detail"]

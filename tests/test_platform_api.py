"""The platform surface: its credential, its refusals, and its Spanish panel.

Two authorities are exercised here and the point of the file is that they do not
overlap. The `/platform` routes take a platform credential *and* an operator
name, and refuse an Organization member's login; `/crm/plataforma` takes an
Organization Administrator and is about their own Organization by construction.

Every mutation is also checked for the thing that makes the audit trail usable:
a written reason. A route that accepted "arreglo" would produce rows nobody can
act on three months later, which is worse than rows with an empty field.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select, text

from realestate.app import create_app
from realestate.config import Settings, get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    LAREVIA_SLUG,
    Organization,
    OrganizationStatus,
    Property,
)
from realestate.domain.platform.credentials import SecretResolver
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = [pytest.mark.anyio, requires_postgres]

TOKEN = "platform-token-for-tests"
OPERATOR = "gerardo"
SLUG = "api-plataforma-test"
ADMIN = "dir@apiplat.test"
ADVISOR = "ana@apiplat.test"
REASON = "Alta acompañada para la suite de la superficie de plataforma."
PHONE = "555777888999000"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "X-Platform-Operator": OPERATOR,
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def wired(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Product with a platform credential configured and a clean slate.

    The credentials go through the environment rather than the ``Settings``
    argument because ``require_developer`` reads the cached process settings —
    the Basic accounts are a local secret, not application state.
    """
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("PLATFORM_OPERATOR_TOKEN", TOKEN)
    monkeypatch.setenv("ORGANIZATION_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON",
        commercial.credentials_json(**{OPERATOR: "support-password"}),
    )
    get_settings.cache_clear()

    database = Database(DATABASE_URL)
    app = create_app(get_settings())
    app.state.database = database
    # The suites drive the resolver rather than the process environment, so one
    # test's credential cannot leak into another's (ADR-0052).
    app.state.secret_resolver = SecretResolver({"APIPLAT_META_TOKEN": "token-api"})
    async with database.session_scope() as session:
        await commercial.forget_organization(session, SLUG)
        await session.execute(
            text(
                "DELETE FROM organization_channel_bindings "
                "WHERE external_id = :external"
            ).bindparams(external=PHONE)
        )
        await session.commit()
        await commercial.provision_bookable_team(session)
    client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    )
    yield client, database, app
    await client.aclose()
    async with database.session_scope() as session:
        await commercial.forget_organization(session, SLUG)
    await database.dispose()
    get_settings.cache_clear()


def _provision_body(**overrides) -> dict:
    body = {
        "slug": SLUG,
        "display_name": "API Plataforma",
        "configuration": {
            "brand": {"working_name": "ApiPlat"},
            "service_area": {"municipalities": ["Zapopan"]},
        },
        "administrators": [ADMIN],
        "advisors": [ADVISOR],
        "default_advisor": ADVISOR,
        "channels": [{"kind": "WhatsAppPhoneNumberId", "external_id": PHONE}],
        "credentials": [
            {"provider": "MetaWhatsApp", "reference": "APIPLAT_META_TOKEN"}
        ],
        "add_ons": ["ExternalInventory"],
        "reason": REASON,
        "command_key": f"api-provision:{uuid.uuid4().hex}",
    }
    body.update(overrides)
    return body


async def _provision(client) -> str:
    response = await client.post(
        "/platform/organizations", json=_provision_body(), headers=HEADERS
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["result"] == "ok"
    return payload["organization_id"]


# -- The credential and the operator name -------------------------------------


async def test_the_platform_surface_refuses_without_its_credential(wired) -> None:
    client, _database, _app = wired
    unauthenticated = await client.get("/platform/organizations")
    assert unauthenticated.status_code == 401

    wrong = await client.get(
        "/platform/organizations",
        headers={"Authorization": "Bearer nope", "X-Platform-Operator": OPERATOR},
    )
    assert wrong.status_code == 401


async def test_an_action_attributed_to_the_token_alone_is_refused(wired) -> None:
    """A platform row nobody can follow up is not an audit trail."""
    client, _database, _app = wired
    nameless = await client.get(
        "/platform/organizations", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert nameless.status_code == 400
    assert "X-Platform-Operator" in nameless.json()["detail"]


async def test_an_organization_administrator_cannot_reach_the_platform_surface(
    wired,
) -> None:
    """The two authorities are separate, and the surface says so with a 401."""
    client, _database, _app = wired
    refused = await client.get(
        "/platform/organizations",
        auth=(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
    )
    assert refused.status_code == 401


async def test_an_unset_platform_token_refuses_everything(tmp_path) -> None:
    """The right default for a local installation nobody configured."""
    settings = Settings(
        _env_file=None,
        DATABASE_URL=DATABASE_URL,
        PLATFORM_OPERATOR_TOKEN="",
        ORGANIZATION_EXPORT_ROOT=str(tmp_path / "exports"),
    )
    app = create_app(settings)
    app.state.database = Database(DATABASE_URL)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        response = await client.get("/platform/organizations", headers=HEADERS)
    assert response.status_code == 401
    await app.state.database.dispose()


# -- Provisioning and lifecycle ------------------------------------------------


async def test_provisioning_reports_every_step_and_lists_the_organization(
    wired,
) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)

    listed = await client.get("/platform/organizations", headers=HEADERS)
    assert listed.status_code == 200
    rows = {item["slug"]: item for item in listed.json()["organizations"]}
    assert rows[SLUG]["status"] == OrganizationStatus.ACTIVE.value
    assert rows[SLUG]["organization_id"] == organization_id


async def test_a_refused_provisioning_answers_409_with_the_reason(wired) -> None:
    """409 rather than 400: the request is well formed and declined."""
    client, _database, _app = wired
    await _provision(client)
    again = await client.post(
        "/platform/organizations", json=_provision_body(), headers=HEADERS
    )
    assert again.status_code == 409
    assert "ya está operando" in again.json()["failure"]


async def test_a_reason_shorter_than_a_sentence_is_refused_by_the_schema(
    wired,
) -> None:
    client, _database, _app = wired
    response = await client.post(
        "/platform/organizations",
        json=_provision_body(reason="arreglo"),
        headers=HEADERS,
    )
    assert response.status_code == 422


async def test_suspend_resume_and_deprovision_move_the_lifecycle(wired) -> None:
    client, database, _app = wired
    organization_id = await _provision(client)
    key = uuid.uuid4().hex

    suspended = await client.post(
        f"/platform/organizations/{organization_id}/suspend",
        json={"reason": REASON, "command_key": f"suspend:{key}"},
        headers=HEADERS,
    )
    assert suspended.json()["status"] == OrganizationStatus.SUSPENDED.value

    resumed = await client.post(
        f"/platform/organizations/{organization_id}/resume",
        json={"reason": REASON, "command_key": f"resume:{key}"},
        headers=HEADERS,
    )
    assert resumed.json()["status"] == OrganizationStatus.ACTIVE.value

    gone = await client.post(
        f"/platform/organizations/{organization_id}/deprovision",
        json={"reason": REASON, "command_key": f"deprovision:{key}"},
        headers=HEADERS,
    )
    assert gone.status_code == 200
    # The sentence people misread, asserted: deprovisioning retains the data.
    assert gone.json()["data_retained"] is True
    async with database.session_scope() as session:
        organization = await session.get(Organization, uuid.UUID(organization_id))
        assert organization is not None
        assert organization.status == OrganizationStatus.DEPROVISIONED.value


async def test_resuming_a_deprovisioned_organization_is_refused(wired) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)
    key = uuid.uuid4().hex
    await client.post(
        f"/platform/organizations/{organization_id}/deprovision",
        json={"reason": REASON, "command_key": f"deprovision:{key}"},
        headers=HEADERS,
    )
    refused = await client.post(
        f"/platform/organizations/{organization_id}/resume",
        json={"reason": REASON, "command_key": f"resume:{key}"},
        headers=HEADERS,
    )
    assert refused.status_code == 409
    assert "se reanuda" in refused.json()["detail"]


async def test_a_run_can_be_rolled_back_through_the_surface(wired) -> None:
    client, database, _app = wired
    body = _provision_body()
    created = await client.post(
        "/platform/organizations", json=body, headers=HEADERS
    )
    run_id = created.json()["run_id"]

    rolled = await client.post(
        f"/platform/runs/{run_id}/rollback",
        json={"reason": REASON, "command_key": f"rollback:{uuid.uuid4().hex}"},
        headers=HEADERS,
    )
    assert rolled.status_code == 200
    assert "Activation" in rolled.json()["undone"]

    missing = await client.post(
        f"/platform/runs/{uuid.uuid4()}/rollback",
        json={"reason": REASON, "command_key": f"rollback:{uuid.uuid4().hex}"},
        headers=HEADERS,
    )
    assert missing.status_code == 409
    assert database is not None


# -- Configuration, entitlements, credentials, channels ------------------------


async def test_configuration_is_recorded_and_read_back_as_versions(wired) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)

    recorded = await client.put(
        f"/platform/organizations/{organization_id}/configuration",
        json={
            "document": {
                "brand": {"working_name": "ApiPlat"},
                "limits": {"campaign_recipients": 25},
            },
            "reason": "El cliente pidió bajar el tope de destinatarios.",
            "command_key": f"configuration:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert recorded.status_code == 200
    assert recorded.json()["version"] == 2

    history = await client.get(
        f"/platform/organizations/{organization_id}/configuration", headers=HEADERS
    )
    versions = history.json()["versions"]
    assert [item["version"] for item in versions] == [2, 1]
    assert versions[0]["is_current"] is True


async def test_a_configuration_carrying_a_credential_is_refused_at_the_surface(
    wired,
) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)
    refused = await client.put(
        f"/platform/organizations/{organization_id}/configuration",
        json={
            "document": {"channels": {"whatsapp": {"access_token": "EAAG..."}}},
            "reason": "Intento de guardar una credencial en la configuración.",
            "command_key": f"configuration:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert refused.status_code == 409
    assert "credenciales" in refused.json()["detail"]


async def test_entitlements_can_be_granted_and_read_with_their_reasons(
    wired,
) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)

    before = await client.get(
        f"/platform/organizations/{organization_id}/entitlements", headers=HEADERS
    )
    rows = {item["capability"]: item for item in before.json()["entitlements"]}
    assert rows["SponsoredPlacement"]["permitted"] is False
    assert rows["ExternalInventory"]["permitted"] is True
    assert rows["AdvisorSeats"]["limit"] == 3
    assert rows["AdvisorSeats"]["used"] == 1

    granted = await client.put(
        f"/platform/organizations/{organization_id}/entitlements",
        json={
            "capability": "SponsoredPlacement",
            "state": "Enabled",
            "reason": "El cliente compró el complemento de patrocinios.",
        },
        headers=HEADERS,
    )
    assert granted.json()["state"] == "Enabled"

    refused = await client.put(
        f"/platform/organizations/{organization_id}/entitlements",
        json={
            "capability": "PublicSite",
            "state": "Enabled",
            "limit_value": 3,
            "reason": "Intento de poner un tope donde no aplica.",
        },
        headers=HEADERS,
    )
    assert refused.status_code == 409


async def test_a_credential_reference_is_recorded_without_its_value(wired) -> None:
    client, database, app = wired
    organization_id = await _provision(client)
    app.state.secret_resolver.record("APIPLAT_META_TOKEN_2", "token-api-2")

    rotated = await client.put(
        f"/platform/organizations/{organization_id}/credentials",
        json={
            "provider": "MetaWhatsApp",
            "reference": "APIPLAT_META_TOKEN_2",
            "reason": "Rotación programada del token de Meta.",
        },
        headers=HEADERS,
    )
    assert rotated.status_code == 200
    assert rotated.json()["reference"] == "APIPLAT_META_TOKEN_2"
    assert rotated.json()["resolves"] is True
    assert "token-api" not in rotated.text

    material = await client.put(
        f"/platform/organizations/{organization_id}/credentials",
        json={
            "provider": "MetaWhatsApp",
            "reference": "-----BEGIN PRIVATE KEY",
            "reason": "Intento de guardar el valor, no el nombre.",
        },
        headers=HEADERS,
    )
    assert material.status_code == 409
    assert "nombre" in material.json()["detail"]
    assert database is not None


async def test_a_channel_can_be_bound_and_a_conflict_is_named(wired) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)

    bound = await client.put(
        f"/platform/organizations/{organization_id}/channels",
        json={
            "kind": "PublicSiteHost",
            "external_id": "apiplat.test",
            "reason": "Se asigna el dominio público de la organización.",
        },
        headers=HEADERS,
    )
    assert bound.json()["state"] == "Active"

    taken = await client.put(
        f"/platform/organizations/{organization_id}/channels",
        json={
            "kind": "WhatsAppPhoneNumberId",
            "external_id": commercial.TEST_PHONE_NUMBER_ID,
            "reason": "Se intenta asignar el número operativo solicitado.",
        },
        headers=HEADERS,
    )
    assert taken.status_code == 409
    assert "otra organización" in taken.json()["detail"]


# -- Support access ------------------------------------------------------------


async def test_support_access_is_granted_listed_and_revoked(wired) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)

    granted = await client.post(
        f"/platform/organizations/{organization_id}/support-access",
        json={
            "engineer_login": OPERATOR,
            "reason": "El cliente reporta que una cita no aparece en la agenda.",
            "command_key": f"support:{uuid.uuid4().hex}",
            "hours": 2,
            "request_reference": "Llamada del 12 de marzo",
        },
        headers=HEADERS,
    )
    assert granted.status_code == 200
    payload = granted.json()
    # ``soporte:<organization>:<engineer>`` — the Organization is in the login
    # because the member login namespace is platform-wide (ADR-0054).
    assert payload["login"] == f"soporte:{SLUG}:{OPERATOR}"
    assert payload["scope"] == "ReadOnly"

    support_auth = (payload["login"], "support-password")
    crm = await client.get("/crm", auth=support_auth)
    assert crm.status_code == 200
    blocked_write = await client.post(
        "/crm/inventario-externo/sincronizar", auth=support_auth
    )
    assert blocked_write.status_code == 403
    assert "sólo lectura" in blocked_write.json()["detail"]

    listed = await client.get("/platform/support-access", headers=HEADERS)
    grants = {item["grant_id"]: item for item in listed.json()["grants"]}
    assert grants[payload["grant_id"]]["state"] == "Vigente"
    assert grants[payload["grant_id"]]["organization"] == SLUG

    revoked = await client.post(
        f"/platform/support-access/{payload['grant_id']}/revoke",
        json={
            "reason": "Diagnóstico terminado; era una ausencia registrada.",
            "command_key": f"revoke:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    missing = await client.post(
        f"/platform/support-access/{uuid.uuid4()}/revoke",
        json={
            "reason": "Revocación de un acceso que no existe.",
            "command_key": f"revoke:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert missing.status_code == 409


async def test_a_support_grant_longer_than_a_day_is_refused_by_the_schema(
    wired,
) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)
    refused = await client.post(
        f"/platform/organizations/{organization_id}/support-access",
        json={
            "engineer_login": OPERATOR,
            "reason": "Investigación que debería pedirse dos veces.",
            "command_key": f"support:{uuid.uuid4().hex}",
            "hours": 24,
        },
        headers=HEADERS,
    )
    assert refused.status_code == 422


# -- Usage, import and the data lifecycle -------------------------------------


async def test_usage_reads_the_stored_month(wired) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)
    response = await client.get(
        f"/platform/organizations/{organization_id}/usage", headers=HEADERS
    )
    assert response.status_code == 200
    metrics = {item["metric"] for item in response.json()["readings"]}
    assert "ActiveAdvisors" in metrics
    assert "WhatsAppConversations" in metrics


def _import_body(**overrides) -> dict:
    body = {
        "source": "Inventario-ApiPlat-2026-03.xlsx",
        "records": [
            {
                "source_reference": "XLS-1",
                "property_key": "casa-api-1",
                "name": "Casa API 1",
                "property_type": "House",
                "facts": {"bedrooms": 3},
            },
            {
                "source_reference": "XLS-2",
                "property_key": "CASA MALA",
                "name": "Casa mala",
                "property_type": "House",
            },
        ],
        "reason": "Migración inicial del inventario del cliente.",
        "command_key": f"import:{uuid.uuid4().hex}",
    }
    body.update(overrides)
    return body


async def test_an_import_dry_run_then_apply_then_rollback_through_the_surface(
    wired,
) -> None:
    client, database, _app = wired
    organization_id = await _provision(client)
    body = _import_body()

    apply_first = await client.post(
        f"/platform/organizations/{organization_id}/import/apply",
        json=body,
        headers=HEADERS,
    )
    assert apply_first.status_code == 409
    assert "prueba en seco" in apply_first.json()["detail"]

    dry = await client.post(
        f"/platform/organizations/{organization_id}/import/dry-run",
        json=body,
        headers=HEADERS,
    )
    assert dry.status_code == 200
    planned = dry.json()
    assert planned["summary"]["Accepted"] == 1
    assert planned["summary"]["Invalid"] == 1
    assert planned["provenance"]["source"] == body["source"]
    async with database.session_scope() as session:
        created = await session.scalars(
            select(Property).where(
                Property.organization_id == uuid.UUID(organization_id)
            )
        )
        assert list(created) == []

    applied = await client.post(
        f"/platform/organizations/{organization_id}/import/apply",
        json={**body, "command_key": f"import-apply:{uuid.uuid4().hex}"},
        headers=HEADERS,
    )
    assert applied.status_code == 200
    assert applied.json()["state"] == "Applied"

    rolled = await client.post(
        f"/platform/import-runs/{applied.json()['run_id']}/rollback",
        json={
            "reason": "El cliente pidió revertir la carga inicial.",
            "command_key": f"import-rollback:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert rolled.json()["state"] == "RolledBack"
    async with database.session_scope() as session:
        remaining = await session.scalars(
            select(Property).where(
                Property.organization_id == uuid.UUID(organization_id)
            )
        )
        assert list(remaining) == []


async def test_export_names_what_it_withholds_and_delete_respects_a_hold(
    wired, tmp_path
) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)

    exported = await client.post(
        f"/platform/organizations/{organization_id}/export",
        json={
            "reason": "Entrega de información solicitada por el cliente.",
            "command_key": f"export:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert exported.status_code == 200
    manifest = exported.json()
    assert manifest["rows"] > 0
    assert "salt" in manifest["withheld"]["pseudonym_salts"]
    artifact = json.loads(
        (tmp_path / "exports" / manifest["artifact_path"].rsplit("/", 1)[-1]).read_text()
    )
    assert artifact["organization"]["slug"] == SLUG
    assert "token-api" not in json.dumps(artifact)

    hold = await client.post(
        f"/platform/organizations/{organization_id}/retention-holds",
        json={
            "basis": "LegalObligation",
            "authority": "Requerimiento 2026/114",
            "description": "Conservar el registro comercial hasta la resolución.",
        },
        headers=HEADERS,
    )
    assert hold.status_code == 200

    blocked = await client.post(
        f"/platform/organizations/{organization_id}/delete",
        json={
            "scope": "Everything",
            "reason": "Solicitud de eliminación del cliente.",
            "command_key": f"delete:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert blocked.status_code == 409
    assert "2026/114" in blocked.json()["blocked_reason"]

    released = await client.post(
        f"/platform/retention-holds/{hold.json()['hold_id']}/release",
        json={
            "reason": "La obligación concluyó el 3 de marzo.",
            "command_key": f"release:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert released.json()["released_at"] is not None

    deleted = await client.post(
        f"/platform/organizations/{organization_id}/delete",
        json={
            "scope": "OperationalContent",
            "reason": "Solicitud de eliminación de conversaciones del cliente.",
            "command_key": f"delete:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert deleted.status_code == 200
    assert deleted.json()["state"] == "Completed"


async def test_a_retention_hold_without_an_authority_is_refused(wired) -> None:
    client, _database, _app = wired
    organization_id = await _provision(client)
    refused = await client.post(
        f"/platform/organizations/{organization_id}/retention-holds",
        json={
            "basis": "Dispute",
            "authority": " ",
            "description": "Retención sin autoridad nombrada.",
        },
        headers=HEADERS,
    )
    assert refused.status_code == 422


# -- The Organization's own read-only panel ------------------------------------


async def test_the_panel_shows_configuration_plan_references_and_support(
    wired,
) -> None:
    """The page a customer reads to check what Maia knows about them."""
    client, database, _app = wired
    await _provision(client)
    # The grant is into the *founding* Organization, because that is whose panel
    # this test reads: a customer's page shows accesses into their own records
    # and nobody else's.
    async with database.session_scope() as session:
        founding = await commercial.organization_id(session)
    # A reference of the founding Organization's own, so the populated table is
    # what this test reads. The bootstrap may or may not have recorded one
    # depending on the process environment, and a test that depended on which
    # would pass or fail by accident.
    named = await client.put(
        f"/platform/organizations/{founding}/credentials",
        json={
            "provider": "EasyBroker",
            "reference": "LAREVIA_EASYBROKER_API_KEY",
            "reason": "Registro de la referencia para la prueba del panel.",
        },
        headers=HEADERS,
    )
    assert named.status_code == 200
    granted = await client.post(
        f"/platform/organizations/{founding}/support-access",
        json={
            "engineer_login": OPERATOR,
            "reason": "El cliente reporta un problema con su bandeja.",
            "command_key": f"support:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert granted.status_code == 200

    # The newcomer's Administrator has no Basic account in this suite, so the
    # panel refuses them at authentication — which is the honest demonstration
    # that the page is reached with the customer's own credential, not the
    # platform's.
    page = await client.get(
        "/crm/plataforma", auth=(ADMIN, commercial.ADMIN_PASSWORD)
    )
    assert page.status_code == 401

    theirs = await client.get(
        "/crm/plataforma",
        auth=(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
    )
    assert theirs.status_code == 200
    body = theirs.text
    assert "Plataforma" in body
    assert "Capacidades incluidas en el plan" in body
    assert "Referencias de credenciales" in body
    assert "LAREVIA_EASYBROKER_API_KEY" in body
    assert "Accesos temporales del equipo de Maia" in body
    assert "Uso medido del mes en curso" in body
    assert f"soporte:{LAREVIA_SLUG}:{OPERATOR}" in body
    assert "El cliente reporta un problema con su bandeja." in body
    # A reference is a name; the value is never on the page.
    assert "token-api" not in body

    # And revoking it leaves the row visible with its new standing, which is the
    # property a customer is actually promised.
    revoked = await client.post(
        f"/platform/support-access/{granted.json()['grant_id']}/revoke",
        json={
            "reason": "Diagnóstico terminado; el problema era una ausencia.",
            "command_key": f"revoke:{uuid.uuid4().hex}",
        },
        headers=HEADERS,
    )
    assert revoked.status_code == 200
    after = await client.get(
        "/crm/plataforma",
        auth=(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
    )
    assert "Revocado" in after.text

    # The reference this test recorded is removed again: it belongs to the
    # founding Organization, which other suites read, and leaving it behind would
    # change what "this Organization has no credential" means for them.
    async with database.session_scope() as session:
        await session.execute(
            text(
                "DELETE FROM organization_secret_references "
                "WHERE organization_id = :org AND provider = 'EasyBroker'"
            ).bindparams(org=founding)
        )
        await session.commit()


async def test_an_advisor_cannot_read_the_platform_panel(wired) -> None:
    client, _database, _app = wired
    refused = await client.get(
        "/crm/plataforma",
        auth=(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD),
    )
    assert refused.status_code == 403


async def test_the_panel_reports_a_live_retention_hold_to_the_customer(
    wired,
) -> None:
    """A customer whose deletion request would be refused is told beforehand."""
    client, database, _app = wired
    async with database.session_scope() as session:
        founding = await commercial.organization_id(session)
    hold = await client.post(
        f"/platform/organizations/{founding}/retention-holds",
        json={
            "basis": "Contract",
            "authority": "Cláusula 9 del contrato",
            "description": "Conservar doce meses tras la terminación.",
        },
        headers=HEADERS,
    )
    assert hold.status_code == 200
    page = await client.get(
        "/crm/plataforma",
        auth=(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
    )
    assert "retención vigente" in page.text
    assert "Cláusula 9 del contrato" in page.text
    async with database.session_scope() as session:
        await session.execute(
            text(
                "DELETE FROM organization_retention_holds WHERE id = :id"
            ).bindparams(id=uuid.UUID(hold.json()["hold_id"]))
        )
        await session.commit()


async def test_the_panel_says_so_when_there_is_no_configuration_yet(
    wired,
) -> None:
    """An Organization operating on defaults nobody chose is the failure mode.

    The founding Organization's versions are removed and put back, because other
    suites read them: a test that left this Organization unconfigured would make
    an unrelated suite fail with the wrong explanation.
    """
    client, database, _app = wired
    async with database.session_scope() as session:
        founding = await commercial.organization_id(session)
        rows = (
            await session.execute(
                text(
                    "SELECT id, version, document, checksum, is_current, note, "
                    "recorded_by, recorded_at, command_key "
                    "FROM organization_configuration_versions "
                    "WHERE organization_id = :org"
                ).bindparams(org=founding)
            )
        ).mappings().all()
        await session.execute(
            text(
                "DELETE FROM organization_configuration_versions "
                "WHERE organization_id = :org"
            ).bindparams(org=founding)
        )
        await session.commit()
    try:
        page = await client.get(
            "/crm/plataforma",
            auth=(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD),
        )
        assert "Aún no hay una configuración registrada" in page.text
    finally:
        async with database.session_scope() as session:
            for row in rows:
                await session.execute(
                    text(
                        "INSERT INTO organization_configuration_versions "
                        "(id, organization_id, version, document, checksum, "
                        " is_current, note, recorded_by, recorded_at, command_key) "
                        "VALUES (:id, :org, :version, CAST(:document AS jsonb), "
                        ":checksum, :is_current, :note, :recorded_by, "
                        ":recorded_at, :command_key)"
                    ).bindparams(
                        id=row["id"],
                        org=founding,
                        version=row["version"],
                        document=json.dumps(row["document"]),
                        checksum=row["checksum"],
                        is_current=row["is_current"],
                        note=row["note"],
                        recorded_by=row["recorded_by"],
                        recorded_at=row["recorded_at"],
                        command_key=row["command_key"],
                    )
                )
            await session.commit()

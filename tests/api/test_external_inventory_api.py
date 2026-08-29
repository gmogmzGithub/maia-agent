"""Admin authorization and credential-redaction for external inventory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import select, text

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import ExternalListingCandidate
from realestate.domain.external_inventory.ports import SourceNotFound
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial
from tests.fixtures.external_inventory import FakeInventorySource

pytestmark = requires_postgres
ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.credentials_json()
    )
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        for table_name in (
            "listing_revalidations",
            "external_offer_candidates",
            "external_listing_candidates",
            "inventory_source_health",
        ):
            await session.execute(text(f"DELETE FROM {table_name}"))
        await commercial.reset(session)
        await commercial.reset(session, members=True)
        await commercial.provision(session)
    app = create_app(get_settings())
    app.state.database = database
    source = FakeInventorySource()
    source._api_key = "must-never-appear"  # type: ignore[attr-defined]
    app.state.easybroker = source
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, database, source
    await database.dispose()


async def test_surface_requires_authentication_and_administrator(wired) -> None:
    client, _, _ = wired

    assert (await client.get("/crm/inventario-externo")).status_code == 401
    assert (
        await client.get("/crm/inventario-externo", auth=ADVISOR)
    ).status_code == 403
    assert (
        await client.post("/crm/inventario-externo/sincronizar", auth=ADVISOR)
    ).status_code == 403


async def test_health_sync_and_evidence_controls_never_render_a_secret(wired) -> None:
    client, database, _ = wired

    initial = await client.get("/crm/inventario-externo", auth=ADMIN)
    synced = await client.post(
        "/crm/inventario-externo/sincronizar", auth=ADMIN
    )
    page = await client.get("/crm/inventario-externo", auth=ADMIN)

    assert initial.status_code == 200
    assert synced.status_code == 303
    assert "Credencial" in page.text
    assert "Configurada" in page.text
    assert "Acceso API MLS" in page.text
    assert "Permiso de retención" in page.text
    assert "EB-FAKE-001" in page.text
    assert "must-never-appear" not in page.text
    async with database.session_scope() as session:
        candidate = await session.scalar(select(ExternalListingCandidate))
        assert candidate is not None

    saved = await client.post(
        f"/crm/inventario-externo/{candidate.id}/evidencia",
        auth=ADMIN,
        data={
            "evidencia": "Acuerdo sintético certificado",
            "atribucion": "Inmobiliaria Demo · Agente Demo",
            "disponibilidad": "Available",
            "colaboracion": "1",
            "tipo_comision": "porcentaje",
            "comision": "2.5%",
        },
    )
    assert saved.status_code == 303
    async with database.session_scope() as session:
        candidate = await session.get(ExternalListingCandidate, candidate.id)
        assert candidate is not None
        assert candidate.authority_state == "Authorized"
        assert candidate.commission_known


async def test_refresh_withdrawal_cleanup_and_invalid_admin_controls(wired) -> None:
    client, database, source = wired
    await client.post("/crm/inventario-externo/sincronizar", auth=ADMIN)
    async with database.session_scope() as session:
        candidate = await session.scalar(select(ExternalListingCandidate))
        assert candidate is not None
        candidate_id = candidate.id

    refreshed = await client.post(
        f"/crm/inventario-externo/{candidate_id}/revalidar", auth=ADMIN
    )
    assert refreshed.status_code == 303

    invalid = await client.post(
        f"/crm/inventario-externo/{candidate_id}/evidencia",
        auth=ADMIN,
        data={"disponibilidad": "Invented"},
    )
    assert invalid.status_code == 400

    unknown = await client.post(
        f"/crm/inventario-externo/{uuid.uuid4()}/evidencia",
        auth=ADMIN,
        data={
            "evidencia": "Evidencia",
            "atribucion": "Fuente",
            "disponibilidad": "Available",
        },
    )
    assert unknown.status_code == 404

    source.retrieve_errors["EB-FAKE-001"] = SourceNotFound()
    withdrawn = await client.post(
        f"/crm/inventario-externo/{candidate_id}/revalidar", auth=ADMIN
    )
    page = await client.get("/crm/inventario-externo", auth=ADMIN)
    assert withdrawn.status_code == 303
    assert "Retirada" in page.text

    async with database.session_scope() as session:
        candidate = await session.get(ExternalListingCandidate, candidate_id)
        assert candidate is not None
        candidate.deletion_due_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        await session.commit()
    cleaned = await client.post("/crm/inventario-externo/limpiar", auth=ADMIN)
    page = await client.get("/crm/inventario-externo", auth=ADMIN)
    assert cleaned.status_code == 303
    assert "Caché eliminada" in page.text


async def test_refresh_unknown_candidate_is_not_found(wired) -> None:
    client, _, _ = wired

    response = await client.post(
        f"/crm/inventario-externo/{uuid.uuid4()}/revalidar", auth=ADMIN
    )

    assert response.status_code == 404

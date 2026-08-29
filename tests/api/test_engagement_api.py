"""Admin authorization, Mexican-Spanish controls and PII-safe audience UI."""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import select

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import DevelopmentCampaign, ReactivationCandidate
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures import commercial
from tests.domain.test_engagement import FakeTemplates, foundation

pytestmark = requires_postgres
ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("MARKETING_OUTBOUND_ACTIVATED", "false")
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.credentials_json()
    )
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await reset_property_inventory(session)
        await commercial.reset(session, members=True)
        await commercial.provision(session)
    app = create_app(get_settings())
    app.state.database = database
    app.state.meta_templates = FakeTemplates(
        ("nueva_coincidencia", "Encontramos una opción nueva para ti."),
        ("nuevo_desarrollo", "Tenemos un desarrollo que podría interesarte."),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, database, app
    await database.dispose()


async def test_surface_requires_an_administrator_and_is_mexican_spanish(wired) -> None:
    client, _, _ = wired

    assert (await client.get("/crm/reactivacion")).status_code == 401
    assert (await client.get("/crm/reactivacion", auth=ADVISOR)).status_code == 403
    page = await client.get("/crm/reactivacion", auth=ADMIN)

    assert page.status_code == 200
    assert "Reactivación y campañas" in page.text
    assert "Consentimiento:</strong> No otorgado" in page.text
    assert "Costo potencial:</strong>" in page.text
    assert "Buscar coincidencias; no enviar" in page.text
    assert "Enviar a todos" not in page.text
    # The surface claims Mexican Spanish, so no durable English enum value may
    # reach it: these are the provider and state words the page renders.
    for untranslated in ("Denied", "Approved", "Draft", "Excluded", "Paused"):
        assert untranslated not in page.text


async def test_admin_workflow_renders_explanations_without_contact_pii(wired) -> None:
    client, database, _ = wired
    listing, development_id, states = await foundation(database)
    state, _ = states[0]

    synced = await client.post("/crm/reactivacion/plantillas/sincronizar", auth=ADMIN)
    discovered = await client.post(
        "/crm/reactivacion/descubrir",
        auth=ADMIN,
        data={"listing_id": str(listing.listing_id)},
    )
    assert synced.status_code == discovered.status_code == 303

    async with database.session_scope() as session:
        candidate = await session.scalar(select(ReactivationCandidate))
        assert candidate is not None
        candidate_id = candidate.id

    denied = await client.post(
        f"/crm/reactivacion/candidatos/{candidate_id}/autorizar",
        auth=ADMIN,
        data={
            "template_name": "nueva_coincidencia",
            "template_language": "es_MX",
            "message_preview": "Encontramos una opción nueva para ti.",
            "reason": "Coincidencia revisada",
        },
    )
    assert denied.status_code == 303

    planned = await client.post(
        "/crm/reactivacion/campanas",
        auth=ADMIN,
        data={
            "development_id": str(development_id),
            "name": "Campaña sintética",
            "property_need_ids": str(state.need_id),
            "exclude_property_need_ids": "",
            "service_area_contains": "Zapopan",
            "template_name": "nuevo_desarrollo",
            "template_language": "es_MX",
            "content_preview": "Tenemos un desarrollo que podría interesarte.",
            "frequency_cap": "1",
            "frequency_window_days": "30",
            "max_recipients": "10",
        },
    )
    assert planned.status_code == 303
    async with database.session_scope() as session:
        campaign = await session.scalar(select(DevelopmentCampaign))
        assert campaign is not None

    activation = await client.post(
        f"/crm/reactivacion/campanas/{campaign.id}/activar", auth=ADMIN
    )
    assert activation.status_code == 400
    assert "activación real" in activation.text

    page = await client.get("/crm/reactivacion", auth=ADMIN)
    assert "Activación real de Marketing no aprobada" in page.text
    assert "MarketingActivationNotApproved" not in page.text
    assert "Vista previa y resultados por referencia" in page.text
    assert "Cumple los criterios" in page.text
    assert state.lead.wa_id not in page.text
    assert "Casilla separada aceptada" not in page.text
    assert "fixture://consent" not in page.text

    cancelled = await client.post(
        f"/crm/reactivacion/campanas/{campaign.id}/cancelar",
        auth=ADMIN,
        data={"reason": "Prueba"},
    )
    assert cancelled.status_code == 303


async def test_invalid_ids_and_transitions_are_operator_readable(wired) -> None:
    client, _, _ = wired

    invalid_listing = await client.post(
        "/crm/reactivacion/descubrir",
        auth=ADMIN,
        data={"listing_id": "no-es-uuid"},
    )
    invalid_audience = await client.post(
        "/crm/reactivacion/campanas",
        auth=ADMIN,
        data={
            "development_id": str(uuid.uuid4()),
            "property_need_ids": "tampoco-es-uuid",
        },
    )
    unknown_candidate = await client.post(
        f"/crm/reactivacion/candidatos/{uuid.uuid4()}/rechazar",
        auth=ADMIN,
        data={"reason": "No existe"},
    )

    assert invalid_listing.status_code == 400
    assert invalid_audience.status_code == 400
    assert unknown_candidate.status_code == 400
    assert "No encontramos" in unknown_candidate.text


async def test_provider_failure_and_invalid_campaign_fields_are_readable(wired) -> None:
    client, _, app = wired
    source = FakeTemplates()
    source.configured = False
    app.state.meta_templates = source

    sync = await client.post("/crm/reactivacion/plantillas/sincronizar", auth=ADMIN)
    invalid = await client.post(
        "/crm/reactivacion/campanas",
        auth=ADMIN,
        data={
            "development_id": str(uuid.uuid4()),
            "property_need_ids": str(uuid.uuid4()),
            "frequency_cap": "no-es-numero",
        },
    )
    unknown_cancel = await client.post(
        f"/crm/reactivacion/campanas/{uuid.uuid4()}/cancelar",
        auth=ADMIN,
        data={"reason": "No existe"},
    )

    assert sync.status_code == 303
    assert "Faltan" in sync.headers["location"]
    assert invalid.status_code == 400
    assert "Datos inválidos" in invalid.text
    assert unknown_cancel.status_code == 400
    assert "No encontramos" in unknown_cancel.text


async def test_synthetic_activation_exercises_revoke_pause_and_cancel_controls(
    wired,
) -> None:
    client, database, app = wired
    app.state.settings = app.state.settings.model_copy(
        update={"marketing_outbound_activated": True}
    )
    listing, development_id, states = await foundation(database)
    await client.post("/crm/reactivacion/plantillas/sincronizar", auth=ADMIN)
    await client.post(
        "/crm/reactivacion/descubrir",
        auth=ADMIN,
        data={"listing_id": str(listing.listing_id)},
    )
    pending_page = await client.get("/crm/reactivacion", auth=ADMIN)
    assert "Revisar" in pending_page.text

    async with database.session_scope() as session:
        candidate = await session.scalar(select(ReactivationCandidate))
        assert candidate is not None
    authorized = await client.post(
        f"/crm/reactivacion/candidatos/{candidate.id}/autorizar",
        auth=ADMIN,
        data={
            "template_name": "nueva_coincidencia",
            "template_language": "es_MX",
            "message_preview": "Encontramos una opción nueva para ti.",
            "reason": "Fixture revisada",
        },
    )
    authorized_page = await client.get("/crm/reactivacion", auth=ADMIN)
    revoked = await client.post(
        f"/crm/reactivacion/candidatos/{candidate.id}/revocar",
        auth=ADMIN,
        data={"reason": "Cambio"},
    )
    revoked_again = await client.post(
        f"/crm/reactivacion/candidatos/{candidate.id}/revocar",
        auth=ADMIN,
        data={"reason": "Otra vez"},
    )
    assert authorized.status_code == revoked.status_code == 303
    assert "Revocar antes del envío" in authorized_page.text
    assert revoked_again.status_code == 400

    planned = await client.post(
        "/crm/reactivacion/campanas",
        auth=ADMIN,
        data={
            "development_id": str(development_id),
            "name": "Control sintético",
            "property_need_ids": str(states[0][0].need_id),
            "template_name": "nuevo_desarrollo",
            "template_language": "es_MX",
            "content_preview": "Tenemos un desarrollo que podría interesarte.",
            "frequency_cap": "1",
            "frequency_window_days": "30",
            "max_recipients": "5",
        },
    )
    assert planned.status_code == 303
    async with database.session_scope() as session:
        campaign = await session.scalar(select(DevelopmentCampaign))
        assert campaign is not None
    active = await client.post(
        f"/crm/reactivacion/campanas/{campaign.id}/activar", auth=ADMIN
    )
    active_page = await client.get("/crm/reactivacion", auth=ADMIN)
    paused = await client.post(
        f"/crm/reactivacion/campanas/{campaign.id}/pausar",
        auth=ADMIN,
        data={"reason": "Revisión"},
    )
    paused_again = await client.post(
        f"/crm/reactivacion/campanas/{campaign.id}/pausar",
        auth=ADMIN,
        data={"reason": "Otra"},
    )
    cancelled = await client.post(
        f"/crm/reactivacion/campanas/{campaign.id}/cancelar",
        auth=ADMIN,
        data={"reason": "Fin"},
    )
    cancelled_page = await client.get("/crm/reactivacion", auth=ADMIN)

    assert active.status_code == paused.status_code == cancelled.status_code == 303
    assert "Pausar" in active_page.text
    assert paused_again.status_code == 400
    assert "Sin acciones nuevas" in cancelled_page.text

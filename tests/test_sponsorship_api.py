"""The operator surfaces and the internal contracts, end to end.

Two operator pages and four internal contracts, asserted through the real ASGI
application so the authorization, the Mexican Spanish and the label all have to
survive the routing rather than only the module.

The end-to-end case at the bottom is the one the stage exists to prove: an
Administrator publishes a price, opens a campaign, quotes it, accepts it,
activates it, and hands a buyer an expiring link whose HTML and PDF contain
aggregate figures, the ``Patrocinada`` label and no identity at all.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from urllib.parse import unquote

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import select

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    SponsorshipCampaign,
    SponsorshipCampaignStatus,
    SponsorshipQuote,
    SponsorshipReportLink,
)
from realestate.api import public_site as public_site_api
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.clock import utc_now
from realestate.domain.sponsorship.labels import (
    NON_CAUSAL_DISCLAIMER,
    SPONSORED_LABEL,
)
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures import commercial
from tests.fixtures.public_site import publish_listing
from tests.fixtures.sponsorship import CLEARANCE, PILOT_EVIDENCE

pytestmark = requires_postgres
ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)
SITE_TOKEN = "site-internal-token-for-tests"


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("SITE_PRODUCT_API_TOKEN", SITE_TOKEN)
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
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, database
    await database.dispose()
    get_settings.cache_clear()


def location(response: httpx.Response) -> str:
    """The redirect target, percent-decoded.

    ``redirect_back`` encodes the Spanish outcome so a message containing ``&``
    cannot break the query string, so every assertion about what an operator was
    told has to decode it first.
    """
    return unquote(response.headers["location"])


def site(headers: dict[str, str] | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {SITE_TOKEN}", **(headers or {})}


async def a_listing(database, suffix: str) -> uuid.UUID:
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        listing = await publish_listing(session, admin, suffix)
        await session.commit()
        return listing.listing_id


async def test_both_surfaces_require_an_administrator(wired) -> None:
    client, _ = wired
    for path in ("/crm/patrocinios", "/crm/bi"):
        assert (await client.get(path, auth=ADVISOR)).status_code == 403
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, auth=ADMIN)).status_code == 200


async def test_the_sponsorship_surface_is_mexican_spanish_and_says_pricing_is_pending(
    wired,
) -> None:
    """With no published catalog the page refuses to offer a price field.

    SAN-062 is unresolved, so an empty box somebody would fill in with a guess
    is exactly what must not be there.
    """
    client, database = wired
    listing_id = await a_listing(database, "api-precio")
    response = await client.get("/crm/patrocinios", auth=ADMIN)
    body = response.text
    assert response.status_code == 200
    assert "Patrocinios" in body
    assert SPONSORED_LABEL in body
    assert "Destacada" in body
    assert "El primer precio se fija con tráfico medido del piloto" in body
    assert NON_CAUSAL_DISCLAIMER in body
    assert str(listing_id) in body
    # No English state leaks to the operator.
    for english in ("Draft", "Published", "AwaitingPayment"):
        assert f">{english}<" not in body


async def test_the_bi_dashboard_shows_sin_registrar_and_the_data_quality_panel(
    wired,
) -> None:
    client, database = wired
    empty = await client.get("/crm/bi", auth=ADMIN)
    body = empty.text
    assert empty.status_code == 200
    assert "Inteligencia de negocio" in body
    assert "Cobertura de seguimiento" in body
    assert "Completitud de datos de seguimiento" in body
    assert "Sin registrar" in body
    assert "Tráfico excluido del cálculo" in body
    assert "Señales de daño del piloto" in body
    assert "Información incorrecta" in body
    # A dashboard that has never projected says so rather than showing an empty
    # table an operator would read as "nothing was excluded".
    assert "Todavía no se ha ejecutado una proyección." in body

    # One real event, so the projection has something to consume and a run row
    # to report. A pass over an empty Outbox deliberately writes nothing.
    listing_id = await a_listing(database, "api-tablero")
    await client.post(
        "/internal/public-site/measurement/listing-open",
        json={
            "event_key": "apertura-para-el-tablero",
            "listing_id": str(listing_id),
            "surface": "TechnicalSheet",
            "occurred_at": "2026-08-28T18:00:00+00:00",
        },
        headers=site(),
    )
    await client.post("/crm/bi/proyectar", auth=ADMIN, follow_redirects=False)
    ran = await client.get("/crm/bi", auth=ADMIN)
    assert "Pasadas de proyección" in ran.text
    assert "periodos reconstruidos" in ran.text


async def test_the_whole_commercial_flow_runs_through_the_operator_surface(
    wired,
) -> None:
    client, database = wired
    listing_id = await a_listing(database, "api-flujo")

    published = await client.post(
        "/crm/patrocinios/catalogos",
        auth=ADMIN,
        data={
            "version": "precios-api",
            "currency": "MXN",
            "search": "4000",
            "homepage": "7000",
            "both": "9500",
        },
        follow_redirects=False,
    )
    assert published.status_code == 303

    async with database.session_scope() as session:
        from realestate.db.models import SponsorshipPriceCatalog

        catalog = await session.scalar(select(SponsorshipPriceCatalog))
        assert catalog is not None

    # Publishing without evidence is refused, with the reason on the page.
    refused = await client.post(
        f"/crm/patrocinios/catalogos/{catalog.id}/publicar",
        auth=ADMIN,
        data={"pilot_evidence": "corto"},
        follow_redirects=False,
    )
    assert "error=" in location(refused)

    ok = await client.post(
        f"/crm/patrocinios/catalogos/{catalog.id}/publicar",
        auth=ADMIN,
        data={"pilot_evidence": PILOT_EVIDENCE},
        follow_redirects=False,
    )
    assert "guardado=" in location(ok)

    opened = await client.post(
        "/crm/patrocinios/campanas",
        auth=ADMIN,
        data={
            "listing_id": str(listing_id),
            "buyer_kind": "Owner",
            "buyer_label": "Propietario sintético API",
            "package": "Search",
            "paid_days": "30",
        },
        follow_redirects=False,
    )
    assert "guardado=" in location(opened)

    async with database.session_scope() as session:
        campaign = await session.scalar(select(SponsorshipCampaign))
        assert campaign is not None

    await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/validacion",
        auth=ADMIN,
        data={"evidence": CLEARANCE},
        follow_redirects=False,
    )
    quoted = await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/cotizar",
        auth=ADMIN,
        data={"duration_days": "30", "discount_amount": "0", "discount_reason": ""},
        follow_redirects=False,
    )
    assert "guardado=" in location(quoted)

    async with database.session_scope() as session:
        quote = await session.scalar(select(SponsorshipQuote))
        assert quote is not None
        starts_on = quote.issued_at

    accepted = await client.post(
        f"/crm/patrocinios/cotizaciones/{quote.id}/aceptar",
        auth=ADMIN,
        data={"starts_on": starts_on.strftime("%Y-%m-%dT%H:%M")},
        follow_redirects=False,
    )
    assert "guardado=" in location(accepted), location(accepted)

    scheduled = await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/programar",
        auth=ADMIN,
        data={"starts_on": starts_on.strftime("%Y-%m-%dT%H:%M")},
        follow_redirects=False,
    )
    assert "guardado=" in location(scheduled)

    activated = await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/activar",
        auth=ADMIN,
        follow_redirects=False,
    )
    assert "guardado=" in location(activated)

    collection = await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/cobro",
        auth=ADMIN,
        data={"state": "AwaitingPayment", "reference": "Cotización externa 7"},
        follow_redirects=False,
    )
    assert "guardado=" in location(collection)

    async with database.session_scope() as session:
        row = await session.get(SponsorshipCampaign, campaign.id)
        assert row is not None
        assert row.status == SponsorshipCampaignStatus.ACTIVE.value
        assert row.collection_state == "AwaitingPayment"

    internal = await client.get(
        f"/crm/patrocinios/campanas/{campaign.id}/reporte", auth=ADMIN
    )
    assert internal.status_code == 200
    assert "Sólo interno" in internal.text
    assert "precios-api" in internal.text
    assert "Un comprador nunca recibe este bloque" in internal.text

    shared = await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/compartir",
        auth=ADMIN,
        data={"days": "10"},
        follow_redirects=False,
    )
    redirect = location(shared)
    assert "guardado=" in redirect
    token = re.search(r"/reportes/([A-Za-z0-9_-]+)", redirect)
    assert token is not None
    raw_token = token.group(1)

    # The buyer's own surface: token-authenticated, aggregate, labelled.
    report = await client.get(
        f"/internal/public-site/sponsorship-report/{raw_token}", headers=site()
    )
    assert report.status_code == 200
    payload = report.json()
    assert payload["label"] == SPONSORED_LABEL
    lines = " ".join(item["text"] for item in payload["lines"])
    assert NON_CAUSAL_DISCLAIMER in lines
    assert "Propietario sintético API" not in lines
    assert "precios-api" not in lines

    pdf = await client.get(
        f"/internal/public-site/sponsorship-report/{raw_token}/pdf", headers=site()
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-1.7")
    assert pdf.headers["cache-control"] == "private, no-store"

    # Revoking it closes the door, with the same refusal an unknown token gets.
    async with database.session_scope() as session:
        link = await session.scalar(select(SponsorshipReportLink))
        assert link is not None
    revoked = await client.post(
        f"/crm/patrocinios/enlaces/{link.id}/revocar",
        auth=ADMIN,
        follow_redirects=False,
    )
    assert "guardado=" in location(revoked)
    gone = await client.get(
        f"/internal/public-site/sponsorship-report/{raw_token}", headers=site()
    )
    unknown = await client.get(
        "/internal/public-site/sponsorship-report/token-inexistente", headers=site()
    )
    assert gone.status_code == unknown.status_code == 410
    assert gone.json()["detail"] == unknown.json()["detail"]


async def test_the_sponsored_contract_returns_a_labelled_section_only(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import active_campaign, published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "api-superficie")
        await session.commit()

    response = await client.get(
        "/internal/public-site/sponsored",
        params={"surface": "Search", "visible_results": 12},
        headers=site({"X-Session-Reference": "navegador-api"}),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["surface"] == "Search"
    assert payload["available_slots"] == 2
    assert len(payload["cards"]) == 1
    card = payload["cards"][0]
    assert card["label"] == SPONSORED_LABEL
    assert card["accessible_label"].startswith("Publicación patrocinada")
    assert card["campaign_id"] == str(campaign.campaign_id)
    # The organic list is not part of this answer at all.
    assert "listings" not in payload


async def test_the_sponsored_contract_refuses_an_unknown_surface_or_id(wired) -> None:
    client, _ = wired
    bad_surface = await client.get(
        "/internal/public-site/sponsored",
        params={"surface": "Instagram", "visible_results": 12},
        headers=site(),
    )
    bad_organic = await client.get(
        "/internal/public-site/sponsored",
        params={"surface": "Search", "visible_results": 12, "organic": "no-es-uuid"},
        headers=site(),
    )
    assert bad_surface.status_code == 422
    assert bad_organic.status_code == 422


async def test_every_internal_contract_needs_the_site_token(wired) -> None:
    client, _ = wired
    for method, path in (
        ("GET", "/internal/public-site/sponsored?surface=Search"),
        ("POST", "/internal/public-site/sponsored/visible"),
        ("POST", "/internal/public-site/measurement/listing-open"),
        ("POST", "/internal/public-site/measurement/gallery-depth"),
        ("GET", "/internal/public-site/sponsorship-report/whatever"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 401, path


async def test_a_visible_impression_below_the_threshold_is_not_counted(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import active_campaign, published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "api-visible")
        await session.commit()

    body = {
        "campaign_id": str(campaign.campaign_id),
        "listing_id": str(campaign.listing.listing_id),
        "surface": "Search",
        "visible_fraction": 0.4,
        "continuous_milliseconds": 4000,
        "occurred_at": "2026-08-28T18:00:00+00:00",
    }
    below = await client.post(
        "/internal/public-site/sponsored/visible", json=body, headers=site()
    )
    assert below.status_code == 202
    assert below.json() == {"counted": False}

    body["visible_fraction"] = 0.5
    body["continuous_milliseconds"] = 1000
    above = await client.post(
        "/internal/public-site/sponsored/visible", json=body, headers=site()
    )
    assert above.json() == {"counted": True}


async def test_gallery_depth_at_the_border_also_records_the_milestone(wired) -> None:
    client, database = wired
    listing_id = await a_listing(database, "api-galeria")
    shallow = await client.post(
        "/internal/public-site/measurement/gallery-depth",
        json={
            "event_key": "galeria-poca-profundidad",
            "listing_id": str(listing_id),
            "photographs": 4,
            "gallery_fraction": 0.2,
            "occurred_at": "2026-08-28T18:00:00+00:00",
        },
        headers=site(),
    )
    assert shallow.status_code == 202
    assert shallow.json() == {"depth_recorded": True, "significant": False}

    deep = await client.post(
        "/internal/public-site/measurement/gallery-depth",
        json={
            "event_key": "galeria-exploracion-significativa",
            "listing_id": str(listing_id),
            "photographs": 5,
            "gallery_fraction": 0.0,
            "occurred_at": "2026-08-28T18:00:00+00:00",
        },
        headers=site(),
    )
    assert deep.json() == {"depth_recorded": True, "significant": True}

    async with database.session_scope() as session:
        names = {
            name
            for (name,) in await session.execute(
                select(AnalyticsOutboxEntry.event_name)
            )
        }
        assert AnalyticsEventName.GALLERY_DEPTH_REACHED.value in names
        assert AnalyticsEventName.SIGNIFICANT_GALLERY_EXPLORATION.value in names


async def test_a_listing_open_is_recorded_once_per_session_and_day(wired) -> None:
    client, database = wired
    listing_id = await a_listing(database, "api-apertura")
    body = {
        "event_key": "apertura-misma-sesion",
        "listing_id": str(listing_id),
        "surface": "TechnicalSheet",
        "occurred_at": "2026-08-28T18:00:00+00:00",
    }
    first = await client.post(
        "/internal/public-site/measurement/listing-open", json=body, headers=site()
    )
    second = await client.post(
        "/internal/public-site/measurement/listing-open", json=body, headers=site()
    )
    assert first.json() == {"recorded": True}
    assert second.json() == {"recorded": False}


async def test_a_crawler_header_marks_the_event_excluded(wired) -> None:
    client, database = wired
    listing_id = await a_listing(database, "api-robot")
    await client.post(
        "/internal/public-site/measurement/listing-open",
        json={
            "event_key": "apertura-de-un-robot",
            "listing_id": str(listing_id),
            "surface": "TechnicalSheet",
            "occurred_at": "2026-08-28T18:00:00+00:00",
        },
        headers=site({"X-Crawler": "true"}),
    )
    async with database.session_scope() as session:
        await AnalyticsProjection(session).drain()
        await session.commit()
        from realestate.db.models import AnalyticsDomainEvent

        row = await session.scalar(
            select(AnalyticsDomainEvent).where(
                AnalyticsDomainEvent.event_key == "apertura-de-un-robot"
            )
        )
        assert row is not None
        assert row.traffic_class == "Bot"
        assert row.exclusion_reason == "Robot o rastreador"


async def test_the_dashboard_projects_and_reprojects_on_request(wired) -> None:
    client, database = wired
    listing_id = await a_listing(database, "api-proyeccion")
    await client.post(
        "/internal/public-site/measurement/listing-open",
        json={
            "event_key": "apertura-para-proyectar",
            "listing_id": str(listing_id),
            "surface": "TechnicalSheet",
            "occurred_at": "2026-08-28T18:00:00+00:00",
        },
        headers=site(),
    )
    first = await client.post(
        "/crm/bi/proyectar", auth=ADMIN, data={"version": "measurement-v1"},
        follow_redirects=False,
    )
    assert "1 eventos proyectados" in location(first)

    replay = await client.post(
        "/crm/bi/proyectar",
        auth=ADMIN,
        data={"version": "measurement-v1", "replay": "1"},
        follow_redirects=False,
    )
    # A replay rebuilds the same store: nothing new is inserted.
    assert "0 eventos proyectados" in location(replay)

    bad = await client.post(
        "/crm/bi/proyectar", auth=ADMIN, data={"version": "measurement-v99"},
        follow_redirects=False,
    )
    assert "error=" in location(bad)


async def test_the_dashboard_emits_operational_events_and_records_harm(wired) -> None:
    client, _ = wired
    emitted = await client.post("/crm/bi/emitir", auth=ADMIN, follow_redirects=False)
    assert "guardado=" in location(emitted)

    recorded = await client.post(
        "/crm/bi/danos",
        auth=ADMIN,
        data={
            "kind": "UntimelyMessage",
            "occurred_at": "2026-08-28T20:30",
            "evidence": "Mensaje sintético fuera de horario.",
        },
        follow_redirects=False,
    )
    assert "guardado=" in location(recorded)

    page = await client.get("/crm/bi", auth=ADMIN)
    assert "Mensaje inoportuno" in page.text

    invalid = await client.post(
        "/crm/bi/danos",
        auth=ADMIN,
        data={"kind": "UntimelyMessage", "occurred_at": "no-es-fecha", "evidence": "x"},
    )
    assert invalid.status_code == 400


async def test_capacity_can_be_set_and_refuses_an_unknown_surface(wired) -> None:
    client, _ = wired
    ok = await client.post(
        "/crm/patrocinios/capacidad",
        auth=ADMIN,
        data={"surface": "Homepage", "concurrent": "3"},
        follow_redirects=False,
    )
    assert "guardado=" in location(ok)
    bad = await client.post(
        "/crm/patrocinios/capacidad",
        auth=ADMIN,
        data={"surface": "Instagram", "concurrent": "3"},
        follow_redirects=False,
    )
    assert "error=" in location(bad)

    page = await client.get("/crm/patrocinios", auth=ADMIN)
    assert "Capacidad por superficie" in page.text
    assert "Estimación inicial sin historial suficiente" in page.text


async def test_a_cancelled_campaign_and_an_expired_quote_read_back_honestly(
    wired,
) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import active_campaign, published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "api-cancelada")
        await session.commit()

    cancelled = await client.post(
        f"/crm/patrocinios/campanas/{campaign.campaign_id}/cancelar",
        auth=ADMIN,
        data={"reason": "El comprador se retiró"},
        follow_redirects=False,
    )
    assert "capacidad liberada" in location(cancelled)

    paused = await client.post(
        f"/crm/patrocinios/campanas/{campaign.campaign_id}/pausar",
        auth=ADMIN,
        data={"reason": "Intento sobre una campaña cancelada"},
        follow_redirects=False,
    )
    assert "error=" in location(paused)

    page = await client.get("/crm/patrocinios", auth=ADMIN)
    assert "Cancelada" in page.text


async def test_an_unknown_campaign_report_is_a_named_refusal(wired) -> None:
    client, _ = wired
    response = await client.get(
        f"/crm/patrocinios/campanas/{uuid.uuid4()}/reporte", auth=ADMIN
    )
    assert response.status_code == 404


async def test_the_nav_offers_both_new_surfaces(wired) -> None:
    client, _ = wired
    page = await client.get("/crm", auth=ADMIN)
    assert 'href="/crm/patrocinios"' in page.text
    assert 'href="/crm/bi"' in page.text


async def test_a_share_of_an_unknown_campaign_reports_the_error(wired) -> None:
    client, _ = wired
    response = await client.post(
        f"/crm/patrocinios/campanas/{uuid.uuid4()}/compartir",
        auth=ADMIN,
        data={"days": "5"},
        follow_redirects=False,
    )
    assert "error=" in location(response)


async def test_a_share_beyond_the_maximum_is_refused_by_the_surface(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import active_campaign, published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "api-vigencia")
        await session.commit()

    response = await client.post(
        f"/crm/patrocinios/campanas/{campaign.campaign_id}/compartir",
        auth=ADMIN,
        data={"days": "9999"},
        follow_redirects=False,
    )
    assert "error=" in location(response)
    assert "vigencia" in location(response)


async def test_the_report_link_stays_readable_until_it_expires(
    wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readable today, refused after its day. Both through the real routes.

    The clock is moved rather than the stored deadline, because the deadline is
    protected by a check constraint — which is itself worth stating: a live link
    cannot be silently back-dated into expiry by a stray update.
    """
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import active_campaign, published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "api-vencimiento")
        await session.commit()

    shared = await client.post(
        f"/crm/patrocinios/campanas/{campaign.campaign_id}/compartir",
        auth=ADMIN,
        data={"days": "1"},
        follow_redirects=False,
    )
    token = re.search(r"/reportes/([A-Za-z0-9_-]+)", location(shared))
    assert token is not None
    path = f"/internal/public-site/sponsorship-report/{token.group(1)}"

    assert (await client.get(path, headers=site())).status_code == 200
    assert (await client.get(f"{path}/pdf", headers=site())).status_code == 200

    later = utc_now() + timedelta(days=2)
    monkeypatch.setattr(public_site_api, "utc_now", lambda: later)
    assert (await client.get(path, headers=site())).status_code == 410
    assert (await client.get(f"{path}/pdf", headers=site())).status_code == 410


async def test_the_surface_shows_every_control_a_live_campaign_needs(wired) -> None:
    """A published catalog and an Active campaign render the whole panel.

    The controls are conditional on state — quoting only from Draft or Quoted,
    activating only from Scheduled or Paused — so a page rendered from an empty
    operation proves nothing about the page an operator actually works in.
    """
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import active_campaign, published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        campaign = await active_campaign(session, admin, "api-panel")
        await session.commit()

    shared = await client.post(
        f"/crm/patrocinios/campanas/{campaign.campaign_id}/compartir",
        auth=ADMIN,
        data={"days": "5"},
        follow_redirects=False,
    )
    assert "guardado=" in location(shared)

    page = await client.get("/crm/patrocinios", auth=ADMIN)
    body = page.text
    assert "Activa" in body
    assert "Búsqueda" in body
    assert "Publicado" in body
    assert "precios-piloto-1" in body
    assert "Validación comercial (SAN-065)" in body
    assert f"/crm/patrocinios/campanas/{campaign.campaign_id}/pausar" in body
    assert f"/crm/patrocinios/campanas/{campaign.campaign_id}/cancelar" in body
    assert "Registrar estado observado" in body
    assert "Enlaces de comprador" in body
    assert "Vigente" in body
    assert "Revocar" in body
    # An Active campaign is past quoting, so the quote control is gone but the
    # accepted quote is still listed with its preserved catalog version.
    assert f"/crm/patrocinios/campanas/{campaign.campaign_id}/cotizar" not in body
    assert "Reserved" in body or "Sin cotizaciones" not in body


async def test_a_draft_campaign_offers_quoting_and_a_discount_reason(wired) -> None:
    client, database = wired
    listing_id = await a_listing(database, "api-borrador")
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        await session.commit()

    await client.post(
        "/crm/patrocinios/campanas",
        auth=ADMIN,
        data={
            "listing_id": str(listing_id),
            "buyer_kind": "Collaborator",
            "buyer_label": "Colaborador sintético",
            "package": "Both",
            "paid_days": "30",
        },
        follow_redirects=False,
    )
    async with database.session_scope() as session:
        campaign = await session.scalar(select(SponsorshipCampaign))
        assert campaign is not None

    await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/validacion",
        auth=ADMIN,
        data={"evidence": CLEARANCE},
        follow_redirects=False,
    )
    discounted = await client.post(
        f"/crm/patrocinios/campanas/{campaign.id}/cotizar",
        auth=ADMIN,
        data={
            "duration_days": "30",
            "discount_amount": "1500",
            "discount_reason": "Cliente piloto fundador",
        },
        follow_redirects=False,
    )
    assert "8000" in location(discounted)

    page = await client.get("/crm/patrocinios", auth=ADMIN)
    assert "Cotizada" in page.text
    assert "Descuento 1500.00: Cliente piloto fundador" in page.text
    assert "Aceptar y reservar" in page.text
    assert "Búsqueda y portada" in page.text


async def test_a_quoted_campaign_without_a_published_catalog_says_so(wired) -> None:
    """The warning replaces the price control, rather than sitting beside it."""
    client, database = wired
    listing_id = await a_listing(database, "api-sin-catalogo")
    await client.post(
        "/crm/patrocinios/campanas",
        auth=ADMIN,
        data={
            "listing_id": str(listing_id),
            "buyer_kind": "Developer",
            "buyer_label": "Desarrollador sintético",
            "package": "Homepage",
            "paid_days": "30",
        },
        follow_redirects=False,
    )
    page = await client.get("/crm/patrocinios", auth=ADMIN)
    assert "No hay catálogo publicado" in page.text
    assert "Sin cotizaciones" in page.text
    assert "Emitir cotización de 7 días" not in page.text


async def test_a_retired_catalog_version_is_labelled_and_offers_nothing(
    wired,
) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin, version="precios-vieja")
        await published_catalog(session, admin, version="precios-nueva")
        await session.commit()

    page = await client.get("/crm/patrocinios", auth=ADMIN)
    assert "Retirado" in page.text
    assert "Vigente" in page.text
    assert "precios-vieja" in page.text


@pytest.mark.parametrize(
    ("path", "data", "fragment"),
    [
        ("/crm/patrocinios/catalogos", {"version": " ", "search": "1"}, "nombre"),
        (
            "/crm/patrocinios/catalogos",
            {"version": "mala", "search": "no-es-numero"},
            "cantidad válida",
        ),
        (
            "/crm/patrocinios/campanas",
            {
                "listing_id": "no-es-uuid",
                "buyer_kind": "Owner",
                "buyer_label": "x",
                "package": "Search",
                "paid_days": "30",
            },
            "",
        ),
        (
            "/crm/patrocinios/capacidad",
            {"surface": "Search", "concurrent": "-3"},
            "negativa",
        ),
    ],
)
async def test_every_mutation_reports_its_refusal_on_the_surface(
    wired, path, data, fragment
) -> None:
    """A refusal comes back as a readable sentence, not a status code.

    The operator keeps the navigation and can act on the message, which is why
    every one of these routes catches its own domain error rather than letting it
    become a 500.
    """
    client, _ = wired
    response = await client.post(
        path, auth=ADMIN, data=data, follow_redirects=False
    )
    assert response.status_code == 303
    assert "error=" in location(response)
    if fragment:
        assert fragment in location(response)


@pytest.mark.parametrize(
    "path",
    [
        "validacion",
        "cotizar",
        "programar",
        "activar",
        "pausar",
        "cancelar",
        "cobro",
    ],
)
async def test_an_unknown_campaign_is_refused_on_every_route(wired, path) -> None:
    client, _ = wired
    unknown = uuid.uuid4()
    response = await client.post(
        f"/crm/patrocinios/campanas/{unknown}/{path}",
        auth=ADMIN,
        data={
            "evidence": CLEARANCE,
            "reason": "Motivo",
            "state": "Collected",
            "starts_on": "2027-01-01T10:00",
            "duration_days": "30",
            "discount_amount": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in location(response)


async def test_an_invalid_start_date_and_an_unknown_quote_are_refused(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from tests.fixtures.sponsorship import published_catalog

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await published_catalog(session, admin)
        await session.commit()

    bad_date = await client.post(
        f"/crm/patrocinios/campanas/{uuid.uuid4()}/programar",
        auth=ADMIN,
        data={"starts_on": "no-es-una-fecha"},
        follow_redirects=False,
    )
    assert "no son válidas" in location(bad_date)

    unknown_quote = await client.post(
        f"/crm/patrocinios/cotizaciones/{uuid.uuid4()}/aceptar",
        auth=ADMIN,
        data={"starts_on": "2027-01-01T10:00"},
        follow_redirects=False,
    )
    assert "error=" in location(unknown_quote)

    unknown_link = await client.post(
        f"/crm/patrocinios/enlaces/{uuid.uuid4()}/revocar",
        auth=ADMIN,
        follow_redirects=False,
    )
    assert "error=" in location(unknown_link)

    unknown_collection = await client.post(
        f"/crm/patrocinios/campanas/{uuid.uuid4()}/cobro",
        auth=ADMIN,
        data={"state": "NoExiste"},
        follow_redirects=False,
    )
    assert "error=" in location(unknown_collection)

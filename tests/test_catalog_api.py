"""Authorization, honesty and accessibility of catalog administration."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import select

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    CatalogListing,
    ListingMedia,
    ListingOffer,
    OrganizationMember,
    Property,
    PropertyExpert,
)
from realestate.domain.catalog.storage import InMemoryMediaStorage
from tests.conftest import DATABASE_URL, requires_postgres, reset_property_inventory
from tests.fixtures import commercial

pytestmark = requires_postgres

ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)


def catalog_form(nonce: str = "catalog-api-create") -> dict[str, str]:
    return {
        "clave": nonce,
        "clave_inmueble": "casa-api",
        "nombre_inmueble": "Casa API",
        "tipo": "House",
        "procedencia_inmueble": "Declaración de administrador de prueba",
        "clave_publicacion": "casa-api-larevia",
        "titulo": "Casa API en Zapopan",
        "fuente_tipo": "Organization",
        "fuente_nombre": "Larevia",
        "atribucion": "Inventario propio",
        "ubicacion": "Zapopan, Jalisco",
        "procedencia_publicacion": "Captura administrativa de prueba",
        "operacion": "Sale",
        "precio": "11999999.99",
        "moneda": "MXN",
        "visibilidad": "Visible",
    }


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON", commercial.credentials_json()
    )
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset_property_inventory(session)
        await commercial.reset(session)
        await commercial.provision(session)

    app = create_app(get_settings())
    app.state.database = database
    app.state.media_storage = InMemoryMediaStorage()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app, database
    await database.dispose()


async def create_listing(client: httpx.AsyncClient) -> str:
    response = await client.post("/crm/catalogo", data=catalog_form(), auth=ADMIN)
    assert response.status_code == 303
    return response.headers["location"].split("/")[-1].split("?")[0]


async def test_catalog_requires_authentication_and_admin_for_mutation(wired) -> None:
    client, _, _ = wired

    assert (await client.get("/crm/catalogo")).status_code == 401
    assert (await client.get("/crm/catalogo/nueva", auth=ADVISOR)).status_code == 403
    assert (
        await client.post("/crm/catalogo", data=catalog_form(), auth=ADVISOR)
    ).status_code == 403


async def test_create_is_atomic_pending_and_idempotent(wired) -> None:
    client, _, database = wired

    first = await client.post("/crm/catalogo", data=catalog_form(), auth=ADMIN)
    replay = await client.post("/crm/catalogo", data=catalog_form(), auth=ADMIN)

    assert first.status_code == replay.status_code == 303
    assert first.headers["location"] == replay.headers["location"]
    async with database.session_scope() as session:
        properties = list(await session.scalars(select(Property)))
        listings = list(await session.scalars(select(CatalogListing)))
        offers = list(await session.scalars(select(ListingOffer)))
    assert len(properties) == len(listings) == len(offers) == 1
    assert properties[0].facts_review_state == "Pending"
    assert listings[0].authority == "Pending"
    assert listings[0].availability == "Unknown"
    assert listings[0].publication_state == "Draft"
    assert offers[0].terms_review_state == "Pending"
    assert offers[0].availability == "Unknown"


async def test_failed_publication_does_not_claim_success_or_change_state(wired) -> None:
    client, _, database = wired
    listing_id = await create_listing(client)

    response = await client.post(
        f"/crm/catalogo/{listing_id}/cambiar",
        data={"clave": "publish-before-ready", "accion": "publicacion", "estado": "Published"},
        auth=ADMIN,
    )

    assert response.status_code == 422
    assert "No se guardó el cambio" in response.text
    assert "El servidor confirmó el cambio" not in response.text
    assert "no está lista" in response.text
    async with database.session_scope() as session:
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None
        assert listing.publication_state == "Draft"


async def test_advisor_sees_only_expert_catalog_and_never_edit_forms(wired) -> None:
    client, _, database = wired
    listing_id = await create_listing(client)

    before = await client.get("/crm/catalogo", auth=ADVISOR)
    assert "Casa API" not in before.text
    async with database.session_scope() as session:
        listing = await session.get(CatalogListing, listing_id)
        admin = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADMIN_LOGIN
            )
        )
        advisor = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert listing is not None and listing.property_uuid is not None
        assert admin is not None and advisor is not None
        session.add(
            PropertyExpert(
                organization_id=listing.organization_id,
                property_uuid=listing.property_uuid,
                advisor_id=advisor.id,
                role="Primary",
                rank=0,
                designated_by=admin.id,
            )
        )
        await session.commit()

    page = await client.get(f"/crm/catalogo/{listing_id}", auth=ADVISOR)

    assert page.status_code == 200
    assert "Inmueble físico o modelo" in page.text
    assert "Publicación de fuente" in page.text
    assert "Ofertas: relación separada" in page.text
    assert "Tienes acceso de consulta como experto" in page.text
    assert "Guardar revisión física" not in page.text
    assert (
        await client.post(
            f"/crm/catalogo/{listing_id}/cambiar",
            data={"clave": "advisor-forbidden", "accion": "disponibilidad", "estado": "Available"},
            auth=ADVISOR,
        )
    ).status_code == 403


async def test_media_waits_for_storage_and_is_visible_after_redirect(wired) -> None:
    client, app, database = wired
    listing_id = await create_listing(client)

    response = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={
            "clave": "media-api-one",
            "accion": "agregar",
            "procedencia": "Fotografía del propietario",
            "evidencia": "Autorización escrita",
            "orden": "0",
            "portada": "1",
            "alta_resolucion": "1",
            "grupo": "Fachada",
        },
        files={"archivo": ("fachada.png", b"\x89PNG\r\n\x1a\nsynthetic", "image/png")},
        auth=ADMIN,
    )

    assert response.status_code == 303
    assert len(app.state.media_storage.objects) == 1
    async with database.session_scope() as session:
        media = (await session.scalars(select(ListingMedia))).one()
        assert media.is_cover
        assert media.authority == "Authorized"


async def test_catalog_shell_covers_mobile_keyboard_loading_and_empty_states(wired) -> None:
    client, _, _ = wired

    page = await client.get("/crm/catalogo", auth=ADMIN)

    assert page.status_code == 200
    assert 'lang="es-MX"' in page.text
    assert 'class="skip"' in page.text
    assert ":focus-visible" in page.text
    assert "@media (max-width:760px)" in page.text
    assert "Procesando…" in page.text
    assert "Espera la confirmación del servidor" in page.text
    assert "Todavía no hay publicaciones" in page.text
    assert "Catálogo" in page.text


async def test_complete_admin_workflow_uses_each_authoritative_command(wired) -> None:
    client, _, database = wired
    listing_id = await create_listing(client)
    async with database.session_scope() as session:
        listing = await session.get(CatalogListing, listing_id)
        assert listing is not None and listing.property_uuid is not None
        property_id = listing.property_uuid

    actions = (
        {"clave": "flow-physical", "accion": "revisar_inmueble", "estado": "Approved"},
        {"clave": "flow-listing", "accion": "revisar_publicacion", "estado": "Approved"},
        {"clave": "flow-available", "accion": "disponibilidad", "estado": "Available"},
        {
            "clave": "flow-authority",
            "accion": "autoridad",
            "estado": "Authorized",
            "evidencia": "Mandato vigente de prueba",
            "revalidar": "2030-08-28T12:00",
        },
        {
            "clave": "flow-offer",
            "accion": "oferta",
            "operacion": "Sale",
            "precio": "21000000",
            "moneda": "MXN",
            "visibilidad": "Hidden",
            "revision": "Approved",
            "disponibilidad": "Available",
        },
        {"clave": "flow-tier", "accion": "nivel", "nivel": "SuperPremium"},
        {"clave": "flow-ready", "accion": "readiness", "habilitado": "1"},
        {"clave": "flow-publish", "accion": "publicacion", "estado": "Published"},
    )
    for data in actions:
        response = await client.post(
            f"/crm/catalogo/{listing_id}/cambiar", data=data, auth=ADMIN
        )
        assert response.status_code == 303, response.text

    detail = await client.get(f"/crm/catalogo/{listing_id}?saved=1", auth=ADMIN)
    assert "El servidor confirmó el cambio" in detail.text
    assert "Precio oculto" in detail.text
    assert "Lista para publicar" in detail.text

    completed = await client.post(
        f"/crm/catalogo/{listing_id}/cambiar",
        data={"clave": "flow-complete", "accion": "concluir", "operacion": "Sale"},
        auth=ADMIN,
    )
    assert completed.status_code == 303
    async with database.session_scope() as session:
        listing = await session.get(CatalogListing, listing_id)
        prop = await session.get(Property, property_id)
        offer = (await session.scalars(select(ListingOffer))).one()
        assert listing is not None and listing.availability == "Sold"
        assert prop is not None and prop.facts_review_state == "Approved"
        assert offer.availability == "Completed"
        assert offer.price_amount == 21000000


async def test_media_can_be_reordered_recovered_and_revoked_from_the_ui(wired) -> None:
    client, app, database = wired
    listing_id = await create_listing(client)
    for index in range(2):
        response = await client.post(
            f"/crm/catalogo/{listing_id}/medios",
            data={
                "clave": f"media-arrange-{index}",
                "accion": "agregar",
                "procedencia": "Fotografía del propietario",
                "evidencia": "Autorización escrita",
                "orden": str(index),
                "portada": "1" if index == 0 else "0",
                "grupo": "Fachada" if index == 0 else "Sala",
            },
            files={
                "archivo": (
                    f"foto-{index}.jpg",
                    b"\xff\xd8\xff" + bytes([index]),
                    "image/jpeg",
                )
            },
            auth=ADMIN,
        )
        assert response.status_code == 303
    async with database.session_scope() as session:
        media = list(
            await session.scalars(select(ListingMedia).order_by(ListingMedia.sort_order))
        )
        first, second = media

    arranged = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={
            "clave": "media-arrange-save",
            "accion": "ordenar",
            "portada": str(second.id),
            f"orden_{first.id}": "1",
            f"grupo_{first.id}": "Exterior",
            f"orden_{second.id}": "0",
            f"grupo_{second.id}": "Interiores",
        },
        auth=ADMIN,
    )
    assert arranged.status_code == 303
    replay = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={
            "clave": "media-arrange-save",
            "accion": "ordenar",
            "portada": str(second.id),
            f"orden_{first.id}": "1",
            f"grupo_{first.id}": "Exterior",
            f"orden_{second.id}": "0",
            f"grupo_{second.id}": "Interiores",
        },
        auth=ADMIN,
    )
    assert replay.status_code == 303

    revoked = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={
            "clave": "media-revoke-ui",
            "accion": f"revocar:{first.id}",
        },
        auth=ADMIN,
    )
    assert revoked.status_code == 303
    page = await client.get(f"/crm/catalogo/{listing_id}", auth=ADMIN)
    assert "Medios revocados" in page.text
    assert "Limpieza completa" in page.text
    assert len(app.state.media_storage.objects) == 1


async def test_malformed_catalog_inputs_are_errors_not_successes(wired) -> None:
    client, _, _ = wired
    bad = catalog_form("catalog-bad-price")
    bad["precio"] = "no-es-precio"
    created = await client.post("/crm/catalogo", data=bad, auth=ADMIN)
    assert created.status_code == 422
    assert "No se guardó el cambio" in created.text

    non_finite = catalog_form("catalog-non-finite-price")
    non_finite["precio"] = "NaN"
    rejected = await client.post("/crm/catalogo", data=non_finite, auth=ADMIN)
    assert rejected.status_code == 422
    assert "precio no es válido" in rejected.text

    listing_id = await create_listing(client)
    new_page = await client.get("/crm/catalogo/nueva", auth=ADMIN)
    assert new_page.status_code == 200
    assert "Registrar inmueble y publicación" in new_page.text
    bad_date = await client.post(
        f"/crm/catalogo/{listing_id}/cambiar",
        data={
            "clave": "bad-date",
            "accion": "autoridad",
            "estado": "Pending",
            "revalidar": "mañana",
        },
        auth=ADMIN,
    )
    assert bad_date.status_code == 422
    assert "fecha de revalidación no es válida" in bad_date.text
    invalid_action = await client.post(
        f"/crm/catalogo/{listing_id}/cambiar",
        data={"clave": "bad-action", "accion": "inventada"},
        auth=ADMIN,
    )
    assert invalid_action.status_code == 422
    missing_upload = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={"clave": "bad-media-upload", "accion": "agregar"},
        auth=ADMIN,
    )
    assert missing_upload.status_code == 422
    assert "fotografía válida" in missing_upload.text
    invalid_media_action = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={"clave": "bad-media-action", "accion": "inventada"},
        auth=ADMIN,
    )
    assert invalid_media_action.status_code == 422
    assert "acción de medios no es válida" in invalid_media_action.text
    invalid_cover = await client.post(
        f"/crm/catalogo/{listing_id}/medios",
        data={
            "clave": "bad-media-cover",
            "accion": "ordenar",
            "portada": "no-es-uuid",
        },
        auth=ADMIN,
    )
    assert invalid_cover.status_code == 422
    assert "portada no es válido" in invalid_cover.text
    missing = await client.get(
        "/crm/catalogo/00000000-0000-0000-0000-000000000000", auth=ADMIN
    )
    assert missing.status_code == 404

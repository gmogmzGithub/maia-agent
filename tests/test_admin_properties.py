"""Manual, image-free Property administration against PostgreSQL."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import delete, select

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import AuditEvent, Property, PropertyDocumentVersion
from realestate.domain.properties import ArtifactStore, CatalogStore
from tests.conftest import (
    DATABASE_URL,
    provision_property_administrator,
    requires_postgres,
    reset_property_inventory,
)

pytestmark = requires_postgres

DEVELOPER = BasicAuth("developer", "test-developer-password")


def property_form(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "name": "Casa Manual",
        "property_type": "House",
        "operation": "Sale",
        "price_amount": "4500000",
        "price_currency": "MXN",
        "state": "Jalisco",
        "city": "Zapopan",
        "neighborhood": "Coto Demo",
        "half_bathrooms": "1",
        "parking_spaces": "2",
        "bedrooms": "3",
        "full_bathrooms": "2",
        "general_description": "Casa amplia para una familia.",
        "distribution": "Tres recámaras, sala, comedor y cocina.",
        "private_characteristics": ["Jardín privado", "Bodega"],
        "other_private_characteristic": "Calentador solar",
        "in_development": "true",
        "community_amenities": ["Alberca", "Seguridad 24 horas"],
        "maintenance_status": "Fee",
        "maintenance_amount": "1800",
        "maintenance_currency": "MXN",
        "maintenance_description": "Cuota mensual para vigilancia y áreas comunes.",
        "visit_address": "Calle Privada 123, Zapopan, Jalisco",
        "intent": "save",
    }
    values.update(overrides)
    return values


def land_property_form(**overrides: object) -> dict[str, object]:
    values = property_form(
        name="Terreno Manual",
        property_type="Land",
        price_amount="2161350",
        city="Zapopan",
        neighborhood="Valle Imperial",
        general_description="Terreno en venta en Valle Imperial coto Maple.",
        distribution="Frente regular y fondo aprovechable dentro del coto.",
        in_development="true",
        community_amenities=[
            "Alberca",
            "Área de juegos infantiles",
            "Salón de usos múltiples",
            "Seguridad 24 horas",
        ],
        maintenance_status="Unknown",
        land_m2="160.1",
        land_front_m="8.01",
        land_depth_m="20.01",
        visit_address="Coto Maple, Valle Imperial, Zapopan, Jalisco",
    )
    for key in (
        "bedrooms",
        "full_bathrooms",
        "half_bathrooms",
        "parking_spaces",
        "construction_m2",
        "floors",
        "year_built",
        "private_characteristics",
        "other_private_characteristic",
        "maintenance_amount",
        "maintenance_currency",
        "maintenance_description",
    ):
        values.pop(key, None)
    values.update(overrides)
    return values


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON",
        '{"developer":"test-developer-password"}',
    )
    get_settings.cache_clear()
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await reset_property_inventory(session)
        await session.execute(delete(AuditEvent))
        await session.commit()
        await provision_property_administrator(session)

    app = create_app(get_settings())
    app.state.database = database
    app.state.artifacts = ArtifactStore(tmp_path / "artifacts")
    app.state.property_catalog = CatalogStore(tmp_path / "catalog")
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, app, tmp_path
    await database.dispose()


async def test_every_admin_page_requires_basic_auth(wired) -> None:
    client, _, _ = wired
    for path in ("/admin/properties", "/admin/properties/new"):
        response = await client.get(path)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Basic"


async def test_new_property_form_has_the_approved_controls_and_no_images(wired) -> None:
    client, _, _ = wired

    response = await client.get("/admin/properties/new", auth=DEVELOPER)

    assert response.status_code == 200
    for label in (
        "Jardín",
        "Bodega",
        "Cisterna",
        "Paneles solares",
        "Estacionamiento techado",
        "Alberca privada",
        "Jardines comunes",
        "Seguridad 24 horas",
        "Otra amenidad",
        "Descripción del mantenimiento",
        "Superficie de terreno",
        "Frente en metros",
        "Fondo en metros",
    ):
        assert label in response.text
    assert 'type="file"' not in response.text
    assert "image_url" not in response.text
    assert 'id="property-name"' in response.text
    assert 'id="property-id"' in response.text
    assert "propertyName.addEventListener('input',updatePropertyId)" in response.text
    assert "[hidden] { display:none !important }" in response.text
    assert "fee.style.display=hasFee?'grid':'none'" in response.text
    assert "maintenanceDescription.required=hasFee" in response.text
    assert "maintenanceAmount.disabled=!hasFee" in response.text
    assert "maintenanceCurrency.disabled=!hasFee" in response.text
    assert "maintenanceDescription.disabled=!hasFee" in response.text
    assert "propertyType.addEventListener('change',toggle)" in response.text
    assert "setBlock(residentialMeasures,!isLand,'grid')" in response.text
    assert "setBlock(landMeasures,isLand,'grid')" in response.text
    assert "setBlock(privateCharacteristics,!isLand,'block')" in response.text


async def test_preview_generates_markdown_without_mutating_any_store(wired) -> None:
    client, app, tmp_path = wired

    response = await client.post(
        "/admin/properties",
        auth=DEVELOPER,
        data=property_form(intent="preview"),
    )

    assert response.status_code == 200
    assert "property_id: casa-manual" in response.text
    assert "Jardín privado" in response.text
    assert "## Amenidades del coto" in response.text
    preview = response.text.split('<textarea class="preview" readonly>', 1)[1].split(
        "</textarea>", 1
    )[0]
    assert "Calle Privada 123" not in preview
    async with app.state.database.session_scope() as session:
        assert (await session.execute(select(Property))).scalars().all() == []
    assert not (tmp_path / "catalog" / "casa-manual.md").exists()


async def test_create_accepts_version_one_active_and_writes_the_catalog(wired) -> None:
    client, app, tmp_path = wired

    response = await client.post(
        "/admin/properties", auth=DEVELOPER, data=property_form()
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/properties/casa-manual?saved=1"
    catalog = (tmp_path / "catalog" / "casa-manual.md").read_text()
    assert "property_id: casa-manual" in catalog
    assert "Jardín privado" in catalog
    assert "Calle Privada 123" not in catalog
    assert "source_url" not in catalog
    assert "image" not in catalog.casefold()
    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        version = (await session.execute(select(PropertyDocumentVersion))).scalar_one()
    assert prop.status == "Active"
    assert prop.inactive_reason is None
    assert prop.visit_address == "Calle Privada 123, Zapopan, Jalisco"
    assert version.version == 1


async def test_create_land_hides_residential_fields_from_the_document(wired) -> None:
    client, app, tmp_path = wired

    response = await client.post(
        "/admin/properties", auth=DEVELOPER, data=land_property_form()
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/properties/terreno-manual?saved=1"
    catalog = (tmp_path / "catalog" / "terreno-manual.md").read_text()
    assert "property_type: Land" in catalog
    assert "land_m2: 160.1" in catalog
    assert "land_front_m: 8.01" in catalog
    assert "land_depth_m: 20.01" in catalog
    assert "## Medidas del terreno" in catalog
    assert "half_bathrooms:" not in catalog
    assert "parking_spaces:" not in catalog
    assert "bedrooms:" not in catalog
    assert "full_bathrooms:" not in catalog
    assert "Características de la propiedad" not in catalog
    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
    assert prop.property_key == "terreno-manual"


async def test_duplicate_create_is_rejected_without_a_numeric_suffix(wired) -> None:
    client, _, tmp_path = wired
    await client.post("/admin/properties", auth=DEVELOPER, data=property_form())

    response = await client.post(
        "/admin/properties", auth=DEVELOPER, data=property_form()
    )

    assert response.status_code == 200
    assert "already exists" in response.text
    assert not (tmp_path / "catalog" / "casa-manual-1.md").exists()


async def test_edit_adds_a_version_keeps_the_id_and_updates_private_address(wired) -> None:
    client, app, tmp_path = wired
    await client.post("/admin/properties", auth=DEVELOPER, data=property_form())

    response = await client.post(
        "/admin/properties/casa-manual",
        auth=DEVELOPER,
        data=property_form(
            name="Casa Manual Renovada",
            price_amount="4750000",
            visit_address="Nueva dirección privada 456",
        ),
    )

    assert response.status_code == 303
    catalog = (tmp_path / "catalog" / "casa-manual.md").read_text()
    assert "name: Casa Manual Renovada" in catalog
    assert "price_amount: 4750000" in catalog
    assert "Nueva dirección privada" not in catalog
    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        versions = (
            await session.execute(
                select(PropertyDocumentVersion).order_by(PropertyDocumentVersion.version)
            )
        ).scalars().all()
    assert prop.property_key == "casa-manual"
    assert prop.visit_address == "Nueva dirección privada 456"
    assert [version.version for version in versions] == [1, 2]


async def test_inventory_can_deactivate_with_reason_and_reactivate(wired) -> None:
    client, app, _ = wired
    await client.post("/admin/properties", auth=DEVELOPER, data=property_form())

    response = await client.post(
        "/admin/properties/casa-manual/status",
        auth=DEVELOPER,
        data={"status": "Inactive", "inactive_reason": "Sold"},
    )
    assert response.status_code == 303
    inactive = await client.get("/admin/properties?view=inactive", auth=DEVELOPER)
    assert "Vendida" in inactive.text

    await client.post(
        "/admin/properties/casa-manual/status",
        auth=DEVELOPER,
        data={"status": "Active"},
    )
    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
    assert prop.status == "Active"
    assert prop.inactive_reason is None


async def test_inventory_detail_and_edit_render_the_current_property(wired) -> None:
    client, _, _ = wired
    await client.post("/admin/properties", auth=DEVELOPER, data=property_form())

    inventory = await client.get("/admin/properties", auth=DEVELOPER)
    detail = await client.get(
        "/admin/properties/casa-manual?saved=1", auth=DEVELOPER
    )
    edit = await client.get("/admin/properties/casa-manual/edit", auth=DEVELOPER)

    assert "Casa Manual" in inventory.text
    assert "Desactivar" in inventory.text
    assert "La propiedad y su nueva versión" in detail.text
    assert "Calle Privada 123" in detail.text
    assert "Documento aprobado" in detail.text
    assert "Editar propiedad" in edit.text
    assert "Casa amplia para una familia" in edit.text
    assert "Tres recámaras, sala, comedor y cocina" in edit.text


async def test_empty_inventory_invalid_view_and_unknown_property_are_safe(wired) -> None:
    client, _, _ = wired

    inventory = await client.get("/admin/properties?view=wrong", auth=DEVELOPER)
    detail = await client.get("/admin/properties/no-existe", auth=DEVELOPER)
    edit = await client.get("/admin/properties/no-existe/edit", auth=DEVELOPER)

    assert "No hay propiedades" in inventory.text
    assert "No se encontró" in detail.text
    assert "No se encontró" in edit.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "***"},
        {"price_amount": "not-a-number"},
    ],
)
async def test_invalid_structured_submission_changes_nothing(wired, overrides) -> None:
    client, app, _ = wired

    response = await client.post(
        "/admin/properties",
        auth=DEVELOPER,
        data=property_form(**overrides),
    )

    assert response.status_code == 200
    assert "No se guardó ningún cambio" in response.text
    async with app.state.database.session_scope() as session:
        assert (await session.execute(select(Property))).scalars().all() == []


async def test_non_development_submission_ignores_hidden_community_fields(wired) -> None:
    client, _, tmp_path = wired

    response = await client.post(
        "/admin/properties",
        auth=DEVELOPER,
        data=property_form(
            in_development="false",
            community_amenities=["Alberca"],
            other_community_amenity="Cancha oculta",
        ),
    )

    assert response.status_code == 303
    markdown = (tmp_path / "catalog" / "casa-manual.md").read_text()
    assert "Amenidades del coto" not in markdown
    assert "Cancha oculta" not in markdown


@pytest.mark.parametrize("status", ["None", "Unknown"])
async def test_non_fee_submission_ignores_hidden_maintenance_fields(wired, status: str) -> None:
    client, _, tmp_path = wired

    response = await client.post(
        "/admin/properties",
        auth=DEVELOPER,
        data=property_form(
            maintenance_status=status,
            maintenance_amount="",
            maintenance_currency="MXN",
            maintenance_description="",
        ),
    )

    assert response.status_code == 303
    markdown = (tmp_path / "catalog" / "casa-manual.md").read_text()
    assert f"maintenance_status: {status}" in markdown
    assert "maintenance_amount:" not in markdown
    assert "maintenance_currency:" not in markdown
    assert "maintenance_description:" not in markdown


async def test_edit_reports_missing_version_and_missing_artifact(wired) -> None:
    client, app, _ = wired
    await client.post("/admin/properties", auth=DEVELOPER, data=property_form())

    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        accepted_id = prop.accepted_version_id
        prop.accepted_version_id = None
        await session.commit()
    no_version = await client.get(
        "/admin/properties/casa-manual/edit", auth=DEVELOPER
    )
    assert "no tiene una versión aceptada" in no_version.text

    async with app.state.database.session_scope() as session:
        prop = (await session.execute(select(Property))).scalar_one()
        prop.accepted_version_id = accepted_id
        version = await session.get(PropertyDocumentVersion, accepted_id)
        Path(version.artifact_path).unlink()
        await session.commit()
    no_artifact = await client.get(
        "/admin/properties/casa-manual/edit", auth=DEVELOPER
    )
    assert "No se pudo leer el documento" in no_artifact.text

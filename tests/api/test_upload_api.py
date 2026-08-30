"""The Property Document upload page and endpoint (P-045, P-051, P-052)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import delete, select

from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import AgentRole, AuditEvent, Property
from realestate.domain.properties import ArtifactStore, CatalogStore, PropertyService
from tests.conftest import (
    DATABASE_URL,
    provision_property_administrator,
    requires_postgres,
    reset_property_inventory,
)
from tests.fixtures import commercial

FIXTURES = Path(__file__).parents[1] / "fixtures"
V1 = (FIXTURES / "casa-roble.md").read_bytes()
V2 = (FIXTURES / "casa-roble-v2.md").read_bytes()

pytestmark = requires_postgres

DEVELOPER = BasicAuth("developer", "test-developer-password")


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An HTTP client plus the app it drives, sharing one real database."""
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON",
        '{"developer":"test-developer-password"}',
    )
    monkeypatch.setenv("ORGANIZATION_ADMIN_LOGINS", "developer")
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
        yield client, app
    await database.dispose()


@pytest.fixture
def app_client(wired):
    return wired[0]


def upload(content: bytes, filename: str = "casa-roble.md") -> dict:
    return {"files": {"file": (filename, content, "text/markdown")}}


# --- Authentication ---------------------------------------------------------


async def test_the_page_requires_the_developer_credential(app_client) -> None:
    response = await app_client.get("/upload")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Basic"


async def test_a_wrong_credential_is_rejected(app_client) -> None:
    response = await app_client.get("/upload", auth=BasicAuth("developer", "wrong"))

    assert response.status_code == 401


async def test_the_endpoint_requires_the_credential_too(app_client) -> None:
    response = await app_client.post("/upload", **upload(V1))

    assert response.status_code == 401


async def test_the_authenticated_page_renders_a_drop_target(app_client) -> None:
    response = await app_client.get("/upload", auth=DEVELOPER)

    assert response.status_code == 200
    assert 'id="drop"' in response.text
    assert "text/html" in response.headers["content-type"]


async def test_no_cors_header_is_offered(app_client) -> None:
    response = await app_client.get(
        "/upload", auth=DEVELOPER, headers={"Origin": "http://evil.test"}
    )

    assert "access-control-allow-origin" not in response.headers


# --- Upload behaviour -------------------------------------------------------


async def test_a_valid_upload_is_accepted_and_reported(app_client) -> None:
    response = await app_client.post("/upload", auth=DEVELOPER, **upload(V1))

    assert response.status_code == 201
    assert "Casa Roble" in response.text
    assert "created" in response.text
    assert "Active" in response.text


async def test_a_malformed_upload_reports_field_level_errors(app_client) -> None:
    malformed = V1.replace(b"price_amount: 3000000", b"price_amount: not-a-number")

    response = await app_client.post("/upload", auth=DEVELOPER, **upload(malformed))

    assert response.status_code == 422
    assert "price_amount" in response.text
    assert "Nothing was changed" in response.text


async def test_a_malformed_replacement_leaves_the_accepted_version_intact(wired) -> None:
    client, app = wired
    await client.post("/upload", auth=DEVELOPER, **upload(V1))
    malformed = V2.replace(b"bedrooms: 4", b"bedrooms: cuatro")

    rejected = await client.post("/upload", auth=DEVELOPER, **upload(malformed))

    assert rejected.status_code == 422
    # The Sales Role still sees version 1 with its original price.
    async with app.state.database.session_scope() as session:
        organization = await commercial.organization_id(session)
        service = PropertyService(session, app.state.artifacts, organization_id=organization)
        current = await service.get_property_information("casa-roble", AgentRole.SALES)

    assert current["document_version"] == 1
    assert '"price": "3000000.00"' in current["document_markdown"]


async def test_a_valid_replacement_becomes_version_two(app_client) -> None:
    await app_client.post("/upload", auth=DEVELOPER, **upload(V1))

    response = await app_client.post("/upload", auth=DEVELOPER, **upload(V2))

    assert response.status_code == 201
    assert "replaced" in response.text
    assert "version 2" in response.text


async def test_a_non_markdown_file_is_rejected(app_client) -> None:
    response = await app_client.post(
        "/upload", auth=DEVELOPER, **upload(V1, filename="casa-roble.txt")
    )

    assert response.status_code == 422
    assert ".md" in response.text


async def test_a_rejected_upload_persists_nothing(wired) -> None:
    client, app = wired
    await client.post("/upload", auth=DEVELOPER, **upload(b"not a document"))

    async with app.state.database.session_scope() as session:
        count = len((await session.execute(select(Property.id))).all())
        audits = len((await session.execute(select(AuditEvent.id))).all())

    assert count == 0
    assert audits == 0


# --- No Developer credential configured --------------------------------------


async def test_an_unconfigured_developer_credential_is_a_503_not_an_open_page(
    app_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing credential must never degrade into "no authentication needed":
    this route is reachable while the webhook is exposed through the tunnel."""
    get_settings.cache_clear()
    monkeypatch.setenv("DEVELOPER_BASIC_CREDENTIALS_JSON", "")
    monkeypatch.setenv("DEVELOPER_BASIC_USER", "")

    response = await app_client.get("/upload", auth=DEVELOPER)

    assert response.status_code == 503
    assert "DEVELOPER_BASIC_USER" in response.json()["detail"]
    get_settings.cache_clear()


async def test_an_unconfigured_developer_password_is_a_503_too(
    app_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DEVELOPER_BASIC_CREDENTIALS_JSON", "")
    monkeypatch.setenv("DEVELOPER_BASIC_USER", "")
    monkeypatch.setenv("DEVELOPER_BASIC_PASSWORD", "")

    response = await app_client.post(
        "/upload", auth=DEVELOPER, **upload(V1)
    )

    assert response.status_code == 503
    get_settings.cache_clear()

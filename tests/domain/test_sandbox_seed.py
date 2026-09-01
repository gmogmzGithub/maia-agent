"""The synthetic walkthrough is explicit, stable and local-only."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from realestate.config import Settings
from realestate.db.engine import Database
from realestate.db.models import (
    CatalogListing,
    Contact,
    ListingMedia,
    Opportunity,
    PropertyNeed,
    ReactivationCandidate,
)
from realestate.domain.commercial.organization import DirectoryPlan, OrganizationDirectory
from realestate.domain.engagement.templates import TemplateObservation, TemplateRegistry
from realestate.sandbox_seed import (
    CRM_SEEDS,
    PROPERTY_SEEDS,
    require_local_sandbox,
    seed,
)
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial
from tests.fixtures.media import InMemoryMediaStorage


class ApprovedMarketingTemplates:
    configured = True

    async def list_templates(self) -> tuple[TemplateObservation, ...]:
        return (
            TemplateObservation(
                waba_id="waba-sandbox-test",
                provider_template_id="template-sandbox-test",
                name="nueva_coincidencia",
                language="es_MX",
                category="MARKETING",
                status="APPROVED",
                components=(
                    {
                        "type": "BODY",
                        "text": "Tenemos una opción nueva que coincide con tu búsqueda.",
                    },
                ),
                quality="GREEN",
                provider_api_version="v25.0",
            ),
        )


def settings(*, site: str, database: str) -> Settings:
    return Settings(
        _env_file=None,
        SITE_PUBLIC_ORIGIN=site,
        DATABASE_URL=database,
    )


def test_seed_definitions_are_unique_and_cover_the_complete_pipeline() -> None:
    assert len(PROPERTY_SEEDS) == 9
    assert len({row.key for row in PROPERTY_SEEDS}) == len(PROPERTY_SEEDS)
    assert len({row.name for row in PROPERTY_SEEDS}) == len(PROPERTY_SEEDS)
    assert len({row.wa_id for row in CRM_SEEDS}) == len(CRM_SEEDS)
    assert {row.target.value for row in CRM_SEEDS} >= {
        "InConversation",
        "Qualified",
        "Searching",
        "Visiting",
        "Negotiating",
        "Dormant",
        "Won",
        "Lost",
    }


def test_bootstrap_media_is_outside_site_source_and_complete() -> None:
    repository = Path(__file__).parents[2]
    bootstrap = repository / "bootstrap/sandbox/listing-media"

    assert not (repository / "src/realestate/site/assets/demo/properties").exists()
    assert len(tuple(bootstrap.glob("*.jpg"))) == 15
    assert (repository / "bootstrap/sandbox/LISTING-MEDIA-PROVENANCE.md").is_file()


def test_seed_requires_explicit_confirmation_and_loopback_services() -> None:
    local = settings(
        site="http://localhost:8080",
        database="postgresql+psycopg://realestate:realestate@db:5432/realestate",
    )
    require_local_sandbox(local, confirmed=True)
    with pytest.raises(RuntimeError, match="confirm-local-sandbox"):
        require_local_sandbox(local, confirmed=False)

    remote_site = settings(
        site="https://maia.example",
        database="postgresql+psycopg://realestate:realestate@db:5432/realestate",
    )
    with pytest.raises(RuntimeError, match="sitio no usa un origen local"):
        require_local_sandbox(remote_site, confirmed=True)

    remote_database = settings(
        site="http://localhost:8080",
        database="postgresql+psycopg://realestate:realestate@db.example:5432/realestate",
    )
    with pytest.raises(RuntimeError, match="PostgreSQL no es local"):
        require_local_sandbox(remote_database, confirmed=True)


@requires_postgres
async def test_seed_runs_the_complete_pipeline_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = Database(DATABASE_URL)
    storage = InMemoryMediaStorage()
    monkeypatch.setattr(
        "realestate.sandbox_seed.media_storage_from_settings",
        lambda _: storage,
    )
    configuration = Settings(
        _env_file=None,
        DATABASE_URL=DATABASE_URL,
        SITE_PUBLIC_ORIGIN="http://localhost:8080",
        ARTIFACT_ROOT=str(tmp_path / "artifacts"),
        PLATFORM_BOOTSTRAP_ORGANIZATION_SLUG="larevia",
    )
    try:
        async with database.session_scope() as session:
            await commercial.reset(session, members=True)
            await OrganizationDirectory(session).reconcile(
                DirectoryPlan(
                    administrators=("developer",),
                    advisors=("developer",),
                    default_advisor="developer",
                )
            )
            await commercial.bind_channels(session)
            await commercial.ensure_entitlements(session)
            actor = await OrganizationDirectory(session).resolve_actor("developer")
            await TemplateRegistry(session).synchronize(
                actor,
                ApprovedMarketingTemplates(),
            )
            await session.commit()

        first = await seed(configuration, confirmed=True)
        async with database.session_scope() as session:
            first_candidates = set(
                await session.execute(
                    select(Contact.display_name, CatalogListing.listing_key)
                    .join(PropertyNeed, PropertyNeed.contact_id == Contact.id)
                    .join(
                        ReactivationCandidate,
                        ReactivationCandidate.property_need_id == PropertyNeed.id,
                    )
                    .join(
                        CatalogListing,
                        CatalogListing.id == ReactivationCandidate.listing_id,
                    )
                )
            )
        second = await seed(configuration, confirmed=True)
        async with database.session_scope() as session:
            second_candidates = set(
                await session.execute(
                    select(Contact.display_name, CatalogListing.listing_key)
                    .join(PropertyNeed, PropertyNeed.contact_id == Contact.id)
                    .join(
                        ReactivationCandidate,
                        ReactivationCandidate.property_need_id == PropertyNeed.id,
                    )
                    .join(
                        CatalogListing,
                        CatalogListing.id == ReactivationCandidate.listing_id,
                    )
                )
            )

        assert first["properties_total"] == 9
        assert first["crm_contacts_total"] == 9
        assert second_candidates == first_candidates
        assert first["reactivation_candidates_total"] == len(first_candidates)
        assert first["reactivation_candidates_total"] == 5
        assert first["development_campaigns_total"] == 1
        assert first["sponsorship_campaigns_total"] == 1
        assert second["properties_created"] == 0
        assert second["reactivation_candidates_total"] == 5
        assert len(storage.objects) == 108
        async with database.session_scope() as session:
            assert await session.scalar(select(func.count()).select_from(CatalogListing)) == 9
            assert await session.scalar(select(func.count()).select_from(ListingMedia)) == 108
            assert await session.scalar(select(func.count()).select_from(Opportunity)) == 9
    finally:
        async with database.session_scope() as session:
            await commercial.reset(session, members=True)
        await database.dispose()

"""The synthetic walkthrough is explicit, stable and local-only."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

import realestate.sandbox_seed as sandbox_seed
from realestate.config import Settings
from realestate.db.engine import Database
from realestate.db.models import (
    CatalogListing,
    Contact,
    CriterionSource,
    CriterionState,
    InboxMessage,
    ListingMedia,
    Opportunity,
    OutboxMessage,
    PropertyNeed,
    PropertyNeedCriterion,
    ReactivationCandidate,
)
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
)
from realestate.domain.commercial.views import CommercialInbox, InboxFilters
from realestate.domain.engagement.templates import TemplateObservation, TemplateRegistry
from realestate.sandbox_seed import (
    CRM_SEEDS,
    PROPERTY_SEEDS,
    _criteria,
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
    for row in CRM_SEEDS:
        statements = _criteria(row)
        assert len(statements) == 5
        assert {statement.evidence for statement in statements} == {row.message}
        assert {statement.state for statement in statements} == {
            CriterionState.CONFIRMED
        }
        assert {statement.source for statement in statements} == {
            CriterionSource.CONTACT_STATED
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


def test_cli_uses_safe_defaults_and_reports_the_walkthrough(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configuration = object()
    received: dict[str, object] = {}

    async def fake_seed(settings, **options):  # noqa: ANN001, ANN202
        received.update(settings=settings, **options)
        return {
            "properties_total": 9,
            "crm_contacts_total": 9,
            "reactivation_candidates_total": 6,
            "development_campaigns_total": 1,
            "sponsorship_campaigns_total": 1,
            "appointments_total": 0,
            "meta_templates_observed": 0,
        }

    monkeypatch.setattr(sandbox_seed, "get_settings", lambda: configuration)
    monkeypatch.setattr(sandbox_seed, "seed", fake_seed)
    monkeypatch.setattr(
        sys, "argv", ["sandbox_seed", "--confirm-local-sandbox"]
    )

    sandbox_seed.main()

    assert received == {
        "settings": configuration,
        "confirmed": True,
        "book_calendar": False,
        "sync_meta_templates": False,
    }
    assert capsys.readouterr().out == (
        "Carga local confirmada: 9 propiedades, 9 contactos CRM, "
        "6 candidatos de reactivación, 1 campaña de desarrollo, "
        "1 campaña patrocinada y 0 cita de Calendar; "
        "0 plantillas observadas en Meta.\n"
    )


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
        assert first["reactivation_candidates_total"] == 6
        assert first["development_campaigns_total"] == 1
        assert first["sponsorship_campaigns_total"] == 1
        assert second["properties_created"] == 0
        assert second["reactivation_candidates_total"] == 6
        assert len(storage.objects) == 108
        async with database.session_scope() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CatalogListing))
                == 9
            )
            assert (
                await session.scalar(select(func.count()).select_from(ListingMedia))
                == 108
            )
            assert (
                await session.scalar(select(func.count()).select_from(Opportunity)) == 9
            )
            assert await session.scalar(
                select(func.count()).select_from(InboxMessage)
            ) == sum(len(row.inbound_messages) for row in CRM_SEEDS)
            assert await session.scalar(
                select(func.count()).select_from(OutboxMessage)
            ) == sum(row.reply is not None for row in CRM_SEEDS)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PropertyNeedCriterion)
                    .where(PropertyNeedCriterion.superseded_at.is_(None))
                )
                == len(CRM_SEEDS) * 5
            )
            actor = await OrganizationDirectory(session).resolve_actor("developer")
            awaiting = await CommercialInbox(session).query(
                actor, InboxFilters(needs_reply=True)
            )
            assert {entry.contact_name for entry in awaiting} == {
                "Demo · Alejandra Soto",
                "Demo · Paula Jiménez",
            }
    finally:
        async with database.session_scope() as session:
            await commercial.reset(session, members=True)
        await database.dispose()

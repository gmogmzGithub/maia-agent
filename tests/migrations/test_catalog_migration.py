"""Stage 4 catalog cut from the legacy Property Document model."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

MIGRATION_DATABASE = "realestate_catalog_migration_test"
STAGE_3_HEAD = "0019_appointment_authority"
HEAD = "0021_stage_three_query_indexes"


@pytest.fixture
def at_stage_three():
    with database_at_revision(MIGRATION_DATABASE, STAGE_3_HEAD) as harness:
        yield harness


def _scalar(engine, sql: str, **params: object):  # noqa: ANN001, ANN202
    with engine.begin() as connection:
        return connection.execute(text(sql), params).scalar()


def _rows(engine, sql: str, **params: object) -> list[tuple]:  # noqa: ANN001
    with engine.begin() as connection:
        return list(connection.execute(text(sql), params))


def _seed_legacy_property(engine) -> dict[str, uuid.UUID]:  # noqa: ANN001
    ids = {"property": uuid.uuid4(), "version": uuid.uuid4()}
    organization_id = _scalar(engine, "SELECT id FROM organizations WHERE slug='larevia'")
    metadata = (
        '{"schema_version":1,"property_id":"casa-legado",'
        '"name":"Casa Legado","property_type":"House",'
        '"operation":"Sale","price_amount":12500000,'
        '"price_currency":"MXN","state":"Jalisco",'
        '"city":"Zapopan","neighborhood":"Valle Real",'
        '"maintenance_status":"Unknown","in_development":false}'
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO properties "
                "(id, organization_id, property_key, name, normalized_name, status) "
                "VALUES (:id, :org, 'casa-legado', 'Casa Legado', "
                "'casa legado', 'Active')"
            ),
            {"id": ids["property"], "org": organization_id},
        )
        connection.execute(
            text(
                "INSERT INTO property_document_versions "
                "(id, property_uuid, version, checksum, artifact_path, byte_size, "
                "document_metadata) VALUES "
                "(:id, :property, 1, :checksum, '/legacy.md', 100, "
                "CAST(:metadata AS jsonb))"
            ),
            {
                "id": ids["version"],
                "property": ids["property"],
                "checksum": "a" * 64,
                "metadata": metadata,
            },
        )
        connection.execute(
            text("UPDATE properties SET accepted_version_id=:version WHERE id=:id"),
            {"version": ids["version"], "id": ids["property"]},
        )
    return ids


def test_empty_and_legacy_databases_converge_on_the_catalog_schema(
    at_stage_three,
) -> None:
    from alembic import command

    config, engine = at_stage_three
    command.upgrade(config, HEAD)
    assert _scalar(engine, "SELECT version_num FROM alembic_version") == HEAD
    for table in (
        "developments",
        "unit_models",
        "catalog_listings",
        "listing_offers",
        "listing_media",
    ):
        assert _scalar(engine, f"SELECT count(*) FROM {table}") == 0


def test_legacy_property_becomes_one_draft_listing_and_one_offer(
    at_stage_three,
) -> None:
    from alembic import command

    config, engine = at_stage_three
    ids = _seed_legacy_property(engine)
    command.upgrade(config, HEAD)

    listing = _rows(
        engine,
        "SELECT property_uuid, source_kind, availability, publication_state, "
        "authority, facts_review_state, automatic_tier, legacy_document_version_id "
        "FROM catalog_listings",
    )
    assert listing == [
        (
            ids["property"],
            "Organization",
            "Available",
            "Draft",
            "Authorized",
            "Approved",
            "Premium",
            ids["version"],
        )
    ]
    assert _rows(
        engine,
        "SELECT operation, price_amount, price_currency, price_visibility, "
        "availability FROM listing_offers",
    ) == [("Sale", 12500000, "MXN", "Visible", "Available")]


def test_catalog_cut_does_not_merge_physical_duplicates(at_stage_three) -> None:
    from alembic import command

    config, engine = at_stage_three
    _seed_legacy_property(engine)
    command.upgrade(config, HEAD)
    organization_id = _scalar(engine, "SELECT id FROM organizations WHERE slug='larevia'")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO properties "
                "(id, organization_id, property_key, name, normalized_name, status, "
                "property_type, physical_facts, facts_review_state, provenance) "
                "VALUES (:id, :org, 'casa-legado-otra', 'Casa Legado', "
                "'casa legado', 'Active', 'House', '{}'::jsonb, 'Pending', '{}'::jsonb)"
            ),
            {"id": uuid.uuid4(), "org": organization_id},
        )
    assert _scalar(engine, "SELECT count(*) FROM properties") == 2


def test_downgrade_preserves_the_legacy_source_and_reupgrade_is_idempotent(
    at_stage_three,
) -> None:
    from alembic import command

    config, engine = at_stage_three
    ids = _seed_legacy_property(engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, STAGE_3_HEAD)

    assert _scalar(engine, "SELECT id FROM properties") == ids["property"]
    assert _scalar(engine, "SELECT accepted_version_id FROM properties") == ids["version"]
    assert _scalar(engine, "SELECT to_regclass('public.catalog_listings')") is None

    command.upgrade(config, HEAD)
    assert _scalar(engine, "SELECT count(*) FROM catalog_listings") == 1
    assert _scalar(engine, "SELECT count(*) FROM listing_offers") == 1

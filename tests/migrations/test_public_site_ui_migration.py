"""The public UI migration never invents a publication date for old rows."""

from __future__ import annotations

import uuid

from alembic import command
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

PREVIOUS_HEAD = "0031_saved_phone_claim"
HEAD = "0032_public_site_ui"
MIGRATION_DATABASE = "realestate_public_site_ui_migration_test"


def test_existing_publication_keeps_an_unknown_first_publication_date() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        property_id = uuid.uuid4()
        listing_id = uuid.uuid4()
        with engine.begin() as connection:
            organization_id = connection.execute(
                text("SELECT id FROM organizations WHERE slug = 'larevia'")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO properties "
                    "(id, organization_id, property_key, name, normalized_name, "
                    "status, property_type, physical_facts, facts_review_state, "
                    "provenance) VALUES "
                    "(:id, :organization_id, 'migration-home', 'Casa migrada', "
                    "'casa migrada', 'Active', 'House', '{}'::jsonb, 'Approved', "
                    "'{}'::jsonb)"
                ),
                {"id": property_id, "organization_id": organization_id},
            )
            connection.execute(
                text(
                    "INSERT INTO catalog_listings "
                    "(id, organization_id, listing_key, property_uuid, source_kind, "
                    "source_name, attribution, title, facts_review_state, availability, "
                    "publication_state, authority, presentation_policy_version, "
                    "gallery_path, technical_sheet_path, created_by) VALUES "
                    "(:id, :organization_id, 'migration-home', :property_id, "
                    "'Organization', 'Larevia', 'Inventario propio', 'Casa migrada', "
                    "'Approved', 'Available', 'Published', 'Authorized', 'migration', "
                    "'/catalogo/migration-home/galeria', "
                    "'/catalogo/migration-home/ficha-tecnica', 'migration-test')"
                ),
                {
                    "id": listing_id,
                    "organization_id": organization_id,
                    "property_id": property_id,
                },
            )

        command.upgrade(config, HEAD)

        with engine.begin() as connection:
            first_published_at = connection.execute(
                text(
                    "SELECT first_published_at FROM catalog_listings WHERE id = :id"
                ),
                {"id": listing_id},
            ).scalar_one_or_none()
            indexed = connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'catalog_listings' "
                    "AND indexname = 'ix_catalog_listings_org_first_published'"
                )
            ).scalar_one()

        assert first_published_at is None
        assert indexed == "ix_catalog_listings_org_first_published"

        command.downgrade(config, PREVIOUS_HEAD)

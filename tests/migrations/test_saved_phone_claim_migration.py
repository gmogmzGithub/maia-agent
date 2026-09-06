"""The phone-claim migration preserves legacy collections without inventing PII."""

from __future__ import annotations

import uuid

from alembic import command
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

PREVIOUS_HEAD = "0030_meta_channels"
HEAD = "0031_saved_phone_claim"
MIGRATION_DATABASE = "realestate_saved_phone_claim_migration_test"


def test_legacy_collections_remain_unclaimed_and_new_claims_are_indexed() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        collection_id = uuid.uuid4()
        with engine.begin() as connection:
            organization_id = connection.execute(
                text("SELECT id FROM organizations LIMIT 1")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO saved_collections "
                    "(id, organization_id, access_token_hash) "
                    "VALUES (:id, :organization_id, :token)"
                ),
                {
                    "id": collection_id,
                    "organization_id": organization_id,
                    "token": "a" * 64,
                },
            )

        command.upgrade(config, HEAD)

        with engine.begin() as connection:
            legacy_claim = connection.execute(
                text(
                    "SELECT claimed_phone_number FROM saved_collections WHERE id = :id"
                ),
                {"id": collection_id},
            ).scalar_one_or_none()
            connection.execute(
                text(
                    "UPDATE saved_collections SET claimed_phone_number = :phone "
                    "WHERE id = :id"
                ),
                {"id": collection_id, "phone": "+523312345678"},
            )
            indexed = connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'saved_collections' "
                    "AND indexname = 'ix_saved_collections_claimed_phone'"
                )
            ).scalar_one()

        assert legacy_claim is None
        assert indexed == "ix_saved_collections_claimed_phone"

        command.downgrade(config, PREVIOUS_HEAD)

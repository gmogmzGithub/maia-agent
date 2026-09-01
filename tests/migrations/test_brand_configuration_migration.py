"""Existing Organization configuration is promoted to production vocabulary."""

from __future__ import annotations

import hashlib
import json

from alembic import command
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

PREVIOUS_HEAD = "0028_customer_market_intel"
HEAD = "0029_brand_config"
MIGRATION_DATABASE = "realestate_brand_configuration_migration_test"


@requires_postgres
def test_legacy_brand_configuration_is_canonicalized() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        legacy = {
            "brand": {"working_name": "Larevia"},
            "origin": "process-environment",
            "note": "Configuración inicial de la organización fundadora.",
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE organization_configuration_versions "
                    "SET document = CAST(:document AS jsonb), checksum = 'legacy'"
                ),
                {"document": json.dumps(legacy)},
            )

        command.upgrade(config, HEAD)

        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT document, checksum FROM "
                    "organization_configuration_versions WHERE is_current IS TRUE"
                )
            ).mappings().one()
        expected = {
            "brand": {"name": "Larevia"},
            "origin": "process-environment",
            "notes": {
                "bootstrap": "Configuración inicial de la organización fundadora."
            },
        }
        canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"))
        assert row["document"] == expected
        assert row["checksum"] == hashlib.sha256(canonical.encode()).hexdigest()

        command.downgrade(config, PREVIOUS_HEAD)

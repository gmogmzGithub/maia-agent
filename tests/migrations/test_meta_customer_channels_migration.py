"""The customer-channel migration preserves WhatsApp and admits Meta peers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import text

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

PREVIOUS_HEAD = "0029_brand_config"
HEAD = "0030_meta_channels"
MIGRATION_DATABASE = "realestate_meta_customer_channels_migration_test"
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def test_whatsapp_identity_is_backfilled_and_new_channels_are_accepted() -> None:
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as (config, engine):
        lead_id = uuid.uuid4()
        cycle_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        contact_id = uuid.uuid4()
        identity_id = uuid.uuid4()
        with engine.begin() as connection:
            organization_id = connection.execute(
                text("SELECT id FROM organizations LIMIT 1")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO leads "
                    "(id, organization_id, wa_id, follow_up_opt_out) "
                    "VALUES (:id, :organization_id, '5213312345678', false)"
                ),
                {"id": lead_id, "organization_id": organization_id},
            )
            connection.execute(
                text(
                    "INSERT INTO lead_engagement_cycles "
                    "(id, organization_id, lead_id, started_at, expires_at) "
                    "VALUES (:id, :organization_id, :lead_id, :started_at, :expires_at)"
                ),
                {
                    "id": cycle_id,
                    "organization_id": organization_id,
                    "lead_id": lead_id,
                    "started_at": NOW,
                    "expires_at": NOW + timedelta(days=30),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO conversations "
                    "(id, organization_id, lead_id, cycle_id, phone_number_id) "
                    "VALUES (:id, :organization_id, :lead_id, :cycle_id, 'phone-1')"
                ),
                {
                    "id": conversation_id,
                    "organization_id": organization_id,
                    "lead_id": lead_id,
                    "cycle_id": cycle_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO contacts (id, organization_id) "
                    "VALUES (:id, :organization_id)"
                ),
                {"id": contact_id, "organization_id": organization_id},
            )
            connection.execute(
                text(
                    "INSERT INTO contact_channel_identities "
                    "(id, organization_id, contact_id, channel, identity, trust, lead_id) "
                    "VALUES (:id, :organization_id, :contact_id, 'WhatsApp', "
                    "'5213312345678', 'Verified', :lead_id)"
                ),
                {
                    "id": identity_id,
                    "organization_id": organization_id,
                    "contact_id": contact_id,
                    "lead_id": lead_id,
                },
            )

        command.upgrade(config, HEAD)

        with engine.begin() as connection:
            lead = connection.execute(
                text(
                    "SELECT channel, channel_account_id FROM leads WHERE id = :id"
                ),
                {"id": lead_id},
            ).one()
            identity_account = connection.execute(
                text(
                    "SELECT channel_account_id FROM contact_channel_identities "
                    "WHERE id = :id"
                ),
                {"id": identity_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO organization_channel_bindings "
                    "(id, organization_id, kind, external_id, state, recorded_by) "
                    "VALUES (:id, :organization_id, 'FacebookPageId', 'page-1', "
                    "'Active', 'MigrationTest')"
                ),
                {"id": uuid.uuid4(), "organization_id": organization_id},
            )
        assert tuple(lead) == ("WhatsApp", "phone-1")
        assert identity_account == "phone-1"

        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM organization_channel_bindings "
                    "WHERE kind = 'FacebookPageId'"
                )
            )

        command.downgrade(config, PREVIOUS_HEAD)


def test_downgrade_refuses_to_discard_non_whatsapp_customer_data() -> None:
    with database_at_revision(MIGRATION_DATABASE, HEAD) as (config, engine):
        with engine.begin() as connection:
            organization_id = connection.execute(
                text("SELECT id FROM organizations LIMIT 1")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO leads "
                    "(id, organization_id, channel, channel_account_id, wa_id, "
                    "follow_up_opt_out) VALUES (:id, :organization_id, 'Instagram', "
                    "'ig-account-1', 'ig-user-1', false)"
                ),
                {"id": uuid.uuid4(), "organization_id": organization_id},
            )

        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            command.downgrade(config, PREVIOUS_HEAD)

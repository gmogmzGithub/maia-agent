"""Revisions 0012 and 0013 against an empty database and a legacy one.

The rest of the suite runs against a database migrated straight to head, which
proves the schema is reachable but not that Santiago's existing Stage 1
database survives the cut. This one starts at 0011, writes rows the old schema
allowed, and then moves in both directions.

What the backfill must *not* do is as important as what it does. It creates one
Contact per WhatsApp channel identity and one ``New`` Demand Opportunity per
Contact that already wrote in. It invents no identity — two Leads are never
merged — no consent, no advisor, and no stage past ``New``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import database_at_revision, requires_postgres

pytestmark = requires_postgres

MIGRATION_DATABASE = "realestate_commercial_migration_test"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

STAGE_1_HEAD = "0011_quarantine_legacy_outbound"
CONTACTS_REVISION = "0012_organization_and_contacts"
OPPORTUNITIES_REVISION = "0013_opportunities_and_actions"
HEAD = "0029_brand_config"


@pytest.fixture
def at_stage_one():
    """A database at revision 0011 — the state Stage 2 has to migrate."""
    with database_at_revision(MIGRATION_DATABASE, STAGE_1_HEAD) as harness:
        yield harness


def _seed_legacy(engine) -> dict[str, uuid.UUID]:  # noqa: ANN001
    """Two separate people, one with a thread, plus a Lead that never wrote.

    The two WhatsApp ids differ only by Mexico's optional mobile ``1``. A
    backfill that normalised them would produce one Contact, which is the
    failure this fixture exists to catch.
    """
    ids = {
        "with_thread": uuid.uuid4(),
        "look_alike": uuid.uuid4(),
        "silent": uuid.uuid4(),
        "cycle": uuid.uuid4(),
        "conversation": uuid.uuid4(),
        "inbox": uuid.uuid4(),
        "property": uuid.uuid4(),
    }
    with engine.begin() as connection:
        for key, wa_id, name in (
            ("with_thread", "5213312345678", "Ana"),
            ("look_alike", "523312345678", None),
            ("silent", "5213399990000", "Sin mensajes"),
        ):
            connection.execute(
                text(
                    "INSERT INTO leads (id, wa_id, profile_name, follow_up_opt_out,"
                    " created_at) VALUES (:id, :wa, :name, false, :created)"
                ),
                {
                    "id": ids[key],
                    "wa": wa_id,
                    "name": name,
                    "created": NOW - timedelta(days=10),
                },
            )
        connection.execute(
            text(
                "INSERT INTO lead_engagement_cycles (id, lead_id, started_at,"
                " expires_at) VALUES (:id, :lead, :started, :expires)"
            ),
            {
                "id": ids["cycle"],
                "lead": ids["with_thread"],
                "started": NOW - timedelta(days=10),
                "expires": NOW + timedelta(days=20),
            },
        )
        connection.execute(
            text(
                "INSERT INTO conversations (id, lead_id, cycle_id, phone_number_id,"
                " created_at) VALUES (:id, :lead, :cycle, '123456', :created)"
            ),
            {
                "id": ids["conversation"],
                "lead": ids["with_thread"],
                "cycle": ids["cycle"],
                "created": NOW - timedelta(days=10),
            },
        )
        connection.execute(
            text(
                "INSERT INTO inbox_messages (id, conversation_id, wamid, from_wa_id,"
                " message_type, text, sent_at, persisted_at, raw_message, status,"
                " attempts) VALUES (:id, :conversation, 'wamid.legacy', '5213312345678',"
                " 'text', 'Hola', :sent, :sent, '{}'::jsonb, 'Processed', 0)"
            ),
            {
                "id": ids["inbox"],
                "conversation": ids["conversation"],
                "sent": NOW - timedelta(days=10),
            },
        )
        connection.execute(
            text(
                "INSERT INTO properties (id, property_key, name, normalized_name,"
                " status) VALUES (:id, 'casa-legado', 'Casa Legado', 'casa legado',"
                " 'Active')"
            ),
            {"id": ids["property"]},
        )
    return ids


def _scalar(engine, sql: str, **params: object):  # noqa: ANN001, ANN202
    with engine.begin() as connection:
        return connection.execute(text(sql), params).scalar()


def _rows(engine, sql: str, **params: object) -> list[tuple]:  # noqa: ANN001
    with engine.begin() as connection:
        return list(connection.execute(text(sql), params))


# -- Empty database --------------------------------------------------------


def test_an_empty_database_upgrades_to_head(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    command.upgrade(config, HEAD)

    assert _scalar(engine, "SELECT version_num FROM alembic_version") == HEAD
    assert _scalar(engine, "SELECT count(*) FROM organizations") == 1
    assert _scalar(engine, "SELECT slug FROM organizations") == "larevia"
    # No people are invented: the directory is reconciled from configuration.
    assert _scalar(engine, "SELECT count(*) FROM organization_members") == 0
    for table in (
        "contacts",
        "contact_channel_identities",
        "property_needs",
        "property_need_criteria",
        "opportunities",
        "opportunity_origins",
        "opportunity_stage_transitions",
        "opportunity_assignments",
        "assignment_queue_entries",
        "next_actions",
        "opportunity_exceptions",
        "commercial_transactions",
        "commercial_command_receipts",
        "developments",
        "unit_models",
        "catalog_listings",
        "listing_offers",
        "listing_media",
        "external_listing_candidates",
        "external_offer_candidates",
        "inventory_source_health",
        "listing_revalidations",
    ):
        assert _scalar(engine, f"SELECT count(*) FROM {table}") == 0


def test_an_empty_database_downgrades_and_upgrades_again(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    command.upgrade(config, HEAD)
    command.downgrade(config, STAGE_1_HEAD)

    assert _scalar(engine, "SELECT version_num FROM alembic_version") == STAGE_1_HEAD
    assert _scalar(engine, "SELECT to_regclass('public.organizations')") is None
    assert _scalar(engine, "SELECT to_regclass('public.opportunities')") is None
    assert _scalar(engine, "SELECT to_regclass('public.leads')") is not None

    command.upgrade(config, HEAD)
    assert _scalar(engine, "SELECT count(*) FROM organizations") == 1


def test_the_revision_identifiers_fit_alembics_version_column(at_stage_one) -> None:
    """``alembic_version.version_num`` is ``varchar(32)``."""
    config, _engine = at_stage_one
    assert len(CONTACTS_REVISION) <= 32
    assert len(HEAD) <= 32
    assert config is not None


# -- Legacy database -------------------------------------------------------


def test_every_legacy_root_is_scoped_to_the_organization(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    _seed_legacy(engine)

    command.upgrade(config, HEAD)

    organization_id = _scalar(engine, "SELECT id FROM organizations")
    for table in ("leads", "conversations", "properties"):
        unscoped = _scalar(
            engine, f"SELECT count(*) FROM {table} WHERE organization_id IS NULL"
        )
        assert unscoped == 0
        assert (
            _scalar(
                engine,
                f"SELECT count(*) FROM {table} WHERE organization_id = :org",
                org=organization_id,
            )
            > 0
        )
    # The column is NOT NULL, so a later insert cannot skip it.
    nullable = _scalar(
        engine,
        "SELECT is_nullable FROM information_schema.columns"
        " WHERE table_name = 'leads' AND column_name = 'organization_id'",
    )
    assert nullable == "NO"


def test_each_legacy_lead_becomes_exactly_one_contact(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    ids = _seed_legacy(engine)

    command.upgrade(config, HEAD)

    assert _scalar(engine, "SELECT count(*) FROM contacts") == 3
    assert _scalar(engine, "SELECT count(*) FROM contact_channel_identities") == 3
    pairs = _rows(
        engine,
        "SELECT ci.identity, ci.trust, ci.lead_id, c.display_name"
        " FROM contact_channel_identities ci"
        " JOIN contacts c ON c.id = ci.contact_id ORDER BY ci.identity",
    )
    assert {row[0] for row in pairs} == {
        "523312345678",
        "5213312345678",
        "5213399990000",
    }
    assert {row[1] for row in pairs} == {"Verified"}
    # The WhatsApp profile name is carried across as a display hint only.
    by_identity = {row[0]: row[3] for row in pairs}
    assert by_identity["5213312345678"] == "Ana"
    assert by_identity["523312345678"] is None
    assert ids["look_alike"] in {row[2] for row in pairs}


def test_look_alike_numbers_are_not_merged_by_the_backfill(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    _seed_legacy(engine)

    command.upgrade(config, HEAD)

    contacts = _scalar(
        engine,
        "SELECT count(DISTINCT contact_id) FROM contact_channel_identities"
        " WHERE identity IN ('5213312345678', '523312345678')",
    )
    assert contacts == 2


def test_a_lead_with_history_gets_one_new_opportunity(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    ids = _seed_legacy(engine)

    command.upgrade(config, HEAD)

    rows = _rows(
        engine,
        "SELECT o.stage, o.kind, o.responsible_advisor_id, o.qualified_at,"
        " o.lost_reason, o.dormant_reason, org.source, org.channel,"
        " org.first_conversation_id, org.first_inbox_id"
        " FROM opportunities o"
        " JOIN opportunity_origins org ON org.opportunity_id = o.id",
    )
    assert len(rows) == 1
    (
        stage,
        kind,
        advisor,
        qualified_at,
        lost_reason,
        dormant_reason,
        source,
        channel,
        conversation_id,
        inbox_id,
    ) = rows[0]
    # ``New`` is the stage that asserts nothing.
    assert stage == "New"
    assert kind == "Demand"
    assert advisor is None
    assert qualified_at is None
    assert lost_reason is None
    assert dormant_reason is None
    assert source == "LegacyBackfill"
    assert channel == "WhatsApp"
    assert conversation_id == ids["conversation"]
    assert inbox_id == ids["inbox"]


def test_a_lead_that_never_wrote_gets_no_opportunity(at_stage_one) -> None:
    """There is no inquiry to represent."""
    from alembic import command

    config, engine = at_stage_one
    ids = _seed_legacy(engine)

    command.upgrade(config, HEAD)

    silent = _scalar(
        engine,
        "SELECT count(*) FROM opportunities o"
        " JOIN contact_channel_identities ci ON ci.contact_id = o.contact_id"
        " WHERE ci.lead_id = :lead",
        lead=ids["silent"],
    )
    assert silent == 0


def test_the_backfill_records_a_transition_that_explains_itself(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    _seed_legacy(engine)

    command.upgrade(config, HEAD)

    rows = _rows(
        engine,
        "SELECT from_stage, to_stage, reason, detail, actor_type, actor_id,"
        " command_key FROM opportunity_stage_transitions",
    )
    assert len(rows) == 1
    from_stage, to_stage, reason, detail, actor_type, actor_id, command_key = rows[0]
    assert from_stage is None
    assert to_stage == "New"
    assert reason == "LegacyBackfill"
    assert "No criteria, advisor, consent or later stage was inferred." in detail
    assert actor_type == "Migration"
    assert actor_id == OPPORTUNITIES_REVISION
    assert command_key.startswith("legacy-backfill:")


def test_the_backfill_invents_no_criteria_advisor_or_consent(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    _seed_legacy(engine)

    command.upgrade(config, HEAD)

    for table in (
        "property_needs",
        "property_need_criteria",
        "opportunity_assignments",
        "assignment_queue_entries",
        "next_actions",
        "opportunity_exceptions",
        "consent_records",
        "suppression_records",
    ):
        assert _scalar(engine, f"SELECT count(*) FROM {table}") == 0


def test_the_backfill_is_idempotent_across_a_downgrade_and_upgrade(
    at_stage_one,
) -> None:
    from alembic import command

    config, engine = at_stage_one
    _seed_legacy(engine)

    command.upgrade(config, HEAD)
    first = _scalar(engine, "SELECT count(*) FROM opportunities")
    command.downgrade(config, CONTACTS_REVISION)
    # Contacts survive the 0013 downgrade; only the Opportunity tables go.
    assert _scalar(engine, "SELECT count(*) FROM contacts") == 3
    command.upgrade(config, HEAD)

    assert _scalar(engine, "SELECT count(*) FROM opportunities") == first == 1
    assert _scalar(engine, "SELECT count(*) FROM contacts") == 3


def test_a_legacy_database_downgrades_back_to_stage_one(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    ids = _seed_legacy(engine)

    command.upgrade(config, HEAD)
    command.downgrade(config, STAGE_1_HEAD)

    assert _scalar(engine, "SELECT version_num FROM alembic_version") == STAGE_1_HEAD
    # The Stage 1 data the cut was applied to is untouched.
    assert _scalar(engine, "SELECT count(*) FROM leads") == 3
    assert _scalar(engine, "SELECT count(*) FROM conversations") == 1
    assert _scalar(engine, "SELECT count(*) FROM inbox_messages") == 1
    assert (
        _scalar(engine, "SELECT wa_id FROM leads WHERE id = :id", id=ids["with_thread"])
        == "5213312345678"
    )
    # The scoping columns and the new tables are gone.
    for table in ("organizations", "contacts", "opportunities", "next_actions"):
        assert _scalar(engine, f"SELECT to_regclass('public.{table}')") is None
    columns = {
        row[0]
        for row in _rows(
            engine,
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'leads'",
        )
    }
    assert "organization_id" not in columns


def test_the_content_expiry_columns_arrive_and_leave_with_the_cut(
    at_stage_one,
) -> None:
    from alembic import command

    config, engine = at_stage_one
    _seed_legacy(engine)

    command.upgrade(config, HEAD)
    for table in ("inbox_messages", "outbox_messages"):
        assert (
            _scalar(
                engine,
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = :table AND column_name = 'content_expired_at'",
                table=table,
            )
            == 1
        )
    # Existing rows are not marked expired by the migration.
    assert (
        _scalar(
            engine,
            "SELECT count(*) FROM inbox_messages WHERE content_expired_at IS NOT NULL",
        )
        == 0
    )

    command.downgrade(config, STAGE_1_HEAD)
    assert (
        _scalar(
            engine,
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'inbox_messages'"
            " AND column_name = 'content_expired_at'",
        )
        == 0
    )


def test_the_invariant_constraints_exist_after_the_upgrade(at_stage_one) -> None:
    """The races are guarded by the database, not only by the service layer."""
    from alembic import command

    config, engine = at_stage_one
    command.upgrade(config, HEAD)

    indexes = {
        row[0]
        for row in _rows(
            engine, "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        )
    }
    for name in (
        "uq_assignment_open",
        "uq_next_action_pending",
        "uq_assignment_queue_open",
        "uq_need_criterion_current",
        "uq_opportunity_exception_open",
        "uq_organization_default_advisor",
        "uq_appointments_active_reschedule",
        "uq_listing_media_cover",
        "uq_listing_media_order",
        "uq_listing_media_checksum",
    ):
        assert name in indexes, name

    constraints = {
        row[0]
        for row in _rows(
            engine,
            "SELECT conname FROM pg_constraint WHERE contype = 'c'",
        )
    }
    for name in (
        "ck_opportunities_lost_reason",
        "ck_opportunities_dormant_reason",
        "ck_opportunities_won_evidence",
        "ck_opportunities_qualified_stamp",
        "ck_next_actions_outcome",
        "ck_organization_members_advisor_advises",
    ):
        assert name in constraints, name

    exclusions = {
        row[0]
        for row in _rows(
            engine,
            "SELECT conname FROM pg_constraint WHERE contype = 'x'",
        )
    }
    assert "ex_appointments_calendar_overlap" in exclusions


def test_whatsapp_identity_is_unique_inside_each_organization(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    command.upgrade(config, HEAD)
    first_org = _scalar(engine, "SELECT id FROM organizations")
    second_org = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations (id, slug, display_name) "
                "VALUES (:id, 'otra', 'Otra')"
            ),
            {"id": second_org},
        )
        for organization_id in (first_org, second_org):
            connection.execute(
                text(
                    "INSERT INTO leads "
                    "(id, organization_id, wa_id, follow_up_opt_out, created_at) "
                    "VALUES (:id, :org, '5213312345678', false, :created)"
                ),
                {"id": uuid.uuid4(), "org": organization_id, "created": NOW},
            )

    assert _scalar(engine, "SELECT count(*) FROM leads") == 2
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO leads "
                    "(id, organization_id, wa_id, follow_up_opt_out, created_at) "
                    "VALUES (:id, :org, '5213312345678', false, :created)"
                ),
                {"id": uuid.uuid4(), "org": first_org, "created": NOW},
            )


def test_cross_organization_contact_identity_is_rejected(at_stage_one) -> None:
    from alembic import command

    config, engine = at_stage_one
    command.upgrade(config, HEAD)
    first_org = _scalar(engine, "SELECT id FROM organizations")
    second_org = uuid.uuid4()
    contact_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations (id, slug, display_name) "
                "VALUES (:id, 'otra', 'Otra')"
            ),
            {"id": second_org},
        )
        connection.execute(
            text(
                "INSERT INTO contacts (id, organization_id, created_at, updated_at) "
                "VALUES (:id, :org, :created, :created)"
            ),
            {"id": contact_id, "org": first_org, "created": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO leads "
                "(id, organization_id, wa_id, follow_up_opt_out, created_at) "
                "VALUES (:id, :org, '5213312345678', false, :created)"
            ),
            {"id": lead_id, "org": second_org, "created": NOW},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO contact_channel_identities "
                    "(id, organization_id, contact_id, channel, identity, trust, "
                    "lead_id, first_seen_at) VALUES "
                    "(:id, :org, :contact, 'WhatsApp', '5213312345678', "
                    "'Verified', :lead, :created)"
                ),
                {
                    "id": uuid.uuid4(),
                    "org": first_org,
                    "contact": contact_id,
                    "lead": lead_id,
                    "created": NOW,
                },
            )


def test_the_orm_metadata_matches_the_migrated_schema(at_stage_one) -> None:
    """Every mapped table and column exists after the upgrade.

    A model added without a migration passes every unit test and fails in
    Compose, so the comparison is worth making explicitly.

    Keyed on ``(schema, table)`` since Stage 8: the pseudonymous analytics
    tables live in their own PostgreSQL schema, and a comparison that read only
    ``public`` would report a mapped analytics table as missing while silently
    ignoring a real one that was.
    """
    from alembic import command

    from realestate.db.models import Base

    config, engine = at_stage_one
    command.upgrade(config, HEAD)

    actual: dict[tuple[str, str], set[str]] = {}
    for row in _rows(
        engine,
        "SELECT table_schema, table_name, column_name FROM"
        " information_schema.columns WHERE table_schema IN "
        "('public', 'analytics', 'market_intelligence')",
    ):
        actual.setdefault((row[0], row[1]), set()).add(row[2])

    for table in Base.metadata.tables.values():
        key = (table.schema or "public", table.name)
        assert key in actual, key
        expected = {column.name for column in table.columns}
        missing = expected - actual[key]
        assert not missing, (key, missing)

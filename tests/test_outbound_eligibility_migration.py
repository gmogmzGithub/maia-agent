"""Revision 0010 applied to a database that already holds real rows.

The rest of the suite runs against a database migrated straight to head, which
proves the schema is reachable but not that an *existing* Stage 0 database
survives the upgrade. This one starts at 0009, writes rows the old schema
allowed, and then moves in both directions.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.conftest import DATABASE_URL, REPO_ROOT, requires_postgres

pytestmark = requires_postgres

MIGRATION_DATABASE = "realestate_migration_test"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _url(database: str) -> str:
    return make_url(DATABASE_URL).set(database=database).render_as_string(
        hide_password=False
    )


def _recreate_database() -> str:
    import psycopg

    admin = _url("postgres").replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(
            f'DROP DATABASE IF EXISTS "{MIGRATION_DATABASE}" WITH (FORCE)'
        )
        connection.execute(f'CREATE DATABASE "{MIGRATION_DATABASE}"')
    return _url(MIGRATION_DATABASE)


def _alembic(url: str):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migrated():
    """A database at revision 0009 with legacy follow-up rows already in it."""
    from alembic import command

    from realestate.config import get_settings

    url = _recreate_database()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    config = _alembic(url)
    try:
        command.upgrade(config, "0009_property_administration")
        engine = create_engine(url, future=True)
        _seed_legacy(engine)
        yield config, engine
        engine.dispose()
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _insert_cycle(  # noqa: ANN201
    connection, wa_id: str, *, opt_out: bool = False  # noqa: ANN001
):
    """One Lead, engagement cycle and Conversation, at revision 0009."""
    lead_id, cycle_id, conversation_id = (uuid.uuid4() for _ in range(3))
    connection.execute(
        text(
            "INSERT INTO leads (id, wa_id, follow_up_opt_out, created_at) "
            "VALUES (:id, :wa_id, :opt_out, :now)"
        ),
        {"id": lead_id, "wa_id": wa_id, "opt_out": opt_out, "now": NOW},
    )
    connection.execute(
        text(
            "INSERT INTO lead_engagement_cycles "
            "(id, lead_id, started_at, expires_at, created_at) "
            "VALUES (:id, :lead, :now, :later, :now)"
        ),
        {
            "id": cycle_id,
            "lead": lead_id,
            "now": NOW,
            "later": NOW + timedelta(days=30),
        },
    )
    connection.execute(
        text(
            "INSERT INTO conversations "
            "(id, lead_id, cycle_id, phone_number_id, created_at) "
            "VALUES (:id, :lead, :cycle, '123456', :now)"
        ),
        {"id": conversation_id, "lead": lead_id, "cycle": cycle_id, "now": NOW},
    )
    return cycle_id, conversation_id


def _insert_outbox(connection, conversation_id, *, status: str) -> None:  # noqa: ANN001
    connection.execute(
        text(
            "INSERT INTO outbox_messages ("
            "id, conversation_id, idempotency_key, to_wa_id, kind, body, "
            "covered_inbox_ids, status, attempts, next_attempt_at, created_at"
            ") VALUES ("
            ":id, :conversation, :key, '5215550003333', 'LeadFollowUp', "
            "'mensaje heredado', '[]'::jsonb, :status, 0, :now, :now"
            ")"
        ),
        {
            "id": uuid.uuid4(),
            "conversation": conversation_id,
            "key": f"legacy:{status.casefold()}",
            "status": status,
            "now": NOW,
        },
    )


def _insert_followup(  # noqa: ANN201
    connection,  # noqa: ANN001
    cycle_id,  # noqa: ANN001
    conversation_id,  # noqa: ANN001
    *,
    day: int,
    status: str,
    policy_version: int | None = None,
):
    """One follow-up row, written against whichever revision is applied."""
    columns = "id, cycle_id, conversation_id, day_number, channel, due_at, status, created_at"
    values = ":id, :cycle, :conversation, :day, 'WhatsApp', :due, :status, :now"
    if policy_version is not None:
        columns += ", policy_id, policy_version"
        values += ", 'unanswered-inquiry', :version"
    connection.execute(
        text(f"INSERT INTO lead_followups ({columns}) VALUES ({values})"),
        {
            "id": uuid.uuid4(),
            "cycle": cycle_id,
            "conversation": conversation_id,
            "day": day,
            "status": status,
            "due": NOW,
            "now": NOW,
            "version": policy_version,
        },
    )


def _seed_legacy(engine) -> None:  # noqa: ANN001
    """Existing cadence, opt-out, and unsent Outbox state at revision 0009."""
    with engine.begin() as connection:
        cycle_id, conversation_id = _insert_cycle(connection, "5215550001111")
        _insert_followup(connection, cycle_id, conversation_id, day=18, status="Enqueued")
        _, opted_conversation = _insert_cycle(
            connection, "5215550003333", opt_out=True
        )
        _insert_outbox(connection, opted_conversation, status="Pending")
        _insert_outbox(connection, opted_conversation, status="Sending")


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        )
        return {row[0] for row in rows}


def _constraints(engine, table: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass)"
            ),
            {"table": table},
        )
        return {row[0] for row in rows}


def _indexes(engine, table: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :table"
            ),
            {"table": table},
        )
        return {row[0] for row in rows}


def test_upgrading_preserves_rows_and_labels_their_policy(migrated) -> None:
    from alembic import command

    config, engine = migrated

    command.upgrade(config, "0010_outbound_eligibility")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT day_number, status, policy_id, policy_version "
                "FROM lead_followups"
            )
        ).one()
    # Kept on the retired day it was actually chosen under, and labelled v1
    # rather than relabelled as the new hypothesis.
    assert row == (18, "Enqueued", "unanswered-inquiry", 1)


def test_upgrading_creates_the_eligibility_tables(migrated) -> None:
    from alembic import command

    config, engine = migrated

    command.upgrade(config, "0010_outbound_eligibility")

    with engine.connect() as connection:
        tables = {
            r[0]
            for r in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
    assert {
        "consent_records",
        "suppression_records",
        "outbound_decisions",
    } <= tables
    assert {"policy_id", "policy_version", "decision_id"} <= _columns(
        engine, "lead_followups"
    )


def test_eligibility_foreign_keys_and_hot_path_indexes_exist(migrated) -> None:
    from alembic import command

    config, engine = migrated
    command.upgrade(config, "0010_outbound_eligibility")

    with engine.connect() as connection:
        foreign_keys = {
            (row[0], row[1])
            for row in connection.execute(
                text(
                    "SELECT source.relname, target.relname "
                    "FROM pg_constraint c "
                    "JOIN pg_class source ON source.oid = c.conrelid "
                    "JOIN pg_class target ON target.oid = c.confrelid "
                    "WHERE c.contype = 'f' AND source.relname IN ("
                    "'consent_records', 'suppression_records', "
                    "'outbound_decisions', 'lead_followups')"
                )
            )
        }

    assert {
        ("consent_records", "leads"),
        ("suppression_records", "leads"),
        ("suppression_records", "inbox_messages"),
        ("outbound_decisions", "conversations"),
        ("outbound_decisions", "leads"),
        ("outbound_decisions", "outbox_messages"),
        ("lead_followups", "outbound_decisions"),
    } <= foreign_keys
    assert {
        "uq_outbound_decision_queued",
        "ix_outbound_decisions_lead",
    } <= _indexes(engine, "outbound_decisions")
    assert "uq_suppression_active" in _indexes(engine, "suppression_records")
    assert "ix_outbox_conversation_recent" in _indexes(engine, "outbox_messages")


def test_the_cadence_stops_being_a_database_constraint(migrated) -> None:
    """A versioned hypothesis must not need a migration to change."""
    from alembic import command

    config, engine = migrated
    assert "ck_lead_followups_day" in _constraints(engine, "lead_followups")

    command.upgrade(config, "0010_outbound_eligibility")

    assert "ck_lead_followups_day" not in _constraints(engine, "lead_followups")


def test_blocked_becomes_an_allowed_status(migrated) -> None:
    from alembic import command

    config, engine = migrated

    command.upgrade(config, "0010_outbound_eligibility")

    with engine.begin() as connection:
        cycle_id, conversation_id = connection.execute(
            text("SELECT cycle_id, conversation_id FROM lead_followups")
        ).one()
        _insert_followup(
            connection,
            cycle_id,
            conversation_id,
            day=3,
            status="Blocked",
            policy_version=2,
        )

    with engine.connect() as connection:
        blocked = connection.execute(
            text("SELECT count(*) FROM lead_followups WHERE status = 'Blocked'")
        ).scalar_one()
    assert blocked == 1


def test_head_quarantines_legacy_outbox_and_preserves_legacy_opt_out(migrated) -> None:
    from alembic import command

    config, engine = migrated
    command.upgrade(config, "head")

    with engine.connect() as connection:
        statuses = dict(
            connection.execute(
                text(
                    "SELECT idempotency_key, status FROM outbox_messages "
                    "WHERE idempotency_key LIKE 'legacy:%'"
                )
            ).all()
        )
        suppression = connection.execute(
            text(
                "SELECT reason FROM suppression_records s "
                "JOIN leads l ON l.id = s.lead_id "
                "WHERE l.wa_id = '5215550003333'"
            )
        ).scalar_one()
        consent = connection.execute(
            text(
                "SELECT state FROM consent_records c "
                "JOIN leads l ON l.id = c.lead_id "
                "WHERE l.wa_id = '5215550003333' AND c.category = 'Marketing'"
            )
        ).scalar_one()
        audits = connection.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE action = 'QuarantineLegacyOutbound'"
            )
        ).scalar_one()

    assert statuses == {
        "legacy:pending": "Failed",
        "legacy:sending": "DeliveryUnknown",
    }
    assert suppression == "LegacyFollowUpOptOut"
    assert consent == "Revoked"
    assert audits == 2


def test_downgrading_0011_does_not_reactivate_quarantined_rows(migrated) -> None:
    from alembic import command

    config, engine = migrated
    command.upgrade(config, "head")
    command.downgrade(config, "0010_outbound_eligibility")

    with engine.connect() as connection:
        statuses = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT status FROM outbox_messages "
                    "WHERE idempotency_key LIKE 'legacy:%'"
                )
            )
        }
    assert statuses == {"Failed", "DeliveryUnknown"}


def test_downgrading_restores_the_previous_schema(migrated) -> None:
    """Rows the old schema cannot express are removed, not mislabelled."""
    from alembic import command

    config, engine = migrated
    command.upgrade(config, "0010_outbound_eligibility")
    with engine.begin() as connection:
        cycle_id, conversation_id = connection.execute(
            text("SELECT cycle_id, conversation_id FROM lead_followups")
        ).one()
        # Day 7 belongs to both cadences and is ordinary history.
        # Day 3 exists only under v2, so the restored CHECK cannot hold it.
        # A Blocked row has no meaning at all under the old schema.
        for day in (7, 3):
            _insert_followup(
                connection,
                cycle_id,
                conversation_id,
                day=day,
                status="Enqueued",
                policy_version=2,
            )
        second_cycle, second_conversation = _insert_cycle(connection, "5215550002222")
        _insert_followup(
            connection,
            second_cycle,
            second_conversation,
            day=14,
            status="Blocked",
            policy_version=2,
        )

    command.downgrade(config, "0009_property_administration")

    with engine.connect() as connection:
        remaining = {
            r[0]
            for r in connection.execute(text("SELECT day_number FROM lead_followups"))
        }
        tables = {
            r[0]
            for r in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        }
    # Days 7 and 18 are expressible under the old schema and survive. Day 3 is
    # not, and neither is the Blocked row on the otherwise valid day 14.
    assert remaining == {7, 18}
    assert not {
        "consent_records",
        "suppression_records",
        "outbound_decisions",
    } & tables
    assert "ck_lead_followups_day" in _constraints(engine, "lead_followups")
    assert not {"policy_id", "policy_version", "decision_id"} & _columns(
        engine, "lead_followups"
    )

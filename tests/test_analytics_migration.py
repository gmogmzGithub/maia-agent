"""Stage 8 schema: additive, constrained, reversible, and schema-separated.

The analytics tables live in their own PostgreSQL schema so that a query written
against the commercial data cannot reach behavioural rows, and a query written
against measurement cannot reach a Contact. That separation is only real if the
migration actually creates it, so it is asserted here rather than assumed.
"""

from __future__ import annotations

import json

import pytest
from alembic import command
from sqlalchemy import inspect, text

from tests.conftest import database_at_revision, requires_postgres

PREVIOUS_HEAD = "0024_reactivation_campaigns"
HEAD = "0027_stage8_measurement_repairs"
MIGRATION_DATABASE = "realestate_analytics_migration_test"

ANALYTICS_TABLES = {
    "pseudonym_salts",
    "measurement_definitions",
    "analytics_outbox",
    "domain_events",
    "projection_runs",
    "funnel_aggregates",
}
SPONSORSHIP_TABLES = {
    "sponsorship_price_catalogs",
    "sponsorship_price_items",
    "sponsorship_surface_capacity",
    "sponsorship_campaigns",
    "sponsorship_quotes",
    "sponsorship_capacity_reservations",
    "sponsored_eligibility_records",
    "sponsorship_delivery_days",
    "sponsored_exposure_counters",
    "sponsorship_report_links",
    "sponsorship_contact_attributions",
    "harm_signals",
}


@pytest.fixture
def at_previous_head():
    with database_at_revision(MIGRATION_DATABASE, PREVIOUS_HEAD) as harness:
        yield harness


@requires_postgres
def test_the_schema_upgrades_downgrades_and_seeds_its_definitions(
    at_previous_head,
) -> None:
    config, engine = at_previous_head
    command.upgrade(config, HEAD)
    inspector = inspect(engine)

    assert ANALYTICS_TABLES <= set(inspector.get_table_names(schema="analytics"))
    assert SPONSORSHIP_TABLES <= set(inspector.get_table_names())
    # Deliberately separate: the commercial schema holds no analytics table.
    assert not ANALYTICS_TABLES & set(inspector.get_table_names())

    with engine.begin() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version"))
            .scalar_one()
        ) == HEAD
        # The counting rules are seeded by the migration, not written by
        # application code on first use: a report resolves its version from this
        # row, so it has to exist before the first event does.
        definition = connection.execute(
            text(
                "SELECT definition FROM analytics.measurement_definitions "
                "WHERE version = 'measurement-v1'"
            )
        ).scalar_one()
        stored = definition if isinstance(definition, dict) else json.loads(definition)
        assert stored["visible_impression"]["minimum_visible_fraction"] == 0.5
        assert stored["visible_impression"]["minimum_continuous_milliseconds"] == 1000
        assert stored["significant_gallery_exploration"] == {
            "minimum_photographs": 5,
            "minimum_gallery_fraction": 0.3,
        }
        assert stored["attribution"] == {
            "view_through_days": 7,
            "engaged_days": 90,
        }
        assert stored["session_daily_visible_impression_cap"] == 3

        # The reporting read path exists and is a materialized view.
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_matviews WHERE schemaname = 'analytics' "
                    "AND matviewname = 'mv_sponsored_delivery'"
                )
            ).scalar_one()
        ) == 1
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_sequences WHERE schemaname = 'analytics' "
                    "AND sequencename = 'analytics_outbox_sequence'"
                )
            ).scalar_one()
        ) == 1

    command.downgrade(config, PREVIOUS_HEAD)
    inspector = inspect(engine)
    assert not SPONSORSHIP_TABLES & set(inspector.get_table_names())
    assert "analytics" not in inspector.get_schema_names()
    # Stage 7 is untouched by the reversal.
    assert "development_campaigns" in set(inspector.get_table_names())


@requires_postgres
def test_definition_replays_with_equal_timestamps_can_downgrade_safely(
    at_previous_head,
) -> None:
    """The old identity keeps exactly one replay even when timestamps tie."""
    config, engine = at_previous_head
    command.upgrade(config, HEAD)
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT id FROM organizations WHERE slug = 'larevia'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO analytics.measurement_definitions "
                "(id, version, definition, effective_from) "
                "SELECT gen_random_uuid(), 'measurement-v2', definition, effective_from "
                "FROM analytics.measurement_definitions "
                "WHERE version = 'measurement-v1'"
            )
        )
        connection.execute(
            text(
                "INSERT INTO analytics.domain_events "
                "(id, sequence, organization_id, event_key, event_name, "
                "schema_version, taxonomy_version, definition_version, "
                "traffic_class, occurred_at, projected_at) VALUES "
                "(gen_random_uuid(), 9001, :organization_id, 'same-raw-event', "
                "'ListingOpened', 1, 'analytics-events-v1', 'measurement-v1', "
                "'Valid', '2026-08-29T00:00:00Z', '2026-08-29T01:00:00Z'), "
                "(gen_random_uuid(), 9002, :organization_id, 'same-raw-event', "
                "'ListingOpened', 1, 'analytics-events-v1', 'measurement-v2', "
                "'Valid', '2026-08-29T00:00:00Z', '2026-08-29T01:00:00Z')"
            ),
            {"organization_id": organization_id},
        )

    command.downgrade(config, "0026_managed_platform")
    with engine.begin() as connection:
        assert connection.execute(
            text(
                "SELECT count(*) FROM analytics.domain_events "
                "WHERE organization_id = :organization_id "
                "AND event_key = 'same-raw-event'"
            ),
            {"organization_id": organization_id},
        ).scalar_one() == 1


@requires_postgres
def test_the_constraints_refuse_the_states_the_modules_refuse(
    at_previous_head,
) -> None:
    """The database repeats the invariants the modules enforce.

    Not redundancy: a module can be bypassed by a migration, a script or a
    future code path, and these are the invariants where a bypassed write would
    be a commercial or measurement lie rather than a tidy-up.
    """
    from sqlalchemy.exc import IntegrityError

    config, engine = at_previous_head
    command.upgrade(config, HEAD)
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT id FROM organizations WHERE slug = 'larevia'")
        ).scalar_one()

    forbidden = [
        # A published catalog with no pilot evidence (SAN-062, ADR-0043).
        (
            "INSERT INTO sponsorship_price_catalogs (id, organization_id, version, "
            "status, currency) VALUES (gen_random_uuid(), :organization_id, 'x', "
            "'Published', 'MXN')"
        ),
        # An event class outside the declared taxonomy.
        (
            "INSERT INTO analytics.domain_events (id, sequence, organization_id, "
            "event_key, event_name, schema_version, taxonomy_version, "
            "definition_version, traffic_class, occurred_at, projected_at) VALUES "
            "(gen_random_uuid(), 1, :organization_id, 'k', 'MaiaStarted', 1, 'v', "
            "'measurement-v1', 'Suspicious', now(), now())"
        ),
        # Negative sellable capacity.
        (
            "INSERT INTO sponsorship_surface_capacity (id, organization_id, surface, "
            "concurrent_campaigns) VALUES (gen_random_uuid(), :organization_id, "
            "'Search', -1)"
        ),
        # A sponsored surface the delivery rules do not define.
        (
            "INSERT INTO sponsorship_surface_capacity (id, organization_id, surface, "
            "concurrent_campaigns) VALUES (gen_random_uuid(), :organization_id, "
            "'Instagram', 2)"
        ),
        # A harm signal outside the agreed stop conditions (SAN-079).
        (
            "INSERT INTO harm_signals (id, organization_id, kind, evidence, "
            "occurred_at, recorded_at, command_key) VALUES (gen_random_uuid(), "
            ":organization_id, 'BadVibes', 'e', now(), now(), 'k')"
        ),
        # An outbox row in a state the drain does not know.
        (
            "INSERT INTO analytics.analytics_outbox (id, organization_id, event_key, "
            "event_name, schema_version, taxonomy_version, occurred_at, status) "
            "VALUES (gen_random_uuid(), :organization_id, 'k2', 'MaiaStarted', 1, "
            "'v', now(), 'Halfway')"
        ),
    ]
    for statement in forbidden:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(statement), {"organization_id": organization_id}
                )

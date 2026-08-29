"""Add the analytics schema, versioned definitions and sponsorship commerce.

Revision ID: 0025_analytics_and_sponsorship
Revises: 0024_reactivation_campaigns
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0025_analytics_and_sponsorship"
down_revision: str | None = "0024_reactivation_campaigns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYTICS = "analytics"

# The initial measurement definition, seeded rather than written by application
# code on first use. A report reproduced later resolves its version from this
# table, so the row has to exist before the first event does.
MEASUREMENT_V1 = {
    "served_impression": {
        "rule": "PlacementRendered",
        "description": (
            "La posición patrocinada se entregó en la respuesta de la superficie."
        ),
    },
    "visible_impression": {
        "minimum_visible_fraction": 0.5,
        "minimum_continuous_milliseconds": 1000,
    },
    "significant_gallery_exploration": {
        "minimum_photographs": 5,
        "minimum_gallery_fraction": 0.3,
    },
    "funnel": [
        "SponsoredVisibleImpression",
        "ListingOpened",
        "GalleryOpened",
        "SignificantGalleryExploration",
        "SavedOrShared",
        "MaiaStarted",
        "WhatsAppHandoff",
        "AppointmentRequested",
        "AppointmentVerified",
        "AppointmentAttended",
        "OpportunityOutcomeKnown",
    ],
    "attribution": {"view_through_days": 7, "engaged_days": 90},
    "search_visible_results_per_sponsored": 6,
    "homepage_maximum_sponsored": 2,
    "session_daily_visible_impression_cap": 3,
    "comparable_minimum_sample": 3,
}


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {ANALYTICS}")

    op.create_table(
        "pseudonym_salts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id", "purpose", name="uq_pseudonym_salt_purpose"
        ),
        schema=ANALYTICS,
    )

    op.create_table(
        "measurement_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(length=40), nullable=False, unique=True),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        schema=ANALYTICS,
    )
    op.execute(
        sa.text(
            f"INSERT INTO {ANALYTICS}.measurement_definitions "
            "(id, version, definition, effective_from) VALUES "
            "(gen_random_uuid(), 'measurement-v1', CAST(:definition AS jsonb), "
            "TIMESTAMPTZ '2026-01-01 00:00:00+00')"
        ).bindparams(definition=json.dumps(MEASUREMENT_V1))
    )

    op.execute(f"CREATE SEQUENCE {ANALYTICS}.analytics_outbox_sequence AS BIGINT")
    op.create_table(
        "analytics_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sequence",
            sa.BigInteger(),
            nullable=False,
            unique=True,
            server_default=sa.text(f"nextval('{ANALYTICS}.analytics_outbox_sequence')"),
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("event_name", sa.String(length=60), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'Pending'"),
        ),
        sa.Column(
            "duplicate_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Projected', 'Rejected')",
            name="ck_analytics_outbox_status",
        ),
        schema=ANALYTICS,
    )
    op.create_index(
        "ix_analytics_outbox_drain",
        "analytics_outbox",
        ["status", "sequence"],
        schema=ANALYTICS,
    )

    op.create_table(
        "domain_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("event_name", sa.String(length=60), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=40), nullable=False),
        sa.Column("definition_version", sa.String(length=40), nullable=False),
        sa.Column("traffic_class", sa.String(length=20), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=60), nullable=True),
        sa.Column("subject_reference", sa.String(length=64), nullable=True),
        sa.Column("session_reference", sa.String(length=64), nullable=True),
        sa.Column("listing_id", UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", UUID(as_uuid=True), nullable=True),
        sa.Column("surface", sa.String(length=30), nullable=True),
        sa.Column("placement_position", sa.Integer(), nullable=True),
        sa.Column(
            "sponsored", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("attributes", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "traffic_class IN ('Valid', 'Bot', 'Internal', 'Test', 'Implausible')",
            name="ck_domain_events_traffic_class",
        ),
        schema=ANALYTICS,
    )
    for name, columns in (
        ("ix_domain_events_funnel", ["organization_id", "occurred_at", "event_name"]),
        ("ix_domain_events_campaign", ["campaign_id", "event_name", "occurred_at"]),
        ("ix_domain_events_sequence", ["sequence"]),
    ):
        op.create_index(name, "domain_events", columns, schema=ANALYTICS)

    op.create_table(
        "projection_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("definition_version", sa.String(length=40), nullable=False),
        sa.Column("from_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "projected_events", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "late_events", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "excluded_events", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "rebuilt_periods", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        schema=ANALYTICS,
    )
    op.create_index(
        "ix_projection_runs_version",
        "projection_runs",
        ["definition_version", "ran_at"],
        schema=ANALYTICS,
    )

    op.create_table(
        "funnel_aggregates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("definition_version", sa.String(length=40), nullable=False),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "grain", sa.String(length=10), nullable=False, server_default=sa.text("'day'")
        ),
        sa.Column("campaign_id", UUID(as_uuid=True), nullable=True),
        sa.Column("listing_id", UUID(as_uuid=True), nullable=True),
        sa.Column("surface", sa.String(length=30), nullable=True),
        sa.Column(
            "sponsored", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "excluded_counts", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "definition_version",
            "organization_id",
            "grain",
            "period_start",
            "campaign_id",
            "listing_id",
            "surface",
            "sponsored",
            name="uq_funnel_aggregate_cell",
        ),
        schema=ANALYTICS,
    )
    op.create_index(
        "ix_funnel_aggregates_read",
        "funnel_aggregates",
        ["definition_version", "organization_id", "period_start"],
        schema=ANALYTICS,
    )

    # The materialized view is the reporting read path: one row per campaign,
    # definition version and service date, with invalid traffic already
    # separated. Deliberately narrow — it exposes counts, never a reference to
    # anybody — so a report that reads only this view cannot leak identity.
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {ANALYTICS}.mv_sponsored_delivery AS
        SELECT
            event.organization_id,
            event.definition_version,
            event.campaign_id,
            event.listing_id,
            event.surface,
            date_trunc('day', event.occurred_at) AS service_date,
            count(*) FILTER (
                WHERE event.event_name = 'SponsoredServedImpression'
                  AND event.traffic_class = 'Valid'
            ) AS served_impressions,
            count(*) FILTER (
                WHERE event.event_name = 'SponsoredVisibleImpression'
                  AND event.traffic_class = 'Valid'
            ) AS visible_impressions,
            count(*) FILTER (
                WHERE event.event_name = 'ListingOpened'
                  AND event.traffic_class = 'Valid'
            ) AS listing_opens,
            count(*) FILTER (
                WHERE event.event_name = 'GalleryOpened'
                  AND event.traffic_class = 'Valid'
            ) AS gallery_opens,
            count(*) FILTER (
                WHERE event.event_name = 'SignificantGalleryExploration'
                  AND event.traffic_class = 'Valid'
            ) AS significant_explorations,
            count(*) FILTER (WHERE event.traffic_class <> 'Valid') AS invalid_events,
            count(DISTINCT event.session_reference) FILTER (
                WHERE event.event_name = 'SponsoredVisibleImpression'
                  AND event.traffic_class = 'Valid'
            ) AS visible_sessions
        FROM {ANALYTICS}.domain_events AS event
        WHERE event.campaign_id IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5, 6
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_mv_sponsored_delivery
        ON {ANALYTICS}.mv_sponsored_delivery (
            organization_id, definition_version, campaign_id, listing_id,
            surface, service_date
        )
        """
    )

    op.create_table(
        "sponsorship_price_catalogs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'Draft'"),
        ),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default=sa.text("'MXN'")
        ),
        sa.Column("pilot_evidence", sa.Text(), nullable=True),
        sa.Column(
            "published_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('Draft', 'Published', 'Retired')",
            name="ck_price_catalog_status",
        ),
        sa.CheckConstraint(
            "status <> 'Published' OR (pilot_evidence IS NOT NULL "
            "AND length(btrim(pilot_evidence)) > 0)",
            name="ck_price_catalog_pilot_evidence",
        ),
        sa.UniqueConstraint(
            "organization_id", "version", name="uq_price_catalog_version"
        ),
    )

    op.create_table(
        "sponsorship_price_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "catalog_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_price_catalogs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("package", sa.String(length=20), nullable=False),
        sa.Column(
            "duration_days", sa.Integer(), nullable=False, server_default=sa.text("30")
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "package IN ('Search', 'Homepage', 'Both')", name="ck_price_item_package"
        ),
        sa.CheckConstraint(
            "duration_days > 0 AND amount >= 0", name="ck_price_item_amounts"
        ),
        sa.UniqueConstraint(
            "catalog_id", "package", "duration_days", name="uq_price_item_package"
        ),
    )

    op.create_table(
        "sponsorship_surface_capacity",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(length=20), nullable=False),
        sa.Column("concurrent_campaigns", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "surface IN ('Search', 'Homepage')", name="ck_surface_capacity_surface"
        ),
        sa.CheckConstraint(
            "concurrent_campaigns >= 0", name="ck_surface_capacity_positive"
        ),
        sa.UniqueConstraint(
            "organization_id", "surface", name="uq_surface_capacity_surface"
        ),
    )

    op.create_table(
        "sponsorship_campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "listing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog_listings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("buyer_kind", sa.String(length=20), nullable=False),
        sa.Column("buyer_label", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'Draft'"),
        ),
        sa.Column("package", sa.String(length=20), nullable=False),
        sa.Column("paid_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column(
            "delivered_days", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("starts_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column(
            "price_currency",
            sa.String(length=3),
            nullable=False,
            server_default=sa.text("'MXN'"),
        ),
        sa.Column(
            "catalog_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_price_catalogs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "collection_state",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'NotInvoiced'"),
        ),
        sa.Column("collection_reference", sa.String(length=120), nullable=True),
        sa.Column("commercial_clearance", sa.Text(), nullable=True),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('Draft', 'Quoted', 'Reserved', 'Scheduled', 'Active', "
            "'Paused', 'Completed', 'Cancelled')",
            name="ck_sponsorship_campaign_status",
        ),
        sa.CheckConstraint(
            "package IN ('Search', 'Homepage', 'Both')",
            name="ck_sponsorship_campaign_package",
        ),
        sa.CheckConstraint(
            "buyer_kind IN ('Owner', 'Developer', 'Collaborator')",
            name="ck_sponsorship_campaign_buyer_kind",
        ),
        sa.CheckConstraint(
            "collection_state IN ('NotInvoiced', 'AwaitingPayment', 'Collected', "
            "'Waived', 'Uncollectible')",
            name="ck_sponsorship_campaign_collection",
        ),
        sa.CheckConstraint(
            "paid_days > 0 AND delivered_days >= 0 AND delivered_days <= paid_days",
            name="ck_sponsorship_campaign_days",
        ),
    )
    op.create_index(
        "ix_sponsorship_campaigns_work",
        "sponsorship_campaigns",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "sponsorship_quotes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "catalog_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_price_catalogs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("catalog_version", sa.String(length=40), nullable=False),
        sa.Column("package", sa.String(length=20), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("list_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "discount_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("discount_reason", sa.Text(), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default=sa.text("'MXN'")
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'Issued'"),
        ),
        sa.Column(
            "issued_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("command_key", sa.String(length=200), nullable=False),
        sa.CheckConstraint(
            "status IN ('Issued', 'Expired', 'Reserved', 'Cancelled')",
            name="ck_sponsorship_quote_status",
        ),
        sa.CheckConstraint(
            "discount_amount >= 0 AND list_amount >= 0 AND total_amount >= 0 "
            "AND total_amount = list_amount - discount_amount",
            name="ck_sponsorship_quote_amounts",
        ),
        sa.CheckConstraint(
            "discount_amount = 0 OR (discount_reason IS NOT NULL "
            "AND length(btrim(discount_reason)) > 0)",
            name="ck_sponsorship_quote_discount_reason",
        ),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_sponsorship_quote_command"
        ),
    )
    op.create_index(
        "ix_sponsorship_quotes_campaign",
        "sponsorship_quotes",
        ["campaign_id", "issued_at"],
    )

    op.create_table(
        "sponsorship_capacity_reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(length=20), nullable=False),
        sa.Column("starts_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_on", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "surface IN ('Search', 'Homepage')", name="ck_capacity_reservation_surface"
        ),
        sa.CheckConstraint("ends_on > starts_on", name="ck_capacity_reservation_range"),
        sa.UniqueConstraint(
            "campaign_id", "surface", name="uq_capacity_reservation_campaign_surface"
        ),
    )
    op.create_index(
        "ix_capacity_reservation_window",
        "sponsorship_capacity_reservations",
        ["organization_id", "surface", "starts_on", "ends_on"],
    )

    op.create_table(
        "sponsored_eligibility_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("surface", sa.String(length=20), nullable=True),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reasons", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("service_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('Daily', 'Exposure')", name="ck_eligibility_scope"),
        sa.UniqueConstraint(
            "campaign_id", "scope", "service_date", name="uq_eligibility_daily"
        ),
    )
    op.create_index(
        "ix_eligibility_records_campaign",
        "sponsored_eligibility_records",
        ["campaign_id", "decided_at"],
    )

    op.create_table(
        "sponsorship_delivery_days",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=False),
        sa.UniqueConstraint("campaign_id", "service_date", name="uq_delivery_day"),
    )

    op.create_table(
        "sponsored_exposure_counters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "listing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog_listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_reference", sa.String(length=64), nullable=False),
        sa.Column("service_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "visible_impressions", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.UniqueConstraint(
            "listing_id",
            "session_reference",
            "service_date",
            name="uq_sponsored_exposure_counter",
        ),
    )

    op.create_table(
        "sponsorship_report_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sponsorship_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(length=64), nullable=False, unique=True),
        sa.Column("definition_version", sa.String(length=40), nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("expires_at > created_at", name="ck_report_link_expiry"),
    )
    op.create_index(
        "ix_report_links_campaign",
        "sponsorship_report_links",
        ["campaign_id", "created_at"],
    )

    op.create_table(
        "harm_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recorded_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("command_key", sa.String(length=200), nullable=False),
        sa.CheckConstraint(
            "kind IN ('WrongInformation', 'Complaint', 'UntimelyMessage', "
            "'AssignmentFailure', 'IncorrectAppointment', 'OperationalOverload')",
            name="ck_harm_signal_kind",
        ),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_harm_signal_command"
        ),
    )
    op.create_index(
        "ix_harm_signals_period",
        "harm_signals",
        ["organization_id", "occurred_at", "kind"],
    )


def downgrade() -> None:
    for table in (
        "harm_signals",
        "sponsorship_report_links",
        "sponsored_exposure_counters",
        "sponsorship_delivery_days",
        "sponsored_eligibility_records",
        "sponsorship_capacity_reservations",
        "sponsorship_quotes",
        "sponsorship_campaigns",
        "sponsorship_surface_capacity",
        "sponsorship_price_items",
        "sponsorship_price_catalogs",
    ):
        op.drop_table(table)
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {ANALYTICS}.mv_sponsored_delivery")
    for table in (
        "funnel_aggregates",
        "projection_runs",
        "domain_events",
        "analytics_outbox",
        "measurement_definitions",
        "pseudonym_salts",
    ):
        op.drop_table(table, schema=ANALYTICS)
    op.execute(f"DROP SEQUENCE IF EXISTS {ANALYTICS}.analytics_outbox_sequence")
    op.execute(f"DROP SCHEMA IF EXISTS {ANALYTICS}")

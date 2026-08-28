"""Add read-only external inventory candidates and revalidation history.

Revision ID: 0023_external_inventory
Revises: 0022_public_site
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0023_external_inventory"
down_revision: str | None = "0022_public_site"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_listing_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_listing_id", sa.String(length=120), nullable=False),
        sa.Column("source_scope", sa.String(length=20), nullable=False),
        sa.Column("source_status", sa.String(length=40), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_checksum", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("public_location", sa.String(length=500), nullable=True),
        sa.Column("municipality", sa.String(length=80), nullable=True),
        sa.Column("location_precision", sa.String(length=20), nullable=False),
        sa.Column("property_type", sa.String(length=80), nullable=True),
        sa.Column("facts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("availability", sa.String(length=30), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("source_agency", sa.String(length=300), nullable=True),
        sa.Column("source_agent", sa.String(length=300), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("authority_state", sa.String(length=20), nullable=False),
        sa.Column("authority_evidence", sa.Text(), nullable=True),
        sa.Column("collaboration_authorized", sa.Boolean(), nullable=True),
        sa.Column("commission_known", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("commission", JSONB(), nullable=True),
        sa.Column("commercial_review_state", sa.String(length=20), nullable=False),
        sa.Column("mapping_issues", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("changed_fields", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cache_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source_scope IN ('Organization', 'Collaborator')", name="ck_external_candidates_scope"),
        sa.CheckConstraint("location_precision IN ('Exact', 'Approximate', 'Unknown')", name="ck_external_candidates_location_precision"),
        sa.CheckConstraint("availability IN ('Available', 'Reserved', 'Sold', 'Rented', 'TemporarilyUnavailable', 'Unknown')", name="ck_external_candidates_availability"),
        sa.CheckConstraint("authority_state IN ('Authorized', 'Pending', 'Denied')", name="ck_external_candidates_authority"),
        sa.CheckConstraint("commercial_review_state IN ('Pending', 'Approved', 'NeedsReview')", name="ck_external_candidates_commercial_review"),
        sa.CheckConstraint("(withdrawn_at IS NULL AND deletion_due_at IS NULL) OR (withdrawn_at IS NOT NULL AND deletion_due_at IS NOT NULL)", name="ck_external_candidates_withdrawal_deadline"),
        sa.UniqueConstraint("organization_id", "source", "source_listing_id", name="uq_external_candidates_source_identity"),
        sa.UniqueConstraint("organization_id", "id", name="uq_external_candidates_org_id"),
    )
    op.create_index(
        "ix_external_candidates_search",
        "external_listing_candidates",
        ["organization_id", "source", "municipality", "authority_state", "availability"],
    )
    op.create_index(
        "ix_external_candidates_cleanup",
        "external_listing_candidates",
        ["deletion_due_at"],
        postgresql_where=sa.text("cache_deleted_at IS NULL"),
    )

    op.create_table(
        "external_offer_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_candidate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_offer_key", sa.String(length=120), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=True),
        sa.Column("price_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_currency", sa.String(length=12), nullable=True),
        sa.Column("price_unit", sa.String(length=40), nullable=True),
        sa.Column("availability", sa.String(length=30), nullable=False),
        sa.Column("terms", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(
            ["organization_id", "listing_candidate_id"],
            ["external_listing_candidates.organization_id", "external_listing_candidates.id"],
            ondelete="CASCADE",
            name="fk_external_offers_candidate_org",
        ),
        sa.CheckConstraint("operation IS NULL OR operation IN ('Sale', 'Rental', 'Presale')", name="ck_external_offers_operation"),
        sa.CheckConstraint("price_amount IS NULL OR price_amount > 0", name="ck_external_offers_price"),
        sa.CheckConstraint("availability IN ('Available', 'Reserved', 'Completed', 'TemporarilyUnavailable', 'Withdrawn', 'Unknown')", name="ck_external_offers_availability"),
        sa.UniqueConstraint("listing_candidate_id", "source_offer_key", name="uq_external_offers_source_key"),
    )
    op.create_index("ix_external_offers_listing", "external_offer_candidates", ["listing_candidate_id", "availability"])

    op.create_table(
        "inventory_source_health",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("credential_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mls_access_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retention_permission_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cursor", sa.String(length=120), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rate_limited_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('Disabled', 'NeverSynced', 'Healthy', 'Partial', 'RateLimited', 'Failed')", name="ck_inventory_source_health_status"),
        sa.CheckConstraint("fetched_count >= 0 AND accepted_count >= 0 AND rejected_count >= 0", name="ck_inventory_source_health_counts"),
        sa.UniqueConstraint("organization_id", "source", name="uq_inventory_source_health"),
    )

    op.create_table(
        "listing_revalidations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_candidate_id", UUID(as_uuid=True), nullable=False),
        sa.Column("intended_action", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reasons", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "listing_candidate_id"],
            ["external_listing_candidates.organization_id", "external_listing_candidates.id"],
            ondelete="CASCADE",
            name="fk_listing_revalidations_candidate_org",
        ),
        sa.CheckConstraint("intended_action IN ('Recommend', 'Share', 'Appointment')", name="ck_listing_revalidations_action"),
        sa.CheckConstraint("outcome IN ('Eligible', 'Pending', 'Denied')", name="ck_listing_revalidations_outcome"),
    )
    op.create_index("ix_listing_revalidations_candidate", "listing_revalidations", ["listing_candidate_id", "evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_listing_revalidations_candidate", table_name="listing_revalidations")
    op.drop_table("listing_revalidations")
    op.drop_table("inventory_source_health")
    op.drop_index("ix_external_offers_listing", table_name="external_offer_candidates")
    op.drop_table("external_offer_candidates")
    op.drop_index("ix_external_candidates_cleanup", table_name="external_listing_candidates")
    op.drop_index("ix_external_candidates_search", table_name="external_listing_candidates")
    op.drop_table("external_listing_candidates")

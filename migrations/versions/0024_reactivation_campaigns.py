"""Add reviewed reactivation, campaigns and provider template evidence.

Revision ID: 0024_reactivation_campaigns
Revises: 0023_external_inventory
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0024_reactivation_campaigns"
down_revision: str | None = "0023_external_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_decisions",
        sa.Column("template_language", sa.String(length=20), nullable=True),
    )
    for name, type_ in (
        ("business_name", sa.String(length=200)),
        ("scope", sa.String(length=120)),
        ("notice_version", sa.String(length=80)),
        ("evidence_locator", sa.String(length=240)),
        ("expires_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("consent_records", sa.Column(name, type_, nullable=True))

    op.create_table(
        "approved_message_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("waba_id", sa.String(length=80), nullable=False),
        sa.Column("provider_template_id", sa.String(length=120), nullable=True),
        sa.Column("template_name", sa.String(length=120), nullable=False),
        sa.Column("language_code", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("provider_status", sa.String(length=20), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("quality", sa.String(length=30), nullable=True),
        sa.Column("component_checksum", sa.String(length=64), nullable=False),
        sa.Column("provider_api_version", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
            "category IN ('Marketing', 'Utility', 'Service')",
            name="ck_message_templates_category",
        ),
        sa.CheckConstraint(
            "provider_status IN ('Approved', 'Pending', 'Rejected', 'Paused', "
            "'Disabled', 'Deleted')",
            name="ck_message_templates_status",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "template_name",
            "language_code",
            name="uq_message_templates_identity",
        ),
    )
    op.create_index(
        "ix_message_templates_approved",
        "approved_message_templates",
        ["organization_id", "provider_status", "category"],
    )

    op.create_table(
        "reactivation_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_need_id",
            UUID(as_uuid=True),
            sa.ForeignKey("property_needs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "listing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog_listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("match_kind", sa.String(length=16), nullable=False),
        sa.Column("rule_version", sa.String(length=60), nullable=False),
        sa.Column(
            "explanation",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("template_name", sa.String(length=120), nullable=True),
        sa.Column("template_language", sa.String(length=20), nullable=True),
        sa.Column("message_preview", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column(
            "decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbound_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "outbox_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbox_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
            "status IN ('Pending', 'Authorized', 'Rejected', 'Revoked', "
            "'Queued', 'Denied', 'Responded')",
            name="ck_reactivation_candidates_status",
        ),
        sa.CheckConstraint(
            "match_kind IN ('Exact', 'Approximate')",
            name="ck_reactivation_candidates_match_kind",
        ),
        sa.CheckConstraint(
            "(status = 'Pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(status <> 'Pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_reactivation_candidates_review",
        ),
        sa.UniqueConstraint(
            "property_need_id",
            "listing_id",
            "rule_version",
            name="uq_reactivation_candidate_match",
        ),
    )
    op.create_index(
        "ix_reactivation_candidates_work",
        "reactivation_candidates",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "development_campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "development_id",
            UUID(as_uuid=True),
            sa.ForeignKey("developments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("criteria_version", sa.String(length=60), nullable=False),
        sa.Column(
            "audience_criteria",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "exclusions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("template_name", sa.String(length=120), nullable=False),
        sa.Column("template_language", sa.String(length=20), nullable=False),
        sa.Column("content_preview", sa.Text(), nullable=False),
        sa.Column("quiet_hours_start", sa.Integer(), nullable=False),
        sa.Column("quiet_hours_end", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=60), nullable=False),
        sa.Column("frequency_cap", sa.Integer(), nullable=False),
        sa.Column("frequency_window_days", sa.Integer(), nullable=False),
        sa.Column("max_recipients", sa.Integer(), nullable=False),
        sa.Column(
            "authorized_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('Draft', 'Active', 'Paused', 'Cancelled', 'Completed')",
            name="ck_development_campaigns_status",
        ),
        sa.CheckConstraint(
            "quiet_hours_start BETWEEN 0 AND 23 AND quiet_hours_end BETWEEN 0 AND 23",
            name="ck_development_campaigns_quiet_hours",
        ),
        sa.CheckConstraint(
            "frequency_cap > 0 AND frequency_window_days > 0 AND "
            "max_recipients > 0 AND max_recipients <= 500",
            name="ck_development_campaigns_limits",
        ),
    )
    op.create_index(
        "ix_development_campaigns_work",
        "development_campaigns",
        ["organization_id", "status", "created_at"],
    )

    op.create_table(
        "campaign_audience_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("development_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_need_id",
            UUID(as_uuid=True),
            sa.ForeignKey("property_needs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("audience_reference", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "reasons", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbound_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "outbox_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbox_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('Included', 'Excluded', 'Queued', 'Denied', 'Responded')",
            name="ck_campaign_audience_status",
        ),
        sa.UniqueConstraint(
            "campaign_id", "property_need_id", name="uq_campaign_audience_need"
        ),
        sa.UniqueConstraint(
            "campaign_id", "audience_reference", name="uq_campaign_audience_reference"
        ),
    )
    op.create_index(
        "ix_campaign_audience_work",
        "campaign_audience_members",
        ["campaign_id", "status", "resolved_at"],
    )

    op.create_table(
        "marketing_touches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("development_campaigns.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "reactivation_candidate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reactivation_candidates.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbound_decisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "outbox_id",
            UUID(as_uuid=True),
            sa.ForeignKey("outbox_messages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(campaign_id IS NOT NULL) <> (reactivation_candidate_id IS NOT NULL)",
            name="ck_marketing_touches_source",
        ),
        sa.UniqueConstraint("outbox_id", name="uq_marketing_touches_outbox"),
    )
    op.create_index(
        "ix_marketing_touches_frequency",
        "marketing_touches",
        ["organization_id", "contact_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_marketing_touches_frequency", table_name="marketing_touches")
    op.drop_table("marketing_touches")
    op.drop_index("ix_campaign_audience_work", table_name="campaign_audience_members")
    op.drop_table("campaign_audience_members")
    op.drop_index("ix_development_campaigns_work", table_name="development_campaigns")
    op.drop_table("development_campaigns")
    op.drop_index(
        "ix_reactivation_candidates_work", table_name="reactivation_candidates"
    )
    op.drop_table("reactivation_candidates")
    op.drop_index(
        "ix_message_templates_approved", table_name="approved_message_templates"
    )
    op.drop_table("approved_message_templates")
    for name in (
        "expires_at",
        "evidence_locator",
        "notice_version",
        "scope",
        "business_name",
    ):
        op.drop_column("consent_records", name)
    op.drop_column("outbound_decisions", "template_language")

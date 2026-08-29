"""Make analytics replay definition-aware.

Revision ID: 0027_stage8_measurement_repairs
Revises: 0026_managed_platform
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0027_stage8_measurement_repairs"
down_revision: str | None = "0026_managed_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYTICS = "analytics"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_channel_handoffs_org_id",
        "channel_handoffs",
        ["organization_id", "id"],
    )
    op.drop_constraint(
        "uq_domain_events_org_event",
        "domain_events",
        schema=ANALYTICS,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_domain_events_org_event_definition",
        "domain_events",
        ["organization_id", "event_key", "definition_version"],
        schema=ANALYTICS,
    )
    op.add_column(
        "projection_runs",
        sa.Column("organization_id", UUID(as_uuid=True), nullable=True),
        schema=ANALYTICS,
    )
    op.execute(
        f"""
        UPDATE {ANALYTICS}.projection_runs
        SET organization_id = (
            SELECT id FROM organizations WHERE slug = 'larevia'
        )
        WHERE organization_id IS NULL
        """
    )
    op.alter_column(
        "projection_runs", "organization_id", nullable=False, schema=ANALYTICS
    )
    op.create_foreign_key(
        "fk_projection_runs_organization",
        "projection_runs",
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema=ANALYTICS,
        referent_schema="public",
        ondelete="CASCADE",
    )
    op.drop_index(
        "ix_projection_runs_version", table_name="projection_runs", schema=ANALYTICS
    )
    op.create_index(
        "ix_projection_runs_org_version",
        "projection_runs",
        ["organization_id", "definition_version", "ran_at"],
        schema=ANALYTICS,
    )
    op.add_column(
        "website_conversations",
        sa.Column("sponsorship_campaign_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_website_conversations_org_sponsorship",
        "website_conversations",
        "sponsorship_campaigns",
        ["organization_id", "sponsorship_campaign_id"],
        ["organization_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.add_column(
        "channel_handoffs",
        sa.Column("sponsorship_campaign_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_channel_handoffs_org_sponsorship",
        "channel_handoffs",
        "sponsorship_campaigns",
        ["organization_id", "sponsorship_campaign_id"],
        ["organization_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "sponsorship_contact_attributions",
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
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "handoff_id",
            UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("engaged_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "handoff_id",
            name="uq_sponsorship_contact_attribution_handoff",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["sponsorship_campaigns.organization_id", "sponsorship_campaigns.id"],
            name="fk_sponsorship_contact_attributions_org_campaign",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "contact_id"],
            ["contacts.organization_id", "contacts.id"],
            name="fk_sponsorship_contact_attributions_org_contact",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "handoff_id"],
            ["channel_handoffs.organization_id", "channel_handoffs.id"],
            name="fk_sponsorship_contact_attributions_org_handoff",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    op.create_index(
        "ix_sponsorship_contact_attribution",
        "sponsorship_contact_attributions",
        ["organization_id", "contact_id", "engaged_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sponsorship_contact_attribution",
        table_name="sponsorship_contact_attributions",
    )
    op.drop_table("sponsorship_contact_attributions")
    op.drop_constraint(
        "fk_channel_handoffs_org_sponsorship",
        "channel_handoffs",
        type_="foreignkey",
    )
    op.drop_column("channel_handoffs", "sponsorship_campaign_id")
    op.drop_constraint(
        "fk_website_conversations_org_sponsorship",
        "website_conversations",
        type_="foreignkey",
    )
    op.drop_column("website_conversations", "sponsorship_campaign_id")
    op.drop_index(
        "ix_projection_runs_org_version",
        table_name="projection_runs",
        schema=ANALYTICS,
    )
    op.create_index(
        "ix_projection_runs_version",
        "projection_runs",
        ["definition_version", "ran_at"],
        schema=ANALYTICS,
    )
    op.drop_constraint(
        "fk_projection_runs_organization",
        "projection_runs",
        schema=ANALYTICS,
        type_="foreignkey",
    )
    op.drop_column("projection_runs", "organization_id", schema=ANALYTICS)
    op.drop_constraint(
        "uq_domain_events_org_event_definition",
        "domain_events",
        schema=ANALYTICS,
        type_="unique",
    )
    # A downgrade cannot preserve several projections of the same raw event
    # under the old two-column identity. Keep the earliest projected version.
    op.execute(
        f"""
        DELETE FROM {ANALYTICS}.domain_events AS duplicate
        USING {ANALYTICS}.domain_events AS kept
        WHERE duplicate.organization_id = kept.organization_id
          AND duplicate.event_key = kept.event_key
          AND (duplicate.projected_at, duplicate.id)
              > (kept.projected_at, kept.id)
        """
    )
    op.create_unique_constraint(
        "uq_domain_events_org_event",
        "domain_events",
        ["organization_id", "event_key"],
        schema=ANALYTICS,
    )
    op.drop_constraint(
        "uq_channel_handoffs_org_id", "channel_handoffs", type_="unique"
    )

"""Add the Stage 5 public-site authority records.

Revision ID: 0022_public_site
Revises: 0021_stage_three_query_indexes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0022_public_site"
down_revision: str | None = "0021_stage_three_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_collections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "protected_contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("merged_into_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["saved_collections.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "protected_contact_id IS NULL OR expires_at IS NULL",
            name="ck_saved_collections_protected_no_expiry",
        ),
        sa.CheckConstraint(
            "merged_into_id IS NULL OR merged_into_id <> id",
            name="ck_saved_collections_not_self_merged",
        ),
    )
    op.create_index(
        "uq_saved_collections_protected_contact",
        "saved_collections",
        ["organization_id", "protected_contact_id"],
        unique=True,
        postgresql_where=sa.text(
            "protected_contact_id IS NOT NULL AND deleted_at IS NULL "
            "AND merged_into_id IS NULL"
        ),
    )
    op.create_index(
        "ix_saved_collections_expiry", "saved_collections", ["expires_at"]
    )

    op.create_table(
        "saved_collection_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("saved_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "listing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog_listings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug_snapshot", sa.String(length=140), nullable=False),
        sa.Column("title_snapshot", sa.String(length=200), nullable=False),
        sa.Column("location_snapshot", sa.String(length=300), nullable=True),
        sa.Column(
            "saved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint(
            "collection_id", "listing_id", name="uq_saved_collection_item"
        ),
    )
    op.create_index(
        "ix_saved_collection_items_collection",
        "saved_collection_items",
        ["collection_id", "saved_at"],
    )

    op.create_table(
        "shared_selections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("saved_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "snapshot", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_shared_selections_expiry", "shared_selections", ["expires_at"]
    )

    op.create_table(
        "website_conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("hermes_session_id", sa.String(length=200), nullable=True),
        sa.Column(
            "verified_contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "listing_context", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('Open', 'HandoffPending', 'Verified', 'Closed')",
            name="ck_website_conversations_status",
        ),
        sa.CheckConstraint(
            "(verified_contact_id IS NULL AND status IN ('Open', 'HandoffPending')) OR "
            "(verified_contact_id IS NOT NULL AND status IN ('Verified', 'Closed'))",
            name="ck_website_conversations_verified_contact",
        ),
    )
    op.create_index(
        "ix_website_conversations_activity",
        "website_conversations",
        ["last_activity_at"],
    )

    op.create_table(
        "website_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("website_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("command_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("content_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('Customer', 'Maia', 'System')", name="ck_website_messages_role"
        ),
    )
    op.create_index(
        "ix_website_messages_thread",
        "website_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_website_messages_expiry",
        "website_messages",
        ["content_expires_at"],
        postgresql_where=sa.text("content_expired_at IS NULL"),
    )

    op.create_table(
        "channel_handoffs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column(
            "website_conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("website_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "saved_collection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("saved_collections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "listing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog_listings.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "expected_contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consumed_by_contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "purpose IN ('ContinueWhatsApp', 'Appointment', "
            "'SavedCollectionProtection')",
            name="ck_channel_handoffs_purpose",
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL) = (consumed_by_contact_id IS NULL)",
            name="ck_channel_handoffs_consumed",
        ),
        sa.CheckConstraint(
            "website_conversation_id IS NOT NULL OR saved_collection_id IS NOT NULL "
            "OR listing_id IS NOT NULL",
            name="ck_channel_handoffs_context",
        ),
    )
    op.create_index("ix_channel_handoffs_expiry", "channel_handoffs", ["expires_at"])

    op.create_table(
        "public_analytics_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column(
            "listing_id",
            UUID(as_uuid=True),
            sa.ForeignKey("catalog_listings.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("presentation_tier", sa.String(length=20), nullable=True),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column(
            "properties", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "name IN ('ListingImpression', 'GalleryOpen', 'ListingSaved', "
            "'MaiaStarted', 'HandoffCreated', 'AppointmentRequested')",
            name="ck_public_analytics_event_name",
        ),
        sa.CheckConstraint(
            "presentation_tier IS NULL OR presentation_tier IN "
            "('Larevia', 'Premium', 'SuperPremium')",
            name="ck_public_analytics_tier",
        ),
    )
    op.create_index(
        "ix_public_analytics_funnel",
        "public_analytics_events",
        ["organization_id", "occurred_at", "name"],
    )


def downgrade() -> None:
    op.drop_index("ix_public_analytics_funnel", table_name="public_analytics_events")
    op.drop_table("public_analytics_events")
    op.drop_index("ix_channel_handoffs_expiry", table_name="channel_handoffs")
    op.drop_table("channel_handoffs")
    op.drop_index("ix_website_messages_expiry", table_name="website_messages")
    op.drop_index("ix_website_messages_thread", table_name="website_messages")
    op.drop_table("website_messages")
    op.drop_index(
        "ix_website_conversations_activity", table_name="website_conversations"
    )
    op.drop_table("website_conversations")
    op.drop_index("ix_shared_selections_expiry", table_name="shared_selections")
    op.drop_table("shared_selections")
    op.drop_index(
        "ix_saved_collection_items_collection", table_name="saved_collection_items"
    )
    op.drop_table("saved_collection_items")
    op.drop_index("ix_saved_collections_expiry", table_name="saved_collections")
    op.drop_index(
        "uq_saved_collections_protected_contact", table_name="saved_collections"
    )
    op.drop_table("saved_collections")

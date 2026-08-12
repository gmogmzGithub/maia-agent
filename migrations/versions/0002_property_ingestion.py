"""Property ingestion and trusted session binding (Checkpoint 1).

Revision ID: 0002_property_ingestion
Revises: 0001_baseline
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_property_ingestion"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("accepted_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("status IN ('Active', 'Inactive')", name="ck_properties_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_key"),
        sa.UniqueConstraint("normalized_name"),
    )

    op.create_table(
        "property_document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("document_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["property_uuid"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_uuid", "version", name="uq_property_version"),
    )
    op.create_index(
        "ix_property_document_versions_property",
        "property_document_versions",
        ["property_uuid"],
    )

    # The accepted-version pointer closes a cycle between the two tables, so it
    # is added after both exist.
    op.create_foreign_key(
        "fk_accepted_version",
        "properties",
        "property_document_versions",
        ["accepted_version_id"],
        ["id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_subject", "audit_events", ["subject_type", "subject_id"]
    )

    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hermes_session_id", sa.String(length=120), nullable=False),
        sa.Column("gateway_session_id", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('Sales', 'Administrative')", name="ck_agent_sessions_role"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hermes_session_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_sessions")
    op.drop_index("ix_audit_events_subject", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_constraint("fk_accepted_version", "properties", type_="foreignkey")
    op.drop_index(
        "ix_property_document_versions_property", table_name="property_document_versions"
    )
    op.drop_table("property_document_versions")
    op.drop_table("properties")

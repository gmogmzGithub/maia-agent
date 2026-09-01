"""Complete organizational isolation and the managed platform's own records.

Revision ID: 0026_managed_platform
Revises: 0025_analytics_and_sponsorship

Two halves, and the first is the one that matters.

**Isolation.** Revisions 0012 through 0015 put ``organization_id`` on the
commercial roots and made the references Organization-safe. What they did not
reach is the operational layer beneath them: an Inbox message, an Outbox row, a
delivery callback, a consent record, an availability snapshot, a Hermes session
binding, an audit event. Every one of those was reachable only through a join,
and every query over them was one forgotten join away from answering with
another Organization's work. This revision gives each of them the column, a
composite foreign key that makes the column and the parent agree, and — where a
business key was globally unique — a per-Organization namespace instead.

The globally unique keys are the sharper problem. ``properties.property_key``,
``appointments.reference``, ``inbox_messages.wamid``,
``outbox_messages.idempotency_key``, ``admin_messages.update_id`` and the
analytics event keys were all unique across the whole installation. A second
Brokerage Organization would have discovered that from a constraint violation
naming somebody else's row, and the duplicate-detection queries that read those
columns without an Organization could resolve across the boundary outright.

**The platform.** The second half adds the tables a managed multi-organization
service needs and did not have: a versioned configuration document, secret
*references* (never values), the channel bindings that map inbound traffic to an
Organization, append-only entitlements, expiring support grants, resumable
provisioning runs, usage periods, import runs with their findings, retention
holds, and the export/deletion record.

The backfill attributes every existing row to the one Organization that exists.
That is correct rather than convenient: every row predates the platform, and
there is nowhere else it could have come from.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0026_managed_platform"
down_revision: str | None = "0025_analytics_and_sponsorship"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYTICS = "analytics"

# The Organization every pre-Stage-9 row belongs to. Named by slug rather than
# "the only row", because the second Organization may already exist by the time
# a staging database runs this and picking the first row would be a coin toss.
BOOTSTRAP_SLUG = "larevia"

_ORG = f"(SELECT id FROM organizations WHERE slug = '{BOOTSTRAP_SLUG}')"


# (table, parent table, local parent column, schema) — the backfill joins. The
# parent already carries ``organization_id``, so each child's value is simply
# read across the reference it already had.
BACKFILL: tuple[tuple[str, str, str, str | None], ...] = (
    ("property_document_versions", "properties", "property_uuid", None),
    ("lead_engagement_cycles", "leads", "lead_id", None),
    # After the cycles, because it reads the value they just received.
    ("lead_followups", "lead_engagement_cycles", "cycle_id", None),
    ("inbox_messages", "conversations", "conversation_id", None),
    ("inbox_groups", "conversations", "conversation_id", None),
    ("outbox_messages", "conversations", "conversation_id", None),
    ("consent_records", "leads", "lead_id", None),
    ("suppression_records", "leads", "lead_id", None),
    ("outbound_decisions", "conversations", "conversation_id", None),
    ("availability_snapshots", "conversations", "conversation_id", None),
    ("appointment_reminders", "appointments", "appointment_id", None),
    ("saved_collection_items", "saved_collections", "collection_id", None),
    ("website_messages", "website_conversations", "conversation_id", None),
    ("sponsorship_price_items", "sponsorship_price_catalogs", "catalog_id", None),
    ("sponsorship_delivery_days", "sponsorship_campaigns", "campaign_id", None),
)

# Tables whose scope cannot be joined to a parent, because the parent reference
# is nullable or there is none. Every existing row is the bootstrap
# Organization's, which is exactly what the constant above says.
DIRECT: tuple[tuple[str, str | None], ...] = (
    ("audit_events", None),
    # Nullable ``outbox_id``: a status can arrive before the row it belongs to.
    ("delivery_statuses", None),
    ("admin_messages", None),
    ("channel_cursors", None),
    # Nullable ``cycle_id``: an Administrative session has no Lead cycle.
    ("agent_sessions", None),
)

# Parent uniques the new composite foreign keys need to point at.
PARENT_UNIQUES: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    ("lead_engagement_cycles", "uq_cycles_org_id", ("organization_id", "id"), None),
    ("inbox_messages", "uq_inbox_org_id", ("organization_id", "id"), None),
    ("outbox_messages", "uq_outbox_org_id", ("organization_id", "id"), None),
    ("appointments", "uq_appointments_org_id", ("organization_id", "id"), None),
    (
        "saved_collections",
        "uq_saved_collections_org_id",
        ("organization_id", "id"),
        None,
    ),
    (
        "website_conversations",
        "uq_website_conversations_org_id",
        ("organization_id", "id"),
        None,
    ),
    (
        "sponsorship_price_catalogs",
        "uq_price_catalog_org_id",
        ("organization_id", "id"),
        None,
    ),
    (
        "sponsorship_campaigns",
        "uq_sponsorship_campaigns_org_id",
        ("organization_id", "id"),
        None,
    ),
)

# (table, constraint name, referred table, local columns, referred columns).
#
# Deferred, and deliberately *without* an ``ondelete`` — the same shape migration
# 0015 established. These constraints exist to enforce one thing: that a row's
# ``organization_id`` and its parent's agree. The delete behaviour belongs to the
# single-column foreign key beside each of them, and adding a second cascade path
# over the same rows is both redundant and a real source of lock-ordering
# deadlocks once two transactions delete overlapping conversations.
COMPOSITE_FKS: tuple[
    tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "property_document_versions",
        "fk_document_versions_org_property",
        "properties",
        ("organization_id", "property_uuid"),
        ("organization_id", "id"),
    ),
    (
        "lead_engagement_cycles",
        "fk_cycles_org_lead",
        "leads",
        ("organization_id", "lead_id"),
        ("organization_id", "id"),
    ),
    (
        "lead_followups",
        "fk_followups_org_cycle",
        "lead_engagement_cycles",
        ("organization_id", "cycle_id"),
        ("organization_id", "id"),
    ),
    (
        "lead_followups",
        "fk_followups_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "inbox_messages",
        "fk_inbox_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "inbox_groups",
        "fk_inbox_groups_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "outbox_messages",
        "fk_outbox_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "delivery_statuses",
        "fk_delivery_statuses_org_outbox",
        "outbox_messages",
        ("organization_id", "outbox_id"),
        ("organization_id", "id"),
    ),
    (
        "consent_records",
        "fk_consent_records_org_lead",
        "leads",
        ("organization_id", "lead_id"),
        ("organization_id", "id"),
    ),
    (
        "suppression_records",
        "fk_suppression_records_org_lead",
        "leads",
        ("organization_id", "lead_id"),
        ("organization_id", "id"),
    ),
    (
        "outbound_decisions",
        "fk_outbound_decisions_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "availability_snapshots",
        "fk_snapshots_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "availability_snapshots",
        "fk_snapshots_org_property",
        "properties",
        ("organization_id", "property_uuid"),
        ("organization_id", "id"),
    ),
    (
        "agent_sessions",
        "fk_agent_sessions_org_cycle",
        "lead_engagement_cycles",
        ("organization_id", "cycle_id"),
        ("organization_id", "id"),
    ),
    (
        "appointment_reminders",
        "fk_reminders_org_appointment",
        "appointments",
        ("organization_id", "appointment_id"),
        ("organization_id", "id"),
    ),
    (
        "saved_collection_items",
        "fk_saved_items_org_collection",
        "saved_collections",
        ("organization_id", "collection_id"),
        ("organization_id", "id"),
    ),
    (
        "saved_collection_items",
        "fk_saved_items_org_listing",
        "catalog_listings",
        ("organization_id", "listing_id"),
        ("organization_id", "id"),
    ),
    (
        "website_messages",
        "fk_website_messages_org_conversation",
        "website_conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "sponsorship_price_items",
        "fk_price_items_org_catalog",
        "sponsorship_price_catalogs",
        ("organization_id", "catalog_id"),
        ("organization_id", "id"),
    ),
    (
        "sponsorship_delivery_days",
        "fk_delivery_days_org_campaign",
        "sponsorship_campaigns",
        ("organization_id", "campaign_id"),
        ("organization_id", "id"),
    ),
)

# Business keys that were global and become per-Organization. The old name is
# dropped and the new constraint created in one step per table, so no window
# exists in which neither is enforced.
RENAMED_UNIQUES: tuple[tuple[str, str, str, tuple[str, ...], str | None], ...] = (
    (
        "properties",
        "properties_property_key_key",
        "uq_properties_org_key",
        ("organization_id", "property_key"),
        None,
    ),
    (
        "inbox_messages",
        "inbox_messages_wamid_key",
        "uq_inbox_org_wamid",
        ("organization_id", "wamid"),
        None,
    ),
    (
        "outbox_messages",
        "outbox_messages_idempotency_key_key",
        "uq_outbox_org_idempotency",
        ("organization_id", "idempotency_key"),
        None,
    ),
    (
        "admin_messages",
        "admin_messages_update_id_key",
        "uq_admin_messages_org_update",
        ("organization_id", "update_id"),
        None,
    ),
    (
        "appointments",
        "appointments_reference_key",
        "uq_appointments_org_reference",
        ("organization_id", "reference"),
        None,
    ),
    (
        "agent_sessions",
        "uq_agent_sessions_channel_key",
        "uq_agent_sessions_org_channel",
        ("organization_id", "channel_key"),
        None,
    ),
    (
        "website_messages",
        "website_messages_command_key_key",
        "uq_website_messages_org_command",
        ("organization_id", "command_key"),
        None,
    ),
    (
        "public_analytics_events",
        "public_analytics_events_event_key_key",
        "uq_public_analytics_org_event",
        ("organization_id", "event_key"),
        None,
    ),
    (
        "delivery_statuses",
        "uq_delivery_status_event",
        "uq_delivery_status_event",
        ("organization_id", "provider_message_id", "status"),
        None,
    ),
    (
        "lead_followups",
        "uq_lead_followup_cycle_day",
        "uq_lead_followup_cycle_day",
        ("organization_id", "cycle_id", "day_number", "channel"),
        None,
    ),
    (
        "availability_snapshots",
        "uq_snapshot_conversation_property",
        "uq_snapshot_conversation_property",
        ("organization_id", "conversation_id", "property_uuid"),
        None,
    ),
    (
        "appointment_reminders",
        "uq_reminder_appointment_kind",
        "uq_reminder_appointment_kind",
        ("organization_id", "appointment_id", "kind"),
        None,
    ),
    (
        "saved_collection_items",
        "uq_saved_collection_item",
        "uq_saved_collection_item",
        ("organization_id", "collection_id", "listing_id"),
        None,
    ),
    (
        "sponsorship_price_items",
        "uq_price_item_package",
        "uq_price_item_package",
        ("organization_id", "catalog_id", "package", "duration_days"),
        None,
    ),
    (
        "sponsorship_delivery_days",
        "uq_delivery_day",
        "uq_delivery_day",
        ("organization_id", "campaign_id", "service_date"),
        None,
    ),
    (
        "catalog_listings",
        "uq_catalog_listings_gallery_path",
        "uq_catalog_listings_gallery_path",
        ("organization_id", "gallery_path"),
        None,
    ),
    (
        "catalog_listings",
        "uq_catalog_listings_sheet_path",
        "uq_catalog_listings_sheet_path",
        ("organization_id", "technical_sheet_path"),
        None,
    ),
    (
        "analytics_outbox",
        "analytics_outbox_event_key_key",
        "uq_analytics_outbox_org_event",
        ("organization_id", "event_key"),
        ANALYTICS,
    ),
    (
        "domain_events",
        "domain_events_event_key_key",
        "uq_domain_events_org_event",
        ("organization_id", "event_key"),
        ANALYTICS,
    ),
)

# What the founding Organization is seeded with, so nothing it can already do
# stops working. Every add-on is enabled and both ceilings take the *largest*
# tier's value: it was never sold a tier, and inventing a small one would mean
# Stage 9 refusing the fourth Advisor of an operation that already has four.
# A provisioned Organization gets its package from
# ``realestate.domain.platform.entitlements.apply_package`` instead, where the
# tier is a commercial decision somebody made.
BASE_CAPABILITIES: tuple[tuple[str, int | None], ...] = (
    ("CommercialCrm", None),
    ("AdvisorSeats", 25),
    ("AuthorizedCatalog", None),
    ("ListingMedia", None),
    ("PublicSite", None),
    ("WebsiteConversation", None),
    ("WhatsAppChannel", None),
    ("CalendarScheduling", None),
    ("ExternalInventory", None),
    ("ReactivationCampaigns", None),
    ("DevelopmentCampaigns", None),
    ("SponsoredPlacement", None),
    ("BusinessIntelligence", None),
    ("MonthlyWhatsAppConversations", 15000),
)


# Two of the newly scoped tables cascade rather than restrict: a Telegram
# cursor and a Hermes session binding are pure runtime state with nothing to
# preserve once the Organization is gone, whereas every operational and
# commercial row must survive long enough for the deletion module to remove it
# deliberately and count what it removed.
CASCADING = frozenset({"channel_cursors", "agent_sessions"})


def _scoped(table: str, schema: str | None = None) -> None:
    """Add a nullable ``organization_id`` with its plain foreign key."""
    op.add_column(
        table,
        sa.Column("organization_id", UUID(as_uuid=True), nullable=True),
        schema=schema,
    )
    op.create_foreign_key(
        f"fk_{table}_organization",
        table,
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE" if table in CASCADING else "RESTRICT",
        source_schema=schema,
        referent_schema=None,
    )


def upgrade() -> None:
    # ---------------------------------------------------------------- lifecycle
    op.add_column(
        "organizations",
        sa.Column("status", sa.String(20), nullable=False, server_default="Active"),
    )
    op.add_column(
        "organizations",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("deprovisioned_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The Organization that already operates is Active as of when it was created.
    # Leaving ``activated_at`` NULL would violate the check constraint below,
    # which is the point: Active without a date is not a state anybody can audit.
    op.execute(
        "UPDATE organizations SET activated_at = created_at WHERE activated_at IS NULL"
    )
    # The server default becomes ``Provisioning`` — not removed — so a row
    # inserted by anything other than the provisioning module is created
    # not-operating rather than rejected. The backfill above set the existing
    # Organization Active before this point.
    op.alter_column("organizations", "status", server_default="Provisioning")
    op.create_check_constraint(
        "ck_organizations_status",
        "organizations",
        "status IN ('Provisioning', 'Active', 'Suspended', 'Deprovisioning', "
        "'Deprovisioned')",
    )
    op.create_check_constraint(
        "ck_organizations_activated",
        "organizations",
        "status <> 'Active' OR activated_at IS NOT NULL",
    )

    # ------------------------------------------------------- scope the columns
    for table, _parent, _column, schema in BACKFILL:
        _scoped(table, schema)
    for table, schema in DIRECT:
        _scoped(table, schema)

    for table, parent, column, schema in BACKFILL:
        op.execute(
            f"UPDATE {table} AS child SET organization_id = parent.organization_id "
            f"FROM {parent} AS parent WHERE parent.id = child.{column}"
        )
    for table, _schema in DIRECT:
        op.execute(f"UPDATE {table} SET organization_id = {_ORG}")

    # The backfill UPDATEs queue the deferred foreign-key triggers migration 0015
    # created — ``fk_followups_cycle_conversation`` among them — and PostgreSQL
    # refuses ``ALTER TABLE`` while a table has pending trigger events. Firing
    # them now is also the right moment to find out the backfill broke an
    # existing constraint, rather than at the end of the transaction.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")

    # ``audit_events`` keeps a nullable column: a row about the platform itself
    # — provisioning an Organization, granting support access — precedes or sits
    # above any single one. The check constraint is what stops that exception
    # from becoming a way to write unscoped history.
    op.create_check_constraint(
        "ck_audit_events_scope",
        "audit_events",
        "organization_id IS NOT NULL OR actor_type = 'Platform'",
    )
    op.create_index(
        "ix_audit_events_organization",
        "audit_events",
        ["organization_id", "occurred_at"],
    )

    for table, _parent, _column, schema in BACKFILL:
        op.alter_column(table, "organization_id", nullable=False, schema=schema)
    for table, schema in DIRECT:
        if table == "audit_events":
            continue
        op.alter_column(table, "organization_id", nullable=False, schema=schema)

    # ``channel_cursors`` gains the Organization as part of its primary key: two
    # Organizations polling their own Telegram bots share a channel *name* and
    # nothing else, and one row would have made each retire the other's backlog.
    op.drop_constraint("channel_cursors_pkey", "channel_cursors", type_="primary")
    op.create_primary_key(
        "channel_cursors_pkey", "channel_cursors", ["organization_id", "channel"]
    )

    op.create_index(
        "ix_delivery_statuses_outbox",
        "delivery_statuses",
        ["organization_id", "outbox_id"],
    )

    # --------------------------------------------- parents, then composite keys
    for table, name, columns, schema in PARENT_UNIQUES:
        op.create_unique_constraint(name, table, list(columns), schema=schema)

    for table, name, referred, local, remote in COMPOSITE_FKS:
        op.create_foreign_key(
            name,
            table,
            referred,
            list(local),
            list(remote),
            deferrable=True,
            initially="DEFERRED",
        )

    # ------------------------------------------ per-Organization business keys
    for table, old_name, new_name, columns, schema in RENAMED_UNIQUES:
        op.drop_constraint(old_name, table, type_="unique", schema=schema)
        op.create_unique_constraint(new_name, table, list(columns), schema=schema)

    # The partial unique index on an allowed outbound decision. Denials repeat
    # freely — refusing the same intent twice is history — so only the Queued
    # row is constrained, and now per Organization.
    op.drop_index("uq_outbound_decision_queued", table_name="outbound_decisions")
    op.create_index(
        "uq_outbound_decision_queued",
        "outbound_decisions",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("outcome = 'Queued'"),
    )

    # ``Support`` provenance, and the one exception it licenses: a support
    # engineer's Advisor row cannot own Opportunities, so the deterministic
    # assignment rule never routes a real Opportunity to Maia's support desk
    # (ADR-0054). Confined to this provenance so it cannot become a way to
    # create an unassignable Advisor by accident.
    op.drop_constraint(
        "ck_organization_members_provisioned_by",
        "organization_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_organization_members_provisioned_by",
        "organization_members",
        "provisioned_by IN ('Configuration', 'Administrator', 'Support')",
    )
    op.drop_constraint(
        "ck_organization_members_advisor_advises",
        "organization_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_organization_members_advisor_advises",
        "organization_members",
        "role <> 'RealEstateAdvisor' OR advises IS TRUE "
        "OR provisioned_by = 'Support'",
    )

    # ----------------------------------------------------- the platform tables
    op.create_table(
        "organization_configuration_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", JSONB(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(200), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("version > 0", name="ck_org_configuration_version"),
        sa.CheckConstraint(
            "length(btrim(note)) > 0", name="ck_org_configuration_note"
        ),
        sa.UniqueConstraint(
            "organization_id", "version", name="uq_org_configuration_version"
        ),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_org_configuration_command"
        ),
    )
    op.create_index(
        "uq_org_configuration_current",
        "organization_configuration_versions",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
    )

    op.create_table(
        "organization_secret_references",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="Active"),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("recorded_by", sa.String(200), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "state IN ('Active', 'Rotating', 'Revoked')",
            name="ck_secret_reference_state",
        ),
        sa.CheckConstraint(
            "provider IN ('MetaWhatsApp', 'MetaBusiness', 'GoogleCalendar', "
            "'Telegram', 'EasyBroker')",
            name="ck_secret_reference_provider",
        ),
        sa.UniqueConstraint(
            "organization_id", "provider", "reference", name="uq_secret_reference_name"
        ),
    )
    op.create_index(
        "uq_secret_reference_active",
        "organization_secret_references",
        ["organization_id", "provider"],
        unique=True,
        postgresql_where=sa.text("state = 'Active'"),
    )

    op.create_table(
        "organization_channel_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="Active"),
        sa.Column("recorded_by", sa.String(200), nullable=False),
        sa.Column(
            "bound_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "kind IN ('WhatsAppPhoneNumberId', 'WhatsAppBusinessAccountId', "
            "'TelegramBotId', 'PublicSiteHost')",
            name="ck_channel_binding_kind",
        ),
        sa.CheckConstraint(
            "state IN ('Active', 'Retired')", name="ck_channel_binding_state"
        ),
    )
    # Global on purpose: an external identifier belongs to one Organization or
    # the inbound mapping is ambiguous, and an ambiguous mapping is how one
    # brokerage answers another's customer.
    op.create_index(
        "uq_channel_binding_active",
        "organization_channel_bindings",
        ["kind", "external_id"],
        unique=True,
        postgresql_where=sa.text("state = 'Active'"),
    )
    op.create_index(
        "ix_channel_bindings_organization",
        "organization_channel_bindings",
        ["organization_id", "kind", "state"],
    )

    op.create_table(
        "organization_entitlements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(60), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("package", sa.String(40), nullable=True),
        sa.Column("tier", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(200), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "state IN ('Enabled', 'Disabled')", name="ck_entitlement_state"
        ),
        sa.CheckConstraint(
            "source IN ('Package', 'Tier', 'AddOn', 'Override')",
            name="ck_entitlement_source",
        ),
        sa.CheckConstraint(
            "limit_value IS NULL OR limit_value >= 0", name="ck_entitlement_limit"
        ),
    )
    op.create_index(
        "uq_entitlement_current",
        "organization_entitlements",
        ["organization_id", "capability"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_entitlements_history",
        "organization_entitlements",
        ["organization_id", "capability", "recorded_at"],
    )

    op.create_table(
        "support_access_grants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("subject_login", sa.String(120), nullable=False),
        sa.Column("member_id", UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False, server_default="ReadOnly"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_reference", sa.String(200), nullable=True),
        sa.Column("granted_by", sa.String(200), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(200), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["organization_members.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint("scope = 'ReadOnly'", name="ck_support_grant_scope"),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_support_grant_reason"
        ),
        sa.CheckConstraint("expires_at > granted_at", name="ck_support_grant_expiry"),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_support_grant_command"
        ),
    )
    op.create_index(
        "uq_support_grant_active",
        "support_access_grants",
        ["organization_id", "subject_login"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_support_grants_expiry", "support_access_grants", ["expires_at"]
    )

    op.create_table(
        "organization_provisioning_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("command_key", sa.String(200), nullable=False, unique=True),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=True),
        sa.Column("intent", sa.String(20), nullable=False, server_default="Provision"),
        sa.Column("state", sa.String(20), nullable=False, server_default="Pending"),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("plan", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "state IN ('Pending', 'Completed', 'Failed', 'RolledBack')",
            name="ck_provisioning_run_state",
        ),
        sa.CheckConstraint(
            "intent IN ('Provision', 'Deprovision')",
            name="ck_provisioning_run_intent",
        ),
    )
    op.create_index(
        "ix_provisioning_runs_slug",
        "organization_provisioning_runs",
        ["slug", "started_at"],
    )

    op.create_table(
        "organization_provisioning_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="Pending"),
        sa.Column(
            "detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["organization_provisioning_runs.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('Pending', 'Completed', 'Failed', 'RolledBack')",
            name="ck_provisioning_step_state",
        ),
        sa.UniqueConstraint("run_id", "name", name="uq_provisioning_step_name"),
    )

    op.create_table(
        "organization_usage_periods",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_quantity"),
        sa.UniqueConstraint(
            "organization_id", "metric", "period_start", name="uq_usage_period_cell"
        ),
    )
    op.create_index(
        "ix_usage_periods_read",
        "organization_usage_periods",
        ["organization_id", "period_start"],
    )

    op.create_table(
        "organization_import_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column(
            "provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "summary", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column(
            "planned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refusal", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("mode IN ('DryRun', 'Apply')", name="ck_import_run_mode"),
        sa.CheckConstraint(
            "state IN ('Planned', 'Applied', 'RolledBack', 'Refused')",
            name="ck_import_run_state",
        ),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_import_run_command"
        ),
    )
    op.create_index(
        "ix_import_runs_organization",
        "organization_import_runs",
        ["organization_id", "planned_at"],
    )

    op.create_table(
        "organization_import_findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("entity", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_record_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["organization_import_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "kind IN ('Accepted', 'Duplicate', 'Invalid', 'Skipped')",
            name="ck_import_finding_kind",
        ),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_import_finding_ordinal"),
    )
    op.create_index(
        "ix_import_findings_run", "organization_import_findings", ["run_id", "kind"]
    )

    op.create_table(
        "organization_retention_holds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("basis", sa.String(30), nullable=False),
        sa.Column("authority", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(200), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(200), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "basis IN ('LegalObligation', 'Contract', 'Dispute')",
            name="ck_retention_hold_basis",
        ),
    )
    op.create_index(
        "ix_retention_holds_live",
        "organization_retention_holds",
        ["organization_id"],
        postgresql_where=sa.text("released_at IS NULL"),
    )

    op.create_table(
        "organization_data_exports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column(
            "row_counts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "withheld", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "state IN ('Requested', 'Completed', 'Blocked', 'Failed')",
            name="ck_data_export_state",
        ),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_data_export_command"
        ),
    )

    op.create_table(
        "organization_data_deletions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(30), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "deleted_counts",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "retained_counts",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "scope IN ('OperationalContent', 'Everything')",
            name="ck_data_deletion_scope",
        ),
        sa.CheckConstraint(
            "state IN ('Requested', 'Completed', 'Blocked', 'Failed')",
            name="ck_data_deletion_state",
        ),
        sa.UniqueConstraint(
            "organization_id", "command_key", name="uq_data_deletion_command"
        ),
    )

    # ---------------------------------------------------- seed the bootstrap
    # The Organization that already operates gets the base package, so nothing
    # it can do today starts being refused tomorrow. Every capability is
    # recorded explicitly rather than defaulted in code: an entitlement that
    # exists only as an ``if`` cannot be reported to a customer.
    for capability, limit in BASE_CAPABILITIES:
        op.execute(
            sa.text(
                "INSERT INTO organization_entitlements "
                "(id, organization_id, capability, state, limit_value, source, "
                " package, tier, note, recorded_by) "
                "SELECT gen_random_uuid(), o.id, :capability, 'Enabled', :limit, "
                "       'Package', 'ManagedBase', NULL, "
                "       'Sembrado por la migración 0026 para preservar la "
                "operación existente. La organización fundadora nunca compró un "
                "nivel, por eso los topes vienen del nivel más amplio y la "
                "columna de nivel queda vacía.', 'Platform' "
                "FROM organizations o WHERE o.slug = :slug"
            ).bindparams(capability=capability, limit=limit, slug=BOOTSTRAP_SLUG)
        )

    # Version 1 of the bootstrap Organization's configuration records what is
    # true today: its behaviour comes from the process environment. That is a
    # statement, not a hiding place — ``OrganizationConfiguration`` treats the
    # environment as authoritative for *this* Organization only, and refuses to
    # fall back to it for any other (ADR-0051).
    op.execute(
        sa.text(
            "INSERT INTO organization_configuration_versions "
            "(id, organization_id, version, document, checksum, is_current, note, "
            " recorded_by, command_key) "
            "SELECT gen_random_uuid(), o.id, 1, CAST(:document AS jsonb), :checksum, TRUE, "
            "       :note, 'Platform', 'migration:0026:bootstrap' "
            "FROM organizations o WHERE o.slug = :slug"
        ).bindparams(
            document=json.dumps(
                {
                    "origin": "process-environment",
                    "brand": {"name": "Larevia"},
                    "notes": {
                        "bootstrap": (
                            "La configuración operativa de esta organización "
                            "sigue viniendo del entorno del proceso. Ninguna "
                            "otra organización puede usar ese entorno como "
                            "respaldo."
                        )
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            # Deliberately a literal rather than a computed digest: the module
            # recomputes and rewrites this on the first recorded version, and a
            # digest computed in two places is a digest that disagrees.
            checksum="bootstrap",
            note=(
                "Versión inicial sembrada por la migración 0026. Registra que la "
                "organización fundadora se configura desde el entorno."
            ),
            slug=BOOTSTRAP_SLUG,
        )
    )


def downgrade() -> None:
    for table in (
        "organization_data_deletions",
        "organization_data_exports",
        "organization_retention_holds",
        "organization_import_findings",
        "organization_import_runs",
        "organization_usage_periods",
        "organization_provisioning_steps",
        "organization_provisioning_runs",
        "support_access_grants",
        "organization_entitlements",
        "organization_channel_bindings",
        "organization_secret_references",
        "organization_configuration_versions",
    ):
        op.drop_table(table)

    op.drop_index("uq_outbound_decision_queued", table_name="outbound_decisions")
    op.create_index(
        "uq_outbound_decision_queued",
        "outbound_decisions",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("outcome = 'Queued'"),
    )

    for table, old_name, new_name, _columns, schema in reversed(RENAMED_UNIQUES):
        op.drop_constraint(new_name, table, type_="unique", schema=schema)
    op.create_unique_constraint(
        "properties_property_key_key", "properties", ["property_key"]
    )
    op.create_unique_constraint("inbox_messages_wamid_key", "inbox_messages", ["wamid"])
    op.create_unique_constraint(
        "outbox_messages_idempotency_key_key", "outbox_messages", ["idempotency_key"]
    )
    op.create_unique_constraint(
        "admin_messages_update_id_key", "admin_messages", ["update_id"]
    )
    op.create_unique_constraint(
        "appointments_reference_key", "appointments", ["reference"]
    )
    op.create_unique_constraint(
        "uq_agent_sessions_channel_key", "agent_sessions", ["channel_key"]
    )
    op.create_unique_constraint(
        "website_messages_command_key_key", "website_messages", ["command_key"]
    )
    op.create_unique_constraint(
        "public_analytics_events_event_key_key", "public_analytics_events", ["event_key"]
    )
    op.create_unique_constraint(
        "uq_delivery_status_event",
        "delivery_statuses",
        ["provider_message_id", "status"],
    )
    op.create_unique_constraint(
        "uq_lead_followup_cycle_day",
        "lead_followups",
        ["cycle_id", "day_number", "channel"],
    )
    op.create_unique_constraint(
        "uq_snapshot_conversation_property",
        "availability_snapshots",
        ["conversation_id", "property_uuid"],
    )
    op.create_unique_constraint(
        "uq_reminder_appointment_kind",
        "appointment_reminders",
        ["appointment_id", "kind"],
    )
    op.create_unique_constraint(
        "uq_saved_collection_item",
        "saved_collection_items",
        ["collection_id", "listing_id"],
    )
    op.create_unique_constraint(
        "uq_price_item_package",
        "sponsorship_price_items",
        ["catalog_id", "package", "duration_days"],
    )
    op.create_unique_constraint(
        "uq_delivery_day", "sponsorship_delivery_days", ["campaign_id", "service_date"]
    )
    op.create_unique_constraint(
        "uq_catalog_listings_gallery_path", "catalog_listings", ["gallery_path"]
    )
    op.create_unique_constraint(
        "uq_catalog_listings_sheet_path", "catalog_listings", ["technical_sheet_path"]
    )
    op.create_unique_constraint(
        "analytics_outbox_event_key_key",
        "analytics_outbox",
        ["event_key"],
        schema=ANALYTICS,
    )
    op.create_unique_constraint(
        "domain_events_event_key_key", "domain_events", ["event_key"], schema=ANALYTICS
    )

    for table, name, _referred, _local, _remote in reversed(COMPOSITE_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
    for table, name, _columns, schema in reversed(PARENT_UNIQUES):
        op.drop_constraint(name, table, type_="unique", schema=schema)

    op.drop_index("ix_delivery_statuses_outbox", table_name="delivery_statuses")
    op.drop_constraint("channel_cursors_pkey", "channel_cursors", type_="primary")
    op.create_primary_key("channel_cursors_pkey", "channel_cursors", ["channel"])

    op.drop_index("ix_audit_events_organization", table_name="audit_events")
    op.drop_constraint("ck_audit_events_scope", "audit_events", type_="check")

    for table, _parent, _column, schema in reversed(BACKFILL):
        op.drop_constraint(f"fk_{table}_organization", table, type_="foreignkey")
        op.drop_column(table, "organization_id", schema=schema)
    for table, schema in reversed(DIRECT):
        op.drop_constraint(f"fk_{table}_organization", table, type_="foreignkey")
        op.drop_column(table, "organization_id", schema=schema)

    op.drop_constraint(
        "ck_organization_members_advisor_advises",
        "organization_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_organization_members_advisor_advises",
        "organization_members",
        "role <> 'RealEstateAdvisor' OR advises IS TRUE",
    )
    op.drop_constraint(
        "ck_organization_members_provisioned_by",
        "organization_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_organization_members_provisioned_by",
        "organization_members",
        "provisioned_by IN ('Configuration', 'Administrator')",
    )

    op.drop_constraint("ck_organizations_activated", "organizations", type_="check")
    op.drop_constraint("ck_organizations_status", "organizations", type_="check")
    for column in ("deprovisioned_at", "suspended_at", "activated_at", "status"):
        op.drop_column("organizations", column)

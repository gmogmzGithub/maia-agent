"""Organization scoping, product roles, and Contact separated from channel identity.

Revision ID: 0012_organization_and_contacts
Revises: 0011_quarantine_legacy_outbound

ADR-0045 deferred organization scoping deliberately: adding an ``organizations``
table that only the eligibility tables referenced would have been decoration
while Leads, Conversations, Appointments and Properties stayed implicitly
global. This is the cut where it can be applied coherently, so it is applied to
those four roots at once. Their children — Inbox, Outbox, consent, suppression,
decisions, cycles, follow-ups — reach the Organization through a NOT NULL
foreign key to one of the four and are therefore scoped without a redundant
column that could disagree.

What this migration will *not* invent:

* **members.** The Organization is created because Larevia is a documented
  product decision; its people are not. ``organization_members`` is created
  empty and reconciled at startup from explicit configuration, so no username
  becomes an implicit administrator by having existed in ``.env``.
* **identity.** Each legacy Lead becomes exactly one Contact. Two Leads are
  never merged: their WhatsApp ids are different strings, and any rule that
  joined them would be a guess about a person.
* **consent or stage.** Neither is touched here.

Downgrade drops the new tables and columns. The Contacts created here do not
survive it, which is the honest consequence of removing the table that holds
them; the Leads, Conversations, Appointments and Properties they were derived
from are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0012_organization_and_contacts"
down_revision: str | None = "0011_quarantine_legacy_outbound"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The four roots that stop being implicitly global.
SCOPED_ROOTS = ("properties", "leads", "conversations", "appointments")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=60), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # The initial Brokerage Organization. Inserted here rather than at startup
    # so that the NOT NULL backfill below has something to point at inside the
    # same transaction, and so an empty database and a legacy one converge on
    # exactly one row.
    op.execute(
        """
        INSERT INTO organizations (id, slug, display_name)
        VALUES (gen_random_uuid(), 'larevia', 'Larevia')
        ON CONFLICT (slug) DO NOTHING
        """
    )

    op.create_table(
        "organization_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("login", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("advises", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "is_default_advisor",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            "role IN ('OrganizationAdministrator', 'RealEstateAdvisor')",
            name="ck_organization_members_role",
        ),
        sa.CheckConstraint(
            "role <> 'RealEstateAdvisor' OR advises IS TRUE",
            name="ck_organization_members_advisor_advises",
        ),
        sa.CheckConstraint(
            "is_default_advisor IS FALSE OR advises IS TRUE",
            name="ck_organization_members_default_advises",
        ),
        sa.UniqueConstraint("login", name="uq_organization_members_login"),
    )
    op.create_index(
        "uq_organization_default_advisor",
        "organization_members",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_default_advisor IS TRUE"),
    )
    op.create_index(
        "ix_organization_members_org", "organization_members", ["organization_id", "role"]
    )

    op.create_table(
        "contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=200), nullable=True),
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
    )
    op.create_index("ix_contacts_org", "contacts", ["organization_id", "created_at"])

    op.create_table(
        "contact_channel_identities",
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
            "channel", sa.String(length=20), nullable=False, server_default="WhatsApp"
        ),
        sa.Column("identity", sa.String(length=120), nullable=False),
        sa.Column("trust", sa.String(length=12), nullable=False),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("channel = 'WhatsApp'", name="ck_contact_identity_channel"),
        sa.CheckConstraint(
            "trust IN ('Verified', 'Asserted')", name="ck_contact_identity_trust"
        ),
        sa.CheckConstraint(
            "channel <> 'WhatsApp' OR lead_id IS NOT NULL",
            name="ck_contact_identity_whatsapp_lead",
        ),
        sa.UniqueConstraint(
            "organization_id", "channel", "identity", name="uq_contact_identity"
        ),
        sa.UniqueConstraint("lead_id", name="uq_contact_identity_lead"),
    )
    op.create_index(
        "ix_contact_identities_contact", "contact_channel_identities", ["contact_id"]
    )

    # -- Scope the four roots ------------------------------------------------
    #
    # Added nullable, backfilled, then made NOT NULL: an existing database has
    # rows, and a NOT NULL column with no default cannot be added to them.
    for table in SCOPED_ROOTS:
        op.add_column(
            table, sa.Column("organization_id", UUID(as_uuid=True), nullable=True)
        )
        op.execute(
            f"""
            UPDATE {table}
            SET organization_id = (SELECT id FROM organizations WHERE slug = 'larevia')
            WHERE organization_id IS NULL
            """
        )
        op.alter_column(table, "organization_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_organization",
            table,
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # -- One Contact per legacy WhatsApp channel identity --------------------
    #
    # ``profile_name`` is carried over as a display hint. It is a claim the
    # sender made to Meta, not verified identity, and the Contact row says so
    # by keeping it in ``display_name`` rather than in a legal-name field.
    # A temporary mapping rather than one clever data-modifying CTE: the
    # Contact and its channel identity are inserted by separate statements, so
    # the foreign key between them is satisfied in an obvious order instead of
    # relying on when PostgreSQL fires referential triggers for sibling CTEs.
    op.execute(
        """
        CREATE TEMPORARY TABLE _contact_backfill AS
        SELECT
            l.id AS lead_id,
            l.wa_id,
            l.profile_name,
            l.created_at,
            gen_random_uuid() AS contact_id
        FROM leads l
        WHERE NOT EXISTS (
            SELECT 1 FROM contact_channel_identities ci WHERE ci.lead_id = l.id
        )
        """
    )
    op.execute(
        """
        INSERT INTO contacts (id, organization_id, display_name, created_at, updated_at)
        SELECT
            b.contact_id,
            (SELECT id FROM organizations WHERE slug = 'larevia'),
            b.profile_name,
            b.created_at,
            b.created_at
        FROM _contact_backfill b
        """
    )
    op.execute(
        """
        INSERT INTO contact_channel_identities (
            id, organization_id, contact_id, channel, identity, trust, lead_id,
            first_seen_at
        )
        SELECT
            gen_random_uuid(),
            (SELECT id FROM organizations WHERE slug = 'larevia'),
            b.contact_id,
            'WhatsApp',
            b.wa_id,
            'Verified',
            b.lead_id,
            b.created_at
        FROM _contact_backfill b
        """
    )
    op.execute("DROP TABLE _contact_backfill")

    # -- Conversation content expires separately from commercial history -----
    for table in ("inbox_messages", "outbox_messages"):
        op.add_column(
            table,
            sa.Column("content_expired_at", sa.DateTime(timezone=True), nullable=True),
        )
    # Superseded by ``ix_inbox_messages_unexpired`` in revision 0014: leading
    # with a column that is NULL for nearly every row indexes almost nothing.
    # Left here rather than rewritten so an already-migrated database follows
    # the same path this one did.
    op.create_index(
        "ix_inbox_messages_retention",
        "inbox_messages",
        ["content_expired_at", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_messages_retention", table_name="inbox_messages")
    for table in ("inbox_messages", "outbox_messages"):
        op.drop_column(table, "content_expired_at")

    for table in reversed(SCOPED_ROOTS):
        op.drop_constraint(f"fk_{table}_organization", table, type_="foreignkey")
        op.drop_column(table, "organization_id")

    op.drop_index(
        "ix_contact_identities_contact", table_name="contact_channel_identities"
    )
    op.drop_table("contact_channel_identities")
    op.drop_index("ix_contacts_org", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_organization_members_org", table_name="organization_members")
    op.drop_index("uq_organization_default_advisor", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_table("organizations")

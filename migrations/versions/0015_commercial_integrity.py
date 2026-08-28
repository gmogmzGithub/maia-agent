"""Organization-safe references, Transactions, and concurrency invariants.

Revision ID: 0015_commercial_integrity
Revises: 0014_commercial_query_indexes

The earlier revisions put ``organization_id`` on the commercial roots, but a
plain foreign key on each id still allowed a child to name Organization A and a
Contact, Opportunity or member from Organization B. This revision makes those
combinations impossible and changes WhatsApp identity uniqueness from global to
per Organization.

It also creates the separate Transaction required by ADR-0032 and records the
idempotency key used to complete a Next Action.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0015_commercial_integrity"
down_revision: str | None = "0014_commercial_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PARENT_UNIQUES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("properties", "uq_properties_org_id", ("organization_id", "id")),
    ("leads", "uq_leads_org_id", ("organization_id", "id")),
    ("conversations", "uq_conversations_org_id", ("organization_id", "id")),
    (
        "conversations",
        "uq_conversations_org_id_lead",
        ("organization_id", "id", "lead_id"),
    ),
    ("conversations", "uq_conversations_lead_id", ("lead_id", "id")),
    ("conversations", "uq_conversations_cycle_id", ("cycle_id", "id")),
    ("contacts", "uq_contacts_org_id", ("organization_id", "id")),
    (
        "organization_members",
        "uq_members_org_id",
        ("organization_id", "id"),
    ),
    ("property_needs", "uq_needs_org_id", ("organization_id", "id")),
    ("opportunities", "uq_opportunities_org_id", ("organization_id", "id")),
    (
        "inbox_messages",
        "uq_inbox_conversation_id",
        ("conversation_id", "id"),
    ),
    (
        "lead_engagement_cycles",
        "uq_cycles_lead_id",
        ("lead_id", "id"),
    ),
    (
        "next_actions",
        "uq_next_actions_org_opportunity_id",
        ("organization_id", "opportunity_id", "id"),
    ),
)


COMPOSITE_FKS: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "conversations",
        "fk_conversations_org_lead",
        "leads",
        ("organization_id", "lead_id"),
        ("organization_id", "id"),
    ),
    (
        "conversations",
        "fk_conversations_org_property",
        "properties",
        ("organization_id", "property_uuid"),
        ("organization_id", "id"),
    ),
    (
        "conversations",
        "fk_conversations_lead_cycle",
        "lead_engagement_cycles",
        ("lead_id", "cycle_id"),
        ("lead_id", "id"),
    ),
    (
        "appointments",
        "fk_appointments_org_conversation",
        "conversations",
        ("organization_id", "conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "appointments",
        "fk_appointments_org_lead",
        "leads",
        ("organization_id", "lead_id"),
        ("organization_id", "id"),
    ),
    (
        "appointments",
        "fk_appointments_org_property",
        "properties",
        ("organization_id", "property_uuid"),
        ("organization_id", "id"),
    ),
    (
        "appointments",
        "fk_appointments_conversation_lead",
        "conversations",
        ("organization_id", "conversation_id", "lead_id"),
        ("organization_id", "id", "lead_id"),
    ),
    (
        "contact_channel_identities",
        "fk_contact_identities_org_contact",
        "contacts",
        ("organization_id", "contact_id"),
        ("organization_id", "id"),
    ),
    (
        "contact_channel_identities",
        "fk_contact_identities_org_lead",
        "leads",
        ("organization_id", "lead_id"),
        ("organization_id", "id"),
    ),
    (
        "property_needs",
        "fk_property_needs_org_contact",
        "contacts",
        ("organization_id", "contact_id"),
        ("organization_id", "id"),
    ),
    (
        "property_need_criteria",
        "fk_need_criteria_org_need",
        "property_needs",
        ("organization_id", "property_need_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunities",
        "fk_opportunities_org_contact",
        "contacts",
        ("organization_id", "contact_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunities",
        "fk_opportunities_org_need",
        "property_needs",
        ("organization_id", "property_need_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunities",
        "fk_opportunities_org_advisor",
        "organization_members",
        ("organization_id", "responsible_advisor_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunities",
        "fk_opportunities_org_won_recorder",
        "organization_members",
        ("organization_id", "won_recorded_by"),
        ("organization_id", "id"),
    ),
    (
        "opportunity_origins",
        "fk_origins_org_opportunity",
        "opportunities",
        ("organization_id", "opportunity_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunity_origins",
        "fk_origins_org_property",
        "properties",
        ("organization_id", "property_uuid"),
        ("organization_id", "id"),
    ),
    (
        "opportunity_origins",
        "fk_origins_org_conversation",
        "conversations",
        ("organization_id", "first_conversation_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunity_origins",
        "fk_origins_conversation_inbox",
        "inbox_messages",
        ("first_conversation_id", "first_inbox_id"),
        ("conversation_id", "id"),
    ),
    (
        "opportunity_stage_transitions",
        "fk_transitions_org_opportunity",
        "opportunities",
        ("organization_id", "opportunity_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunity_assignments",
        "fk_assignments_org_opportunity",
        "opportunities",
        ("organization_id", "opportunity_id"),
        ("organization_id", "id"),
    ),
    (
        "opportunity_assignments",
        "fk_assignments_org_advisor",
        "organization_members",
        ("organization_id", "advisor_id"),
        ("organization_id", "id"),
    ),
    (
        "assignment_queue_entries",
        "fk_queue_org_opportunity",
        "opportunities",
        ("organization_id", "opportunity_id"),
        ("organization_id", "id"),
    ),
    (
        "next_actions",
        "fk_next_actions_org_opportunity",
        "opportunities",
        ("organization_id", "opportunity_id"),
        ("organization_id", "id"),
    ),
    (
        "next_actions",
        "fk_next_actions_org_member",
        "organization_members",
        ("organization_id", "responsible_member_id"),
        ("organization_id", "id"),
    ),
    (
        "next_actions",
        "fk_next_actions_same_opportunity_successor",
        "next_actions",
        ("organization_id", "opportunity_id", "superseded_by_id"),
        ("organization_id", "opportunity_id", "id"),
    ),
    (
        "opportunity_exceptions",
        "fk_exceptions_org_opportunity",
        "opportunities",
        ("organization_id", "opportunity_id"),
        ("organization_id", "id"),
    ),
    (
        "outbound_decisions",
        "fk_outbound_decisions_lead_conversation",
        "conversations",
        ("lead_id", "conversation_id"),
        ("lead_id", "id"),
    ),
    (
        "lead_followups",
        "fk_followups_cycle_conversation",
        "conversations",
        ("cycle_id", "conversation_id"),
        ("cycle_id", "id"),
    ),
)


def upgrade() -> None:
    op.drop_constraint("leads_wa_id_key", "leads", type_="unique")
    op.create_unique_constraint(
        "uq_leads_org_wa_id", "leads", ["organization_id", "wa_id"]
    )
    op.add_column(
        "next_actions",
        sa.Column("completion_command_key", sa.String(length=200), nullable=True),
    )
    op.create_unique_constraint(
        "uq_next_actions_completion_command",
        "next_actions",
        ["completion_command_key"],
    )

    for table, name, columns in PARENT_UNIQUES:
        op.create_unique_constraint(name, table, list(columns))
    for table, name, remote, local_columns, remote_columns in COMPOSITE_FKS:
        op.create_foreign_key(
            name,
            table,
            remote,
            list(local_columns),
            list(remote_columns),
            deferrable=True,
            initially="DEFERRED",
        )

    op.create_table(
        "commercial_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "property_uuid",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evidence", sa.String(length=60), nullable=False),
        sa.Column("evidence_detail", sa.Text(), nullable=False),
        sa.Column(
            "accepted_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("command_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence IN ('CompletedSale', 'SignedRentalAgreement', "
            "'AcceptedBindingPresale')",
            name="ck_commercial_transactions_evidence",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_transactions_org_id"),
    )
    op.create_index(
        "ix_commercial_transactions_org_completed",
        "commercial_transactions",
        ["organization_id", "completed_at"],
    )
    for name, remote, local, target in (
        (
            "fk_transactions_org_opportunity",
            "opportunities",
            ("organization_id", "opportunity_id"),
            ("organization_id", "id"),
        ),
        (
            "fk_transactions_org_contact",
            "contacts",
            ("organization_id", "contact_id"),
            ("organization_id", "id"),
        ),
        (
            "fk_transactions_org_property",
            "properties",
            ("organization_id", "property_uuid"),
            ("organization_id", "id"),
        ),
        (
            "fk_transactions_org_acceptor",
            "organization_members",
            ("organization_id", "accepted_by"),
            ("organization_id", "id"),
        ),
    ):
        op.create_foreign_key(
            name,
            "commercial_transactions",
            remote,
            list(local),
            list(target),
            deferrable=True,
            initially="DEFERRED",
        )

    # The list-query cache and assignment history are two representations of
    # one fact. Deferred triggers inspect the final transaction state, so the
    # module may insert/close history and update the cache in either order but
    # no caller can commit them divergent.
    op.execute(
        """
        CREATE FUNCTION check_opportunity_assignment_consistency(target_id uuid)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            cached uuid;
            historical uuid;
        BEGIN
            SELECT responsible_advisor_id INTO cached
              FROM opportunities WHERE id = target_id;
            IF NOT FOUND THEN RETURN; END IF;
            SELECT advisor_id INTO historical
              FROM opportunity_assignments
             WHERE opportunity_id = target_id AND unassigned_at IS NULL;
            IF cached IS DISTINCT FROM historical THEN
                RAISE EXCEPTION 'responsible advisor diverges from open assignment for %', target_id
                    USING ERRCODE = '23514';
            END IF;
            RETURN;
        END $$;

        CREATE FUNCTION check_assignment_from_opportunity()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM check_opportunity_assignment_consistency(NEW.id);
            RETURN NULL;
        END $$;

        CREATE FUNCTION check_assignment_from_history()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM check_opportunity_assignment_consistency(OLD.opportunity_id);
            ELSE
                PERFORM check_opportunity_assignment_consistency(NEW.opportunity_id);
            END IF;
            RETURN NULL;
        END $$;

        CREATE CONSTRAINT TRIGGER ck_opportunity_assignment_cache
        AFTER INSERT OR UPDATE OF responsible_advisor_id ON opportunities
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_assignment_from_opportunity();

        CREATE CONSTRAINT TRIGGER ck_assignment_opportunity_cache
        AFTER INSERT OR UPDATE OR DELETE ON opportunity_assignments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_assignment_from_history();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER ck_assignment_opportunity_cache ON opportunity_assignments"
    )
    op.execute("DROP TRIGGER ck_opportunity_assignment_cache ON opportunities")
    op.execute("DROP FUNCTION check_assignment_from_history()")
    op.execute("DROP FUNCTION check_assignment_from_opportunity()")
    op.execute("DROP FUNCTION check_opportunity_assignment_consistency(uuid)")

    op.drop_table("commercial_transactions")
    for table, name, _remote, _local, _target in reversed(COMPOSITE_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
    for table, name, _columns in reversed(PARENT_UNIQUES):
        op.drop_constraint(name, table, type_="unique")

    op.drop_constraint(
        "uq_next_actions_completion_command", "next_actions", type_="unique"
    )
    op.drop_column("next_actions", "completion_command_key")
    op.drop_constraint("uq_leads_org_wa_id", "leads", type_="unique")
    op.create_unique_constraint("leads_wa_id_key", "leads", ["wa_id"])

"""Property Needs, Opportunities, Assignment, Next Actions and exceptions.

Revision ID: 0013_opportunities_and_actions
Revises: 0012_organization_and_contacts

The tables that carry the operating promise: no qualified Opportunity without a
Responsible Advisor, an explicit stage, and a live Next Action or an auditable
exception.

Four constraints do most of the work, and they are constraints rather than
service-layer checks because a race must not be able to defeat them:

* ``uq_assignment_open`` — one open assignment per Opportunity, so two
  concurrent assignments resolve to one Responsible Advisor;
* ``uq_next_action_pending`` — one Pending Next Action per Opportunity, which is
  what makes "substituted" mean something;
* ``uq_assignment_queue_open`` — one open queue entry, so repeated assignment
  attempts do not pile up in the Administrator's queue;
* ``uq_need_criterion_current`` — one current value per named criterion, with
  the superseded rows retained.

The terminal-evidence CHECK constraints are the same idea applied to outcomes:
Lost needs a reason, Dormant needs one too, and Won needs recorded evidence and
the Administrator who accepted it. A conversational inference cannot satisfy
them by accident.

Legacy backfill opens one Demand Opportunity at stage ``New`` for each
Contact whose channel identity already has a Conversation, with an origin of
``LegacyBackfill``. ``New`` is the stage that asserts nothing — no criteria, no
advisor, no consent — which is why it is the only honest one to assign to
history. Opportunities are created for suppressed Contacts too: Do Not Contact
is a communication restriction, not an outcome, and hiding those Opportunities
would be the failure the CRM exists to prevent.

The alternative was to create no Opportunities at all and let intake open one on
the Contact's next message. It was rejected because it makes the operation's
existing backlog invisible until each person happens to write again — the CRM
would open reporting Follow-up Coverage over an empty pipeline while real
conversations sat unassigned. Assigning ``New`` is a claim, and a small one:
"somebody wrote to us and nothing has been established since". Everything a
reader might mistake for inference is instead recorded as absent, and the
stage-transition row says so in words.

Downgrade drops every table here. The commercial history they hold does not
survive that, which is stated rather than worked around.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0013_opportunities_and_actions"
down_revision: str | None = "0012_organization_and_contacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _org_fk(nullable: bool = False) -> sa.Column[UUID]:
    return sa.Column(
        "organization_id",
        UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=nullable,
    )


def _created_at(name: str = "created_at") -> sa.Column[sa.DateTime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "property_needs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transaction_intent", sa.String(length=20), nullable=True),
        sa.Column(
            "status", sa.String(length=10), nullable=False, server_default="Active"
        ),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("became_stale_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _created_at("updated_at"),
        sa.CheckConstraint(
            "transaction_intent IS NULL OR "
            "transaction_intent IN ('Buy', 'Rent', 'Sell', 'LeaseOut')",
            name="ck_property_needs_intent",
        ),
        sa.CheckConstraint(
            "status IN ('Active', 'Stale')", name="ck_property_needs_status"
        ),
        sa.CheckConstraint(
            "(status = 'Stale') = (became_stale_at IS NOT NULL)",
            name="ck_property_needs_stale_stamp",
        ),
    )
    op.create_index(
        "ix_property_needs_contact", "property_needs", ["contact_id", "created_at"]
    )
    op.create_index(
        "ix_property_needs_staleness",
        "property_needs",
        ["status", "last_confirmed_at"],
    )

    op.create_table(
        "property_need_criteria",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "property_need_id",
            UUID(as_uuid=True),
            sa.ForeignKey("property_needs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        _created_at("recorded_at"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('Confirmed', 'Pending')", name="ck_need_criteria_state"
        ),
        sa.CheckConstraint(
            "source IN ('ContactStated', 'ModelInferred', 'AdvisorRecorded')",
            name="ck_need_criteria_source",
        ),
        sa.CheckConstraint(
            "(state = 'Confirmed') = (confirmed_at IS NOT NULL)",
            name="ck_need_criteria_confirmed_stamp",
        ),
    )
    op.create_index(
        "uq_need_criterion_current",
        "property_need_criteria",
        ["property_need_id", "name"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "opportunities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_need_id",
            UUID(as_uuid=True),
            sa.ForeignKey("property_needs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False, server_default="New"),
        sa.Column(
            "responsible_advisor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_reason", sa.String(length=60), nullable=True),
        sa.Column("dormant_reason", sa.String(length=60), nullable=True),
        sa.Column("dormant_revisit_condition", sa.Text(), nullable=True),
        sa.Column("won_evidence", sa.String(length=60), nullable=True),
        sa.Column("won_evidence_detail", sa.Text(), nullable=True),
        sa.Column(
            "won_recorded_by",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at("last_activity_at"),
        _created_at(),
        _created_at("updated_at"),
        sa.CheckConstraint(
            "kind IN ('Demand', 'ListingAcquisition')", name="ck_opportunities_kind"
        ),
        sa.CheckConstraint(
            "stage IN ('New', 'InConversation', 'Qualified', 'Searching', "
            "'Visiting', 'Negotiating', 'Won', 'Lost', 'Dormant')",
            name="ck_opportunities_stage",
        ),
        sa.CheckConstraint(
            "stage <> 'Lost' OR lost_reason IS NOT NULL",
            name="ck_opportunities_lost_reason",
        ),
        sa.CheckConstraint(
            "stage <> 'Dormant' OR dormant_reason IS NOT NULL",
            name="ck_opportunities_dormant_reason",
        ),
        sa.CheckConstraint(
            "stage <> 'Won' OR "
            "(won_evidence IS NOT NULL AND won_recorded_by IS NOT NULL)",
            name="ck_opportunities_won_evidence",
        ),
        sa.CheckConstraint(
            "stage NOT IN ('Qualified', 'Searching', 'Visiting', 'Negotiating') "
            "OR qualified_at IS NOT NULL",
            name="ck_opportunities_qualified_stamp",
        ),
    )
    op.create_index(
        "ix_opportunities_org_stage", "opportunities", ["organization_id", "stage"]
    )
    op.create_index(
        "ix_opportunities_advisor", "opportunities", ["responsible_advisor_id", "stage"]
    )
    op.create_index(
        "ix_opportunities_contact", "opportunities", ["contact_id", "created_at"]
    )

    op.create_table(
        "opportunity_origins",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("campaign", sa.String(length=120), nullable=True),
        sa.Column("advertisement", sa.String(length=120), nullable=True),
        sa.Column("referral", sa.String(length=200), nullable=True),
        sa.Column(
            "property_uuid",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "first_conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "first_inbox_id",
            UUID(as_uuid=True),
            sa.ForeignKey("inbox_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _created_at("recorded_at"),
        sa.CheckConstraint(
            "source IN ('WhatsAppInbound', 'WebsiteConversation', 'Referral', "
            "'Campaign', 'AdvisorEntry', 'LegacyBackfill')",
            name="ck_opportunity_origins_source",
        ),
    )

    op.create_table(
        "opportunity_stage_transitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_stage", sa.String(length=20), nullable=True),
        sa.Column("to_stage", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("command_key", sa.String(length=200), nullable=False, unique=True),
        _created_at("occurred_at"),
    )
    op.create_index(
        "ix_stage_transitions_opportunity",
        "opportunity_stage_transitions",
        ["opportunity_id", "occurred_at"],
    )

    op.create_table(
        "opportunity_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "advisor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("assigned_by", sa.String(length=200), nullable=False),
        _created_at("assigned_at"),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "basis IN ('Preserved', 'PropertyExpert', 'DefaultAdvisor', 'ManualAdmin')",
            name="ck_opportunity_assignments_basis",
        ),
    )
    op.create_index(
        "uq_assignment_open",
        "opportunity_assignments",
        ["opportunity_id"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )
    op.create_index(
        "ix_assignments_advisor",
        "opportunity_assignments",
        ["advisor_id", "assigned_at"],
    )

    op.create_table(
        "assignment_queue_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        _created_at(),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "reason IN ('NoEligibleAdvisor', 'DefaultAdvisorInactive')",
            name="ck_assignment_queue_reason",
        ),
    )
    op.create_index(
        "uq_assignment_queue_open",
        "assignment_queue_entries",
        ["opportunity_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    op.create_table(
        "next_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column(
            "responsible_member_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organization_members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=12), nullable=False, server_default="Pending"
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=True),
        sa.Column("outcome_detail", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("command_key", sa.String(length=200), nullable=False, unique=True),
        _created_at(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "superseded_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("next_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "kind IN ('Qualify', 'Call', 'WhatsAppMessage', 'SendListings', "
            "'ScheduleVisit', 'VisitFollowUp', 'DocumentReview', 'Other')",
            name="ck_next_actions_kind",
        ),
        sa.CheckConstraint(
            "status IN ('Pending', 'Completed', 'Superseded', 'Cancelled')",
            name="ck_next_actions_status",
        ),
        sa.CheckConstraint(
            "(status = 'Completed') = (outcome IS NOT NULL)",
            name="ck_next_actions_outcome",
        ),
        sa.CheckConstraint(
            "(status = 'Completed') = (completed_at IS NOT NULL)",
            name="ck_next_actions_completed_stamp",
        ),
    )
    op.create_index(
        "uq_next_action_pending",
        "next_actions",
        ["opportunity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Pending'"),
    )
    op.create_index(
        "ix_next_actions_due", "next_actions", ["organization_id", "status", "due_at"]
    )
    op.create_index(
        "ix_next_actions_member",
        "next_actions",
        ["responsible_member_id", "status", "due_at"],
    )

    op.create_table(
        "opportunity_exceptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _org_fk(),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=200), nullable=False),
        sa.Column("command_key", sa.String(length=200), nullable=False, unique=True),
        _created_at("recorded_at"),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('AwaitingContact', 'ContactUnreachable', 'DoNotContact', "
            "'OutOfServiceArea', 'AdminReview')",
            name="ck_opportunity_exceptions_reason",
        ),
    )
    op.create_index(
        "uq_opportunity_exception_open",
        "opportunity_exceptions",
        ["opportunity_id"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
    )

    _backfill_legacy_opportunities()


def _backfill_legacy_opportunities() -> None:
    """One New Demand Opportunity per legacy Contact that already wrote in.

    Keyed on the Contact rather than the Conversation: engagement cycles come
    and go beneath a Lead (ADR-0012), and one commercial pursuit per historical
    thread would multiply the same person's history into unrelated pipelines.
    Contacts with no Conversation at all get nothing — there is no inquiry to
    represent.
    """
    op.execute(
        """
        CREATE TEMPORARY TABLE _opportunity_backfill AS
        SELECT
            gen_random_uuid() AS opportunity_id,
            c.id AS contact_id,
            c.organization_id,
            first_thread.conversation_id,
            first_thread.inbox_id,
            first_thread.started_at
        FROM contacts c
        JOIN contact_channel_identities ci ON ci.contact_id = c.id
        JOIN LATERAL (
            SELECT
                conv.id AS conversation_id,
                (
                    SELECT m.id
                    FROM inbox_messages m
                    WHERE m.conversation_id = conv.id
                    ORDER BY m.sent_at, m.persisted_at, m.id
                    LIMIT 1
                ) AS inbox_id,
                conv.created_at AS started_at
            FROM conversations conv
            WHERE conv.lead_id = ci.lead_id
            ORDER BY conv.created_at, conv.id
            LIMIT 1
        ) first_thread ON TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM opportunities o WHERE o.contact_id = c.id
        )
        """
    )
    op.execute(
        """
        INSERT INTO opportunities (
            id, organization_id, contact_id, kind, stage, last_activity_at,
            created_at, updated_at
        )
        SELECT
            b.opportunity_id, b.organization_id, b.contact_id, 'Demand', 'New',
            b.started_at, b.started_at, b.started_at
        FROM _opportunity_backfill b
        """
    )
    op.execute(
        """
        INSERT INTO opportunity_origins (
            id, organization_id, opportunity_id, source, channel,
            first_conversation_id, first_inbox_id, recorded_at
        )
        SELECT
            gen_random_uuid(), b.organization_id, b.opportunity_id,
            'LegacyBackfill', 'WhatsApp', b.conversation_id, b.inbox_id,
            b.started_at
        FROM _opportunity_backfill b
        """
    )
    op.execute(
        """
        INSERT INTO opportunity_stage_transitions (
            id, organization_id, opportunity_id, from_stage, to_stage, reason,
            detail, actor_type, actor_id, command_key, occurred_at
        )
        SELECT
            gen_random_uuid(), b.organization_id, b.opportunity_id, NULL, 'New',
            'LegacyBackfill',
            'Opportunity opened from existing WhatsApp history by revision 0013. '
            'No criteria, advisor, consent or later stage was inferred.',
            'Migration', '0013_opportunities_and_actions',
            'legacy-backfill:' || b.opportunity_id::text,
            b.started_at
        FROM _opportunity_backfill b
        """
    )
    op.execute("DROP TABLE _opportunity_backfill")


def downgrade() -> None:
    for table in (
        "opportunity_exceptions",
        "next_actions",
        "assignment_queue_entries",
        "opportunity_assignments",
        "opportunity_stage_transitions",
        "opportunity_origins",
        "opportunities",
        "property_need_criteria",
        "property_needs",
    ):
        op.drop_table(table)

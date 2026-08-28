"""Human operation, team administration and Advisor-owned visits.

Revision ID: 0018_human_operation_and_visits
Revises: 0017_assignment_trigger_repair

Stage 3 adds five capabilities and one backfill.

The capabilities: Advisor Absences that only an Administrator controls, Property
Expert designations that are explicitly *not* Opportunity ownership,
Conversation Handling Mode, unmet human-handoff requests with a stamped
escalation, and a durable internal-alert channel that is deliberately separate
from the customer Outbox.

The backfill: every existing appointment predates Advisor ownership. Rather than
invent an owner, `advisor_id` stays NULL on historical rows and Product refuses
to treat an unowned appointment as bookable work; the CRM Calendar shows them in
a "requires review" state instead. Downgrade drops the new tables and columns,
so the handling state and alerts they hold do not survive it.

`btree_gist` is created because two overlapping live absences for one Advisor
must be impossible under concurrency, and an application check cannot promise
that. The extension ships with the standard PostgreSQL distribution.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0018_human_operation_and_visits"
down_revision: str | None = "0017_assignment_trigger_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str, *, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    # -- Members gain the operational configuration an Administrator owns ----
    op.add_column(
        "organization_members",
        sa.Column(
            "provisioned_by",
            sa.String(length=20),
            nullable=False,
            server_default="Configuration",
        ),
    )
    op.add_column(
        "organization_members",
        sa.Column("calendar_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "organization_members",
        sa.Column("telegram_chat_id", sa.String(length=40), nullable=True),
    )
    # Existing rows came from configuration, which the server default above
    # already states. New rows get their provenance from the caller, so the
    # default is dropped to stop a future insert from silently claiming to be
    # configuration-owned.
    op.alter_column("organization_members", "provisioned_by", server_default=None)
    op.create_check_constraint(
        "ck_organization_members_provisioned_by",
        "organization_members",
        "provisioned_by IN ('Configuration', 'Administrator')",
    )

    # -- Assignment can now reach the expert branches, and record absence ----
    op.drop_constraint(
        "ck_opportunity_assignments_basis", "opportunity_assignments", type_="check"
    )
    op.create_check_constraint(
        "ck_opportunity_assignments_basis",
        "opportunity_assignments",
        "basis IN ('Preserved', 'PropertyExpert', 'ExpertBackup', "
        "'DefaultAdvisor', 'ManualAdmin')",
    )
    op.drop_constraint(
        "ck_assignment_queue_reason", "assignment_queue_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_assignment_queue_reason",
        "assignment_queue_entries",
        "reason IN ('NoEligibleAdvisor', 'DefaultAdvisorInactive', "
        "'EveryCandidateAbsent')",
    )

    # -- Advisor Absences ----------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "advisor_absences",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("advisor_id", UUID(as_uuid=True), nullable=False),
        _timestamp("starts_at", nullable=False),
        _timestamp("ends_at", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("recorded_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _timestamp("ended_early_at"),
        _timestamp("cancelled_at"),
        sa.Column("ended_by", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["advisor_id"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["ended_by"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_advisor_absence_period"),
        sa.CheckConstraint(
            "ended_by IS NOT NULL OR (ended_early_at IS NULL AND cancelled_at IS NULL)",
            name="ck_advisor_absence_ended_by",
        ),
    )
    op.create_index(
        "ix_advisor_absences_advisor", "advisor_absences", ["advisor_id", "starts_at"]
    )
    # The real guarantee: one Advisor cannot hold two live overlapping absences,
    # however many Administrators press the button at once.
    op.execute(
        """
        ALTER TABLE advisor_absences
            ADD CONSTRAINT ex_advisor_absence_overlap
            EXCLUDE USING gist (
                advisor_id WITH =,
                tstzrange(starts_at, ends_at) WITH &&
            )
            WHERE (cancelled_at IS NULL)
        """
    )

    # -- Property Experts ----------------------------------------------------
    op.create_table(
        "property_experts",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("property_uuid", UUID(as_uuid=True), nullable=False),
        sa.Column("advisor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("designated_by", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "designated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _timestamp("revoked_at"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["property_uuid"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["advisor_id"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["designated_by"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "role IN ('Primary', 'Backup')", name="ck_property_expert_role"
        ),
        sa.CheckConstraint(
            "(role = 'Primary') = (rank = 0)", name="ck_property_expert_rank"
        ),
    )
    op.create_index(
        "uq_property_expert_primary",
        "property_experts",
        ["property_uuid"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL AND role = 'Primary'"),
    )
    op.create_index(
        "uq_property_expert_live",
        "property_experts",
        ["property_uuid", "advisor_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_property_experts_advisor", "property_experts", ["advisor_id"])

    # -- Conversation Handling Mode -----------------------------------------
    op.create_table(
        "conversation_handling",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="Maia"),
        sa.Column("holder_member_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "since",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=60), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["holder_member_id"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_conversation_handling"),
        sa.CheckConstraint(
            "mode IN ('Maia', 'Human', 'AwaitingContact', 'AdminReview')",
            name="ck_conversation_handling_mode",
        ),
        sa.CheckConstraint(
            "(mode = 'Human') = (holder_member_id IS NOT NULL)",
            name="ck_conversation_handling_holder",
        ),
    )

    # -- Human handoff requests ---------------------------------------------
    op.create_table(
        "human_handoff_requests",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=True),
        sa.Column("opportunity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("advisor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=14), nullable=False, server_default="Pending"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _timestamp("escalate_at", nullable=False),
        _timestamp("advisor_alert_at"),
        _timestamp("admin_alert_at"),
        _timestamp("resolved_at"),
        sa.Column("resolved_by", UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_inbox_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["advisor_id"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_inbox_id"], ["inbox_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "source IN ('ContactRequest', 'PostHandoffRouting', 'HumanInitiated')",
            name="ck_handoff_source",
        ),
        sa.CheckConstraint(
            "status IN ('Pending', 'Acknowledged', 'Cancelled')",
            name="ck_handoff_status",
        ),
        sa.CheckConstraint(
            "(status = 'Pending') = (resolved_at IS NULL)",
            name="ck_handoff_resolution",
        ),
    )
    op.create_index(
        "uq_handoff_open",
        "human_handoff_requests",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'Pending'"),
    )
    op.create_index(
        "ix_handoff_escalation", "human_handoff_requests", ["status", "escalate_at"]
    )

    # -- The internal alert channel -----------------------------------------
    op.create_table(
        "internal_alerts",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("recipient_member_id", UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=14), nullable=False, server_default="Pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _timestamp("claimed_at"),
        _timestamp("delivered_at"),
        _timestamp("acknowledged_at"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_member_id"], ["organization_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('Pending', 'Sent', 'Undeliverable', 'Failed')",
            name="ck_internal_alert_status",
        ),
        sa.UniqueConstraint(
            "organization_id", "dedupe_key", name="uq_internal_alert_dedupe"
        ),
    )
    op.create_index(
        "ix_internal_alerts_pending", "internal_alerts", ["status", "created_at"]
    )
    op.create_index(
        "ix_internal_alerts_recipient",
        "internal_alerts",
        ["recipient_member_id", "created_at"],
    )

    # -- Appointments belong to an Advisor ----------------------------------
    op.add_column(
        "appointments", sa.Column("advisor_id", UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "appointments",
        sa.Column("conducting_advisor_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "appointments", sa.Column("calendar_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("opportunity_id", UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "appointments", sa.Column("rescheduled_to_id", UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "appointments",
        sa.Column("rescheduled_from_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "appointments", sa.Column("attendance", sa.String(length=12), nullable=True)
    )
    op.add_column("appointments", _timestamp("attendance_recorded_at"))
    op.add_column(
        "appointments",
        sa.Column("attendance_recorded_by", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("appointments", sa.Column("visit_outcome", sa.Text(), nullable=True))
    op.add_column(
        "appointments",
        sa.Column(
            "reschedule_invitation_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_foreign_key(
        "fk_appointments_advisor",
        "appointments",
        "organization_members",
        ["advisor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_appointments_conducting_advisor",
        "appointments",
        "organization_members",
        ["conducting_advisor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_appointments_attendance_author",
        "appointments",
        "organization_members",
        ["attendance_recorded_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_appointments_opportunity",
        "appointments",
        "opportunities",
        ["opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_appointments_rescheduled_to",
        "appointments",
        "appointments",
        ["rescheduled_to_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_appointments_rescheduled_from",
        "appointments",
        "appointments",
        ["rescheduled_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    op.create_check_constraint(
        "ck_appointments_status",
        "appointments",
        "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview', "
        "'Cancelled', 'Rescheduled')",
    )
    op.create_check_constraint(
        "ck_appointments_attendance",
        "appointments",
        "attendance IS NULL OR attendance IN ('Attended', 'Missed')",
    )
    op.create_check_constraint(
        "ck_appointments_attendance_author",
        "appointments",
        "(attendance IS NULL) = (attendance_recorded_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_appointments_reschedule_invitation",
        "appointments",
        "reschedule_invitation_authorized IS FALSE OR attendance = 'Missed'",
    )
    op.create_index("ix_appointments_advisor", "appointments", ["advisor_id", "starts_at"])

    # A quote names whose calendar it came from.
    op.add_column(
        "availability_snapshots",
        sa.Column("advisor_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_availability_snapshots_advisor",
        "availability_snapshots",
        "organization_members",
        ["advisor_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "appointment_reminders",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("appointment_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        _timestamp("due_at", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _timestamp("settled_at"),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["appointment_id"], ["appointments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('DayBefore', 'DayOf')", name="ck_reminder_kind"),
        sa.UniqueConstraint(
            "appointment_id", "kind", name="uq_reminder_appointment_kind"
        ),
    )
    op.create_index("ix_reminders_due", "appointment_reminders", ["settled_at", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_reminders_due", table_name="appointment_reminders")
    op.drop_table("appointment_reminders")

    op.drop_constraint(
        "fk_availability_snapshots_advisor", "availability_snapshots", type_="foreignkey"
    )
    op.drop_column("availability_snapshots", "advisor_id")

    op.drop_index("ix_appointments_advisor", table_name="appointments")
    for name in (
        "ck_appointments_reschedule_invitation",
        "ck_appointments_attendance_author",
        "ck_appointments_attendance",
    ):
        op.drop_constraint(name, "appointments", type_="check")
    op.drop_constraint("ck_appointments_status", "appointments", type_="check")
    # A row that reached Rescheduled has no pre-Stage-3 meaning. It is folded
    # into Cancelled rather than dropped: the visit genuinely did not happen at
    # that time, and inventing Confirmed would be worse.
    op.execute(
        "UPDATE appointments SET status = 'Cancelled' WHERE status = 'Rescheduled'"
    )
    op.create_check_constraint(
        "ck_appointments_status",
        "appointments",
        "status IN ('Pending', 'Confirmed', 'Rejected', 'NeedsReview', 'Cancelled')",
    )
    for name in (
        "fk_appointments_rescheduled_from",
        "fk_appointments_rescheduled_to",
        "fk_appointments_opportunity",
        "fk_appointments_attendance_author",
        "fk_appointments_conducting_advisor",
        "fk_appointments_advisor",
    ):
        op.drop_constraint(name, "appointments", type_="foreignkey")
    for column in (
        "reschedule_invitation_authorized",
        "visit_outcome",
        "attendance_recorded_by",
        "attendance_recorded_at",
        "attendance",
        "rescheduled_from_id",
        "rescheduled_to_id",
        "opportunity_id",
        "calendar_id",
        "conducting_advisor_id",
        "advisor_id",
    ):
        op.drop_column("appointments", column)

    op.drop_index("ix_internal_alerts_recipient", table_name="internal_alerts")
    op.drop_index("ix_internal_alerts_pending", table_name="internal_alerts")
    op.drop_table("internal_alerts")

    op.drop_index("ix_handoff_escalation", table_name="human_handoff_requests")
    op.drop_index("uq_handoff_open", table_name="human_handoff_requests")
    op.drop_table("human_handoff_requests")

    op.drop_table("conversation_handling")

    op.drop_index("ix_property_experts_advisor", table_name="property_experts")
    op.drop_index("uq_property_expert_live", table_name="property_experts")
    op.drop_index("uq_property_expert_primary", table_name="property_experts")
    op.drop_table("property_experts")

    op.execute(
        "ALTER TABLE advisor_absences DROP CONSTRAINT ex_advisor_absence_overlap"
    )
    op.drop_index("ix_advisor_absences_advisor", table_name="advisor_absences")
    op.drop_table("advisor_absences")
    # btree_gist is left installed: another object may depend on it, and
    # dropping an extension is not this revision's business to undo.

    op.drop_constraint(
        "ck_assignment_queue_reason", "assignment_queue_entries", type_="check"
    )
    op.execute(
        "UPDATE assignment_queue_entries SET reason = 'NoEligibleAdvisor' "
        "WHERE reason = 'EveryCandidateAbsent'"
    )
    op.create_check_constraint(
        "ck_assignment_queue_reason",
        "assignment_queue_entries",
        "reason IN ('NoEligibleAdvisor', 'DefaultAdvisorInactive')",
    )
    op.drop_constraint(
        "ck_opportunity_assignments_basis", "opportunity_assignments", type_="check"
    )
    op.execute(
        "UPDATE opportunity_assignments SET basis = 'PropertyExpert' "
        "WHERE basis = 'ExpertBackup'"
    )
    op.create_check_constraint(
        "ck_opportunity_assignments_basis",
        "opportunity_assignments",
        "basis IN ('Preserved', 'PropertyExpert', 'DefaultAdvisor', 'ManualAdmin')",
    )

    op.drop_constraint(
        "ck_organization_members_provisioned_by", "organization_members", type_="check"
    )
    for column in ("telegram_chat_id", "calendar_id", "provisioned_by"):
        op.drop_column("organization_members", column)

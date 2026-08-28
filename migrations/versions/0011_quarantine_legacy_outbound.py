"""Quarantine pre-gate outbound work and preserve legacy opt-outs.

Revision ID: 0011_quarantine_legacy_outbound
Revises: 0010_outbound_eligibility

Revision 0010 introduced eligibility evidence, but an already-running Stage 0
database can still contain Pending or Sending Outbox rows created before that
evidence existed. They must not survive the cutover as deliverable work.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_quarantine_legacy_outbound"
down_revision: str | None = "0010_outbound_eligibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO suppression_records (
            id, lead_id, channel, scope, reason, evidence, recorded_at
        )
        SELECT
            gen_random_uuid(), l.id, 'WhatsApp', 'BusinessInitiated',
            'LegacyFollowUpOptOut', 'leads.follow_up_opt_out=true', now()
        FROM leads l
        WHERE l.follow_up_opt_out IS TRUE
          AND NOT EXISTS (
              SELECT 1 FROM suppression_records s
              WHERE s.lead_id = l.id
                AND s.channel = 'WhatsApp'
                AND s.revoked_at IS NULL
          )
        """
    )
    op.execute(
        """
        INSERT INTO consent_records (
            id, lead_id, channel, category, state, source, evidence, recorded_at
        )
        SELECT
            gen_random_uuid(), l.id, 'WhatsApp', 'Marketing', 'Revoked',
            'LegacyFollowUpOptOut', 'leads.follow_up_opt_out=true', now()
        FROM leads l
        WHERE l.follow_up_opt_out IS TRUE
          AND NOT EXISTS (
              SELECT 1 FROM consent_records c
              WHERE c.lead_id = l.id
                AND c.channel = 'WhatsApp'
                AND c.category = 'Marketing'
                AND c.state = 'Revoked'
                AND c.source = 'LegacyFollowUpOptOut'
          )
        """
    )

    # Keep one immutable audit event per affected row before changing status.
    # A Queued decision is the positive evidence that a row came through the
    # new gate; absence means the pre-Stage-1 row is unsafe to deliver.
    op.execute(
        """
        INSERT INTO audit_events (
            id, occurred_at, actor_type, actor_id, action,
            subject_type, subject_id, details
        )
        SELECT
            gen_random_uuid(), now(), 'Product', 'Migration0011',
            'QuarantineLegacyOutbound', 'OutboxMessage', o.id::text,
            jsonb_build_object(
                'previous_status', o.status,
                'reason', 'EligibilityEvidenceMissing'
            )
        FROM outbox_messages o
        WHERE o.status IN ('Pending', 'Sending')
          AND NOT EXISTS (
              SELECT 1 FROM outbound_decisions d
              WHERE d.outbox_id = o.id AND d.outcome = 'Queued'
          )
        """
    )
    op.execute(
        """
        UPDATE outbox_messages o
        SET status = CASE
                WHEN o.status = 'Sending' THEN 'DeliveryUnknown'
                ELSE 'Failed'
            END,
            next_attempt_at = NULL,
            last_error = CASE
                WHEN o.status = 'Sending'
                    THEN 'Quarantined during Stage 1 cutover: delivery may already have occurred.'
                ELSE 'Quarantined during Stage 1 cutover: no eligibility evidence.'
            END
        WHERE o.status IN ('Pending', 'Sending')
          AND NOT EXISTS (
              SELECT 1 FROM outbound_decisions d
              WHERE d.outbox_id = o.id AND d.outcome = 'Queued'
          )
        """
    )


def downgrade() -> None:
    # Safety data is intentionally irreversible. Re-enabling rows that may have
    # been sent, suppressed, or proven ineligible would be less compatible than
    # leaving them quarantined; revision 0010 can read every resulting value.
    pass

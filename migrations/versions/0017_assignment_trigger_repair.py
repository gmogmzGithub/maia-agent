"""Repair the deferred assignment consistency trigger in upgraded databases.

Revision ID: 0017_assignment_trigger_repair
Revises: 0016_commercial_command_receipts

An intermediate local 0015 revision installed one generic trigger function
that referenced ``NEW.opportunity_id`` even when invoked for an Opportunity
row.  The final 0015 source is correct for fresh databases; this forward repair
makes already-upgraded databases converge on that same definition.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_assignment_trigger_repair"
down_revision: str | None = "0016_commercial_command_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS ck_assignment_opportunity_cache
            ON opportunity_assignments;
        DROP TRIGGER IF EXISTS ck_opportunity_assignment_cache
            ON opportunities;
        DROP FUNCTION IF EXISTS assert_opportunity_assignment_consistency();
        DROP FUNCTION IF EXISTS check_assignment_from_history();
        DROP FUNCTION IF EXISTS check_assignment_from_opportunity();
        DROP FUNCTION IF EXISTS check_opportunity_assignment_consistency(uuid);

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
                RAISE EXCEPTION
                    'responsible advisor diverges from open assignment for %',
                    target_id USING ERRCODE = '23514';
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
                PERFORM check_opportunity_assignment_consistency(
                    OLD.opportunity_id
                );
            ELSE
                PERFORM check_opportunity_assignment_consistency(
                    NEW.opportunity_id
                );
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
    # The repair makes the installed schema match the final 0015 definition.
    # Reintroducing the invalid intermediate function would make downgrade
    # destructive; 0016 legitimately contains the same correct trigger.
    pass

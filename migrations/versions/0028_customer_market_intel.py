"""Add versioned transaction journeys and contributed market intelligence.

Revision ID: 0028_customer_market_intel
Revises: 0027_stage8_measurement_repairs
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028_customer_market_intel"
down_revision: str | None = "0027_stage8_measurement_repairs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS market_intelligence")
    op.execute(
        """
        CREATE TABLE transaction_journey_template_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          version integer NOT NULL,
          name varchar(200) NOT NULL,
          state varchar(20) NOT NULL DEFAULT 'Draft'
            CHECK (state IN ('Draft', 'Approved', 'Superseded')),
          plan jsonb NOT NULL,
          created_by uuid NOT NULL REFERENCES organization_members(id) ON DELETE RESTRICT,
          approved_by uuid REFERENCES organization_members(id) ON DELETE RESTRICT,
          created_at timestamptz NOT NULL DEFAULT now(),
          approved_at timestamptz,
          CONSTRAINT ck_journey_template_approval CHECK (
            state <> 'Approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)
          ),
          CONSTRAINT uq_journey_template_org_version UNIQUE (organization_id, version),
          CONSTRAINT uq_journey_template_org_id UNIQUE (organization_id, id)
        );
        CREATE INDEX ix_journey_template_org_state
          ON transaction_journey_template_versions (organization_id, state);

        CREATE TABLE transaction_journeys (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          opportunity_id uuid NOT NULL,
          template_version_id uuid NOT NULL,
          responsible_advisor_id uuid NOT NULL REFERENCES organization_members(id) ON DELETE RESTRICT,
          state varchar(20) NOT NULL DEFAULT 'Active'
            CHECK (state IN ('Active', 'Completed', 'Cancelled')),
          frozen_plan jsonb NOT NULL,
          started_by uuid NOT NULL REFERENCES organization_members(id) ON DELETE RESTRICT,
          completed_by uuid REFERENCES organization_members(id) ON DELETE RESTRICT,
          cancellation_reason text,
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          cancelled_at timestamptz,
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_transaction_journey_cancelled CHECK (
            state <> 'Cancelled' OR (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)
          ),
          CONSTRAINT ck_transaction_journey_completed CHECK (
            state <> 'Completed' OR (completed_at IS NOT NULL AND completed_by IS NOT NULL)
          ),
          CONSTRAINT fk_journey_org_opportunity FOREIGN KEY (organization_id, opportunity_id)
            REFERENCES opportunities(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT fk_journey_org_template FOREIGN KEY (organization_id, template_version_id)
            REFERENCES transaction_journey_template_versions(organization_id, id)
            DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT uq_transaction_journeys_org_id UNIQUE (organization_id, id),
          CONSTRAINT uq_journey_org_opportunity UNIQUE (organization_id, opportunity_id)
        );
        CREATE INDEX ix_transaction_journeys_org_state
          ON transaction_journeys (organization_id, state);

        CREATE TABLE transaction_milestones (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          journey_id uuid NOT NULL,
          sequence integer NOT NULL,
          code varchar(80) NOT NULL,
          name varchar(240) NOT NULL,
          responsibility varchar(120) NOT NULL,
          state varchar(20) NOT NULL DEFAULT 'Pending'
            CHECK (state IN ('Pending', 'InProgress', 'Blocked', 'Completed', 'Skipped', 'Cancelled')),
          required_evidence boolean NOT NULL DEFAULT true,
          evidence text,
          reason text,
          due_at timestamptz,
          confirmed_by uuid REFERENCES organization_members(id) ON DELETE RESTRICT,
          confirmed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_transaction_milestone_reason CHECK (
            state NOT IN ('Blocked', 'Skipped', 'Cancelled') OR reason IS NOT NULL
          ),
          CONSTRAINT ck_transaction_milestone_evidence CHECK (
            state <> 'Completed' OR required_evidence IS false OR evidence IS NOT NULL
          ),
          CONSTRAINT fk_milestone_org_journey FOREIGN KEY (organization_id, journey_id)
            REFERENCES transaction_journeys(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT uq_milestone_sequence UNIQUE (organization_id, journey_id, sequence)
        );
        CREATE INDEX ix_transaction_milestones_journey
          ON transaction_milestones (journey_id, sequence);

        CREATE TABLE purchase_profiles (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          opportunity_id uuid NOT NULL,
          journey_id uuid NOT NULL,
          birth_year integer CHECK (birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100),
          monthly_income numeric(14,2) CHECK (monthly_income IS NULL OR monthly_income >= 0),
          income_currency varchar(3),
          adults integer CHECK (adults IS NULL OR adults >= 1),
          children integer CHECK (children IS NULL OR children >= 0),
          financial_dependants integer CHECK (financial_dependants IS NULL OR financial_dependants >= 0),
          co_buyers integer CHECK (co_buyers IS NULL OR co_buyers >= 0),
          home_purchase_number integer CHECK (home_purchase_number IS NULL OR home_purchase_number >= 1),
          payment_path varchar(20) CHECK (payment_path IS NULL OR payment_path IN ('Cash', 'Credit', 'Combined')),
          financing_modality varchar(200),
          down_payment numeric(14,2),
          down_payment_currency varchar(3),
          target_monthly_payment numeric(14,2),
          target_payment_currency varchar(3),
          preapproval_state varchar(30) CHECK (preapproval_state IS NULL OR preapproval_state IN ('NotStarted', 'InProgress', 'Preapproved', 'Denied', 'NotApplicable')),
          field_states jsonb NOT NULL DEFAULT '{}'::jsonb,
          recorded_by uuid NOT NULL REFERENCES organization_members(id) ON DELETE RESTRICT,
          recorded_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          source_version integer NOT NULL DEFAULT 1,
          CONSTRAINT fk_profile_org_opportunity FOREIGN KEY (organization_id, opportunity_id)
            REFERENCES opportunities(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT fk_profile_org_journey FOREIGN KEY (organization_id, journey_id)
            REFERENCES transaction_journeys(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT uq_purchase_profiles_org_id UNIQUE (organization_id, id),
          CONSTRAINT uq_profile_org_opportunity UNIQUE (organization_id, opportunity_id),
          CONSTRAINT uq_profile_org_journey UNIQUE (organization_id, journey_id)
        );

        CREATE TABLE market_sale_records (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          opportunity_id uuid NOT NULL,
          journey_id uuid NOT NULL,
          purchase_profile_id uuid NOT NULL,
          state varchar(20) NOT NULL DEFAULT 'Preparation'
            CHECK (state IN ('Preparation', 'Completed', 'Cancelled')),
          outcome varchar(20) NOT NULL DEFAULT 'InProgress'
            CHECK (outcome IN ('InProgress', 'Won', 'Lost', 'Cancelled')),
          property_uuid uuid,
          property_type varchar(80),
          municipality varchar(120),
          colonia varchar(160),
          address text,
          land_area_sqm numeric(12,2) CHECK (land_area_sqm IS NULL OR land_area_sqm > 0),
          construction_area_sqm numeric(12,2) CHECK (construction_area_sqm IS NULL OR construction_area_sqm > 0),
          bedrooms integer,
          bathrooms numeric(4,1),
          parking_spaces integer,
          construction_year integer,
          property_condition varchar(30) CHECK (property_condition IS NULL OR property_condition IN ('New', 'Excellent', 'Good', 'NeedsImprovement')),
          publication_date date,
          completion_date date,
          published_price numeric(16,2) CHECK (published_price IS NULL OR published_price >= 0),
          published_currency varchar(3),
          appraisal_value numeric(16,2) CHECK (appraisal_value IS NULL OR appraisal_value >= 0),
          appraisal_currency varchar(3),
          paid_price numeric(16,2) CHECK (paid_price IS NULL OR paid_price >= 0),
          paid_currency varchar(3),
          field_states jsonb NOT NULL DEFAULT '{}'::jsonb,
          source_version integer NOT NULL DEFAULT 1,
          recorded_by uuid NOT NULL REFERENCES organization_members(id) ON DELETE RESTRICT,
          completed_by uuid REFERENCES organization_members(id) ON DELETE RESTRICT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT ck_market_sale_published_money CHECK ((published_price IS NULL) = (published_currency IS NULL)),
          CONSTRAINT ck_market_sale_appraisal_money CHECK ((appraisal_value IS NULL) = (appraisal_currency IS NULL)),
          CONSTRAINT ck_market_sale_paid_money CHECK ((paid_price IS NULL) = (paid_currency IS NULL)),
          CONSTRAINT ck_market_sale_completed_minimum CHECK (
            state <> 'Completed' OR (
              property_uuid IS NOT NULL AND property_type IS NOT NULL AND municipality IS NOT NULL
              AND completion_date IS NOT NULL AND paid_price IS NOT NULL AND paid_currency IS NOT NULL
              AND completed_by IS NOT NULL AND completed_at IS NOT NULL
            )
          ),
          CONSTRAINT fk_market_sale_org_opportunity FOREIGN KEY (organization_id, opportunity_id)
            REFERENCES opportunities(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT fk_market_sale_org_journey FOREIGN KEY (organization_id, journey_id)
            REFERENCES transaction_journeys(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT fk_market_sale_org_profile FOREIGN KEY (organization_id, purchase_profile_id)
            REFERENCES purchase_profiles(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT fk_market_sale_org_property FOREIGN KEY (organization_id, property_uuid)
            REFERENCES properties(organization_id, id) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT uq_market_sale_records_org_id UNIQUE (organization_id, id),
          CONSTRAINT uq_market_sale_org_opportunity UNIQUE (organization_id, opportunity_id),
          CONSTRAINT uq_market_sale_org_journey UNIQUE (organization_id, journey_id)
        );
        CREATE INDEX ix_market_sale_org_state
          ON market_sale_records (organization_id, state, completion_date);

        CREATE TABLE market_record_revisions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          source_type varchar(30) NOT NULL CHECK (source_type IN ('MarketSaleRecord', 'PurchaseProfile')),
          source_id uuid NOT NULL,
          source_version integer NOT NULL,
          old_values jsonb NOT NULL,
          new_values jsonb NOT NULL,
          database_role varchar(120) NOT NULL,
          changed_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_market_revision_source_version UNIQUE (source_type, source_id, source_version)
        );
        CREATE INDEX ix_market_revision_org_source
          ON market_record_revisions (organization_id, source_type, source_id);

        CREATE TABLE market_contributions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          source_type varchar(30) NOT NULL CHECK (source_type IN ('MarketSaleRecord', 'PurchaseProfile')),
          source_id uuid NOT NULL,
          source_version integer NOT NULL,
          event_key varchar(200) NOT NULL UNIQUE,
          payload jsonb NOT NULL,
          state varchar(20) NOT NULL DEFAULT 'Pending' CHECK (state IN ('Pending', 'Projected', 'Failed')),
          attempts integer NOT NULL DEFAULT 0,
          last_error text,
          created_at timestamptz NOT NULL DEFAULT now(),
          projected_at timestamptz,
          CONSTRAINT uq_market_contribution_source_version UNIQUE (source_type, source_id, source_version)
        );
        CREATE INDEX ix_market_contribution_pending ON market_contributions (state, created_at);

        CREATE TABLE market_intelligence.market_sale_resolutions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          reason text NOT NULL,
          resolved_by varchar(200) NOT NULL,
          resolved_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE market_intelligence.shared_market_records (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          source_organization_id uuid NOT NULL,
          source_record_id uuid NOT NULL,
          source_version integer NOT NULL,
          state varchar(20) NOT NULL,
          outcome varchar(20) NOT NULL,
          property_uuid uuid,
          property_type varchar(80),
          municipality varchar(120),
          colonia varchar(160),
          land_area_sqm numeric(12,2),
          construction_area_sqm numeric(12,2),
          bedrooms integer,
          bathrooms numeric(4,1),
          parking_spaces integer,
          construction_year integer,
          property_condition varchar(30),
          publication_date date,
          completion_date date,
          published_price numeric(16,2),
          published_currency varchar(3),
          appraisal_value numeric(16,2),
          appraisal_currency varchar(3),
          paid_price numeric(16,2),
          paid_currency varchar(3),
          field_states jsonb NOT NULL,
          resolution_id uuid REFERENCES market_intelligence.market_sale_resolutions(id) ON DELETE SET NULL,
          projected_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_shared_market_source UNIQUE (source_organization_id, source_record_id)
        );
        CREATE INDEX ix_shared_market_comparables ON market_intelligence.shared_market_records
          (state, paid_currency, municipality, property_type, completion_date);
        CREATE TABLE market_intelligence.shared_buyer_profiles (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          source_organization_id uuid NOT NULL,
          source_profile_id uuid NOT NULL,
          source_version integer NOT NULL,
          source_sale_record_id uuid NOT NULL,
          facts jsonb NOT NULL,
          field_states jsonb NOT NULL,
          projected_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_shared_profile_source UNIQUE (source_organization_id, source_profile_id)
        );
        CREATE TABLE market_intelligence.shared_market_record_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          source_record_id uuid NOT NULL,
          source_version integer NOT NULL,
          values jsonb NOT NULL,
          replaced_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_shared_market_version UNIQUE (source_record_id, source_version)
        );
        CREATE TABLE market_intelligence.market_sale_resolution_members (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          resolution_id uuid NOT NULL REFERENCES market_intelligence.market_sale_resolutions(id) ON DELETE CASCADE,
          shared_record_id uuid NOT NULL REFERENCES market_intelligence.shared_market_records(id) ON DELETE RESTRICT,
          CONSTRAINT uq_market_resolution_record UNIQUE (shared_record_id)
        );
        """
    )

    # The BEFORE trigger owns monotonically increasing source versions and the
    # revision. The AFTER trigger owns the durable projection request. Because
    # both run inside the writer's transaction, direct psql corrections cannot
    # update current truth without preserving and republishing it (ADR-0059).
    op.execute(
        """
        CREATE FUNCTION capture_market_source_revision() RETURNS trigger AS $$
        DECLARE source_name text;
        BEGIN
          source_name := CASE TG_TABLE_NAME
            WHEN 'market_sale_records' THEN 'MarketSaleRecord'
            ELSE 'PurchaseProfile'
          END;
          NEW.source_version := OLD.source_version + 1;
          NEW.updated_at := now();
          INSERT INTO market_record_revisions (
            id, organization_id, source_type, source_id, source_version,
            old_values, new_values, database_role, changed_at
          ) VALUES (
            gen_random_uuid(), OLD.organization_id, source_name, OLD.id,
            NEW.source_version, to_jsonb(OLD), to_jsonb(NEW), session_user, now()
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE FUNCTION enqueue_market_contribution() RETURNS trigger AS $$
        DECLARE source_name text;
        BEGIN
          source_name := CASE TG_TABLE_NAME
            WHEN 'market_sale_records' THEN 'MarketSaleRecord'
            ELSE 'PurchaseProfile'
          END;
          INSERT INTO market_contributions (
            id, organization_id, source_type, source_id, source_version,
            event_key, payload, state, attempts, created_at
          ) VALUES (
            gen_random_uuid(), NEW.organization_id, source_name, NEW.id,
            NEW.source_version, source_name || ':' || NEW.id || ':' || NEW.source_version,
            to_jsonb(NEW),
            'Pending', 0, now()
          ) ON CONFLICT (source_type, source_id, source_version) DO NOTHING;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER market_sale_revision_before_update
          BEFORE UPDATE ON market_sale_records
          FOR EACH ROW EXECUTE FUNCTION capture_market_source_revision();
        CREATE TRIGGER purchase_profile_revision_before_update
          BEFORE UPDATE ON purchase_profiles
          FOR EACH ROW EXECUTE FUNCTION capture_market_source_revision();
        CREATE TRIGGER market_sale_contribution_after_write
          AFTER INSERT OR UPDATE ON market_sale_records
          FOR EACH ROW EXECUTE FUNCTION enqueue_market_contribution();
        CREATE TRIGGER purchase_profile_contribution_after_write
          AFTER INSERT OR UPDATE ON purchase_profiles
          FOR EACH ROW EXECUTE FUNCTION enqueue_market_contribution();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS purchase_profile_contribution_after_write ON purchase_profiles;
        DROP TRIGGER IF EXISTS market_sale_contribution_after_write ON market_sale_records;
        DROP TRIGGER IF EXISTS purchase_profile_revision_before_update ON purchase_profiles;
        DROP TRIGGER IF EXISTS market_sale_revision_before_update ON market_sale_records;
        DROP FUNCTION IF EXISTS enqueue_market_contribution();
        DROP FUNCTION IF EXISTS capture_market_source_revision();
        DROP TABLE IF EXISTS market_intelligence.market_sale_resolution_members;
        DROP TABLE IF EXISTS market_intelligence.shared_market_record_versions;
        DROP TABLE IF EXISTS market_intelligence.shared_buyer_profiles;
        DROP TABLE IF EXISTS market_intelligence.shared_market_records;
        DROP TABLE IF EXISTS market_intelligence.market_sale_resolutions;
        DROP TABLE IF EXISTS market_contributions;
        DROP TABLE IF EXISTS market_record_revisions;
        DROP TABLE IF EXISTS market_sale_records;
        DROP TABLE IF EXISTS purchase_profiles;
        DROP TABLE IF EXISTS transaction_milestones;
        DROP TABLE IF EXISTS transaction_journeys;
        DROP TABLE IF EXISTS transaction_journey_template_versions;
        DROP SCHEMA IF EXISTS market_intelligence;
        """
    )

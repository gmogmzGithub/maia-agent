"""Property, source Listing, Offer, Development, Unit Model and media authority.

Revision ID: 0020_authoritative_catalog
Revises: 0019_appointment_authority

The Stage 0 Property Document remains immutable provenance.  This cut copies its
accepted physical facts and commercial terms once into Product's catalog; later
catalog edits never write back to the document.  Legacy accepted inventory is an
Organization Listing authorized for the pre-existing private Maia/visit use, but
stays Draft for public publication.  Nothing external is invented.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0020_authoritative_catalog"
down_revision: str | None = "0019_appointment_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "developments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("development_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("facts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("facts_review_state", sa.String(length=20), nullable=False),
        sa.Column("provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("organization_members.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("facts_review_state IN ('Pending', 'Approved', 'NeedsReview')", name="ck_developments_facts_review"),
        sa.UniqueConstraint("organization_id", "development_key", name="uq_developments_org_key"),
        sa.UniqueConstraint("organization_id", "id", name="uq_developments_org_id"),
    )
    op.create_table(
        "unit_models",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("development_id", UUID(as_uuid=True), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("facts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("facts_review_state", sa.String(length=20), nullable=False),
        sa.Column("provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("organization_members.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "development_id"],
            ["developments.organization_id", "developments.id"],
            ondelete="CASCADE",
            name="fk_unit_models_development_org",
        ),
        sa.CheckConstraint("facts_review_state IN ('Pending', 'Approved', 'NeedsReview')", name="ck_unit_models_facts_review"),
        sa.UniqueConstraint("development_id", "model_key", name="uq_unit_models_development_key"),
        sa.UniqueConstraint("organization_id", "id", name="uq_unit_models_org_id"),
    )

    op.add_column("properties", sa.Column("property_type", sa.String(length=30), nullable=True))
    op.add_column("properties", sa.Column("physical_facts", JSONB(), nullable=True))
    op.add_column("properties", sa.Column("facts_review_state", sa.String(length=20), nullable=True))
    op.add_column("properties", sa.Column("provenance", JSONB(), nullable=True))
    op.add_column("properties", sa.Column("facts_reviewed_by", UUID(as_uuid=True), nullable=True))
    op.add_column("properties", sa.Column("facts_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("properties", sa.Column("development_id", UUID(as_uuid=True), nullable=True))
    op.add_column("properties", sa.Column("unit_model_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_properties_facts_reviewer", "properties", "organization_members", ["facts_reviewed_by"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_properties_development", "properties", "developments", ["development_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_properties_unit_model", "properties", "unit_models", ["unit_model_id"], ["id"], ondelete="SET NULL")
    op.execute(
        """
        UPDATE properties
        SET property_type = 'Other', physical_facts = '{}'::jsonb,
            facts_review_state = 'Pending',
            provenance = jsonb_build_object('kind', 'LegacyProperty')
        """
    )
    op.execute(
        """
        UPDATE properties p
        SET property_type = COALESCE(v.document_metadata->>'property_type', 'Other'),
            physical_facts = v.document_metadata - ARRAY[
                'schema_version', 'property_id', 'name', 'operation',
                'price_amount', 'price_currency'
            ],
            facts_review_state = 'Approved',
            provenance = jsonb_build_object(
                'kind', 'PropertyDocument', 'version_id', v.id,
                'checksum', v.checksum, 'accepted_at', v.accepted_at
            ),
            facts_reviewed_at = v.accepted_at
        FROM property_document_versions v
        WHERE v.id = p.accepted_version_id
        """
    )
    op.alter_column("properties", "property_type", nullable=False)
    op.alter_column("properties", "physical_facts", nullable=False)
    op.alter_column("properties", "facts_review_state", nullable=False)
    op.alter_column("properties", "provenance", nullable=False)
    op.create_check_constraint("ck_properties_facts_review", "properties", "facts_review_state IN ('Pending', 'Approved', 'NeedsReview')")
    # Similar public names are weak evidence, never physical identity (SAN-045).
    op.drop_constraint("properties_normalized_name_key", "properties", type_="unique")
    op.create_index("ix_properties_normalized_name", "properties", ["organization_id", "normalized_name"])

    op.create_table(
        "catalog_listings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_key", sa.String(length=140), nullable=False),
        sa.Column("property_uuid", UUID(as_uuid=True), nullable=True),
        sa.Column("unit_model_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_reference", sa.String(length=300), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.Column("provenance", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("public_location", sa.String(length=300), nullable=True),
        sa.Column("facts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("facts_review_state", sa.String(length=20), nullable=False),
        sa.Column("availability", sa.String(length=30), nullable=False),
        sa.Column("publication_state", sa.String(length=20), nullable=False),
        sa.Column("authority", sa.String(length=20), nullable=False),
        sa.Column("authority_evidence", sa.Text(), nullable=True),
        sa.Column("freshness_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revalidate_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("automatic_tier", sa.String(length=20), nullable=True),
        sa.Column("tier_override", sa.String(length=20), nullable=True),
        sa.Column("tier_override_by", UUID(as_uuid=True), sa.ForeignKey("organization_members.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("tier_override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("readiness_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("readiness_override_by", UUID(as_uuid=True), sa.ForeignKey("organization_members.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("readiness_override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presentation_policy_version", sa.String(length=60), nullable=False),
        sa.Column("gallery_path", sa.String(length=240), nullable=False),
        sa.Column("technical_sheet_path", sa.String(length=240), nullable=False),
        sa.Column("legacy_document_version_id", UUID(as_uuid=True), sa.ForeignKey("property_document_versions.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "property_uuid"], ["properties.organization_id", "properties.id"], ondelete="RESTRICT", name="fk_catalog_listings_property_org"),
        sa.ForeignKeyConstraint(["organization_id", "unit_model_id"], ["unit_models.organization_id", "unit_models.id"], ondelete="RESTRICT", name="fk_catalog_listings_unit_model_org"),
        sa.CheckConstraint("(property_uuid IS NOT NULL) <> (unit_model_id IS NOT NULL)", name="ck_catalog_listings_subject"),
        sa.CheckConstraint("source_kind IN ('Organization', 'Collaborator')", name="ck_catalog_listings_source_kind"),
        sa.CheckConstraint("facts_review_state IN ('Pending', 'Approved', 'NeedsReview')", name="ck_catalog_listings_facts_review"),
        sa.CheckConstraint("availability IN ('Available', 'Reserved', 'Sold', 'Rented', 'TemporarilyUnavailable', 'Unknown')", name="ck_catalog_listings_availability"),
        sa.CheckConstraint("publication_state IN ('Draft', 'Published', 'Unpublished')", name="ck_catalog_listings_publication"),
        sa.CheckConstraint("authority IN ('Authorized', 'Pending', 'Expired', 'Revoked')", name="ck_catalog_listings_authority"),
        sa.CheckConstraint("automatic_tier IS NULL OR automatic_tier IN ('Larevia', 'Premium', 'SuperPremium')", name="ck_catalog_listings_auto_tier"),
        sa.CheckConstraint("tier_override IS NULL OR tier_override IN ('Larevia', 'Premium', 'SuperPremium')", name="ck_catalog_listings_tier_override"),
        sa.CheckConstraint("(tier_override IS NULL) = (tier_override_by IS NULL AND tier_override_at IS NULL)", name="ck_catalog_listings_tier_override_actor"),
        sa.CheckConstraint(
            "(readiness_override AND readiness_override_by IS NOT NULL "
            "AND readiness_override_at IS NOT NULL) OR "
            "(NOT readiness_override AND readiness_override_by IS NULL "
            "AND readiness_override_at IS NULL)",
            name="ck_catalog_listings_readiness_override_actor",
        ),
        sa.UniqueConstraint("organization_id", "listing_key", name="uq_catalog_listings_org_key"),
        sa.UniqueConstraint("organization_id", "id", name="uq_catalog_listings_org_id"),
        sa.UniqueConstraint("gallery_path", name="uq_catalog_listings_gallery_path"),
        sa.UniqueConstraint("technical_sheet_path", name="uq_catalog_listings_sheet_path"),
    )
    op.create_index("ix_catalog_listings_eligibility", "catalog_listings", ["organization_id", "publication_state", "authority", "availability"])
    op.create_index("ix_catalog_listings_property", "catalog_listings", ["property_uuid", "source_kind"])

    op.create_table(
        "listing_offers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("price_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("price_currency", sa.String(length=3), nullable=False),
        sa.Column("price_visibility", sa.String(length=10), nullable=False),
        sa.Column("hidden_price_copy", sa.String(length=120), nullable=True),
        sa.Column("terms", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("terms_review_state", sa.String(length=20), nullable=False),
        sa.Column("availability", sa.String(length=30), nullable=False),
        sa.Column("unavailable_reason", sa.String(length=40), nullable=True),
        sa.Column("legacy_document_version_id", UUID(as_uuid=True), sa.ForeignKey("property_document_versions.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "listing_id"], ["catalog_listings.organization_id", "catalog_listings.id"], ondelete="CASCADE", name="fk_listing_offers_listing_org"),
        sa.CheckConstraint("operation IN ('Sale', 'Rental', 'Presale')", name="ck_listing_offers_operation"),
        sa.CheckConstraint("price_amount > 0", name="ck_listing_offers_price"),
        sa.CheckConstraint("price_currency IN ('MXN', 'USD')", name="ck_listing_offers_currency"),
        sa.CheckConstraint("price_visibility IN ('Visible', 'Hidden')", name="ck_listing_offers_visibility"),
        sa.CheckConstraint("(price_visibility = 'Hidden') = (hidden_price_copy IS NOT NULL)", name="ck_listing_offers_hidden_copy"),
        sa.CheckConstraint("terms_review_state IN ('Pending', 'Approved', 'NeedsReview')", name="ck_listing_offers_terms_review"),
        sa.CheckConstraint("availability IN ('Available', 'Reserved', 'Completed', 'TemporarilyUnavailable', 'Withdrawn', 'Unknown')", name="ck_listing_offers_availability"),
        sa.UniqueConstraint("listing_id", "operation", name="uq_listing_offers_operation"),
        sa.UniqueConstraint("organization_id", "id", name="uq_listing_offers_org_id"),
    )
    op.create_index("ix_listing_offers_listing_availability", "listing_offers", ["listing_id", "availability"])

    op.create_table(
        "listing_media",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("listing_id", UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("authority", sa.String(length=20), nullable=False),
        sa.Column("authority_evidence", sa.Text(), nullable=True),
        sa.Column("is_cover", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("space_group", sa.String(length=80), nullable=True),
        sa.Column("high_resolution", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cache_keys", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("organization_members.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID(as_uuid=True), sa.ForeignKey("organization_members.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("storage_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cache_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id", "listing_id"], ["catalog_listings.organization_id", "catalog_listings.id"], ondelete="CASCADE", name="fk_listing_media_listing_org"),
        sa.CheckConstraint("content_type IN ('image/jpeg', 'image/png', 'image/webp')", name="ck_listing_media_type"),
        sa.CheckConstraint("byte_size > 0", name="ck_listing_media_size"),
        sa.CheckConstraint("length(checksum) = 64", name="ck_listing_media_checksum"),
        sa.CheckConstraint("authority IN ('Authorized', 'Pending', 'Expired', 'Revoked')", name="ck_listing_media_authority"),
        sa.CheckConstraint("sort_order >= 0", name="ck_listing_media_order"),
        sa.CheckConstraint("(authority = 'Revoked') = (revoked_at IS NOT NULL AND revoked_by IS NOT NULL)", name="ck_listing_media_revocation"),
    )
    op.create_index("uq_listing_media_cover", "listing_media", ["listing_id"], unique=True, postgresql_where=sa.text("is_cover IS TRUE AND revoked_at IS NULL"))
    op.create_index("uq_listing_media_order", "listing_media", ["listing_id", "sort_order"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_index("uq_listing_media_checksum", "listing_media", ["listing_id", "checksum"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_index("ix_listing_media_authority", "listing_media", ["listing_id", "authority", "sort_order"])

    op.execute(
        """
        INSERT INTO catalog_listings (
            id, organization_id, listing_key, property_uuid, source_kind,
            source_name, attribution, provenance, title, public_location, facts,
            facts_review_state, availability, publication_state, authority,
            authority_evidence, freshness_checked_at, automatic_tier,
            presentation_policy_version, gallery_path, technical_sheet_path,
            legacy_document_version_id, created_by, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), p.organization_id, p.property_key || '-legacy', p.id,
            'Organization', 'Catálogo Larevia', 'Inventario propio de Larevia',
            jsonb_build_object(
                'kind', 'LegacyPropertyDocument', 'property_id', p.id,
                'document_version_id', v.id, 'checksum', v.checksum
            ),
            p.name,
            concat_ws(', ', NULLIF(v.document_metadata->>'neighborhood', ''),
                NULLIF(v.document_metadata->>'city', ''),
                NULLIF(v.document_metadata->>'state', '')),
            p.physical_facts,
            p.facts_review_state,
            CASE p.status
                WHEN 'Active' THEN 'Available'
                WHEN 'Inactive' THEN CASE p.inactive_reason
                    WHEN 'Sold' THEN 'Sold'
                    WHEN 'Rented' THEN 'Rented'
                    WHEN 'Reserved' THEN 'Reserved'
                    WHEN 'TemporarilyUnavailable' THEN 'TemporarilyUnavailable'
                    ELSE 'Unknown' END
                ELSE 'Unknown' END,
            'Draft',
            CASE WHEN v.id IS NULL THEN 'Pending' ELSE 'Authorized' END,
            CASE WHEN v.id IS NULL THEN NULL ELSE 'Aceptación administrativa legacy del documento de propiedad' END,
            COALESCE(v.accepted_at, p.updated_at),
            CASE
                WHEN v.id IS NULL THEN NULL
                WHEN v.document_metadata->>'property_type' NOT IN ('House', 'Apartment') THEN NULL
                WHEN v.document_metadata->>'price_currency' = 'USD' THEN 'Premium'
                WHEN v.document_metadata->>'operation' = 'Sale'
                    AND (v.document_metadata->>'price_amount')::numeric > 20000000 THEN 'SuperPremium'
                WHEN v.document_metadata->>'operation' = 'Sale'
                    AND (v.document_metadata->>'price_amount')::numeric >= 12000000 THEN 'Premium'
                WHEN v.document_metadata->>'operation' = 'Rental'
                    AND (v.document_metadata->>'price_amount')::numeric > 85000 THEN 'SuperPremium'
                WHEN v.document_metadata->>'operation' = 'Rental'
                    AND (v.document_metadata->>'price_amount')::numeric >= 50000 THEN 'Premium'
                ELSE 'Larevia'
            END,
            'initial-2026-08-pending-san-058',
            '/catalogo/' || p.property_key || '-legacy/galeria',
            '/catalogo/' || p.property_key || '-legacy/ficha-tecnica',
            v.id, '0020_authoritative_catalog', p.created_at, p.updated_at
        FROM properties p
        LEFT JOIN property_document_versions v ON v.id = p.accepted_version_id
        """
    )
    op.execute(
        """
        INSERT INTO listing_offers (
            id, organization_id, listing_id, operation, price_amount,
            price_currency, price_visibility, hidden_price_copy, terms,
            terms_review_state, availability, unavailable_reason,
            legacy_document_version_id, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), l.organization_id, l.id,
            v.document_metadata->>'operation',
            (v.document_metadata->>'price_amount')::numeric,
            v.document_metadata->>'price_currency', 'Visible', NULL, '{}'::jsonb,
            'Approved',
            CASE WHEN l.availability = 'Available' THEN 'Available'
                 WHEN l.availability = 'Reserved' THEN 'Reserved'
                 WHEN l.availability IN ('Sold', 'Rented') THEN 'Completed'
                 WHEN l.availability = 'TemporarilyUnavailable' THEN 'TemporarilyUnavailable'
                 ELSE 'Unknown' END,
            CASE WHEN l.availability IN ('Sold', 'Rented') THEN l.availability ELSE NULL END,
            v.id, l.created_at, l.updated_at
        FROM catalog_listings l
        JOIN property_document_versions v ON v.id = l.legacy_document_version_id
        WHERE v.document_metadata->>'operation' IN ('Sale', 'Rental')
          AND v.document_metadata->>'price_currency' IN ('MXN', 'USD')
          AND (v.document_metadata->>'price_amount')::numeric > 0
        """
    )


def downgrade() -> None:
    op.drop_index("ix_listing_media_authority", table_name="listing_media")
    op.drop_index("uq_listing_media_checksum", table_name="listing_media")
    op.drop_index("uq_listing_media_order", table_name="listing_media")
    op.drop_index("uq_listing_media_cover", table_name="listing_media")
    op.drop_table("listing_media")
    op.drop_index("ix_listing_offers_listing_availability", table_name="listing_offers")
    op.drop_table("listing_offers")
    op.drop_index("ix_catalog_listings_property", table_name="catalog_listings")
    op.drop_index("ix_catalog_listings_eligibility", table_name="catalog_listings")
    op.drop_table("catalog_listings")

    op.drop_index("ix_properties_normalized_name", table_name="properties")
    # The legacy resolver required a unique normalized name.  Preserve every
    # physical row by disambiguating only this derived lookup key on rollback.
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY normalized_name ORDER BY created_at, id
            ) AS position
            FROM properties
        )
        UPDATE properties p
        SET normalized_name = left(p.normalized_name, 150) || ' ' || left(p.property_key, 40)
        FROM ranked r
        WHERE r.id = p.id AND r.position > 1
        """
    )
    op.create_unique_constraint("properties_normalized_name_key", "properties", ["normalized_name"])
    op.drop_constraint("ck_properties_facts_review", "properties", type_="check")
    op.drop_constraint("fk_properties_unit_model", "properties", type_="foreignkey")
    op.drop_constraint("fk_properties_development", "properties", type_="foreignkey")
    op.drop_constraint("fk_properties_facts_reviewer", "properties", type_="foreignkey")
    for column in (
        "unit_model_id",
        "development_id",
        "facts_reviewed_at",
        "facts_reviewed_by",
        "provenance",
        "facts_review_state",
        "physical_facts",
        "property_type",
    ):
        op.drop_column("properties", column)
    op.drop_table("unit_models")
    op.drop_table("developments")

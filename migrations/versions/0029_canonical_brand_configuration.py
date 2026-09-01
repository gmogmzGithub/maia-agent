"""Promote the canonical Brokerage Brand configuration key.

Revision ID: 0029_brand_config
Revises: 0028_customer_market_intel
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json

from alembic import op
import sqlalchemy as sa

revision: str = "0029_brand_config"
down_revision: str | None = "0028_customer_market_intel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical(document: Mapping[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def upgrade() -> None:
    """Canonicalize existing documents without discarding their history."""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, document FROM organization_configuration_versions")
    ).mappings()
    for row in rows:
        document = dict(row["document"])
        changed = False
        brand_value = document.get("brand")
        if isinstance(brand_value, Mapping) and "working_name" in brand_value:
            brand = dict(brand_value)
            legacy_name = brand.pop("working_name")
            brand.setdefault("name", legacy_name)
            document["brand"] = brand
            changed = True
        legacy_note = document.pop("note", None)
        if legacy_note is not None:
            notes_value = document.get("notes")
            notes = dict(notes_value) if isinstance(notes_value, Mapping) else {}
            notes.setdefault("bootstrap", legacy_note)
            document["notes"] = notes
            changed = True
        if not changed:
            continue
        canonical = _canonical(document)
        connection.execute(
            sa.text(
                "UPDATE organization_configuration_versions "
                "SET document = CAST(:document AS jsonb), checksum = :checksum "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "document": canonical,
                "checksum": hashlib.sha256(canonical.encode()).hexdigest(),
            },
        )


def downgrade() -> None:
    # Production brand identity is not made provisional again on rollback.
    pass

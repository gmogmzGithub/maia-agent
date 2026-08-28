"""The one writer of the audit trail.

Every consequential mutation records who did it, to what, and why (P-065). The
row is built here so the ingestion and administrative surfaces cannot drift into
writing differently-shaped history while both claiming to be "the audit trail".
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AuditEvent


async def record_audit(
    session: AsyncSession,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    subject_id: str,
    details: dict[str, Any],
    subject_type: str = "Property",
    commit: bool = True,
) -> None:
    """Append one audit row.

    Commits by default, because most callers record history about a mutation
    that has already landed. Pass ``commit=False`` when the audit row belongs to
    a transaction the caller is still assembling — an opt-out recorded while the
    message that expressed it is still being persisted must not become durable
    on its own.
    """
    session.add(
        AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            details=details,
        )
    )
    if commit:
        await session.commit()

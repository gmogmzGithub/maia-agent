"""The one writer of the audit trail.

Every consequential mutation records who did it, to what, and why (P-065). The
row is built here so the ingestion and administrative surfaces cannot drift into
writing differently-shaped history while both claiming to be "the audit trail".
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AuditEvent


async def record_audit(
    session: AsyncSession,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    subject_id: str,
    details: dict,
    subject_type: str = "Property",
) -> None:
    """Append one audit row and commit it."""
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
    await session.commit()

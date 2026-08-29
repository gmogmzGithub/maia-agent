"""The one writer of the audit trail.

Every consequential mutation records who did it, to what, and why (P-065). The
row is built here so the ingestion and administrative surfaces cannot drift into
writing differently-shaped history while both claiming to be "the audit trail".

Since Stage 9 every row also names the Organization whose history it is. That is
required rather than optional: an audit trail is one of the things a Brokerage
Organization is entitled to receive on export and to have deleted on request, and
neither is possible if the rows cannot be told apart. The single exception is an
action about the platform itself — provisioning an Organization, granting support
access — which happens before or above any one of them; the table's own check
constraint confines that exception to ``actor_type='Platform'`` so it cannot
become a convenient way to write unscoped history (ADR-0050).
"""

from __future__ import annotations

import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import AuditEvent

#: The one ``actor_type`` permitted to write a row with no Organization.
PLATFORM_ACTOR_TYPE = "Platform"


async def record_audit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
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

    ``organization_id`` is keyword-only and has no default. A default would be
    either wrong (attributing history to one Organization) or ``None`` (writing
    unscoped rows), and both are exactly the mistake this signature exists to
    prevent. ``None`` is accepted only from a platform actor, and rejected here
    rather than left to the database so the failure names the caller.
    """
    if organization_id is None and actor_type != PLATFORM_ACTOR_TYPE:
        raise ValueError(
            f"An audit event for {action!r} must name an Organization. Only "
            f"{PLATFORM_ACTOR_TYPE!r} may write platform-level history."
        )
    session.add(
        AuditEvent(
            organization_id=organization_id,
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

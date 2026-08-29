"""The list of Organizations, and the one question every worker asks about it.

A background pass that used to say "the Organization" now has to say "each
operating Organization", and there are seven of them across the workers. Spelling
the query once means the definition of *operating* cannot drift: a suspended
Organization is skipped by every pass or by none, never by four of them.

Suspended is skipped deliberately. A suspended Organization is one whose service
has been paused — for non-payment, at their request, during an incident — and
continuing to emit its analytics, count its sponsored days or expire its quotes
would be doing work on their behalf that nobody authorised. Provisioning and
deprovisioning are skipped for a stronger reason: their data is mid-flight.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import Organization, OrganizationStatus


@dataclass(frozen=True)
class OrganizationSummary:
    """Enough of an Organization to name it in a log line or a report."""

    organization_id: uuid.UUID
    slug: str
    display_name: str
    status: OrganizationStatus

    @classmethod
    def of(cls, row: Organization) -> OrganizationSummary:
        return cls(
            organization_id=row.id,
            slug=row.slug,
            display_name=row.display_name,
            status=OrganizationStatus(row.status),
        )


#: What *operating* means, spelled once. Both the summary query and the
#: identifier-only query read it, so neither can drift into a different
#: definition of which Organizations a background pass acts for.
_OPERATING = Organization.status == OrganizationStatus.ACTIVE.value

#: Ordered by creation so a pass's log output is stable across runs, which
#: matters more than it sounds: an operator comparing two ticks should not have
#: to work out whether the order changed or the content did.
_STABLE_ORDER = (Organization.created_at, Organization.slug)


async def operating_organizations(
    session: AsyncSession,
) -> list[OrganizationSummary]:
    """Every Organization a background pass should act for, oldest first."""
    rows = await session.scalars(
        select(Organization).where(_OPERATING).order_by(*_STABLE_ORDER)
    )
    return [OrganizationSummary.of(row) for row in rows]


async def operating_organization_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Just the identifiers, for a pass that logs nothing per Organization.

    Its own query rather than a projection of :func:`operating_organizations`:
    every worker tick calls this, and loading whole rows to keep one column of
    each is work the database can skip.
    """
    rows = await session.scalars(
        select(Organization.id).where(_OPERATING).order_by(*_STABLE_ORDER)
    )
    return list(rows)


async def all_organizations(session: AsyncSession) -> list[OrganizationSummary]:
    """Every Organization whatever its state, for the platform's own surfaces.

    Separate from :func:`operating_organizations` rather than a flag on it: a
    worker must never accidentally include a suspended Organization because a
    default changed, and a platform report must never hide one.
    """
    rows = await session.scalars(select(Organization).order_by(*_STABLE_ORDER))
    return [OrganizationSummary.of(row) for row in rows]

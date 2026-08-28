"""Loading one commercial record the Actor is allowed to touch.

Three modules need the same three steps before they may act on an Opportunity:
load it, refuse another Organization's, and refuse an Advisor somebody else's.
That is an *authorization* rule, and it had drifted into three copies with the
same Spanish string — a change to who may see an Opportunity would have had to
be made in all of them, with nothing failing if one was missed.

It lives in its own module rather than on either side because
:mod:`~realestate.domain.commercial.opportunities` already imports
:mod:`~realestate.domain.commercial.next_actions`; hosting it on one of them
would make the other's import circular.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import Opportunity
from realestate.domain.commercial.actors import Actor, NotFound

#: One wording for "you cannot reach this", whether it does not exist, belongs
#: to another Organization, or belongs to another Advisor. Telling an Advisor
#: that an Opportunity exists but is somebody else's already discloses the
#: pipeline.
UNREACHABLE = "No encontramos esa oportunidad."


async def visible_opportunity(
    session: AsyncSession,
    actor: Actor,
    opportunity_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Opportunity:
    """The Opportunity this Actor may act on, or :class:`NotFound`.

    ``lock`` takes the row for update, which every mutation wants: the stage
    read, the legality check and the write have to be one atomic step.
    """
    query = select(Opportunity).where(Opportunity.id == opportunity_id)
    if lock:
        query = query.with_for_update()
    found: Opportunity | None = await session.scalar(query)
    if found is None:
        raise NotFound(UNREACHABLE)
    actor.require_same_organization(found.organization_id)
    actor.require_owns(found.responsible_advisor_id, UNREACHABLE)
    return found

"""Loading one Listing the Actor is allowed to touch.

The three catalog command modules — administration, offers and media — each
need the same three steps before they may act on a Listing: load it, optionally
lock the row, and refuse another Organization's. That is an *authorization*
rule, and it had drifted into three byte-identical copies, so a change to who
may reach a Listing would have had to be made in all of them with nothing
failing if one was missed.

It lives in its own module for the reason
:mod:`~realestate.domain.commercial.records` gives: hosting it on one of the
three would make the others' imports circular.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import CatalogListing
from realestate.domain.commercial.actors import Actor, NotFound


async def visible_listing(
    session: AsyncSession,
    actor: Actor,
    listing_id: uuid.UUID,
    *,
    lock: bool = False,
) -> CatalogListing:
    """The Listing this Actor may act on, or :class:`NotFound`.

    ``lock`` takes the row for update, which every command that mutates a
    Listing does before it reads the state it is about to change.
    """
    statement = select(CatalogListing).where(CatalogListing.id == listing_id)
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise NotFound()
    actor.require_same_organization(row.organization_id)
    return row

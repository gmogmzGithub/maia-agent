"""Internal support access: temporary, explained, expiring, and audited.

The thing this module refuses to build is the thing every platform builds first: a
superadmin. An account that can read every Organization is convenient exactly once
— during the incident — and after that it is a permanent, invisible hole in the
isolation the rest of Stage 9 exists to create. It also makes the audit trail
useless, because "the platform read this record" cannot be distinguished from "the
customer's own administrator read it".

What replaces it:

* an internal engineer gets an **ordinary member row inside one Organization**,
  so every existing authorization check applies unchanged. There is no new code
  path with weaker rules, because there is no new code path;
* the role is Advisor, not Administrator, and the grant records ``ReadOnly``. A
  support engineer cannot mark an Opportunity Won, change an entitlement, publish
  a Listing or send a message, because an Advisor cannot;
* it **expires**. The expiry is on the grant, checked when the login is resolved,
  and the member row is deactivated the moment it passes. Nobody has to remember
  to revoke it;
* it names a **reason** and, when there is one, the customer's request. A grant
  with no written justification is refused;
* it is **counted**. ``use_count`` and ``last_used_at`` make "was this access
  actually needed" answerable afterwards, and a grant that expired unused is
  evidence the process is working rather than a wasted step.

The remaining exposure is honest and worth stating: an internal engineer with the
platform credential can grant themselves read access to any Organization. What
they cannot do is read it *without leaving a dated row that says so*, and that is
the property a customer can actually be promised (ADR-0054).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    MemberProvisioning,
    MemberRole,
    Organization,
    OrganizationMember,
    SupportAccessGrant,
    SupportAccessScope,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import CommercialError, NotFound
from realestate.domain.platform.authority import PlatformOperator, require_reason

logger = logging.getLogger(__name__)

#: The longest a grant may run. Eight hours is one working day: long enough to
#: finish an investigation, short enough that "we forgot to revoke it" cannot
#: become "they had access for a month". A longer investigation asks again, which
#: leaves a second dated row — which is the point.
MAX_GRANT_HOURS = 8

#: What a grant defaults to when the operator does not say. Deliberately short:
#: the common case is looking at one thing.
DEFAULT_GRANT_HOURS = 2

#: How support logins are named: ``soporte:<organization>:<engineer>``.
#:
#: The prefix is not security — it is legibility. An Administrator looking at
#: their own team surface must be able to tell at a glance that this row is
#: Maia's support engineer and not somebody they hired.
#:
#: The *Organization* is in the login because the member login namespace is
#: platform-wide (HTTP Basic carries no Organization). Without it one engineer
#: could hold a grant in only one Organization at a time, which is exactly the
#: moment two customers report a problem on the same afternoon.
SUPPORT_LOGIN_PREFIX = "soporte:"

SUPPORT_DISPLAY_NAME = "Soporte Maia (acceso temporal)"


class SupportAccessRefused(CommercialError):
    """The grant cannot be issued as asked."""

    message = "No se puede otorgar ese acceso de soporte."


@dataclass(frozen=True)
class GrantSupportAccess:
    """One request for temporary read-only access to one Organization."""

    organization_id: uuid.UUID
    #: The internal engineer's own login. Prefixed on the way in, so a support
    #: row can never be confused with a member the customer added.
    engineer_login: str
    reason: str
    command_key: str
    hours: int = DEFAULT_GRANT_HOURS
    #: Where the customer asked for help — a ticket, a call, a message.
    request_reference: str | None = None


@dataclass(frozen=True)
class SupportGrantView:
    """One grant, as a platform or organization surface reads it."""

    grant_id: uuid.UUID
    organization_id: uuid.UUID
    organization_slug: str
    subject_login: str
    reason: str
    request_reference: str | None
    granted_by: str
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None
    last_used_at: datetime | None
    use_count: int

    def live(self, at: datetime) -> bool:
        return self.revoked_at is None and at < self.expires_at

    @property
    def state(self) -> str:
        """Mexican Spanish standing, for a surface that shows a list."""
        if self.revoked_at is not None:
            return "Revocado"
        return "Vigente" if utc_now() < self.expires_at else "Expirado"


def support_login_for(engineer_login: str, organization_slug: str) -> str:
    """The member login one engineer holds inside one Organization.

    Idempotent on an already-qualified login, so a caller passing back what a
    previous grant produced gets the same value rather than a doubled prefix.
    """
    bare = engineer_login.strip().lower()
    if not bare:
        raise SupportAccessRefused("Falta el usuario de la persona de soporte.")
    slug = organization_slug.strip().lower()
    if not slug:
        raise SupportAccessRefused("Falta la organización del acceso de soporte.")
    qualified = f"{SUPPORT_LOGIN_PREFIX}{slug}:"
    return bare if bare.startswith(qualified) else qualified + bare


class SupportAccess:
    """Issue, revoke, expire and report temporary internal access.

    Hides: the member row a grant creates, the expiry sweep that deactivates it,
    the single-live-grant index, and the audit trail for each.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant(
        self,
        operator: PlatformOperator,
        command: GrantSupportAccess,
        *,
        at: datetime | None = None,
    ) -> SupportGrantView:
        """Issue one grant and the member row it entitles. Does not commit.

        Idempotent on ``command_key``: a resubmitted form replays the existing
        grant rather than extending it, because extending by accident is exactly
        how a two-hour window becomes a day.
        """
        reason = require_reason(command.reason)
        moment = at or utc_now()
        if not 1 <= command.hours <= MAX_GRANT_HOURS:
            raise SupportAccessRefused(
                f"El acceso de soporte dura entre 1 y {MAX_GRANT_HOURS} horas."
            )
        organization = await self._session.get(
            Organization, command.organization_id
        )
        if organization is None:
            raise NotFound("No encontramos esa organización.")

        replay = await self._session.scalar(
            select(SupportAccessGrant)
            .where(SupportAccessGrant.organization_id == command.organization_id)
            .where(SupportAccessGrant.command_key == command.command_key)
        )
        if replay is not None:
            return self._view(replay, organization.slug)

        login = support_login_for(command.engineer_login, organization.slug)
        live = await self._session.scalar(
            select(SupportAccessGrant)
            .where(SupportAccessGrant.organization_id == command.organization_id)
            .where(SupportAccessGrant.subject_login == login)
            .where(SupportAccessGrant.revoked_at.is_(None))
            .with_for_update()
        )
        if live is not None and moment < live.expires_at:
            raise SupportAccessRefused(
                "Esa persona ya tiene un acceso de soporte vigente en esta "
                "organización. Espera a que expire o revócalo antes de otorgar "
                "otro."
            )
        if live is not None:
            # An expired grant still holds the partial unique index. Closing it
            # here — rather than waiting for the sweep — is what lets a second
            # investigation start immediately after the first one lapsed.
            live.revoked_at = moment
            live.revoked_by = operator.label
            await self._session.flush()

        member = await self._support_member(command.organization_id, login)
        grant = SupportAccessGrant(
            organization_id=command.organization_id,
            subject_login=login,
            member_id=member.id,
            scope=SupportAccessScope.READ_ONLY.value,
            reason=reason,
            request_reference=command.request_reference,
            granted_by=operator.label,
            granted_at=moment,
            expires_at=moment + timedelta(hours=command.hours),
            command_key=command.command_key,
        )
        self._session.add(grant)
        await self._session.flush()

        await record_audit(
            self._session,
            organization_id=command.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="GrantSupportAccess",
            subject_type="SupportAccessGrant",
            subject_id=str(grant.id),
            details={
                "subject_login": login,
                "hours": command.hours,
                "expires_at": grant.expires_at.isoformat(),
                "reason": reason,
                "request_reference": command.request_reference,
                "scope": SupportAccessScope.READ_ONLY.value,
            },
            commit=False,
        )
        logger.info(
            "Granted read-only support access to %s in Organization %s until %s",
            login,
            organization.slug,
            grant.expires_at.isoformat(),
        )
        return self._view(grant, organization.slug)

    async def revoke(
        self,
        operator: PlatformOperator,
        *,
        grant_id: uuid.UUID,
        reason: str,
        at: datetime | None = None,
    ) -> SupportGrantView:
        """End one grant now and deactivate its member row. Does not commit."""
        explanation = require_reason(reason)
        moment = at or utc_now()
        grant = await self._session.get(
            SupportAccessGrant, grant_id, with_for_update=True
        )
        if grant is None:
            raise NotFound("No encontramos ese acceso de soporte.")
        organization = await self._session.get(Organization, grant.organization_id)
        slug = organization.slug if organization is not None else ""
        if grant.revoked_at is not None:
            return self._view(grant, slug)

        grant.revoked_at = moment
        grant.revoked_by = operator.label
        await self._deactivate(grant)
        await record_audit(
            self._session,
            organization_id=grant.organization_id,
            actor_type=operator.actor_type,
            actor_id=operator.label,
            action="RevokeSupportAccess",
            subject_type="SupportAccessGrant",
            subject_id=str(grant.id),
            details={
                "subject_login": grant.subject_login,
                "reason": explanation,
                "used": grant.use_count,
            },
            commit=False,
        )
        await self._session.flush()
        return self._view(grant, slug)

    async def expire_due(self, *, at: datetime | None = None) -> int:
        """Deactivate every lapsed grant's member row. Does not commit.

        Run by the background loop. It is a *safety net*, not the mechanism:
        :meth:`live_for_login` refuses an expired grant at resolution time, so an
        access does not depend on a worker having run. What the sweep adds is that
        the member row stops existing as an active row, which is what an
        Administrator sees on their own team surface.
        """
        moment = at or utc_now()
        rows = list(
            await self._session.scalars(
                select(SupportAccessGrant)
                .where(SupportAccessGrant.revoked_at.is_(None))
                .where(SupportAccessGrant.expires_at <= moment)
                .with_for_update(skip_locked=True)
            )
        )
        for grant in rows:
            grant.revoked_at = moment
            grant.revoked_by = "Platform:Expiry"
            await self._deactivate(grant)
            await record_audit(
                self._session,
                organization_id=grant.organization_id,
                actor_type="Platform",
                actor_id="SupportAccessExpiry",
                action="ExpireSupportAccess",
                subject_type="SupportAccessGrant",
                subject_id=str(grant.id),
                details={
                    "subject_login": grant.subject_login,
                    "used": grant.use_count,
                    # The interesting case. A grant nobody used is evidence the
                    # process asked for access it did not need.
                    "unused": grant.use_count == 0,
                },
                commit=False,
            )
        if rows:
            await self._session.flush()
            logger.info("Expired %d support access grant(s)", len(rows))
        return len(rows)

    async def live_for_login(
        self, login: str, *, at: datetime | None = None
    ) -> SupportAccessGrant | None:
        """The live grant behind a support login, or ``None``.

        Called on every resolution of a support login, which is what makes expiry
        real rather than dependent on the sweep. Records the use in the same
        breath: an access nobody counted is an access nobody can review.
        """
        if not login.startswith(SUPPORT_LOGIN_PREFIX):
            return None
        moment = at or utc_now()
        grant: SupportAccessGrant | None = await self._session.scalar(
            select(SupportAccessGrant)
            .where(SupportAccessGrant.subject_login == login)
            .where(SupportAccessGrant.revoked_at.is_(None))
            .order_by(SupportAccessGrant.granted_at.desc())
            .limit(1)
        )
        if grant is None:
            return None
        if moment >= grant.expires_at:
            logger.info(
                "Refused expired support access for %s (expired %s)",
                login,
                grant.expires_at.isoformat(),
            )
            return None
        grant.use_count += 1
        grant.last_used_at = moment
        await self._session.flush()
        return grant

    async def grants(
        self, organization_id: uuid.UUID | None = None
    ) -> list[SupportGrantView]:
        """Grants, newest first. One Organization's, or every one.

        The unscoped form is for the platform's own surface. An Organization's
        Administrator reads :meth:`grants_for_organization`, which cannot be
        asked for anybody else's.
        """
        query = select(SupportAccessGrant, Organization).join(
            Organization, Organization.id == SupportAccessGrant.organization_id
        )
        if organization_id is not None:
            query = query.where(
                SupportAccessGrant.organization_id == organization_id
            )
        rows = await self._session.execute(
            query.order_by(SupportAccessGrant.granted_at.desc())
        )
        return [self._view(grant, organization.slug) for grant, organization in rows]

    async def _support_member(
        self, organization_id: uuid.UUID, login: str
    ) -> OrganizationMember:
        """The member row a grant activates, created or reactivated.

        Reused rather than recreated, because assignments and audit rows may
        reference it from a previous investigation and history has to stay
        readable — the same reason ordinary members are deactivated instead of
        deleted (ADR-0047).

        ``advises`` is deliberately ``False``: a support engineer must not be
        assignable, or the deterministic assignment rule could route a real
        Opportunity to Maia's support desk.
        """
        member: OrganizationMember | None = await self._session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.login == login)
            .with_for_update()
        )
        if member is None:
            member = OrganizationMember(
                organization_id=organization_id,
                login=login,
                display_name=SUPPORT_DISPLAY_NAME,
                role=MemberRole.ADVISOR.value,
                advises=False,
                is_default_advisor=False,
                active=True,
                provisioned_by=MemberProvisioning.SUPPORT.value,
            )
            self._session.add(member)
        else:
            member.active = True
            member.role = MemberRole.ADVISOR.value
            member.advises = False
            member.provisioned_by = MemberProvisioning.SUPPORT.value
        await self._session.flush()
        return member

    async def _deactivate(self, grant: SupportAccessGrant) -> None:
        if grant.member_id is None:
            return
        member = await self._session.get(OrganizationMember, grant.member_id)
        if member is not None:
            member.active = False

    @staticmethod
    def _view(grant: SupportAccessGrant, slug: str) -> SupportGrantView:
        return SupportGrantView(
            grant_id=grant.id,
            organization_id=grant.organization_id,
            organization_slug=slug,
            subject_login=grant.subject_login,
            reason=grant.reason,
            request_reference=grant.request_reference,
            granted_by=grant.granted_by,
            granted_at=grant.granted_at,
            expires_at=grant.expires_at,
            revoked_at=grant.revoked_at,
            revoked_by=grant.revoked_by,
            last_used_at=grant.last_used_at,
            use_count=grant.use_count,
        )

"""The Organization and its people: one reconciled directory, one Actor lookup.

Two responsibilities that belong together because they are the same fact read
in two directions.

**Reconciliation** turns explicit configuration into member rows. The bootstrap
problem is real — somebody has to be an administrator before anybody can create
an administrator — and it is solved by declaring the initial team in
configuration rather than by treating the first credential that authenticates
as privileged. Reconciliation is idempotent, audited, and never deletes: a login
that disappears from configuration is deactivated, because assignments and Next
Actions point at it and history must stay readable.

**Resolution** turns an authenticated login into an
:class:`~realestate.domain.commercial.actors.Actor`. A credential with no member
row is refused. That is the whole migration to an unambiguous model: authority
now comes from a row that names an Organization and a role, not from the mere
existence of a password.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    LAREVIA_SLUG,
    MemberRole,
    Organization,
    OrganizationMember,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    UnknownMember,
    authority_for,
)

logger = logging.getLogger(__name__)

ROLE_LABELS: dict[str, str] = {
    MemberRole.ADMINISTRATOR.value: "Administrador de la organización",
    MemberRole.ADVISOR.value: "Asesor inmobiliario",
}


def parse_logins(raw: str) -> tuple[str, ...]:
    """Comma-separated logins, in order, without blanks or duplicates.

    Order is preserved because it is the only thing a human reading the
    configuration can rely on, and duplicates are dropped rather than rejected:
    a stray comma should not stop the product from starting.
    """
    seen: dict[str, None] = {}
    for part in raw.split(","):
        login = part.strip()
        if login:
            seen.setdefault(login, None)
    return tuple(seen)


@dataclass(frozen=True)
class DirectoryPlan:
    """The intended team, already validated as internally consistent."""

    administrators: tuple[str, ...]
    advisors: tuple[str, ...]
    default_advisor: str | None

    @classmethod
    def from_configuration(
        cls,
        *,
        administrators: str,
        advisors: str,
        default_advisor: str,
    ) -> DirectoryPlan:
        admin_logins = parse_logins(administrators)
        advisor_logins = parse_logins(advisors)
        default = default_advisor.strip() or None
        if default is not None and default not in set(admin_logins) | set(advisor_logins):
            # Fail loudly rather than silently leaving the operation without the
            # deterministic assignment fallback. A typo here would otherwise
            # send every new Opportunity to the Assignment Queue.
            raise ValueError(
                "ORGANIZATION_DEFAULT_ADVISOR_LOGIN must also appear in "
                "ORGANIZATION_ADMIN_LOGINS or ORGANIZATION_ADVISOR_LOGINS."
            )
        if default is None and len(advisor_logins) == 1:
            # One advisor is unambiguous, so requiring the operator to name it
            # twice buys nothing.
            default = advisor_logins[0]
        return cls(
            administrators=admin_logins,
            advisors=advisor_logins,
            default_advisor=default,
        )

    @property
    def logins(self) -> frozenset[str]:
        return frozenset(self.administrators) | frozenset(self.advisors)

    def role_of(self, login: str) -> MemberRole:
        return (
            MemberRole.ADMINISTRATOR
            if login in self.administrators
            else MemberRole.ADVISOR
        )

    def advises(self, login: str) -> bool:
        """Whether this member may own Opportunities.

        Being listed as an Advisor is the whole rule. An Administrator advises
        only when they are *also* listed as one, which is how "Santiago
        initially has both roles" is expressed without an ambiguous third role.
        """
        return login in self.advisors


@dataclass(frozen=True)
class Reconciliation:
    """What reconciliation changed. Reported at startup, asserted in tests."""

    organization_id: uuid.UUID
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    deactivated: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.deactivated)


class OrganizationDirectory:
    """The Organization's identity and membership.

    Hides: the singleton lookup, the partial unique index on the default
    Advisor, deactivation instead of deletion, and the audit trail for each.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def organization(self, slug: str | None = None) -> Organization:
        """The Brokerage Organization. Created by migration 0012, not here.

        A missing row means the database is behind the code, which must fail
        loudly: inserting one would hand every legacy record to an Organization
        that the backfill never scoped it to.
        """
        # Read at call time rather than bound as a default: a default argument
        # is evaluated once at import, which would make the constant impossible
        # to override — including by the mapping that will eventually replace it.
        wanted = slug or LAREVIA_SLUG
        organization: Organization | None = await self._session.scalar(
            select(Organization).where(Organization.slug == wanted)
        )
        if organization is None:
            raise RuntimeError(
                f"The {wanted!r} Organization is missing. Run `alembic upgrade head`."
            )
        return organization

    async def organization_id(self, slug: str | None = None) -> uuid.UUID:
        """The Organization commercial work belongs to.

        The single answer to that question. Three copies of this lookup existed
        briefly — one on the inbound path, one on Property acceptance, one here
        — two of which each described themselves as "the place a real mapping
        will replace". Only one can be, so only one exists.

        Stage 2 resolves it by slug because there is one Organization and no
        caller can supply a better hint: Meta's webhook knows a phone number,
        not a brokerage. This is the seam that mapping will land on.
        """
        return (await self.organization(slug)).id

    async def reconcile(self, plan: DirectoryPlan) -> Reconciliation:
        """Make the member table match the configured team. Commits.

        Idempotent by construction: a second run with the same plan reports no
        changes and writes no audit events.
        """
        organization = await self.organization()
        existing = {
            member.login: member
            for member in (
                await self._session.scalars(
                    select(OrganizationMember)
                    .where(OrganizationMember.organization_id == organization.id)
                    .with_for_update()
                )
            )
        }

        created: list[str] = []
        updated: list[str] = []
        deactivated: list[str] = []

        # One pre-pass over what is already there. Two things happen here and
        # both must happen before anything is written: the outgoing default
        # Advisor is cleared, because the partial unique index permits one per
        # Organization and setting the new one first would collide with the old;
        # and a login that has left the configuration is deactivated rather than
        # deleted, because assignments and Next Actions reference the row and a
        # RESTRICT foreign key would refuse anyway.
        for login, held in existing.items():
            departed = login not in plan.logins
            if departed and held.active:
                held.active = False
                deactivated.append(login)
            if held.is_default_advisor and (departed or login != plan.default_advisor):
                held.is_default_advisor = False

        for login in sorted(plan.logins):
            role = plan.role_of(login)
            advises = plan.advises(login)
            current = existing.get(login)
            if current is None:
                self._session.add(
                    OrganizationMember(
                        organization_id=organization.id,
                        login=login,
                        display_name=login,
                        role=role.value,
                        advises=advises,
                        is_default_advisor=False,
                        active=True,
                    )
                )
                created.append(login)
                continue
            if (current.role, current.advises, current.active) != (
                role.value,
                advises,
                True,
            ):
                current.role = role.value
                current.advises = advises
                current.active = True
                updated.append(login)

        await self._session.flush()

        if plan.default_advisor is not None:
            fallback = await self._member(organization.id, plan.default_advisor)
            if fallback is not None and not fallback.is_default_advisor:
                fallback.is_default_advisor = True
                if fallback.login not in created and fallback.login not in updated:
                    updated.append(fallback.login)

        result = Reconciliation(
            organization_id=organization.id,
            created=tuple(created),
            updated=tuple(updated),
            deactivated=tuple(deactivated),
        )
        if result.changed:
            await record_audit(
                self._session,
                actor_type="Product",
                actor_id="OrganizationDirectory",
                action="ReconcileOrganizationMembers",
                subject_type="Organization",
                subject_id=str(organization.id),
                details={
                    "created": list(result.created),
                    "updated": list(result.updated),
                    "deactivated": list(result.deactivated),
                    "default_advisor": plan.default_advisor,
                },
                commit=False,
            )
        await self._session.commit()
        return result

    async def resolve_actor(self, login: str) -> Actor:
        """The Actor behind an authenticated login, or a refusal.

        The only way an Actor comes into existence for a human caller.
        """
        member: OrganizationMember | None = await self._session.scalar(
            select(OrganizationMember).where(OrganizationMember.login == login)
        )
        if member is None or not member.active:
            logger.info("Refused commercial access for login %r: no active member", login)
            raise UnknownMember()
        return Actor(
            organization_id=member.organization_id,
            authority=authority_for(member.role),
            member_id=member.id,
            label=member.login,
            display_name=member.display_name,
        )

    async def _member(
        self, organization_id: uuid.UUID, login: str
    ) -> OrganizationMember | None:
        found: OrganizationMember | None = await self._session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.login == login)
        )
        return found

    async def members(
        self, organization_id: uuid.UUID, *, advisors_only: bool = False
    ) -> list[OrganizationMember]:
        """Active members, Administrators first, then by display name."""
        query = (
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.active.is_(True))
        )
        if advisors_only:
            query = query.where(OrganizationMember.advises.is_(True))
        rows = await self._session.scalars(
            query.order_by(
                OrganizationMember.role, OrganizationMember.display_name
            )
        )
        return list(rows)

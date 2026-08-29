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
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    LAREVIA_SLUG,
    MemberProvisioning,
    MemberRole,
    Organization,
    OrganizationMember,
    OrganizationStatus,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    NotFound,
    UnknownMember,
    authority_for,
)
from realestate.domain.platform.support import SUPPORT_LOGIN_PREFIX, SupportAccess


class OrganizationSuspended(CommercialError):
    """The member exists but their Organization is not operating."""

    message = (
        "El servicio de tu organización está pausado. Contacta a tu "
        "administrador o al equipo de Maia."
    )


class SupportAccessExpired(CommercialError):
    """A support login whose temporary grant has ended (ADR-0054)."""

    message = (
        "Tu acceso temporal de soporte terminó. Solicita uno nuevo con el motivo "
        "correspondiente."
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


def parse_assignments(raw: str) -> dict[str, str]:
    """Parse ``login=value,login2=value2`` into a mapping.

    Used for the two per-member operational values configuration can supply: an
    Advisor's authoritative calendar and where their immediate alerts go. A
    malformed entry is skipped rather than fatal — an unparsable calendar id
    leaves that Advisor unbookable, which fails closed, whereas refusing to
    start would take the whole operation down over one typo.
    """
    mapping: dict[str, str] = {}
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk or "=" not in chunk:
            continue
        login, _, value = chunk.partition("=")
        login, value = login.strip(), value.strip()
        if login and value:
            mapping[login] = value
    return mapping


@dataclass(frozen=True)
class DirectoryPlan:
    """The intended team, already validated as internally consistent."""

    administrators: tuple[str, ...]
    advisors: tuple[str, ...]
    default_advisor: str | None
    #: Per-Advisor authoritative calendars, by login (ADR-0048).
    calendars: Mapping[str, str] = field(default_factory=dict)
    #: Where each member's immediate operational alerts go, by login.
    telegram_ids: Mapping[str, str] = field(default_factory=dict)
    #: The single calendar Stage 0 configured. Applied to the default Advisor
    #: when no per-login mapping names them, so an existing local setup keeps
    #: working instead of silently becoming unbookable.
    fallback_calendar_id: str | None = None

    @classmethod
    def from_configuration(
        cls,
        *,
        administrators: str,
        advisors: str,
        default_advisor: str,
        calendars: str = "",
        telegram_ids: str = "",
        fallback_calendar_id: str = "",
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
            calendars=parse_assignments(calendars),
            telegram_ids=parse_assignments(telegram_ids),
            fallback_calendar_id=fallback_calendar_id.strip() or None,
        )

    def calendar_for(self, login: str) -> str | None:
        """The authoritative calendar this login should have, if configured."""
        explicit = self.calendars.get(login)
        if explicit:
            return explicit
        if login == self.default_advisor and self.fallback_calendar_id:
            return self.fallback_calendar_id
        return None

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
        """One Organization by slug, defaulting to the founding one.

        The default is the *bootstrap* Organization and nothing more general than
        that. It is what startup reconciliation of the process environment reads,
        and it is deliberately not what any inbound, public or worker path reads
        any more: those resolve an Organization from a channel binding, an Actor
        or the registry (ADR-0050).

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

    async def reconcile(
        self, plan: DirectoryPlan, *, organization_id: uuid.UUID | None = None
    ) -> Reconciliation:
        """Make one Organization's member table match a team plan. Commits.

        Idempotent by construction: a second run with the same plan reports no
        changes and writes no audit events.

        ``organization_id`` is how Stage 9 provisioning reconciles a *second*
        Organization's founding team with the same code the first one uses. Left
        unset it means the bootstrap Organization, which is what the startup
        reconciliation of the process environment is about and the only caller
        that may omit it.
        """
        organization = (
            await self._session.get(Organization, organization_id)
            if organization_id is not None
            else await self.organization()
        )
        if organization is None:
            raise NotFound("No encontramos esa organización.")
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
            configured = held.provisioned_by == MemberProvisioning.CONFIGURATION.value
            # Only configuration's own rows are governed by configuration
            # (ADR-0047). Deactivating an Administrator-created Advisor because
            # they were never in .env would delete the team on the next restart,
            # which is exactly the failure the provenance column prevents.
            if departed and configured and held.active:
                held.active = False
                deactivated.append(login)
            if held.is_default_advisor and (
                (departed and configured) or login != plan.default_advisor
            ):
                # The default Advisor *is* configuration's decision even for a
                # row an Administrator created, because the fallback is named
                # in one place and the partial unique index permits one.
                if plan.default_advisor is not None or (departed and configured):
                    held.is_default_advisor = False

        for login in sorted(plan.logins):
            role = plan.role_of(login)
            advises = plan.advises(login)
            calendar_id = plan.calendar_for(login)
            telegram_chat_id = plan.telegram_ids.get(login)
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
                        provisioned_by=MemberProvisioning.CONFIGURATION.value,
                        calendar_id=calendar_id,
                        telegram_chat_id=telegram_chat_id,
                    )
                )
                created.append(login)
                continue
            changed = False
            if (current.role, current.advises, current.active) != (
                role.value,
                advises,
                True,
            ):
                current.role = role.value
                current.advises = advises
                current.active = True
                changed = True
            # A login named in configuration is configuration's to govern from
            # now on, whoever created the row first.
            if current.provisioned_by != MemberProvisioning.CONFIGURATION.value:
                current.provisioned_by = MemberProvisioning.CONFIGURATION.value
                changed = True
            # Configuration only ever *supplies* these two; it never clears a
            # value an Administrator set through the team surface, because the
            # absence of an environment variable is not an instruction.
            if calendar_id is not None and current.calendar_id != calendar_id:
                current.calendar_id = calendar_id
                changed = True
            if (
                telegram_chat_id is not None
                and current.telegram_chat_id != telegram_chat_id
            ):
                current.telegram_chat_id = telegram_chat_id
                changed = True
            if changed:
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
                organization_id=organization.id,
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

        Three refusals, and Stage 9 added the last two:

        * no active member row — a credential that authenticates but belongs to
          nobody (ADR-0046);
        * the member's Organization is not operating. A suspended or
          half-provisioned Organization must not be worked in, and the member
          rows are deliberately left intact so resuming it is a status change
          rather than a re-provisioning;
        * the login is a support login whose grant has lapsed. Checked here
          rather than trusted to the expiry sweep, so an internal engineer's
          access ends on the clock and not on a worker having run (ADR-0054).

        The login namespace is platform-wide, not per Organization: HTTP Basic
        carries no Organization, so the username has to identify one row. That is
        a named Stage 9 limit — a login already taken elsewhere is refused at
        provisioning time with a message saying so, rather than silently attached
        to the wrong brokerage.
        """
        member: OrganizationMember | None = await self._session.scalar(
            select(OrganizationMember).where(OrganizationMember.login == login)
        )
        if member is None or not member.active:
            logger.info("Refused commercial access for login %r: no active member", login)
            raise UnknownMember()

        organization = await self._session.get(Organization, member.organization_id)
        if organization is None or organization.status != OrganizationStatus.ACTIVE.value:
            logger.info(
                "Refused commercial access for login %r: Organization %s is %s",
                login,
                member.organization_id,
                organization.status if organization is not None else "missing",
            )
            raise OrganizationSuspended()

        read_only = False
        if login.startswith(SUPPORT_LOGIN_PREFIX):
            grant = await SupportAccess(self._session).live_for_login(login)
            if grant is None:
                logger.info("Refused lapsed support access for login %r", login)
                raise SupportAccessExpired()
            read_only = True

        return Actor(
            organization_id=member.organization_id,
            authority=authority_for(member.role),
            member_id=member.id,
            label=member.login,
            display_name=member.display_name,
            read_only=read_only,
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

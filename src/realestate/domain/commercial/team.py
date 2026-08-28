"""The team: who may work, when they cannot, and who specialises in what.

``TeamAdministration.record(command)`` is the only way membership, an Advisor
Absence or a Property Expert designation changes. Everything that makes that
safe lives behind it: the Administrator-only authority, the invariants that stop
an operation from losing its last administrator or its assignment fallback, the
exclusion constraint that makes two overlapping absences impossible, idempotency
by command key, and the audit trail.

Three separations are load-bearing.

**Expert is not owner.** A :class:`~realestate.db.models.PropertyExpert` names a
Property. A Responsible Advisor owns an Opportunity. Designating somebody the
specialist for a Property changes *nothing* about work already assigned, which
is why the two live in different tables and why nothing here writes
``responsible_advisor_id``.

**An absence blocks new work, never existing work.** Recording one removes the
Advisor from the assignment rule and from new bookings. It does not reassign an
Opportunity or cancel a visit; those are surfaced for the Administrator to
decide (PROJECT_MEMORY, SAN-035). The alert this raises is the whole mechanism
by which "surfaced" is true rather than aspirational.

**Configuration bootstraps, an Administrator operates.** Startup reconciliation
deactivates a login that has left the configuration, which would delete an
Administrator-created Advisor on the next restart. So a member row records who
provisioned it and reconciliation only governs its own (ADR-0047).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from typing import Any
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ACTIVE_STAGES,
    AdvisorAbsence,
    Appointment,
    AppointmentStatus,
    InternalAlertKind,
    MemberProvisioning,
    MemberRole,
    Opportunity,
    OrganizationMember,
    Property,
    PropertyExpert,
    PropertyExpertRole,
)
from realestate.domain.audit import record_audit
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    NotAuthorized,
    NotFound,
)
from realestate.domain.commercial.idempotency import CommercialCommands
from realestate.domain.internal_alerts import InternalAlerts

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


EXPERT_ROLE_LABELS: dict[str, str] = {
    PropertyExpertRole.PRIMARY.value: "Especialista principal",
    PropertyExpertRole.BACKUP.value: "Especialista suplente",
}

PROVISIONING_LABELS: dict[str, str] = {
    MemberProvisioning.CONFIGURATION.value: "Alta por configuración",
    MemberProvisioning.ADMINISTRATOR.value: "Alta por el administrador",
}


class TeamError(CommercialError):
    """Base class for a team refusal, so a router can catch the family."""


class OverlappingAbsence(TeamError):
    message = (
        "Ese asesor ya tiene una ausencia registrada que se cruza con estas "
        "fechas. Termina la ausencia existente o ajusta el periodo."
    )


class LastAdministrator(TeamError):
    message = (
        "No puedes dar de baja al último administrador activo de la "
        "organización."
    )


class NotAnAdvisor(TeamError):
    message = "Esa persona no puede recibir oportunidades ni citas."


class LoginTaken(TeamError):
    message = "Ese usuario ya existe en la organización."


# ---------------------------------------------------------------- Commands ---


@dataclass(frozen=True)
class _Command:
    command_key: str


@dataclass(frozen=True)
class AddMember(_Command):
    """Create one member. The login must already authenticate.

    Product does not mint credentials: authentication is HTTP Basic against the
    configured operational accounts (ADR-0046). Creating a member row for a
    login that cannot authenticate is legitimate — the row is the authority, and
    the credential can be added afterwards — so this does not check, it records.
    """

    login: str
    display_name: str
    role: MemberRole
    advises: bool
    calendar_id: str | None = None
    telegram_chat_id: str | None = None


@dataclass(frozen=True)
class UpdateMember(_Command):
    """Change what an Administrator may change about a member.

    Every field is optional and ``None`` means "leave it alone", so a form that
    renders three inputs cannot blank the two it did not show. Clearing a value
    is expressed as the empty string.
    """

    member_id: uuid.UUID
    display_name: str | None = None
    advises: bool | None = None
    calendar_id: str | None = None
    telegram_chat_id: str | None = None


@dataclass(frozen=True)
class SetMemberActive(_Command):
    member_id: uuid.UUID
    active: bool


@dataclass(frozen=True)
class SetDefaultAdvisor(_Command):
    """Name the deterministic assignment fallback, or clear it."""

    member_id: uuid.UUID | None


@dataclass(frozen=True)
class StartAbsence(_Command):
    advisor_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None


@dataclass(frozen=True)
class EndAbsence(_Command):
    absence_id: uuid.UUID


@dataclass(frozen=True)
class DesignateExpert(_Command):
    property_uuid: uuid.UUID
    advisor_id: uuid.UUID
    role: PropertyExpertRole
    rank: int = 0


@dataclass(frozen=True)
class RevokeExpert(_Command):
    property_uuid: uuid.UUID
    advisor_id: uuid.UUID


Command = (
    AddMember
    | UpdateMember
    | SetMemberActive
    | SetDefaultAdvisor
    | StartAbsence
    | EndAbsence
    | DesignateExpert
    | RevokeExpert
)


@dataclass(frozen=True)
class TeamRecorded:
    """What one command changed."""

    subject_type: str
    subject_id: uuid.UUID
    #: False for an exact replay of a command key already applied.
    changed: bool
    detail: str = ""


# ------------------------------------------------------------------- Views ---


@dataclass(frozen=True)
class TeamMemberView:
    """One row of the team surface."""

    member: OrganizationMember
    #: The absence in force right now, if any.
    current_absence: AdvisorAbsence | None
    upcoming_absences: tuple[AdvisorAbsence, ...]
    open_opportunities: int
    future_appointments: int

    @property
    def absent(self) -> bool:
        return self.current_absence is not None

    @property
    def can_receive_appointments(self) -> bool:
        """Whether a visit could be booked with this person right now."""
        return (
            self.member.active
            and self.member.advises
            and not self.absent
            and bool(self.member.calendar_id)
        )


@dataclass(frozen=True)
class ExpertDesignationView:
    property_uuid: uuid.UUID
    property_key: str
    property_name: str
    primary: OrganizationMember | None
    backups: tuple[OrganizationMember, ...]


# ------------------------------------------------------- Absence as a fact ---


def absence_in_force(moment: datetime) -> Select[tuple[AdvisorAbsence]]:
    """Absences in force at *moment*. One definition, three callers.

    Assignment, scheduling and the team surface all need "is this person away
    right now", and three copies of the predicate is how one of them ends up
    disagreeing after a schema change.
    """
    return (
        select(AdvisorAbsence)
        .where(AdvisorAbsence.cancelled_at.is_(None))
        .where(AdvisorAbsence.starts_at <= moment)
        .where(AdvisorAbsence.ends_at > moment)
    )


async def absent_advisor_ids(
    session: AsyncSession,
    organization_id: uuid.UUID,
    moment: datetime,
    *,
    among: Iterable[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """Which of these Advisors are away at *moment*."""
    query = absence_in_force(moment).where(
        AdvisorAbsence.organization_id == organization_id
    )
    candidates = list(among) if among is not None else None
    if candidates is not None:
        if not candidates:
            return set()
        query = query.where(AdvisorAbsence.advisor_id.in_(candidates))
    rows = await session.scalars(query)
    return {row.advisor_id for row in rows}


async def current_absence(
    session: AsyncSession, advisor_id: uuid.UUID, moment: datetime
) -> AdvisorAbsence | None:
    found: AdvisorAbsence | None = await session.scalar(
        absence_in_force(moment)
        .where(AdvisorAbsence.advisor_id == advisor_id)
        .limit(1)
    )
    return found


# ------------------------------------------------------------------ Module ---


class TeamAdministration:
    """The team module.

    Hides: Administrator-only authority, the member invariants, absence
    overlap, the primary/backup expert indexes, revocation instead of deletion,
    the Administrator review alert an absence raises, idempotency and audit.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._commands = CommercialCommands(session)
        self._alerts = InternalAlerts(session)

    async def record(self, actor: Actor, command: Command) -> TeamRecorded:
        """Apply one command. Never commits.

        Administrator-only, without exception. An Advisor changing their own
        absence is exactly the ambiguity PROJECT_MEMORY removes: the person who
        wants the day off is not the person who decides the operation can cover
        it.
        """
        actor.require_administrator()
        if isinstance(command, AddMember):
            return await self._add_member(actor, command)
        if isinstance(command, UpdateMember):
            return await self._update_member(actor, command)
        if isinstance(command, SetMemberActive):
            return await self._set_active(actor, command)
        if isinstance(command, SetDefaultAdvisor):
            return await self._set_default(actor, command)
        if isinstance(command, StartAbsence):
            return await self._start_absence(actor, command)
        if isinstance(command, EndAbsence):
            return await self._end_absence(actor, command)
        if isinstance(command, DesignateExpert):
            return await self._designate_expert(actor, command)
        return await self._revoke_expert(actor, command)

    # -- Members -----------------------------------------------------------

    async def _add_member(self, actor: Actor, command: AddMember) -> TeamRecorded:
        login = command.login.strip()
        if not login:
            raise InvalidTransition("El usuario no puede quedar vacío.")
        advises = command.advises or command.role is MemberRole.ADVISOR
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="AddMember",
            subject_type="OrganizationMember",
            subject_id=login,
            payload={"role": command.role.value, "advises": advises},
        )
        existing = await self._session.scalar(
            select(OrganizationMember).where(OrganizationMember.login == login)
        )
        if replay and existing is not None:
            return TeamRecorded("OrganizationMember", existing.id, changed=False)
        if existing is not None:
            raise LoginTaken()

        member = OrganizationMember(
            organization_id=actor.organization_id,
            login=login,
            display_name=command.display_name.strip() or login,
            role=command.role.value,
            advises=advises,
            is_default_advisor=False,
            active=True,
            provisioned_by=MemberProvisioning.ADMINISTRATOR.value,
            calendar_id=_clean(command.calendar_id),
            telegram_chat_id=_clean(command.telegram_chat_id),
        )
        self._session.add(member)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise LoginTaken() from exc
        await self._audit(
            actor,
            "AddOrganizationMember",
            member.id,
            {
                "login": login,
                "role": command.role.value,
                "advises": advises,
                "calendar_configured": bool(member.calendar_id),
            },
        )
        logger.info("Added Organization member %s as %s", login, command.role.value)
        return TeamRecorded("OrganizationMember", member.id, changed=True)

    async def _update_member(self, actor: Actor, command: UpdateMember) -> TeamRecorded:
        member = await self._member(actor, command.member_id, lock=True)
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="UpdateMember",
            subject_type="OrganizationMember",
            subject_id=str(member.id),
            payload={
                "display_name": command.display_name,
                "advises": command.advises,
                "calendar_id": command.calendar_id,
                "telegram_chat_id": command.telegram_chat_id,
            },
        )
        if replay:
            return TeamRecorded("OrganizationMember", member.id, changed=False)

        changes: dict[str, object] = {}
        if command.display_name is not None and command.display_name.strip():
            if member.display_name != command.display_name.strip():
                member.display_name = command.display_name.strip()
                changes["display_name"] = member.display_name
        if command.advises is not None and member.advises != command.advises:
            if not command.advises and member.role == MemberRole.ADVISOR.value:
                # ``ck_organization_members_advisor_advises`` forbids it anyway;
                # refusing here turns a constraint violation into a sentence.
                raise InvalidTransition(
                    "Un asesor inmobiliario siempre puede recibir "
                    "oportunidades. Cambia su rol o dale de baja."
                )
            if not command.advises and member.is_default_advisor:
                raise InvalidTransition(
                    "Es el asesor predeterminado. Nombra a otro antes de "
                    "quitarle la elegibilidad."
                )
            member.advises = command.advises
            changes["advises"] = member.advises
        if command.calendar_id is not None:
            wanted = _clean(command.calendar_id)
            if member.calendar_id != wanted:
                member.calendar_id = wanted
                changes["calendar_configured"] = bool(wanted)
        if command.telegram_chat_id is not None:
            wanted = _clean(command.telegram_chat_id)
            if member.telegram_chat_id != wanted:
                member.telegram_chat_id = wanted
                changes["alert_channel_configured"] = bool(wanted)

        if not changes:
            return TeamRecorded("OrganizationMember", member.id, changed=False)
        member.updated_at = _now()
        await self._session.flush()
        await self._audit(actor, "UpdateOrganizationMember", member.id, changes)
        return TeamRecorded("OrganizationMember", member.id, changed=True)

    async def _set_active(self, actor: Actor, command: SetMemberActive) -> TeamRecorded:
        member = await self._member(actor, command.member_id, lock=True)
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="SetMemberActive",
            subject_type="OrganizationMember",
            subject_id=str(member.id),
            payload={"active": command.active},
        )
        if replay or member.active == command.active:
            return TeamRecorded("OrganizationMember", member.id, changed=False)

        if not command.active:
            await self._refuse_losing_last_administrator(actor, member)
            member.active = False
            # A deactivated member cannot be the fallback: leaving the flag
            # would let ``Assignment`` pick somebody who can no longer log in.
            # The queue then reports ``DefaultAdvisorInactive`` — the honest
            # reason — until an Administrator names another.
            member.is_default_advisor = False
        else:
            member.active = True
        member.updated_at = _now()
        await self._session.flush()
        await self._audit(
            actor,
            "ActivateOrganizationMember" if command.active else "DeactivateOrganizationMember",
            member.id,
            {"login": member.login},
        )
        if not command.active:
            await self._raise_review_alert(
                actor,
                member,
                kind=InternalAlertKind.ABSENCE_REVIEW,
                dedupe_key=f"member-deactivated:{member.id}",
                title=f"{member.display_name} quedó dado de baja",
                headline=(
                    "Sus oportunidades y citas no se reasignaron ni se "
                    "cancelaron. Revísalas y decide qué hacer."
                ),
            )
        return TeamRecorded("OrganizationMember", member.id, changed=True)

    async def _refuse_losing_last_administrator(
        self, actor: Actor, member: OrganizationMember
    ) -> None:
        if member.role != MemberRole.ADMINISTRATOR.value:
            return
        remaining = await self._session.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(OrganizationMember.organization_id == actor.organization_id)
            .where(OrganizationMember.role == MemberRole.ADMINISTRATOR.value)
            .where(OrganizationMember.active.is_(True))
            .where(OrganizationMember.id != member.id)
        )
        if not remaining:
            raise LastAdministrator()

    async def _set_default(
        self, actor: Actor, command: SetDefaultAdvisor
    ) -> TeamRecorded:
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="SetDefaultAdvisor",
            subject_type="Organization",
            subject_id=str(actor.organization_id),
            payload={"member_id": str(command.member_id)},
        )
        if replay:
            return TeamRecorded("Organization", actor.organization_id, changed=False)

        # The outgoing fallback is cleared first: the partial unique index
        # permits one per Organization, so setting the new one first collides.
        current = await self._session.scalars(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == actor.organization_id)
            .where(OrganizationMember.is_default_advisor.is_(True))
            .with_for_update()
        )
        for held in current:
            if held.id != command.member_id:
                held.is_default_advisor = False
        await self._session.flush()

        if command.member_id is None:
            await self._audit(
                actor, "ClearDefaultAdvisor", actor.organization_id, {}, subject="Organization"
            )
            return TeamRecorded("Organization", actor.organization_id, changed=True)

        member = await self._member(actor, command.member_id, lock=True)
        if not member.active or not member.advises:
            raise NotAnAdvisor()
        member.is_default_advisor = True
        await self._session.flush()
        await self._audit(
            actor, "SetDefaultAdvisor", member.id, {"login": member.login}
        )
        return TeamRecorded("OrganizationMember", member.id, changed=True)

    # -- Absences ----------------------------------------------------------

    async def _start_absence(self, actor: Actor, command: StartAbsence) -> TeamRecorded:
        if command.ends_at <= command.starts_at:
            raise InvalidTransition(
                "La ausencia debe terminar después de que empieza."
            )
        member = await self._member(actor, command.advisor_id, lock=True)
        if not member.active or not member.advises:
            raise NotAnAdvisor()
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="StartAbsence",
            subject_type="AdvisorAbsence",
            subject_id=str(member.id),
            payload={
                "starts_at": command.starts_at,
                "ends_at": command.ends_at,
            },
        )
        if replay:
            existing = await self._session.scalar(
                select(AdvisorAbsence)
                .where(AdvisorAbsence.advisor_id == member.id)
                .where(AdvisorAbsence.starts_at == command.starts_at)
                .where(AdvisorAbsence.cancelled_at.is_(None))
                .limit(1)
            )
            if existing is not None:
                return TeamRecorded("AdvisorAbsence", existing.id, changed=False)

        absence: AdvisorAbsence | None = None
        try:
            # A savepoint, because the exclusion constraint is the arbiter of
            # overlap and the loser has to become a readable refusal rather
            # than poisoning the caller's transaction. The row is constructed
            # *inside* it on purpose: an object added before the savepoint
            # survives its rollback still pending and is inserted again by the
            # next flush, which reproduces the very violation just handled.
            async with self._session.begin_nested():
                absence = AdvisorAbsence(
                    organization_id=actor.organization_id,
                    advisor_id=member.id,
                    starts_at=command.starts_at,
                    ends_at=command.ends_at,
                    reason=_clean(command.reason),
                    recorded_by=_acting_member(actor),
                )
                self._session.add(absence)
                await self._session.flush()
        except IntegrityError as exc:
            if "ex_advisor_absence_overlap" not in str(exc.orig):
                raise
            raise OverlappingAbsence() from exc
        assert absence is not None

        await self._audit(
            actor,
            "RecordAdvisorAbsence",
            absence.id,
            {
                "advisor_id": str(member.id),
                "starts_at": command.starts_at.isoformat(),
                "ends_at": command.ends_at.isoformat(),
            },
            subject="AdvisorAbsence",
        )
        # Existing work is deliberately untouched. It is surfaced instead, so
        # "not silently reassigned" does not become "silently forgotten".
        await self._raise_review_alert(
            actor,
            member,
            kind=InternalAlertKind.ABSENCE_REVIEW,
            dedupe_key=f"absence:{absence.id}",
            title=f"Ausencia registrada: {member.display_name}",
            headline=(
                "No recibirá asignaciones nuevas durante la ausencia. Sus "
                "oportunidades y citas siguen siendo suyas: revísalas."
            ),
            window=(command.starts_at, command.ends_at),
        )
        logger.info(
            "Recorded an absence for %s from %s to %s",
            member.login,
            command.starts_at,
            command.ends_at,
        )
        return TeamRecorded("AdvisorAbsence", absence.id, changed=True)

    async def _end_absence(self, actor: Actor, command: EndAbsence) -> TeamRecorded:
        absence: AdvisorAbsence | None = await self._session.scalar(
            select(AdvisorAbsence)
            .where(AdvisorAbsence.id == command.absence_id)
            .with_for_update()
        )
        if absence is None:
            raise NotFound("No encontramos esa ausencia.")
        actor.require_same_organization(absence.organization_id)
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="EndAbsence",
            subject_type="AdvisorAbsence",
            subject_id=str(absence.id),
            payload={},
        )
        if replay or absence.cancelled_at is not None:
            return TeamRecorded("AdvisorAbsence", absence.id, changed=False)

        moment = _now()
        if moment <= absence.starts_at:
            # It never took effect, so it is voided rather than truncated: a
            # zero-length period would violate ``ck_advisor_absence_period``.
            absence.cancelled_at = moment
            outcome = "cancelled"
        elif absence.ends_at <= moment:
            return TeamRecorded("AdvisorAbsence", absence.id, changed=False)
        else:
            absence.ends_at = moment
            absence.ended_early_at = moment
            outcome = "ended"
        absence.ended_by = _acting_member(actor)
        await self._session.flush()
        await self._audit(
            actor,
            "EndAdvisorAbsence",
            absence.id,
            {"advisor_id": str(absence.advisor_id), "outcome": outcome},
            subject="AdvisorAbsence",
        )
        return TeamRecorded("AdvisorAbsence", absence.id, changed=True, detail=outcome)

    # -- Property Experts --------------------------------------------------

    async def _designate_expert(
        self, actor: Actor, command: DesignateExpert
    ) -> TeamRecorded:
        member = await self._member(actor, command.advisor_id, lock=True)
        if not member.active or not member.advises:
            raise NotAnAdvisor()
        prop = await self._session.get(Property, command.property_uuid)
        if prop is None:
            raise NotFound("No encontramos esa propiedad.")
        actor.require_same_organization(prop.organization_id)
        rank = 0 if command.role is PropertyExpertRole.PRIMARY else max(1, command.rank)
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="DesignateExpert",
            subject_type="PropertyExpert",
            subject_id=f"{command.property_uuid}:{command.advisor_id}",
            payload={"role": command.role.value, "rank": rank},
        )
        if replay:
            return TeamRecorded("PropertyExpert", command.property_uuid, changed=False)

        live = list(
            await self._session.scalars(
                select(PropertyExpert)
                .where(PropertyExpert.property_uuid == command.property_uuid)
                .where(PropertyExpert.revoked_at.is_(None))
                .with_for_update()
            )
        )
        moment = _now()
        for row in live:
            same_person = row.advisor_id == command.advisor_id
            displaced_primary = (
                command.role is PropertyExpertRole.PRIMARY
                and row.role == PropertyExpertRole.PRIMARY.value
            )
            if same_person or displaced_primary:
                if (
                    same_person
                    and row.role == command.role.value
                    and row.rank == rank
                ):
                    return TeamRecorded(
                        "PropertyExpert", row.id, changed=False
                    )
                row.revoked_at = moment
        await self._session.flush()

        designation = PropertyExpert(
            organization_id=actor.organization_id,
            property_uuid=command.property_uuid,
            advisor_id=command.advisor_id,
            role=command.role.value,
            rank=rank,
            designated_by=_acting_member(actor),
        )
        self._session.add(designation)
        await self._session.flush()
        await self._audit(
            actor,
            "DesignatePropertyExpert",
            designation.id,
            {
                "property_key": prop.property_key,
                "advisor_id": str(command.advisor_id),
                "role": command.role.value,
                "rank": rank,
                # Stated explicitly in the trail: this is not an assignment.
                "changes_opportunity_ownership": False,
            },
            subject="PropertyExpert",
        )
        return TeamRecorded("PropertyExpert", designation.id, changed=True)

    async def _revoke_expert(self, actor: Actor, command: RevokeExpert) -> TeamRecorded:
        row: PropertyExpert | None = await self._session.scalar(
            select(PropertyExpert)
            .where(PropertyExpert.property_uuid == command.property_uuid)
            .where(PropertyExpert.advisor_id == command.advisor_id)
            .where(PropertyExpert.revoked_at.is_(None))
            .with_for_update()
            .limit(1)
        )
        replay = await self._commands.claim(
            actor,
            command_key=command.command_key,
            operation="RevokeExpert",
            subject_type="PropertyExpert",
            subject_id=f"{command.property_uuid}:{command.advisor_id}",
            payload={},
        )
        if row is None or replay:
            return TeamRecorded("PropertyExpert", command.property_uuid, changed=False)
        actor.require_same_organization(row.organization_id)
        row.revoked_at = _now()
        await self._session.flush()
        await self._audit(
            actor,
            "RevokePropertyExpert",
            row.id,
            {"advisor_id": str(command.advisor_id)},
            subject="PropertyExpert",
        )
        return TeamRecorded("PropertyExpert", row.id, changed=True)

    # -- Reads -------------------------------------------------------------

    async def team(self, actor: Actor, *, now: datetime | None = None) -> list[TeamMemberView]:
        """The whole team, with why each person can or cannot take new work.

        Readable by an Advisor as well as an Administrator: knowing who is away
        is how a human decides whether to wait or escalate, and it discloses no
        Contact. Only an Administrator can *change* any of it.
        """
        moment = now or _now()
        members = list(
            await self._session.scalars(
                select(OrganizationMember)
                .where(OrganizationMember.organization_id == actor.organization_id)
                .order_by(
                    OrganizationMember.active.desc(),
                    OrganizationMember.role,
                    OrganizationMember.display_name,
                )
            )
        )
        if not members:
            return []
        ids = [member.id for member in members]
        absences = list(
            await self._session.scalars(
                select(AdvisorAbsence)
                .where(AdvisorAbsence.advisor_id.in_(ids))
                .where(AdvisorAbsence.cancelled_at.is_(None))
                .where(AdvisorAbsence.ends_at > moment)
                .order_by(AdvisorAbsence.starts_at)
            )
        )
        # The grouped column is nullable in the schema, so the rows are typed
        # ``UUID | None``. Every row here has one — the query filters on
        # ``in_(ids)`` — and building the dict from a comprehension says so
        # without a cast that would also hide a real ``None``.
        open_counts: dict[uuid.UUID, int] = _counts_by_member(
            (
                await self._session.execute(
                    select(Opportunity.responsible_advisor_id, func.count())
                    .where(Opportunity.organization_id == actor.organization_id)
                    .where(Opportunity.stage.in_(ACTIVE_STAGES))
                    .where(Opportunity.responsible_advisor_id.in_(ids))
                    .group_by(Opportunity.responsible_advisor_id)
                )
            ).all()
        )
        visit_counts: dict[uuid.UUID, int] = _counts_by_member(
            (
                await self._session.execute(
                    select(Appointment.advisor_id, func.count())
                    .where(Appointment.advisor_id.in_(ids))
                    .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
                    .where(Appointment.starts_at > moment)
                    .group_by(Appointment.advisor_id)
                )
            ).all()
        )

        views: list[TeamMemberView] = []
        for member in members:
            mine = [row for row in absences if row.advisor_id == member.id]
            live = next((row for row in mine if row.covers(moment)), None)
            views.append(
                TeamMemberView(
                    member=member,
                    current_absence=live,
                    upcoming_absences=tuple(row for row in mine if row is not live),
                    open_opportunities=int(open_counts.get(member.id, 0)),
                    future_appointments=int(visit_counts.get(member.id, 0)),
                )
            )
        return views

    async def absences(
        self, actor: Actor, *, include_past: bool = False, now: datetime | None = None
    ) -> list[AdvisorAbsence]:
        moment = now or _now()
        query = (
            select(AdvisorAbsence)
            .where(AdvisorAbsence.organization_id == actor.organization_id)
            .order_by(AdvisorAbsence.starts_at.desc())
        )
        if not include_past:
            query = query.where(AdvisorAbsence.ends_at > moment).where(
                AdvisorAbsence.cancelled_at.is_(None)
            )
        return list(await self._session.scalars(query))

    async def experts_for(
        self, property_uuid: uuid.UUID
    ) -> list[PropertyExpert]:
        """Live designations for one Property, primary first then by rank."""
        rows = await self._session.scalars(
            select(PropertyExpert)
            .where(PropertyExpert.property_uuid == property_uuid)
            .where(PropertyExpert.revoked_at.is_(None))
            .order_by(PropertyExpert.rank, PropertyExpert.designated_at)
        )
        return list(rows)

    async def expert_directory(self, actor: Actor) -> list[ExpertDesignationView]:
        """Every Property with its specialists, for the Administrator surface."""
        properties = list(
            await self._session.scalars(
                select(Property)
                .where(Property.organization_id == actor.organization_id)
                .order_by(Property.name)
            )
        )
        if not properties:
            return []
        designations = list(
            await self._session.scalars(
                select(PropertyExpert)
                .where(PropertyExpert.organization_id == actor.organization_id)
                .where(PropertyExpert.revoked_at.is_(None))
                .order_by(PropertyExpert.rank, PropertyExpert.designated_at)
            )
        )
        members = {
            member.id: member
            for member in await self._session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == actor.organization_id
                )
            )
        }
        views: list[ExpertDesignationView] = []
        for prop in properties:
            mine = [row for row in designations if row.property_uuid == prop.id]
            primary = next(
                (
                    members.get(row.advisor_id)
                    for row in mine
                    if row.role == PropertyExpertRole.PRIMARY.value
                ),
                None,
            )
            backups = tuple(
                member
                for member in (
                    members.get(row.advisor_id)
                    for row in mine
                    if row.role == PropertyExpertRole.BACKUP.value
                )
                if member is not None
            )
            views.append(
                ExpertDesignationView(
                    property_uuid=prop.id,
                    property_key=prop.property_key,
                    property_name=prop.name,
                    primary=primary,
                    backups=backups,
                )
            )
        return views

    # -- Internals ---------------------------------------------------------

    async def _member(
        self, actor: Actor, member_id: uuid.UUID, *, lock: bool = False
    ) -> OrganizationMember:
        query = select(OrganizationMember).where(OrganizationMember.id == member_id)
        if lock:
            query = query.with_for_update()
        member: OrganizationMember | None = await self._session.scalar(query)
        if member is None:
            raise NotFound("No encontramos a esa persona en la organización.")
        actor.require_same_organization(member.organization_id)
        return member

    async def _audit(
        self,
        actor: Actor,
        action: str,
        subject_id: uuid.UUID,
        details: dict[str, object],
        *,
        subject: str = "OrganizationMember",
    ) -> None:
        await record_audit(
            self._session,
            actor_type=actor.actor_type,
            actor_id=actor.label,
            action=action,
            subject_type=subject,
            subject_id=str(subject_id),
            details=details,
            commit=False,
        )

    async def _raise_review_alert(
        self,
        actor: Actor,
        member: OrganizationMember,
        *,
        kind: InternalAlertKind,
        dedupe_key: str,
        title: str,
        headline: str,
        window: tuple[datetime, datetime] | None = None,
    ) -> None:
        """Tell the Administrators what this change did *not* do.

        The absence rule's whole safety property is that existing work is left
        alone. That is only trustworthy if somebody is told which work it left
        alone, so the counts are computed here and named in the alert.
        """
        opportunities = await self._session.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(Opportunity.responsible_advisor_id == member.id)
            .where(Opportunity.stage.in_(ACTIVE_STAGES))
        )
        visit_query = (
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.advisor_id == member.id)
            .where(Appointment.status == AppointmentStatus.CONFIRMED.value)
        )
        if window is not None:
            visit_query = visit_query.where(Appointment.starts_at >= window[0]).where(
                Appointment.starts_at < window[1]
            )
        else:
            visit_query = visit_query.where(Appointment.starts_at > _now())
        visits = await self._session.scalar(visit_query)
        body = "\n".join(
            [
                headline,
                f"Oportunidades activas a su nombre: {opportunities or 0}",
                f"Citas confirmadas en el periodo: {visits or 0}",
            ]
        )
        await self._alerts.raise_alert(
            actor,
            kind=kind,
            subject_type="OrganizationMember",
            subject_id=str(member.id),
            title=title,
            body=body,
            dedupe_key=dedupe_key,
            recipient_member_id=None,
        )


def _counts_by_member(
    rows: Sequence[Any],
) -> dict[uuid.UUID, int]:
    """``(member_id, count)`` rows as a mapping, skipping a null key.

    The grouped columns are nullable in the schema — an Opportunity can have no
    Responsible Advisor and an appointment can predate ownership — so a null key
    is possible in general even though these queries filter it out. Skipping it
    is the honest narrowing; a cast would hide a real one.
    """
    return {row[0]: int(row[1]) for row in rows if row[0] is not None}


def _clean(value: str | None) -> str | None:
    """A trimmed string, or ``None`` for a blank one.

    The empty string is how a form says "clear this", and storing it would make
    ``calendar_id IS NOT NULL`` mean "configured" while the value is unusable.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _acting_member(actor: Actor) -> uuid.UUID:
    """The member id behind an Administrator command.

    ``Actor.member_id`` is optional because Product's own deterministic work has
    none. Every command here is Administrator-only, so a missing id means the
    Actor was assembled wrongly rather than that attribution is unavailable.
    """
    if actor.member_id is None:  # pragma: no cover - require_administrator precedes
        raise NotAuthorized(
            "Esta operación requiere una persona identificada de la organización."
        )
    return actor.member_id


def expert_candidates(
    designations: Sequence[PropertyExpert],
) -> list[tuple[uuid.UUID, str]]:
    """Expert advisor ids in the order the assignment rule must try them.

    Primary first, then backups by rank. Returned with each one's role so the
    caller records *which* expert branch was taken — "the specialist took it"
    and "the specialist could not" are different facts about the operation.
    """
    return [
        (row.advisor_id, row.role)
        for row in sorted(designations, key=lambda row: (row.rank, row.designated_at))
        if row.revoked_at is None
    ]

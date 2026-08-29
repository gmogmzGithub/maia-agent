"""Team administration: who may change it, and what a change must not break.

Three properties this suite holds still.

**Only an Administrator.** Alta, ausencia, especialista and the default Advisor
are the Organization Administrator's authority (PROJECT_MEMORY, SAN-035). An
Advisor may *see* the team — knowing a colleague is away is how a human decides
whether to wait — and may change none of it.

**An absence blocks new work, never existing work.** This is the property most
likely to be quietly broken by a later "helpful" improvement, so it is asserted
directly: after recording an absence, the Advisor's open Opportunities still
name them and their confirmed visits still exist.

**Expert is not owner.** Designating somebody the specialist for a Property
changes nothing about who is responsible for an Opportunity, and the audit trail
says so explicitly.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from realestate.db.models import (
    AdvisorAbsence,
    AppointmentStatus,
    AuditEvent,
    InternalAlert,
    InternalAlertKind,
    MemberProvisioning,
    MemberRole,
    Opportunity,
    Organization,
    OrganizationMember,
    Property,
    PropertyExpert,
    PropertyExpertRole,
    PropertyStatus,
)
from realestate.domain.commercial.actors import NotAuthorized, NotFound
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
)
from realestate.domain.commercial.team import (
    AddMember,
    DesignateExpert,
    EndAbsence,
    LastAdministrator,
    LoginTaken,
    NotAnAdvisor,
    OverlappingAbsence,
    RevokeExpert,
    SetDefaultAdvisor,
    SetMemberActive,
    StartAbsence,
    TeamAdministration,
    UpdateMember,
    absent_advisor_ids,
    current_absence,
)
from tests.conftest import requires_postgres
from tests.fixtures.visits import key
from tests.fixtures import commercial, visits

pytestmark = requires_postgres


# -- Administrator versus Advisor -----------------------------------------


async def test_only_an_administrator_may_add_a_member(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized):
            await TeamAdministration(session).record(
                built.advisor,
                AddMember(
                    command_key=key("add"),
                    login="tercero@larevia.test",
                    display_name="Tercer Asesor",
                    role=MemberRole.ADVISOR,
                    advises=True,
                ),
            )


async def test_an_administrator_adds_an_advisor_with_a_calendar(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            AddMember(
                command_key=key("add"),
                login="tercero@larevia.test",
                display_name="Tercer Asesor",
                role=MemberRole.ADVISOR,
                advises=True,
                calendar_id="tercero@larevia.test",
                telegram_chat_id="9004",
            ),
        )
        await session.commit()
        member = await session.get(OrganizationMember, recorded.subject_id)

    assert recorded.changed
    assert member is not None
    assert member.advises
    assert member.calendar_id == "tercero@larevia.test"
    # An Administrator-created member is not configuration's to remove.
    assert member.provisioned_by == MemberProvisioning.ADMINISTRATOR.value


async def test_adding_the_same_member_twice_with_one_key_creates_one(operation) -> None:
    database, built = operation
    command = AddMember(
        command_key=key("add"),
        login="tercero@larevia.test",
        display_name="Tercer Asesor",
        role=MemberRole.ADVISOR,
        advises=True,
    )
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        first = await administration.record(built.admin, command)
        await session.commit()
    async with database.session_scope() as session:
        second = await TeamAdministration(session).record(built.admin, command)
        await session.commit()

    assert first.changed
    assert not second.changed
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.login == "tercero@larevia.test"
                )
            )
        )
    assert len(rows) == 1


async def test_an_advisor_sees_the_team_but_no_forms_authority(operation) -> None:
    """Visibility and authority are separate; only the second is restricted."""
    database, built = operation
    async with database.session_scope() as session:
        views = await TeamAdministration(session).team(built.advisor)

    assert {view.member.login for view in views} >= {
        commercial.ADMIN_LOGIN,
        commercial.ADVISOR_LOGIN,
        commercial.SECOND_ADVISOR_LOGIN,
    }


async def test_the_last_active_administrator_cannot_be_deactivated(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        # ``developer`` also administers in the fixture plan, so it goes first.
        developer = await session.scalar(
            select(OrganizationMember).where(OrganizationMember.login == "developer")
        )
        assert developer is not None
        await TeamAdministration(session).record(
            built.admin,
            SetMemberActive(
                command_key=key("state"), member_id=developer.id, active=False
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(LastAdministrator):
            await TeamAdministration(session).record(
                built.admin,
                SetMemberActive(
                    command_key=key("state"),
                    member_id=built.admin_id,
                    active=False,
                ),
            )


async def test_deactivating_the_default_advisor_clears_the_fallback(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            SetMemberActive(
                command_key=key("state"), member_id=built.advisor_id, active=False
            ),
        )
        await session.commit()
        member = await session.get(OrganizationMember, built.advisor_id)

    assert member is not None
    assert not member.active
    # Leaving the flag would let assignment pick somebody who cannot log in.
    assert not member.is_default_advisor


async def test_a_member_who_cannot_advise_cannot_become_the_fallback(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotAnAdvisor):
            await TeamAdministration(session).record(
                built.admin,
                SetDefaultAdvisor(
                    command_key=key("default"), member_id=built.admin_id
                ),
            )


async def test_the_default_advisor_moves_to_the_second_advisor(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            SetDefaultAdvisor(
                command_key=key("default"), member_id=built.second_advisor_id
            ),
        )
        await session.commit()
        rows = list(
            await session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.is_default_advisor.is_(True)
                )
            )
        )

    assert [row.id for row in rows] == [built.second_advisor_id]


# -- Absences ------------------------------------------------------------


async def test_only_an_administrator_may_record_an_absence(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotAuthorized):
            await TeamAdministration(session).record(
                built.advisor,
                StartAbsence(
                    command_key=key("absence"),
                    advisor_id=built.advisor_id,
                    starts_at=visits.now() + timedelta(days=1),
                    ends_at=visits.now() + timedelta(days=3),
                ),
            )


async def test_an_absence_is_recorded_audited_and_surfaced(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() - timedelta(hours=1),
                ends_at=visits.now() + timedelta(days=3),
                reason="Vacaciones",
            ),
        )
        await session.commit()

        absence = await session.get(AdvisorAbsence, recorded.subject_id)
        actions = [
            event.action
            for event in await session.scalars(
                select(AuditEvent).where(AuditEvent.subject_type == "AdvisorAbsence")
            )
        ]
        alerts = list(
            await session.scalars(
                select(InternalAlert).where(
                    InternalAlert.kind == InternalAlertKind.ABSENCE_REVIEW.value
                )
            )
        )

    assert absence is not None
    assert absence.covers(visits.now())
    assert "RecordAdvisorAbsence" in actions
    # "Surfaced for Administrator review" is only true if somebody is told.
    assert len(alerts) == 1
    assert "no se reasignaron" in alerts[0].body or "siguen siendo suyas" in alerts[0].body


async def test_two_overlapping_absences_are_impossible(operation) -> None:
    database, built = operation
    start = visits.now() + timedelta(days=1)
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=start,
                ends_at=start + timedelta(days=5),
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(OverlappingAbsence):
            await TeamAdministration(session).record(
                built.admin,
                StartAbsence(
                    command_key=key("absence"),
                    advisor_id=built.advisor_id,
                    starts_at=start + timedelta(days=2),
                    ends_at=start + timedelta(days=7),
                ),
            )
        # The refusal did not poison the transaction: the session still works.
        assert await session.scalar(select(AdvisorAbsence.id)) is not None


async def test_an_absence_in_progress_is_truncated_not_deleted(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() - timedelta(days=1),
                ends_at=visits.now() + timedelta(days=3),
            ),
        )
        await session.commit()
        absence_id = recorded.subject_id

    async with database.session_scope() as session:
        ended = await TeamAdministration(session).record(
            built.admin, EndAbsence(command_key=key("end"), absence_id=absence_id)
        )
        await session.commit()
        absence = await session.get(AdvisorAbsence, absence_id)

    assert ended.detail == "ended"
    assert absence is not None
    assert absence.ended_early_at is not None
    assert absence.ended_by == built.admin_id
    # History stays readable: the period it covered is still there.
    assert absence.starts_at < absence.ends_at
    assert not absence.covers(visits.now())


async def test_ending_a_future_absence_voids_it(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() + timedelta(days=2),
                ends_at=visits.now() + timedelta(days=4),
            ),
        )
        await session.commit()
        absence_id = recorded.subject_id

    async with database.session_scope() as session:
        ended = await TeamAdministration(session).record(
            built.admin, EndAbsence(command_key=key("end"), absence_id=absence_id)
        )
        await session.commit()
        absence = await session.get(AdvisorAbsence, absence_id)

    assert ended.detail == "cancelled"
    assert absence is not None and absence.cancelled_at is not None


async def test_an_absence_does_not_reassign_or_cancel_existing_work(
    operation,
) -> None:
    """The safety property of the whole absence rule, asserted directly."""
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-absence", body="Quiero ver la casa"
        )
        visit = await visits.confirmed_visit(built, session, conversation)
        opportunity = await session.scalar(
            select(Opportunity).where(Opportunity.id == visit.opportunity_id)
        )
        assert opportunity is not None
        owner_before = opportunity.responsible_advisor_id
        assert owner_before == built.advisor_id
        visit_id = visit.id

    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() - timedelta(hours=1),
                ends_at=visits.now() + timedelta(days=10),
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        opportunity = await session.scalar(
            select(Opportunity).where(Opportunity.id == opportunity.id)
        )
        visit = await session.get(visits.Appointment, visit_id)

    assert opportunity is not None
    assert opportunity.responsible_advisor_id == owner_before
    assert visit is not None
    assert visit.status == AppointmentStatus.CONFIRMED.value
    assert visit.advisor_id == built.advisor_id
    assert visit.cancelled_at is None


async def test_absence_lookups_agree_about_who_is_away(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.second_advisor_id,
                starts_at=visits.now() - timedelta(minutes=5),
                ends_at=visits.now() + timedelta(days=1),
            ),
        )
        await session.commit()

        moment = visits.now()
        away = await absent_advisor_ids(
            session, built.admin.organization_id, moment
        )
        one = await current_absence(session, built.second_advisor_id, moment)
        other = await current_absence(session, built.advisor_id, moment)

    assert away == {built.second_advisor_id}
    assert one is not None
    assert other is None


# -- Property Experts ----------------------------------------------------


async def test_designating_an_expert_does_not_change_who_is_responsible(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        conversation = await visits.inbound(
            session, wamid="w-expert", body="Me interesa la casa"
        )
        await visits.confirmed_visit(built, session, conversation)
        opportunity = await session.scalar(
            select(Opportunity).where(
                Opportunity.responsible_advisor_id == built.advisor_id
            )
        )
        assert opportunity is not None
        opportunity_id = opportunity.id

    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        designations = await TeamAdministration(session).experts_for(
            built.property_uuid
        )
        audit = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "DesignatePropertyExpert"
                )
            )
        )

    assert opportunity is not None
    # The specialist changed; the responsible Advisor did not.
    assert opportunity.responsible_advisor_id == built.advisor_id
    assert [row.advisor_id for row in designations] == [built.second_advisor_id]
    assert audit and audit[0].details["changes_opportunity_ownership"] is False


async def test_an_administrator_cannot_designate_another_organizations_property(
    operation,
) -> None:
    """A property UUID is not authority to cross the organization boundary."""
    database, built = operation
    suffix = uuid.uuid4().hex
    async with database.session_scope() as session:
        other = Organization(slug=f"other-{suffix}", display_name="Otra organización")
        session.add(other)
        await session.flush()
        foreign_property = Property(
            organization_id=other.id,
            property_key=f"foreign-{suffix}",
            name="Propiedad ajena",
            normalized_name=f"propiedad ajena {suffix}",
            status=PropertyStatus.ACTIVE.value,
        )
        session.add(foreign_property)
        await session.flush()
        foreign_property_id = foreign_property.id
        with pytest.raises(NotFound):
            await TeamAdministration(session).record(
                built.admin,
                DesignateExpert(
                    command_key=key("foreign-expert"),
                    property_uuid=foreign_property_id,
                    advisor_id=built.advisor_id,
                    role=PropertyExpertRole.PRIMARY,
                ),
            )
        designation = await session.scalar(
            select(PropertyExpert).where(
                PropertyExpert.property_uuid == foreign_property_id
            )
        )
        assert designation is None
        await session.rollback()


async def test_one_property_has_at_most_one_primary_expert(operation) -> None:
    database, built = operation
    administration_key = key("expert")
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=administration_key,
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        live = list(
            await session.scalars(
                select(PropertyExpert)
                .where(PropertyExpert.property_uuid == built.property_uuid)
                .where(PropertyExpert.revoked_at.is_(None))
            )
        )
        revoked = list(
            await session.scalars(
                select(PropertyExpert).where(
                    PropertyExpert.revoked_at.is_not(None)
                )
            )
        )

    assert [row.advisor_id for row in live] == [built.second_advisor_id]
    # Revoked, not deleted: a past visit's attribution still has an answer.
    assert [row.advisor_id for row in revoked] == [built.advisor_id]


async def test_a_backup_expert_coexists_with_the_primary(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.BACKUP,
                rank=1,
            ),
        )
        await session.commit()
        designations = await administration.experts_for(built.property_uuid)

    assert [row.role for row in designations] == [
        PropertyExpertRole.PRIMARY.value,
        PropertyExpertRole.BACKUP.value,
    ]


async def test_revoking_an_expert_is_idempotent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        first = await TeamAdministration(session).record(
            built.admin,
            RevokeExpert(
                command_key=key("revoke"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        second = await TeamAdministration(session).record(
            built.admin,
            RevokeExpert(
                command_key=key("revoke"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
            ),
        )
        await session.commit()

    assert first.changed
    assert not second.changed


async def test_an_unknown_member_reads_as_absent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await TeamAdministration(session).record(
                built.admin,
                UpdateMember(
                    command_key=key("update"),
                    member_id=uuid.uuid4(),
                    display_name="Nadie",
                ),
            )


# -- Configuration versus the Administrator ------------------------------


async def test_reconciliation_never_deactivates_an_administrator_created_member(
    operation,
) -> None:
    """ADR-0047: configuration governs its own rows and nothing else.

    Without the provenance column, the next restart would delete the team an
    Administrator had just built.
    """
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            AddMember(
                command_key=key("add"),
                login="contratado@larevia.test",
                display_name="Asesor Contratado",
                role=MemberRole.ADVISOR,
                advises=True,
                calendar_id="contratado@larevia.test",
            ),
        )
        await session.commit()
        member_id = recorded.subject_id

    async with database.session_scope() as session:
        # Startup reconciliation runs with the original configured plan, which
        # has never heard of the new Advisor.
        await OrganizationDirectory(session).reconcile(commercial.BOOKABLE_PLAN)
        member = await session.get(OrganizationMember, member_id)

    assert member is not None
    assert member.active
    assert member.calendar_id == "contratado@larevia.test"


async def test_a_configured_login_that_disappears_is_still_deactivated(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN, "developer"),
                advisors=(commercial.ADVISOR_LOGIN,),
                default_advisor=commercial.ADVISOR_LOGIN,
                calendars=dict(commercial.BOOKABLE_PLAN.calendars),
            )
        )
        member = await session.get(OrganizationMember, built.second_advisor_id)

    assert member is not None
    assert not member.active


async def test_configuration_supplies_a_calendar_without_clearing_one(
    operation,
) -> None:
    """An absent environment variable is not an instruction to erase a value."""
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            UpdateMember(
                command_key=key("update"),
                member_id=built.second_advisor_id,
                calendar_id="cambiado@larevia.test",
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN, "developer"),
                advisors=(commercial.ADVISOR_LOGIN, commercial.SECOND_ADVISOR_LOGIN),
                default_advisor=commercial.ADVISOR_LOGIN,
                calendars={},
            )
        )
        member = await session.get(OrganizationMember, built.second_advisor_id)

    assert member is not None
    assert member.calendar_id == "cambiado@larevia.test"


# -- Reads the surfaces depend on ----------------------------------------


async def test_the_expert_directory_lists_primary_and_backups(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.second_advisor_id,
                role=PropertyExpertRole.BACKUP,
                rank=1,
            ),
        )
        await session.commit()
        directory = await administration.expert_directory(built.admin)

    assert len(directory) == 1
    view = directory[0]
    assert view.primary is not None
    assert view.primary.id == built.advisor_id
    assert [member.id for member in view.backups] == [built.second_advisor_id]
    assert view.property_key


async def test_the_absence_list_separates_current_from_upcoming(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() - timedelta(hours=1),
                ends_at=visits.now() + timedelta(days=1),
            ),
        )
        await administration.record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() + timedelta(days=5),
                ends_at=visits.now() + timedelta(days=7),
            ),
        )
        await session.commit()
        views = {view.member.id: view for view in await administration.team(built.admin)}
        live = await administration.absences(built.admin)
        everything = await administration.absences(built.admin, include_past=True)

    view = views[built.advisor_id]
    assert view.absent
    assert len(view.upcoming_absences) == 1
    assert not view.can_receive_appointments
    assert len(live) == 2
    assert len(everything) == 2


async def test_the_default_advisor_can_be_cleared(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin, SetDefaultAdvisor(command_key=key("default"), member_id=None)
        )
        await session.commit()
        remaining = list(
            await session.scalars(
                select(OrganizationMember).where(
                    OrganizationMember.is_default_advisor.is_(True)
                )
            )
        )

    assert recorded.changed
    assert remaining == []


async def test_updating_nothing_reports_no_change(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            UpdateMember(command_key=key("update"), member_id=built.advisor_id),
        )
        await session.commit()

    assert not recorded.changed


async def test_a_member_can_be_renamed_and_reconfigured(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            UpdateMember(
                command_key=key("update"),
                member_id=built.advisor_id,
                display_name="Santiago Larevia",
                calendar_id="  santiago@larevia.test  ",
                telegram_chat_id="",
            ),
        )
        await session.commit()
        member = await session.get(OrganizationMember, built.advisor_id)

    assert member is not None
    assert member.display_name == "Santiago Larevia"
    # Trimmed, and the empty string is how a form says "clear this".
    assert member.calendar_id == "santiago@larevia.test"
    assert member.telegram_chat_id is None


async def test_an_advisor_cannot_be_made_ineligible_to_own_work(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import InvalidTransition

        with pytest.raises(InvalidTransition):
            await TeamAdministration(session).record(
                built.admin,
                UpdateMember(
                    command_key=key("update"),
                    member_id=built.second_advisor_id,
                    advises=False,
                ),
            )


async def test_an_absence_must_move_forward_in_time(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import InvalidTransition

        moment = visits.now()
        with pytest.raises(InvalidTransition):
            await TeamAdministration(session).record(
                built.admin,
                StartAbsence(
                    command_key=key("absence"),
                    advisor_id=built.advisor_id,
                    starts_at=moment + timedelta(days=2),
                    ends_at=moment + timedelta(days=1),
                ),
            )


async def test_a_deactivated_advisor_cannot_receive_an_absence(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await TeamAdministration(session).record(
            built.admin,
            SetMemberActive(
                command_key=key("state"),
                member_id=built.second_advisor_id,
                active=False,
            ),
        )
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(NotAnAdvisor):
            await TeamAdministration(session).record(
                built.admin,
                StartAbsence(
                    command_key=key("absence"),
                    advisor_id=built.second_advisor_id,
                    starts_at=visits.now() + timedelta(days=1),
                    ends_at=visits.now() + timedelta(days=2),
                ),
            )


async def test_a_deactivated_member_can_be_reactivated(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            SetMemberActive(
                command_key=key("state"),
                member_id=built.second_advisor_id,
                active=False,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            SetMemberActive(
                command_key=key("state"),
                member_id=built.second_advisor_id,
                active=True,
            ),
        )
        await session.commit()
        member = await session.get(OrganizationMember, built.second_advisor_id)

    assert recorded.changed
    assert member is not None and member.active


async def test_ending_an_absence_that_already_finished_changes_nothing(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            StartAbsence(
                command_key=key("absence"),
                advisor_id=built.advisor_id,
                starts_at=visits.now() + timedelta(days=1),
                ends_at=visits.now() + timedelta(days=2),
            ),
        )
        await session.commit()
        absence_id = recorded.subject_id
        await visits.age_absence(session, absence_id, days=5)

    async with database.session_scope() as session:
        ended = await TeamAdministration(session).record(
            built.admin, EndAbsence(command_key=key("end"), absence_id=absence_id)
        )
        await session.commit()

    assert not ended.changed


async def test_ending_an_unknown_absence_reads_as_absent(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await TeamAdministration(session).record(
                built.admin,
                EndAbsence(command_key=key("end"), absence_id=uuid.uuid4()),
            )


async def test_designating_an_expert_for_an_unknown_property_reads_as_absent(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await TeamAdministration(session).record(
                built.admin,
                DesignateExpert(
                    command_key=key("expert"),
                    property_uuid=uuid.uuid4(),
                    advisor_id=built.advisor_id,
                    role=PropertyExpertRole.PRIMARY,
                ),
            )


async def test_designating_the_same_expert_in_the_same_role_is_a_no_op(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        await administration.record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        again = await TeamAdministration(session).record(
            built.admin,
            DesignateExpert(
                command_key=key("expert"),
                property_uuid=built.property_uuid,
                advisor_id=built.advisor_id,
                role=PropertyExpertRole.PRIMARY,
            ),
        )
        await session.commit()

    assert not again.changed


async def test_an_advisor_who_cannot_own_work_cannot_be_an_expert(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(NotAnAdvisor):
            await TeamAdministration(session).record(
                built.admin,
                DesignateExpert(
                    command_key=key("expert"),
                    property_uuid=built.property_uuid,
                    advisor_id=built.admin_id,
                    role=PropertyExpertRole.PRIMARY,
                ),
            )


async def test_a_blank_login_is_refused(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import InvalidTransition

        with pytest.raises(InvalidTransition):
            await TeamAdministration(session).record(
                built.admin,
                AddMember(
                    command_key=key("add"),
                    login="   ",
                    display_name="Nadie",
                    role=MemberRole.ADVISOR,
                    advises=True,
                ),
            )


async def test_an_existing_login_cannot_be_added_again(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        with pytest.raises(LoginTaken):
            await TeamAdministration(session).record(
                built.admin,
                AddMember(
                    command_key=key("add"),
                    login=commercial.ADVISOR_LOGIN,
                    display_name="Duplicado",
                    role=MemberRole.ADVISOR,
                    advises=True,
                ),
            )


async def test_an_administrator_added_as_an_administrator_does_not_advise(
    operation,
) -> None:
    """The role and the eligibility to own work are separate facts (ADR-0046)."""
    database, built = operation
    async with database.session_scope() as session:
        recorded = await TeamAdministration(session).record(
            built.admin,
            AddMember(
                command_key=key("add"),
                login="jefe@larevia.test",
                display_name="Jefa",
                role=MemberRole.ADMINISTRATOR,
                advises=False,
            ),
        )
        await session.commit()
        member = await session.get(OrganizationMember, recorded.subject_id)

    assert member is not None
    assert member.role == MemberRole.ADMINISTRATOR.value
    assert not member.advises


async def test_every_team_label_has_spanish(operation) -> None:
    """A value that reached a screen as an English identifier would be a leak."""
    from realestate.domain.commercial.team import EXPERT_ROLE_LABELS

    assert set(EXPERT_ROLE_LABELS) == {
        PropertyExpertRole.PRIMARY.value,
        PropertyExpertRole.BACKUP.value,
    }
    for label in EXPERT_ROLE_LABELS.values():
        assert label and label[0].isupper()


async def test_an_empty_organization_has_an_empty_team(operation) -> None:
    database, built = operation
    async with database.session_scope() as session:
        await session.execute(
            visits.delete(OrganizationMember).where(
                OrganizationMember.organization_id == built.admin.organization_id
            )
        )
        await session.commit()
        assert await TeamAdministration(session).team(built.admin) == []
        assert await TeamAdministration(session).expert_directory(built.admin) != []


async def test_replaying_a_start_absence_key_returns_the_same_absence(
    operation,
) -> None:
    database, built = operation
    command_key = key("absence")
    starts = visits.now() + timedelta(days=1)
    ends = visits.now() + timedelta(days=2)
    results = []
    for _ in range(2):
        async with database.session_scope() as session:
            results.append(
                await TeamAdministration(session).record(
                    built.admin,
                    StartAbsence(
                        command_key=command_key,
                        advisor_id=built.advisor_id,
                        starts_at=starts,
                        ends_at=ends,
                    ),
                )
            )
            await session.commit()

    assert results[0].subject_id == results[1].subject_id
    assert results[0].changed and not results[1].changed
    async with database.session_scope() as session:
        rows = list(await session.scalars(select(AdvisorAbsence)))
    assert len(rows) == 1


async def test_replaying_the_state_and_default_keys_changes_nothing_twice(
    operation,
) -> None:
    database, built = operation
    state_key = key("state")
    default_key = key("default")
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        first = await administration.record(
            built.admin,
            SetMemberActive(
                command_key=state_key,
                member_id=built.second_advisor_id,
                active=False,
            ),
        )
        default_first = await administration.record(
            built.admin,
            SetDefaultAdvisor(command_key=default_key, member_id=built.advisor_id),
        )
        await session.commit()
    async with database.session_scope() as session:
        administration = TeamAdministration(session)
        second = await administration.record(
            built.admin,
            SetMemberActive(
                command_key=state_key,
                member_id=built.second_advisor_id,
                active=False,
            ),
        )
        default_second = await administration.record(
            built.admin,
            SetDefaultAdvisor(command_key=default_key, member_id=built.advisor_id),
        )
        await session.commit()

    assert first.changed and not second.changed
    assert not default_second.changed
    assert default_first.subject_id == built.advisor_id


async def test_replaying_an_update_key_changes_nothing_twice(operation) -> None:
    database, built = operation
    command_key = key("update")
    for _ in range(2):
        async with database.session_scope() as session:
            recorded = await TeamAdministration(session).record(
                built.admin,
                UpdateMember(
                    command_key=command_key,
                    member_id=built.advisor_id,
                    display_name="Nombre Único",
                ),
            )
            await session.commit()

    assert not recorded.changed
    async with database.session_scope() as session:
        member = await session.get(OrganizationMember, built.advisor_id)
    assert member is not None and member.display_name == "Nombre Único"


async def test_replaying_an_expert_designation_key_changes_nothing_twice(
    operation,
) -> None:
    database, built = operation
    command_key = key("expert")
    for _ in range(2):
        async with database.session_scope() as session:
            recorded = await TeamAdministration(session).record(
                built.admin,
                DesignateExpert(
                    command_key=command_key,
                    property_uuid=built.property_uuid,
                    advisor_id=built.advisor_id,
                    role=PropertyExpertRole.PRIMARY,
                ),
            )
            await session.commit()

    assert not recorded.changed
    async with database.session_scope() as session:
        live = list(
            await session.scalars(
                select(PropertyExpert).where(PropertyExpert.revoked_at.is_(None))
            )
        )
    assert len(live) == 1


async def test_the_default_advisor_cannot_lose_eligibility_while_holding_it(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        from realestate.domain.commercial.actors import InvalidTransition

        # The role check fires first for an Advisor, so this exercises the
        # fallback guard on a member who administers *and* advises.
        member = await session.get(OrganizationMember, built.advisor_id)
        assert member is not None
        member.role = MemberRole.ADMINISTRATOR.value
        await session.commit()

        with pytest.raises(InvalidTransition) as raised:
            await TeamAdministration(session).record(
                built.admin,
                UpdateMember(
                    command_key=key("update"),
                    member_id=built.advisor_id,
                    advises=False,
                ),
            )
    assert "predeterminado" in str(raised.value)


async def test_absence_lookups_with_no_candidates_answer_immediately(
    operation,
) -> None:
    database, built = operation
    async with database.session_scope() as session:
        assert (
            await absent_advisor_ids(
                session, built.admin.organization_id, visits.now(), among=[]
            )
            == set()
        )

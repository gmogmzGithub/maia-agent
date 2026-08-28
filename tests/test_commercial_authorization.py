"""Who may see and change what: roles, Organization scoping, and the directory.

Authentication is unchanged from Stage 0 — HTTP Basic against the configured
operational credentials. What Stage 2 adds is that the authenticated username
resolves to a member row naming an Organization and a role. A credential that
exists in the environment but not in the directory is refused rather than
treated as an implicit administrator, which is the ambiguity this cut removes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from realestate.db.engine import Database
from realestate.db.models import (
    AuditEvent,
    MemberRole,
    OpportunityStage,
    Organization,
    OrganizationMember,
)
from realestate.domain.commercial.actors import (
    Actor,
    Authority,
    CommercialError,
    NotAuthorized,
    NotFound,
    UnknownMember,
)
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.identity import CommercialIdentity
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    OpportunityManagement,
)
from realestate.domain.commercial.organization import (
    DirectoryPlan,
    OrganizationDirectory,
    parse_logins,
)
from realestate.domain.commercial.views import CommercialInbox
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres


@pytest.fixture
async def wired():
    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        # This suite asserts on reconciliation itself, so it needs the member
        # table empty rather than whatever an earlier suite provisioned.
        await commercial.reset(session, members=True)
    yield database
    await database.dispose()


# -- Reading configuration -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ()),
        ("uno", ("uno",)),
        (" uno , dos ", ("uno", "dos")),
        ("uno,,dos,", ("uno", "dos")),
        ("uno,dos,uno", ("uno", "dos")),
    ],
)
def test_logins_are_read_forgivingly_but_without_duplicates(
    raw: str, expected: tuple[str, ...]
) -> None:
    assert parse_logins(raw) == expected


def test_a_login_in_both_lists_administers_and_advises() -> None:
    """How "Santiago initially has both roles" is expressed unambiguously."""
    plan = DirectoryPlan.from_configuration(
        administrators="santiago", advisors="santiago,ana", default_advisor=""
    )
    assert plan.role_of("santiago") is MemberRole.ADMINISTRATOR
    assert plan.advises("santiago") is True
    assert plan.role_of("ana") is MemberRole.ADVISOR
    assert plan.advises("ana") is True


def test_an_administrator_who_is_not_listed_as_an_advisor_does_not_advise() -> None:
    plan = DirectoryPlan.from_configuration(
        administrators="guillermo", advisors="ana", default_advisor="ana"
    )
    assert plan.advises("guillermo") is False
    assert plan.advises("ana") is True


def test_a_single_advisor_is_the_default_without_being_named_twice() -> None:
    plan = DirectoryPlan.from_configuration(
        administrators="guillermo", advisors="ana", default_advisor=""
    )
    assert plan.default_advisor == "ana"


def test_two_advisors_and_no_default_leaves_the_fallback_unset() -> None:
    plan = DirectoryPlan.from_configuration(
        administrators="", advisors="ana,beto", default_advisor=""
    )
    assert plan.default_advisor is None


def test_a_default_advisor_who_is_nobody_is_refused_loudly() -> None:
    """A typo here would silently send every Opportunity to the queue."""
    with pytest.raises(ValueError, match="ORGANIZATION_DEFAULT_ADVISOR_LOGIN"):
        DirectoryPlan.from_configuration(
            administrators="guillermo", advisors="ana", default_advisor="anna"
        )


def test_the_settings_expose_the_same_validated_plan() -> None:
    from realestate.config import Settings

    settings = Settings(
        _env_file=None,
        ORGANIZATION_ADMIN_LOGINS="guillermo",
        ORGANIZATION_ADVISOR_LOGINS="ana,beto",
        ORGANIZATION_DEFAULT_ADVISOR_LOGIN="beto",
    )
    plan = settings.directory_plan
    assert plan.administrators == ("guillermo",)
    assert plan.default_advisor == "beto"

    invalid = Settings(
        _env_file=None,
        ORGANIZATION_ADMIN_LOGINS="guillermo",
        ORGANIZATION_ADVISOR_LOGINS="ana",
        ORGANIZATION_DEFAULT_ADVISOR_LOGIN="nadie",
    )
    with pytest.raises(ValueError):
        _ = invalid.directory_plan


# -- Reconciling the directory ---------------------------------------------


async def test_reconciliation_creates_the_configured_team_and_audits_it(
    wired,
) -> None:
    async with wired.session_scope() as session:
        result = await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)

        assert set(result.created) == {
            commercial.ADMIN_LOGIN,
            commercial.ADVISOR_LOGIN,
            commercial.SECOND_ADVISOR_LOGIN,
        }
        assert result.changed is True
        members = {
            member.login: member
            for member in await session.scalars(select(OrganizationMember))
        }
        assert members[commercial.ADMIN_LOGIN].role == MemberRole.ADMINISTRATOR.value
        assert members[commercial.ADMIN_LOGIN].advises is False
        assert members[commercial.ADVISOR_LOGIN].is_default_advisor is True
        assert members[commercial.SECOND_ADVISOR_LOGIN].is_default_advisor is False
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "ReconcileOrganizationMembers"
                )
            )
            == 1
        )


async def test_reconciling_twice_changes_nothing(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)

    async with wired.session_scope() as session:
        result = await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)
        assert result.changed is False
        assert (
            await session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "ReconcileOrganizationMembers"
                )
            )
            == 1
        )


async def test_a_changed_role_is_updated_in_place(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)

    async with wired.session_scope() as session:
        promoted = DirectoryPlan(
            administrators=(commercial.ADMIN_LOGIN, commercial.ADVISOR_LOGIN),
            advisors=(commercial.ADVISOR_LOGIN, commercial.SECOND_ADVISOR_LOGIN),
            default_advisor=commercial.ADVISOR_LOGIN,
        )
        result = await OrganizationDirectory(session).reconcile(promoted)

        assert result.updated == (commercial.ADVISOR_LOGIN,)
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert member is not None
        assert member.role == MemberRole.ADMINISTRATOR.value
        # Still advises, and still the deterministic fallback.
        assert member.advises is True
        assert member.is_default_advisor is True


async def test_a_removed_login_is_deactivated_not_deleted(wired) -> None:
    """Assignments and Next Actions point at the row; history must stay legible."""
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)

    async with wired.session_scope() as session:
        smaller = DirectoryPlan(
            administrators=(commercial.ADMIN_LOGIN,),
            advisors=(commercial.ADVISOR_LOGIN,),
            default_advisor=commercial.ADVISOR_LOGIN,
        )
        result = await OrganizationDirectory(session).reconcile(smaller)

        assert result.deactivated == (commercial.SECOND_ADVISOR_LOGIN,)
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.SECOND_ADVISOR_LOGIN
            )
        )
        assert member is not None
        assert member.active is False
        assert member.is_default_advisor is False


async def test_a_reappearing_login_is_reactivated(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(commercial.ADVISOR_LOGIN,),
                default_advisor=commercial.ADVISOR_LOGIN,
            )
        )

    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(),
                default_advisor=None,
            )
        )

    async with wired.session_scope() as session:
        result = await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(commercial.ADVISOR_LOGIN,),
                default_advisor=commercial.ADVISOR_LOGIN,
            )
        )
        assert commercial.ADVISOR_LOGIN in result.updated
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert member is not None and member.active is True


async def test_the_default_advisor_moves_without_colliding(wired) -> None:
    """At most one per Organization, enforced by a partial unique index."""
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)

    async with wired.session_scope() as session:
        moved = DirectoryPlan(
            administrators=(commercial.ADMIN_LOGIN,),
            advisors=(commercial.ADVISOR_LOGIN, commercial.SECOND_ADVISOR_LOGIN),
            default_advisor=commercial.SECOND_ADVISOR_LOGIN,
        )
        await OrganizationDirectory(session).reconcile(moved)

        defaults = list(
            await session.scalars(
                select(OrganizationMember.login).where(
                    OrganizationMember.is_default_advisor.is_(True)
                )
            )
        )
        assert defaults == [commercial.SECOND_ADVISOR_LOGIN]


async def test_a_missing_organization_fails_loudly(wired) -> None:
    async with wired.session_scope() as session:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            await OrganizationDirectory(session).organization("no-existe")


async def test_the_organization_row_is_singular(wired) -> None:
    async with wired.session_scope() as session:
        slugs = list(await session.scalars(select(Organization.slug)))
        assert slugs == ["larevia"]


# -- Resolving an Actor ----------------------------------------------------


async def test_an_unknown_credential_is_refused_with_an_explanation(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)
        with pytest.raises(UnknownMember) as raised:
            await OrganizationDirectory(session).resolve_actor("nadie@larevia.test")
        assert "administrador" in raised.value.message
        assert raised.value.message.endswith("de alta.")


async def test_a_deactivated_member_can_no_longer_act(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)
        member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.login == commercial.ADVISOR_LOGIN
            )
        )
        assert member is not None
        member.active = False
        await session.flush()

        with pytest.raises(UnknownMember):
            await OrganizationDirectory(session).resolve_actor(commercial.ADVISOR_LOGIN)


async def test_the_resolved_actor_carries_its_organization_and_authority(
    wired,
) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)
        organization_id = await commercial.organization_id(session)

        admin = await OrganizationDirectory(session).resolve_actor(
            commercial.ADMIN_LOGIN
        )
        advisor = await OrganizationDirectory(session).resolve_actor(
            commercial.ADVISOR_LOGIN
        )

        assert admin.organization_id == organization_id
        assert admin.authority is Authority.ADMINISTRATOR
        assert admin.is_administrator is True
        assert admin.sees_whole_operation is True
        assert admin.actor_type == "OrganizationMember"

        assert advisor.authority is Authority.ADVISOR
        assert advisor.is_administrator is False
        assert advisor.sees_whole_operation is False


def test_product_is_organization_scoped_but_not_an_administrator() -> None:
    """The deterministic paths reach unowned work; they do not declare wins."""
    organization_id = uuid.uuid4()
    product = Actor.product(organization_id, "DormancySweep")

    assert product.organization_id == organization_id
    assert product.is_product is True
    assert product.is_administrator is False
    assert product.sees_whole_operation is True
    assert product.actor_type == "Product"
    with pytest.raises(NotAuthorized):
        product.require_administrator()


def test_a_record_from_another_organization_reads_as_absent() -> None:
    actor = Actor.product(uuid.uuid4(), "Test")
    actor.require_same_organization(actor.organization_id)
    with pytest.raises(NotFound):
        actor.require_same_organization(uuid.uuid4())


def test_every_commercial_error_carries_mexican_spanish() -> None:
    for error in (
        CommercialError(),
        NotAuthorized(),
        UnknownMember(),
        NotFound(),
    ):
        assert error.message
        assert error.message[-1] in ".:"
        assert error.message == str(error)

    custom = NotFound("No encontramos esa oportunidad.")
    assert custom.message == "No encontramos esa oportunidad."


def test_the_members_helper_can_narrow_to_advisors() -> None:
    """Signature check: ``advisors_only`` is the only filter callers get."""
    import inspect

    signature = inspect.signature(OrganizationDirectory.members)
    assert list(signature.parameters) == [
        "self",
        "organization_id",
        "advisors_only",
    ]


async def test_only_advisors_come_back_when_asked_for_advisors(wired) -> None:
    async with wired.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)
        organization_id = await commercial.organization_id(session)
        directory = OrganizationDirectory(session)

        everyone = {member.login for member in await directory.members(organization_id)}
        advisors = {
            member.login
            for member in await directory.members(organization_id, advisors_only=True)
        }

        assert commercial.ADMIN_LOGIN in everyone
        assert commercial.ADMIN_LOGIN not in advisors
        assert advisors == {
            commercial.ADVISOR_LOGIN,
            commercial.SECOND_ADVISOR_LOGIN,
        }


# -- Scoping in practice ---------------------------------------------------


async def test_an_advisor_cannot_reach_a_colleagues_opportunity(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        await Assignment(session).assign_manually(
            admin, opportunity_id, members[commercial.SECOND_ADVISOR_LOGIN]
        )
        await session.commit()

    async with wired.session_scope() as session:
        management = OpportunityManagement(session)
        owner = await commercial.actor_for(session, commercial.SECOND_ADVISOR_LOGIN)
        other = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)

        assert (
            await management.opportunity(owner, opportunity_id)
        ).id == opportunity_id
        assert (
            await management.opportunity(admin, opportunity_id)
        ).id == opportunity_id
        with pytest.raises(NotFound):
            await management.opportunity(other, opportunity_id)
        with pytest.raises(NotFound):
            await CommercialIdentity(session).contact(other, contact_id)


async def test_an_unassigned_opportunity_is_invisible_to_an_advisor(wired) -> None:
    """Nobody is responsible for it yet — which is the Administrator's problem."""
    async with wired.session_scope() as session:
        await commercial.provision(session)
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        with pytest.raises(NotFound):
            await OpportunityManagement(session).opportunity(advisor, opportunity_id)
        rows = await CommercialInbox(session).opportunities(advisor)
        assert rows == []


async def test_an_advisor_sees_only_their_own_pipeline_and_contacts(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        mine_contact, _ = await commercial.make_contact(session, "5213311110000")
        theirs_contact, _ = await commercial.make_contact(session, "5213322220000")
        mine = await commercial.open_opportunity(session, admin, mine_contact)
        theirs = await commercial.open_opportunity(session, admin, theirs_contact)
        assignment = Assignment(session)
        await assignment.assign_manually(admin, mine, members[commercial.ADVISOR_LOGIN])
        await assignment.assign_manually(
            admin, theirs, members[commercial.SECOND_ADVISOR_LOGIN]
        )
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        views = CommercialInbox(session)

        pipeline = await views.opportunities(advisor)
        assert [row.opportunity.id for row in pipeline] == [mine]

        contacts = await views.contacts(advisor)
        assert [row.contact.id for row in contacts] == [mine_contact]

        # Asking for "everything" still means everything they may see.
        everything = await views.opportunities(advisor, scope="all")
        assert [row.opportunity.id for row in everything] == [mine]


async def test_an_administrator_sees_the_whole_initial_operation(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        first_contact, _ = await commercial.make_contact(session, "5213311110000")
        second_contact, _ = await commercial.make_contact(session, "5213322220000")
        first = await commercial.open_opportunity(session, admin, first_contact)
        second = await commercial.open_opportunity(session, admin, second_contact)
        await Assignment(session).assign_manually(
            admin, first, members[commercial.SECOND_ADVISOR_LOGIN]
        )
        await session.commit()

    async with wired.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        rows = await CommercialInbox(session).opportunities(admin)
        assert {row.opportunity.id for row in rows} == {first, second}
        contacts = await CommercialInbox(session).contacts(admin)
        assert {row.contact.id for row in contacts} == {first_contact, second_contact}


async def test_another_organization_sees_nothing_of_this_one(wired) -> None:
    async with wired.session_scope() as session:
        await commercial.provision(session)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        await session.commit()

    async with wired.session_scope() as session:
        outsider = Actor.product(uuid.uuid4(), "OtraInmobiliaria")
        views = CommercialInbox(session)

        assert await views.opportunities(outsider) == []
        assert await views.contacts(outsider) == []
        assert await views.query(outsider) == []
        coverage = await views.coverage(outsider)
        assert coverage.active == 0
        with pytest.raises(NotFound):
            await CommercialIdentity(session).contact(outsider, contact_id)
        with pytest.raises(NotFound):
            await OpportunityManagement(session).opportunity(outsider, opportunity_id)


async def test_an_advisor_may_advance_their_own_opportunity(wired) -> None:
    async with wired.session_scope() as session:
        members = await commercial.provision(session)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        contact_id, _ = await commercial.make_contact(session, "5213312345678")
        opportunity_id = await commercial.open_opportunity(session, admin, contact_id)
        await Assignment(session).assign_manually(
            admin, opportunity_id, members[commercial.ADVISOR_LOGIN]
        )
        await session.commit()

    async with wired.session_scope() as session:
        advisor = await commercial.actor_for(session, commercial.ADVISOR_LOGIN)
        result = await OpportunityManagement(session).record(
            advisor,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.IN_CONVERSATION,
                command_key="advisor:advance",
            ),
        )
        await session.commit()
        assert result.stage is OpportunityStage.IN_CONVERSATION

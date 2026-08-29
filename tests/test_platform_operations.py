"""Provisioning, configuration, entitlements, support, import and lifecycle.

The isolation matrix lives in ``test_platform_isolation.py``. This file is about
the *operations* a managed service performs on an Organization, and the property
each one has to have:

* provisioning is resumable after a failure and reversible afterwards;
* configuration is versioned, idempotent on the document, and cannot carry a
  credential;
* an entitlement change lands while the operation is running and is explainable
  at both times;
* support access expires on the clock, not on a worker having run;
* an import's dry run and its apply agree, and rollback removes exactly what the
  apply created;
* an export names what it withholds, and a deletion refuses a retention hold
  rather than partially complying.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from realestate.db.engine import Database
from realestate.db.models import (
    Capability,
    ChannelBindingKind,
    DataLifecycleState,
    DeletionScope,
    EntitlementSource,
    EntitlementState,
    ImportFindingKind,
    ImportState,
    IntegrationProvider,
    Organization,
    OrganizationMember,
    OrganizationStatus,
    Property,
    ProvisioningState,
    RetentionBasis,
    SecretReferenceState,
    UsageMetric,
)
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    NotAuthorized,
)
from realestate.domain.commercial.organization import (
    OrganizationDirectory,
    SupportAccessExpired,
)
from realestate.domain.platform.authority import (
    PlatformOperator,
    ReasonRequired,
    require_reason,
)
from realestate.domain.platform.configuration import (
    ConfigurationMissing,
    InvalidConfiguration,
    OrganizationConfiguration,
    RecordConfiguration,
    checksum_of,
)
from realestate.domain.platform.credentials import (
    InvalidReference,
    IntegrationCredentials,
    RecordSecretReference,
    SecretResolver,
    UnresolvableCredential,
    validate_reference,
)
from realestate.domain.platform.entitlements import (
    ADD_ONS,
    BASE_PACKAGE,
    Entitlements,
    GrantEntitlement,
    NotEntitled,
    TIERS,
    tier_for,
)
from realestate.domain.platform.imports import (
    ImportPlan,
    ImportRefused,
    IncomingProperty,
    OrganizationImport,
)
from realestate.domain.platform.lifecycle import (
    DeleteOrganizationData,
    ExportOrganizationData,
    OrganizationDataLifecycle,
    RecordRetentionHold,
)
from realestate.domain.platform.provisioning import (
    ChannelAssignment,
    CredentialAssignment,
    DeprovisionOrganization,
    OrganizationProvisioning,
    ProvisionOrganization,
    ProvisioningRefused,
    STEP_ACTIVATION,
    STEP_CHANNELS,
    STEP_TEAM,
    normalise_slug,
)
from realestate.domain.platform.support import (
    GrantSupportAccess,
    MAX_GRANT_HOURS,
    SupportAccess,
    SupportAccessRefused,
    support_login_for,
)
from realestate.domain.platform.usage import PlatformUsage, month_start
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = [pytest.mark.anyio, requires_postgres]

OPERATOR = PlatformOperator(label="operations-tester")
SLUG = "operaciones-test"
ADMIN = "dir@operaciones.test"
ADVISOR = "ana@operaciones.test"
REASON = "Prueba de operaciones de plataforma en la suite automatizada."

CONFIGURATION = {
    "brand": {"working_name": "Operaciones"},
    "service_area": {"municipalities": ["Guadalajara"]},
    "scheduling": {"time_zone": "America/Mexico_City", "visit_minutes": 90},
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await _forget(session)
    yield db
    async with db.session_scope() as session:
        await _forget(session)
    await db.dispose()


#: Channel identifiers this suite claims. Retired from *whichever* Organization
#: holds them before each test, because one deliberately-failing test binds one
#: of them to the founding Organization — and a run that stopped before its own
#: cleanup would otherwise make every later test refuse for the right reason at
#: the wrong time.
CLAIMED_CHANNELS = ("555000111222333", "555000999888777")


async def _forget(session) -> None:
    """Remove every trace of the suite's Organization, including its runs.

    Delegated to the shared helper: the scoped tables reference the Organization
    with RESTRICT on purpose, so a plain ``DELETE FROM organizations`` fails the
    moment the suite has written one audit row.
    """
    await commercial.forget_organization(session, SLUG)
    await session.execute(
        text(
            "DELETE FROM organization_channel_bindings "
            "WHERE kind = :kind AND external_id = ANY(:ids)"
        ).bindparams(
            kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER.value,
            ids=list(CLAIMED_CHANNELS),
        )
    )
    await session.commit()


def _command(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _plan(**overrides) -> ProvisionOrganization:
    fields = {
        "slug": SLUG,
        "display_name": "Operaciones Test",
        "configuration": CONFIGURATION,
        "administrators": (ADMIN,),
        "advisors": (ADVISOR,),
        "default_advisor": ADVISOR,
        "channels": (
            ChannelAssignment(
                kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
                external_id="555000111222333",
            ),
        ),
        "credentials": (
            CredentialAssignment(
                provider=IntegrationProvider.META_WHATSAPP,
                reference="OPERACIONES_META_TOKEN",
            ),
        ),
        "add_ons": (),
        "reason": REASON,
        "command_key": _command("provision"),
    }
    fields.update(overrides)
    return ProvisionOrganization(**fields)


async def _provisioned(database, resolver: SecretResolver | None = None):
    used = resolver or SecretResolver({"OPERACIONES_META_TOKEN": "token-x"})
    async with database.session_scope() as session:
        result = await OrganizationProvisioning(session, resolver=used).provision(
            OPERATOR, _plan()
        )
    assert result.operable, result.failure
    return result, used


# ---------------------------------------------------------------------------
# Authority and reasons.
# ---------------------------------------------------------------------------


def test_a_platform_mutation_requires_a_reason_somebody_can_act_on() -> None:
    """An empty reason is refused. See the next test for a too-short one."""
    with pytest.raises(ReasonRequired):
        require_reason("")


def test_a_short_reason_is_refused_and_whitespace_is_normalised() -> None:
    """A formality in an audit trail is worse than an empty field.

    It looks like evidence, which is the problem: "arreglo" cannot be acted on
    three months later, and its presence stops anybody asking.
    """
    with pytest.raises(ReasonRequired):
        require_reason("arreglo")
    assert require_reason("  Alta   acompañada de Acme.  ") == (
        "Alta acompañada de Acme."
    )


def test_a_platform_operator_writes_history_as_the_platform() -> None:
    assert OPERATOR.actor_type == "Platform"


# ---------------------------------------------------------------------------
# Provisioning.
# ---------------------------------------------------------------------------


def test_a_slug_is_refused_rather_than_silently_rewritten() -> None:
    """The operator has to see the value they entered."""
    assert normalise_slug("  Acme-MX ") == "acme-mx"
    for bad in ("a", "acme_mx", "-acme", "acme-", "Ácme"):
        with pytest.raises(ProvisioningRefused):
            normalise_slug(bad)


async def test_provisioning_runs_every_step_and_activates_last(database) -> None:
    result, _resolver = await _provisioned(database)
    assert [step.name for step in result.steps][-1] == STEP_ACTIVATION
    assert all(step.completed for step in result.steps)
    async with database.session_scope() as session:
        organization = await session.get(Organization, result.organization_id)
        assert organization is not None
        assert organization.status == OrganizationStatus.ACTIVE.value
        # The team, the entitlements and the binding all landed.
        members = await OrganizationDirectory(session).members(organization.id)
        assert {member.login for member in members} == {ADMIN, ADVISOR}
        assert any(member.is_default_advisor for member in members)


async def test_re_running_the_same_command_key_changes_nothing(database) -> None:
    """Idempotent by construction: the second run skips every step."""
    result, resolver = await _provisioned(database)
    async with database.session_scope() as session:
        again = await OrganizationProvisioning(session, resolver=resolver).provision(
            OPERATOR,
            _plan(command_key=await _command_key_of(session, result.run_id)),
        )
    assert again.run_id == result.run_id
    assert again.operable
    async with database.session_scope() as session:
        versions = await session.scalar(
            text(
                "SELECT count(*) FROM organization_configuration_versions "
                "WHERE organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        assert versions == 1


async def _command_key_of(session, run_id: uuid.UUID) -> str:
    found = await session.scalar(
        text(
            "SELECT command_key FROM organization_provisioning_runs WHERE id = :id"
        ).bindparams(id=run_id)
    )
    assert found is not None
    return found


async def test_a_failed_step_leaves_a_resumable_inoperable_organization(
    database,
) -> None:
    """The failure this module exists for.

    A channel identifier another Organization already holds fails step five. The
    Organization exists, is *not* Active, and the run resumes once the conflict
    is removed — rather than leaving a row that looks ready and cannot receive a
    message.
    """
    contested = "555000999888777"
    resolver = SecretResolver({"OPERACIONES_META_TOKEN": "token-x"})
    async with database.session_scope() as session:
        # Larevia claims the identifier first.
        from realestate.domain.platform.routing import OrganizationRouting

        first = await commercial.organization_id(session)
        await OrganizationRouting(session).bind(
            organization_id=first,
            kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
            external_id=contested,
            recorded_by="test",
        )
        await session.commit()

    key = _command("provision-conflict")
    contested_plan = _plan(
        command_key=key,
        channels=(
            ChannelAssignment(
                kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
                external_id=contested,
            ),
        ),
    )
    async with database.session_scope() as session:
        failed = await OrganizationProvisioning(session, resolver=resolver).provision(
            OPERATOR, contested_plan
        )
    assert not failed.operable
    assert failed.state is ProvisioningState.FAILED
    assert failed.step(STEP_CHANNELS) is not None
    assert not failed.step(STEP_CHANNELS).completed
    assert failed.step(STEP_TEAM).completed
    async with database.session_scope() as session:
        organization = await session.get(Organization, failed.organization_id)
        assert organization is not None
        assert organization.status == OrganizationStatus.PROVISIONING.value
        # And the half-built Organization cannot be logged into.
        from realestate.domain.commercial.organization import OrganizationSuspended

        with pytest.raises(OrganizationSuspended):
            await OrganizationDirectory(session).resolve_actor(ADMIN)

    # Remove the conflict and resume with the same key.
    async with database.session_scope() as session:
        from realestate.domain.platform.routing import OrganizationRouting

        first = await commercial.organization_id(session)
        await OrganizationRouting(session).retire(
            organization_id=first,
            kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
            external_id=contested,
        )
        await session.commit()
    async with database.session_scope() as session:
        resumed = await OrganizationProvisioning(
            session, resolver=resolver
        ).provision(OPERATOR, contested_plan)
    assert resumed.operable
    assert resumed.run_id == failed.run_id


async def test_a_login_another_organization_holds_is_refused_by_name(
    database,
) -> None:
    """Left to the unique index this is a constraint violation with no remedy."""
    resolver = SecretResolver({"OPERACIONES_META_TOKEN": "token-x"})
    async with database.session_scope() as session:
        # The founding Organization has to actually hold the login for the
        # collision to exist. ``provision_bookable_team`` rather than the plain
        # default plan: the default plan omits the ``developer`` login that the
        # rest of the session's suites authenticate with, and reconciliation
        # deactivates a configuration-provisioned login it does not name.
        await commercial.provision_bookable_team(session)
    async with database.session_scope() as session:
        result = await OrganizationProvisioning(session, resolver=resolver).provision(
            OPERATOR, _plan(administrators=(commercial.ADMIN_LOGIN,))
        )
    assert not result.operable
    failure = result.step(STEP_TEAM)
    assert failure is not None
    assert commercial.ADMIN_LOGIN in failure.detail["error"]


async def test_rollback_undoes_capability_but_keeps_history(database) -> None:
    """Configuration and entitlements survive: they are the evidence."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        rolled = await OrganizationProvisioning(session).rollback(
            OPERATOR, run_id=result.run_id, reason=REASON
        )
    assert rolled.state is ProvisioningState.ROLLED_BACK
    async with database.session_scope() as session:
        active_members = await session.scalar(
            select(func.count(OrganizationMember.id))
            .where(OrganizationMember.organization_id == result.organization_id)
            .where(OrganizationMember.active.is_(True))
        )
        assert active_members == 0
        references = await session.execute(
            text(
                "SELECT state FROM organization_secret_references "
                "WHERE organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        assert {row[0] for row in references} == {SecretReferenceState.REVOKED.value}
        versions = await session.scalar(
            text(
                "SELECT count(*) FROM organization_configuration_versions "
                "WHERE organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        assert versions == 1


async def test_deprovisioning_stops_service_and_says_the_data_is_retained(
    database,
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        outcome = await OrganizationProvisioning(session).deprovision(
            OPERATOR,
            DeprovisionOrganization(
                organization_id=result.organization_id,
                reason=REASON,
                command_key=_command("deprovision"),
            ),
        )
    assert outcome.state is ProvisioningState.COMPLETED
    async with database.session_scope() as session:
        organization = await session.get(Organization, result.organization_id)
        assert organization is not None
        assert organization.status == OrganizationStatus.DEPROVISIONED.value
        assert organization.deprovisioned_at is not None
        audits = await session.execute(
            text(
                "SELECT details FROM audit_events WHERE organization_id = :org "
                "AND action = 'DeprovisionOrganization'"
            ).bindparams(org=result.organization_id)
        )
        rows = audits.all()
        assert rows and rows[0][0]["data_retained"] is True


async def test_provisioning_refuses_to_rewrite_a_live_organization(database) -> None:
    """A months-old plan must not overwrite a brokerage that is operating."""
    result, resolver = await _provisioned(database)
    assert result.operable
    async with database.session_scope() as session:
        blocked = await OrganizationProvisioning(
            session, resolver=resolver
        ).provision(OPERATOR, _plan(command_key=_command("provision-again")))
    assert not blocked.operable
    assert "ya está operando" in (blocked.failure or "")


# ---------------------------------------------------------------------------
# Configuration.
# ---------------------------------------------------------------------------


async def test_recording_the_same_document_records_no_new_version(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        configuration = OrganizationConfiguration(session)
        first = await configuration.current(result.organization_id)
        same = await configuration.record(
            OPERATOR,
            RecordConfiguration(
                organization_id=result.organization_id,
                # Reordered keys, same document. Compared on the canonical
                # checksum, so this is recognised as unchanged.
                document=dict(reversed(list(CONFIGURATION.items()))),
                reason=REASON,
                command_key=_command("configuration"),
            ),
        )
        await session.commit()
        assert same.version == first.version
        assert same.checksum == checksum_of(CONFIGURATION)


async def test_a_new_document_supersedes_the_current_one(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        configuration = OrganizationConfiguration(session)
        second = await configuration.record(
            OPERATOR,
            RecordConfiguration(
                organization_id=result.organization_id,
                document={**CONFIGURATION, "limits": {"campaign_recipients": 25}},
                reason="Acme pidió bajar el tope de destinatarios por campaña.",
                command_key=_command("configuration"),
            ),
        )
        await session.commit()
        assert second.version == 2
        history = await configuration.history(result.organization_id)
        assert [item.version for item in history.versions] == [2, 1]
        assert history.current is not None
        assert history.current.version == 2


async def test_an_unknown_section_is_refused_with_the_valid_ones_named(
    database,
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        with pytest.raises(InvalidConfiguration) as refusal:
            await OrganizationConfiguration(session).record(
                OPERATOR,
                RecordConfiguration(
                    organization_id=result.organization_id,
                    document={"whatever": {"x": 1}},
                    reason=REASON,
                    command_key=_command("configuration"),
                ),
            )
    assert "secciones válidas" in refusal.value.message


async def test_an_organization_with_no_configuration_is_refused_not_defaulted(
    database,
) -> None:
    async with database.session_scope() as session:
        with pytest.raises(ConfigurationMissing):
            await OrganizationConfiguration(session).current(uuid.uuid4())


async def test_only_the_bootstrap_organization_may_read_the_process_environment(
    database,
) -> None:
    """The asymmetry, asserted rather than described."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        first = await commercial.organization_id(session)
        configuration = OrganizationConfiguration(
            session, bootstrap_organization_id=first
        )
        assert configuration.uses_process_environment(first) is True
        assert configuration.uses_process_environment(result.organization_id) is False
        # And an installation with no founding Organization gives nobody the
        # environment.
        assert (
            OrganizationConfiguration(session).uses_process_environment(first) is False
        )


# ---------------------------------------------------------------------------
# Credentials.
# ---------------------------------------------------------------------------


def test_a_reference_is_a_name_and_material_is_refused() -> None:
    assert validate_reference(" ACME_META_TOKEN ") == "ACME_META_TOKEN"
    assert validate_reference("secrets/acme/meta:latest") == "secrets/acme/meta:latest"
    for material in (
        "-----BEGIN PRIVATE KEY-----",
        json.dumps({"type": "service_account"}),
        "EAAG token with spaces",
        "x",
    ):
        with pytest.raises(InvalidReference):
            validate_reference(material)


async def test_a_rotation_keeps_both_rows_and_proves_the_value_changed(
    database,
) -> None:
    result, resolver = await _provisioned(database)
    resolver.record("OPERACIONES_META_TOKEN_2", "token-y")
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        before = await credentials.resolve(
            result.organization_id, IntegrationProvider.META_WHATSAPP
        )
        await credentials.record(
            OPERATOR,
            RecordSecretReference(
                organization_id=result.organization_id,
                provider=IntegrationProvider.META_WHATSAPP,
                reference="OPERACIONES_META_TOKEN_2",
                command_key=_command("rotate"),
                reason="Rotación programada del token de Meta.",
            ),
        )
        await session.commit()
        after = await credentials.resolve(
            result.organization_id, IntegrationProvider.META_WHATSAPP
        )
    assert before.material == "token-x"
    assert after.material == "token-y"
    assert before.fingerprint != after.fingerprint
    async with database.session_scope() as session:
        rows = await session.execute(
            text(
                "SELECT reference, state FROM organization_secret_references "
                "WHERE organization_id = :org ORDER BY reference"
            ).bindparams(org=result.organization_id)
        )
        assert dict(rows.all()) == {
            "OPERACIONES_META_TOKEN": SecretReferenceState.ROTATING.value,
            "OPERACIONES_META_TOKEN_2": SecretReferenceState.ACTIVE.value,
        }


async def test_a_rotating_reference_answers_when_the_active_one_is_gone(
    database,
) -> None:
    """A half-applied rotation must not take the integration down."""
    result, resolver = await _provisioned(database)
    resolver.record("OPERACIONES_META_TOKEN_2", "")
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        await credentials.record(
            OPERATOR,
            RecordSecretReference(
                organization_id=result.organization_id,
                provider=IntegrationProvider.META_WHATSAPP,
                reference="OPERACIONES_META_TOKEN_2",
                command_key=_command("rotate"),
                reason="Rotación con el secreto nuevo aún sin escribir.",
            ),
        )
        await session.commit()
        resolved = await credentials.resolve(
            result.organization_id, IntegrationProvider.META_WHATSAPP
        )
    assert resolved.material == "token-x"
    assert resolved.origin.endswith(SecretReferenceState.ROTATING.value)


async def test_a_reference_that_resolves_to_nothing_is_its_own_refusal(
    database,
) -> None:
    """Distinct from "nobody configured it": different fix, different message."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        empty = IntegrationCredentials(session, SecretResolver())
        with pytest.raises(UnresolvableCredential):
            await empty.resolve(
                result.organization_id, IntegrationProvider.META_WHATSAPP
            )


async def test_an_administrator_reads_references_but_cannot_change_them(
    database,
) -> None:
    result, resolver = await _provisioned(database)
    async with database.session_scope() as session:
        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)
        inventory = await IntegrationCredentials(session, resolver).inventory(actor)
        assert [row.reference for row in inventory] == ["OPERACIONES_META_TOKEN"]
        advisor = await OrganizationDirectory(session).resolve_actor(ADVISOR)
        with pytest.raises(NotAuthorized):
            await IntegrationCredentials(session, resolver).inventory(advisor)


# ---------------------------------------------------------------------------
# Entitlements.
# ---------------------------------------------------------------------------


def test_the_tier_is_the_smallest_one_that_covers_the_advisors() -> None:
    assert tier_for(1).name == TIERS[0].name
    assert tier_for(TIERS[0].advisor_seats).name == TIERS[0].name
    assert tier_for(TIERS[0].advisor_seats + 1).name == TIERS[1].name
    # Past the largest tier the operation has already grown; refusing to name
    # its tier would not undo that.
    assert tier_for(10_000).name == TIERS[-1].name


async def test_provisioning_records_the_whole_package_explicitly(database) -> None:
    """Including the add-ons nobody bought, as ``Disabled``.

    "We did not sell this" and "nobody has decided" have to stay different
    answers.
    """
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        entitlements = Entitlements(session)
        for capability in BASE_PACKAGE:
            decision = await entitlements.evaluate(
                result.organization_id, capability
            )
            assert decision.permitted, capability
            assert decision.source is EntitlementSource.PACKAGE
        for capability in ADD_ONS:
            decision = await entitlements.evaluate(
                result.organization_id, capability
            )
            assert not decision.permitted
            assert decision.reason == "Disabled"


async def test_an_unrecorded_capability_is_refused_rather_than_permitted(
    database,
) -> None:
    async with database.session_scope() as session:
        decision = await Entitlements(session).evaluate(
            uuid.uuid4(), Capability.SPONSORED_PLACEMENT
        )
        assert not decision.permitted
        assert decision.reason == "NotRecorded"


async def test_an_entitlement_change_during_operation_keeps_both_answers(
    database,
) -> None:
    """The reason history is append-only.

    A campaign refused at 14:00 and permitted at 14:05 has to be explainable at
    both times, which an edited row cannot do.
    """
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        entitlements = Entitlements(session)
        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)
        with pytest.raises(NotEntitled):
            await entitlements.require(actor, Capability.SPONSORED_PLACEMENT)

        await entitlements.grant(
            OPERATOR,
            GrantEntitlement(
                organization_id=result.organization_id,
                capability=Capability.SPONSORED_PLACEMENT,
                state=EntitlementState.ENABLED,
                reason="Acme compró el complemento de posiciones patrocinadas.",
            ),
        )
        await session.commit()
        permitted = await entitlements.require(
            actor, Capability.SPONSORED_PLACEMENT
        )
        assert permitted.permitted

        history = await entitlements.history(
            result.organization_id, Capability.SPONSORED_PLACEMENT
        )
        assert len(history) == 2
        assert [row.state for row in history] == [
            EntitlementState.ENABLED.value,
            EntitlementState.DISABLED.value,
        ]
        assert history[1].superseded_at is not None


async def test_a_seat_ceiling_refuses_with_the_numbers_in_the_sentence(
    database,
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        entitlements = Entitlements(session)
        await entitlements.grant(
            OPERATOR,
            GrantEntitlement(
                organization_id=result.organization_id,
                capability=Capability.ADVISOR_SEATS,
                state=EntitlementState.ENABLED,
                limit_value=1,
                reason="Nivel fundadora reducido a un asesor para la prueba.",
                source=EntitlementSource.TIER,
            ),
        )
        await session.commit()
        decision = await entitlements.evaluate(
            result.organization_id, Capability.ADVISOR_SEATS
        )
        assert decision.limit == 1
        assert decision.used == 1
        assert decision.remaining == 0
        assert not decision.permitted
        assert "1 de 1" in decision.detail


async def test_a_limit_on_an_unbounded_capability_is_refused(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        with pytest.raises(NotEntitled):
            await Entitlements(session).grant(
                OPERATOR,
                GrantEntitlement(
                    organization_id=result.organization_id,
                    capability=Capability.PUBLIC_SITE,
                    state=EntitlementState.ENABLED,
                    limit_value=3,
                    reason="Intento de poner un tope donde no aplica.",
                ),
            )


async def test_the_summary_lists_what_the_organization_does_not_have(
    database,
) -> None:
    """A report that only lists grants cannot answer "what do we have"."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        summary = await Entitlements(session).summary(result.organization_id)
        assert len(summary) == len(list(Capability))
        assert any(not item.permitted for item in summary)


# ---------------------------------------------------------------------------
# Support access.
# ---------------------------------------------------------------------------


def test_a_support_login_names_the_organization_and_the_engineer() -> None:
    """Both halves matter.

    The prefix is legibility: an Administrator has to see at a glance that this
    row is Maia's, not somebody they hired. The Organization is *necessity*: the
    member login namespace is platform-wide, so without it one engineer could
    hold a grant in only one Organization at a time.
    """
    assert support_login_for("Gerardo", "Acme") == "soporte:acme:gerardo"
    assert support_login_for("soporte:acme:gerardo", "acme") == "soporte:acme:gerardo"
    with pytest.raises(SupportAccessRefused):
        support_login_for("   ", "acme")
    with pytest.raises(SupportAccessRefused):
        support_login_for("gerardo", " ")


async def test_a_grant_creates_a_read_only_unassignable_member(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        grant = await SupportAccess(session).grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Acme reporta que una cita no aparece en la agenda.",
                command_key=_command("support"),
                hours=2,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        actor = await OrganizationDirectory(session).resolve_actor(
            grant.subject_login
        )
        assert actor.organization_id == result.organization_id
        assert not actor.is_administrator
        member = await session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == result.organization_id)
            .where(OrganizationMember.login == grant.subject_login)
        )
        assert member is not None
        # Unassignable, or the deterministic assignment rule could route a real
        # Opportunity to Maia's support desk.
        assert member.advises is False


async def test_a_grant_longer_than_a_working_day_is_refused(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        with pytest.raises(SupportAccessRefused):
            await SupportAccess(session).grant(
                OPERATOR,
                GrantSupportAccess(
                    organization_id=result.organization_id,
                    engineer_login="gerardo",
                    reason="Investigación larga que debería pedirse dos veces.",
                    command_key=_command("support"),
                    hours=MAX_GRANT_HOURS + 1,
                ),
            )


async def test_an_expired_grant_is_refused_at_login_not_by_the_sweep(
    database,
) -> None:
    """Access ends on the clock. The worker is a safety net, not the mechanism."""
    result, _resolver = await _provisioned(database)
    # Granted three hours ago for one hour, so it lapsed two hours ago. Written
    # this way rather than by editing ``expires_at`` afterwards, because the
    # table's own check constraint refuses an expiry before its grant — which is
    # itself worth not working around.
    granted_at = datetime.now(tz=UTC) - timedelta(hours=3)
    async with database.session_scope() as session:
        grant = await SupportAccess(session).grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Diagnóstico de una cita que no aparece en la agenda.",
                command_key=_command("support"),
                hours=1,
            ),
            at=granted_at,
        )
        await session.commit()
    assert grant.expires_at < datetime.now(tz=UTC)
    async with database.session_scope() as session:
        with pytest.raises(SupportAccessExpired):
            await OrganizationDirectory(session).resolve_actor(grant.subject_login)


async def test_the_sweep_deactivates_a_lapsed_grants_member_row(database) -> None:
    """What the customer's own Administrator sees on their team surface."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        grant = await SupportAccess(session).grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Diagnóstico del canal de WhatsApp de Acme.",
                command_key=_command("support"),
                hours=1,
            ),
        )
        await session.commit()
    later = datetime.now(tz=UTC) + timedelta(hours=2)
    async with database.session_scope() as session:
        expired = await SupportAccess(session).expire_due(at=later)
        await session.commit()
        assert expired >= 1
    async with database.session_scope() as session:
        member = await session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == result.organization_id)
            .where(OrganizationMember.login == grant.subject_login)
        )
        assert member is not None
        assert member.active is False
        audits = await session.execute(
            text(
                "SELECT details FROM audit_events WHERE action = 'ExpireSupportAccess' "
                "AND organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        rows = audits.all()
        # A grant that expired unused is evidence the process is working.
        assert rows and rows[0][0]["unused"] is True


async def test_use_is_counted_so_the_access_can_be_reviewed(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        grant = await SupportAccess(session).grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Revisión de la bandeja tras un reporte de Acme.",
                command_key=_command("support"),
                hours=2,
            ),
        )
        await session.commit()
    async with database.session_scope() as session:
        for _ in range(3):
            await OrganizationDirectory(session).resolve_actor(grant.subject_login)
        await session.commit()
    async with database.session_scope() as session:
        grants = await SupportAccess(session).grants(result.organization_id)
        assert grants[0].use_count == 3
        assert grants[0].last_used_at is not None


async def test_a_second_live_grant_for_the_same_person_is_refused(database) -> None:
    """"When does this access end" must have one answer."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        support = SupportAccess(session)
        await support.grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Primera investigación sobre el canal de Acme.",
                command_key=_command("support"),
            ),
        )
        await session.commit()
        with pytest.raises(SupportAccessRefused):
            await support.grant(
                OPERATOR,
                GrantSupportAccess(
                    organization_id=result.organization_id,
                    engineer_login="gerardo",
                    reason="Segunda investigación mientras la primera sigue viva.",
                    command_key=_command("support"),
                ),
            )


# ---------------------------------------------------------------------------
# Import.
# ---------------------------------------------------------------------------


def _records(count: int = 3) -> tuple[IncomingProperty, ...]:
    return tuple(
        IncomingProperty(
            source_reference=f"XLS-{index}",
            property_key=f"casa-importada-{index}",
            name=f"Casa Importada {index}",
            property_type="House",
            facts={"bedrooms": 3},
        )
        for index in range(1, count + 1)
    )


def _import_plan(organization_id: uuid.UUID, records, **overrides) -> ImportPlan:
    fields = {
        "organization_id": organization_id,
        "source": "Inventario-Acme-2026-03.xlsx",
        "records": records,
        "reason": "Migración inicial del inventario de la organización.",
        "command_key": _command("import"),
    }
    fields.update(overrides)
    return ImportPlan(**fields)


async def test_an_apply_without_a_dry_run_of_the_same_source_is_refused(
    database,
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        with pytest.raises(ImportRefused):
            await OrganizationImport(session).apply(
                OPERATOR, _import_plan(result.organization_id, _records())
            )


async def test_a_dry_run_creates_nothing_and_the_apply_agrees_with_it(
    database,
) -> None:
    """The comparison the two-phase shape exists for."""
    result, _resolver = await _provisioned(database)
    records = _records()
    async with database.session_scope() as session:
        planned = await OrganizationImport(session).plan(
            OPERATOR, _import_plan(result.organization_id, records)
        )
    assert planned.state is ImportState.PLANNED
    assert planned.accepted == 3
    async with database.session_scope() as session:
        created = await session.scalar(
            select(func.count(Property.id)).where(
                Property.organization_id == result.organization_id
            )
        )
        assert created == 0

    async with database.session_scope() as session:
        applied = await OrganizationImport(session).apply(
            OPERATOR, _import_plan(result.organization_id, records)
        )
    assert applied.state is ImportState.APPLIED
    assert applied.matches(planned)
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(Property).where(
                    Property.organization_id == result.organization_id
                )
            )
        )
        assert len(rows) == 3
        # Nothing publishable: facts are Pending review, which is the existing
        # catalog rule rather than a special case for imports.
        assert {row.facts_review_state for row in rows} == {"Pending"}
        assert all(row.provenance["origin"] == "OrganizationImport" for row in rows)


async def test_every_record_gets_a_finding_with_its_source_reference(
    database,
) -> None:
    """A summary of counts cannot answer "which ones were rejected"."""
    result, _resolver = await _provisioned(database)
    records = (
        *_records(2),
        # A duplicate of the first, inside the same file: the common case.
        IncomingProperty(
            source_reference="XLS-dup",
            property_key="casa-importada-1",
            name="Casa Importada 1",
            property_type="House",
        ),
        IncomingProperty(
            source_reference="XLS-bad-type",
            property_key="casa-importada-9",
            name="Casa Rara",
            property_type="Castle",
        ),
        IncomingProperty(
            source_reference="",
            property_key="casa-importada-10",
            name="Sin origen",
            property_type="House",
        ),
    )
    async with database.session_scope() as session:
        report = await OrganizationImport(session).plan(
            OPERATOR, _import_plan(result.organization_id, records)
        )
    assert report.count(ImportFindingKind.ACCEPTED) == 2
    assert report.count(ImportFindingKind.DUPLICATE) == 1
    assert report.count(ImportFindingKind.INVALID) == 2
    references = {item.source_reference for item in report.findings}
    assert "XLS-dup" in references and "XLS-bad-type" in references


async def test_rollback_removes_exactly_what_the_apply_created(database) -> None:
    result, _resolver = await _provisioned(database)
    records = _records(2)
    async with database.session_scope() as session:
        await OrganizationImport(session).plan(
            OPERATOR, _import_plan(result.organization_id, records)
        )
    async with database.session_scope() as session:
        applied = await OrganizationImport(session).apply(
            OPERATOR, _import_plan(result.organization_id, records)
        )
    async with database.session_scope() as session:
        rolled = await OrganizationImport(session).roll_back(
            OPERATOR,
            run_id=applied.run_id,
            reason="La inmobiliaria pidió revertir la carga inicial.",
        )
    assert rolled.state is ImportState.ROLLED_BACK
    async with database.session_scope() as session:
        remaining = await session.scalar(
            select(func.count(Property.id)).where(
                Property.organization_id == result.organization_id
            )
        )
        assert remaining == 0


async def test_an_import_names_its_provenance_and_refuses_without_one(
    database,
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        with pytest.raises(ImportRefused):
            await OrganizationImport(session).plan(
                OPERATOR, _import_plan(result.organization_id, _records(), source="  ")
            )
    async with database.session_scope() as session:
        report = await OrganizationImport(session).plan(
            OPERATOR, _import_plan(result.organization_id, _records())
        )
        assert report.provenance["source"] == "Inventario-Acme-2026-03.xlsx"
        assert report.provenance["checksum"]


# ---------------------------------------------------------------------------
# Export, deletion and retention.
# ---------------------------------------------------------------------------


async def test_an_export_covers_every_scoped_table_and_names_what_it_withholds(
    database, tmp_path
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        exported = await OrganizationDataLifecycle(
            session, root=tmp_path / "exports"
        ).export(
            OPERATOR,
            ExportOrganizationData(
                organization_id=result.organization_id,
                reason="Entrega de información solicitada por la organización.",
                command_key=_command("export"),
            ),
        )
    from realestate.domain.platform.scoping import organization_scopes

    assert exported.tables == len(organization_scopes())
    assert exported.rows > 0
    document = json.loads((tmp_path / "exports").glob("*.json").__next__().read_text())
    assert document["organization"]["slug"] == SLUG
    # The dangerous columns are named, not silently dropped.
    assert "salt" in document["export"]["withheld_columns"]["pseudonym_salts"]
    assert (
        "fingerprint"
        in document["export"]["withheld_columns"]["organization_secret_references"]
    )
    payload = json.dumps(document)
    assert "token-x" not in payload


async def test_a_repeated_export_command_returns_the_first_artifact(
    database, tmp_path
) -> None:
    """A resubmitted request must not write a second copy of a customer base."""
    result, _resolver = await _provisioned(database)
    key = _command("export")
    async with database.session_scope() as session:
        lifecycle = OrganizationDataLifecycle(session, root=tmp_path / "exports")
        first = await lifecycle.export(
            OPERATOR,
            ExportOrganizationData(
                organization_id=result.organization_id,
                reason="Entrega de información solicitada por la organización.",
                command_key=key,
            ),
        )
    async with database.session_scope() as session:
        again = await OrganizationDataLifecycle(
            session, root=tmp_path / "exports"
        ).export(
            OPERATOR,
            ExportOrganizationData(
                organization_id=result.organization_id,
                reason="Entrega de información solicitada por la organización.",
                command_key=key,
            ),
        )
    assert again.export_id == first.export_id
    assert again.checksum == first.checksum
    assert len(list((tmp_path / "exports").glob("*.json"))) == 1


async def test_a_live_retention_hold_refuses_deletion_with_its_authority(
    database,
) -> None:
    """No partial compliance: a half-deleted Organization satisfies nobody."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        lifecycle = OrganizationDataLifecycle(session)
        await lifecycle.record_hold(
            OPERATOR,
            RecordRetentionHold(
                organization_id=result.organization_id,
                basis=RetentionBasis.LEGAL_OBLIGATION,
                authority="Requerimiento fiscal 2026/114",
                description="Conservar el registro comercial hasta la resolución.",
            ),
        )
    async with database.session_scope() as session:
        blocked = await OrganizationDataLifecycle(session).delete(
            OPERATOR,
            DeleteOrganizationData(
                organization_id=result.organization_id,
                scope=DeletionScope.EVERYTHING,
                reason="Solicitud de eliminación de la organización.",
                command_key=_command("delete"),
            ),
        )
    assert blocked.state is DataLifecycleState.BLOCKED
    assert "2026/114" in (blocked.blocked_reason or "")
    assert blocked.deleted == 0


async def test_releasing_the_hold_permits_the_deletion(database) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        hold = await OrganizationDataLifecycle(session).record_hold(
            OPERATOR,
            RecordRetentionHold(
                organization_id=result.organization_id,
                basis=RetentionBasis.CONTRACT,
                authority="Cláusula 9 del contrato",
                description="Conservar doce meses tras la terminación.",
            ),
        )
    async with database.session_scope() as session:
        await OrganizationDataLifecycle(session).release_hold(
            OPERATOR,
            hold_id=hold.id,
            reason="La obligación contractual concluyó el 3 de marzo.",
        )
    async with database.session_scope() as session:
        deleted = await OrganizationDataLifecycle(session).delete(
            OPERATOR,
            DeleteOrganizationData(
                organization_id=result.organization_id,
                scope=DeletionScope.EVERYTHING,
                reason="Solicitud de eliminación confirmada por escrito.",
                command_key=_command("delete"),
            ),
        )
    assert deleted.state is DataLifecycleState.COMPLETED
    async with database.session_scope() as session:
        # The Organization row and the evidence survive; an erasure nobody can
        # prove happened is not a service.
        organization = await session.get(Organization, result.organization_id)
        assert organization is not None
        audits = await session.scalar(
            text(
                "SELECT count(*) FROM audit_events WHERE organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        assert audits > 0
        members = await session.scalar(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.organization_id == result.organization_id
            )
        )
        assert members == 0


async def test_operational_content_deletion_keeps_the_commercial_record(
    database,
) -> None:
    """Two genuinely different requests, and only one touches the company."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        outcome = await OrganizationDataLifecycle(session).delete(
            OPERATOR,
            DeleteOrganizationData(
                organization_id=result.organization_id,
                scope=DeletionScope.OPERATIONAL_CONTENT,
                reason="La organización pidió borrar sus conversaciones.",
                command_key=_command("delete"),
            ),
        )
    assert outcome.state is DataLifecycleState.COMPLETED
    assert "organization_members" in outcome.retained_counts
    async with database.session_scope() as session:
        members = await session.scalar(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.organization_id == result.organization_id
            )
        )
        assert members == 2


# ---------------------------------------------------------------------------
# Usage.
# ---------------------------------------------------------------------------


async def test_usage_is_recomputed_so_a_repeated_pass_changes_nothing(
    database,
) -> None:
    """A counter a repeated pass increments is a counter nobody can trust."""
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        usage = PlatformUsage(session)
        first = await usage.refresh()
        await session.commit()
        second = await usage.refresh()
        await session.commit()
    assert first.cells == second.cells
    async with database.session_scope() as session:
        read = await PlatformUsage(session).read(result.organization_id)
        assert read.period_start == month_start(datetime.now(tz=UTC))
        advisors = read.of(UsageMetric.ACTIVE_ADVISORS)
        assert advisors is not None
        assert advisors.quantity == 1
        integrations = read.of(UsageMetric.ACTIVE_INTEGRATIONS)
        assert integrations is not None
        assert integrations.quantity == 1
        assert len(read.readings) == len(list(UsageMetric))


async def test_the_platform_worker_expires_grants_and_refreshes_usage(
    database,
) -> None:
    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        await SupportAccess(session).grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Acceso que la prueba deja expirar deliberadamente.",
                command_key=_command("support"),
                hours=1,
            ),
        )
        await session.commit()
    from realestate.worker.platform import PlatformWorker

    report = await PlatformWorker(database=database).run(
        now=datetime.now(tz=UTC) + timedelta(hours=3)
    )
    assert report.grants_expired >= 1
    assert report.usage_cells >= len(list(UsageMetric))
    assert report.changed


async def test_a_product_actor_cannot_be_used_as_a_platform_operator() -> None:
    """The two authorities are different types, not two values of one flag."""
    actor = Actor.product(uuid.uuid4(), "Anything")
    assert not isinstance(actor, PlatformOperator)
    assert actor.actor_type == "Product"


# ---------------------------------------------------------------------------
# Enforcement: the entitlements are a control, not a report.
# ---------------------------------------------------------------------------


async def test_a_disabled_add_on_refuses_the_work_it_names(database) -> None:
    """The check the whole entitlement model is for.

    Without this the rows are a report: an Organization could be recorded as not
    having bought collaborator inventory, reactivation, Development campaigns or
    paid placement and use all four anyway. Each capability is asserted at the
    seam that performs the work, not at a surface that could be bypassed.
    """
    from realestate.domain.engagement.campaigns import Campaigns, PlanCampaign
    from realestate.domain.engagement.reactivation import Reactivation
    from realestate.domain.external_inventory.inventory import ExternalInventory
    from realestate.domain.sponsorship.quoting import (
        QuoteCommand,
        SponsorshipQuoting,
    )
    from tests.fixtures.external_inventory import FakeInventorySource

    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)

        with pytest.raises(NotEntitled) as inventory:
            await ExternalInventory(
                session, actor, FakeInventorySource()
            ).synchronize(at=datetime.now(tz=UTC))
        assert inventory.value.capability is Capability.EXTERNAL_INVENTORY

        with pytest.raises(NotEntitled) as reactivation:
            await Reactivation(session, actor).discover(uuid.uuid4())
        assert reactivation.value.capability is Capability.REACTIVATION_CAMPAIGNS

        with pytest.raises(NotEntitled) as campaigns:
            await Campaigns(session, actor).plan(
                PlanCampaign(
                    development_id=uuid.uuid4(),
                    name="Campaña que nunca llega a validarse",
                    property_need_ids=(),
                    template_name="cualquiera",
                    template_language="es_MX",
                    content_preview="Texto de vista previa.",
                )
            )
        assert campaigns.value.capability is Capability.DEVELOPMENT_CAMPAIGNS

        with pytest.raises(NotEntitled) as sponsorship:
            await SponsorshipQuoting(session, actor).quote(
                QuoteCommand(
                    campaign_id=uuid.uuid4(),
                    command_key=_command("quote"),
                    duration_days=30,
                ),
                at=datetime.now(tz=UTC),
            )
        assert sponsorship.value.capability is Capability.SPONSORED_PLACEMENT


async def test_an_enabled_add_on_stops_refusing_immediately(database) -> None:
    """The change lands mid-operation, which is the case ADR-0053 is about."""
    from realestate.domain.engagement.reactivation import Reactivation

    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)
        with pytest.raises(NotEntitled):
            await Reactivation(session, actor).discover(uuid.uuid4())

        await Entitlements(session).grant(
            OPERATOR,
            GrantEntitlement(
                organization_id=result.organization_id,
                capability=Capability.REACTIVATION_CAMPAIGNS,
                state=EntitlementState.ENABLED,
                reason="El cliente compró el complemento de reactivación.",
            ),
        )
        await session.commit()

        # Now the entitlement passes and the refusal comes from the *work* — the
        # Listing does not exist — which is what proves the gate moved rather
        # than the call having stopped happening.
        with pytest.raises(CommercialError) as refusal:
            await Reactivation(session, actor).discover(uuid.uuid4())
        assert not isinstance(refusal.value, NotEntitled)


async def test_the_seat_ceiling_refuses_the_advisor_past_the_tier(database) -> None:
    """Told to upgrade, rather than the eleventh Advisor landing unnoticed."""
    from realestate.db.models import MemberRole
    from realestate.domain.commercial.team import AddMember, TeamAdministration

    result, _resolver = await _provisioned(database)
    async with database.session_scope() as session:
        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)
        await Entitlements(session).grant(
            OPERATOR,
            GrantEntitlement(
                organization_id=result.organization_id,
                capability=Capability.ADVISOR_SEATS,
                state=EntitlementState.ENABLED,
                limit_value=1,
                reason="Nivel reducido a un asesor para la prueba del tope.",
                source=EntitlementSource.TIER,
            ),
        )
        await session.commit()
        with pytest.raises(NotEntitled) as refusal:
            await TeamAdministration(session).record(
                actor,
                AddMember(
                    login="segundo@operaciones.test",
                    display_name="Segundo asesor",
                    role=MemberRole.ADVISOR,
                    advises=True,
                    command_key=_command("add-member"),
                ),
            )
        assert refusal.value.capability is Capability.ADVISOR_SEATS
        assert "1 de 1" in refusal.value.message

        # An Administrator who does not advise is unaffected: the ceiling is
        # about Advisors, not headcount.
        await session.rollback()
        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)
        recorded = await TeamAdministration(session).record(
            actor,
            AddMember(
                login="segundo-admin@operaciones.test",
                display_name="Segunda administradora",
                role=MemberRole.ADMINISTRATOR,
                advises=False,
                command_key=_command("add-admin"),
            ),
        )
        assert recorded.changed

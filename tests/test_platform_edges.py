"""The platform's refusals, its bootstrap, and the paths nobody wants to reach.

The happy paths are covered by ``test_platform_operations.py`` and the boundary by
``test_platform_isolation.py``. This file is about the branches that only run when
something is wrong — a table nobody classified, a reference that resolves to
nothing, a rollback blocked by a record somebody else already made, an export that
cannot be written — because those are precisely the branches nobody exercises by
hand and the ones an operator meets during an incident.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from realestate.db.engine import Database
from realestate.db.models import (
    LAREVIA_SLUG,
    Appointment,
    AppointmentStatus,
    ChannelBindingKind,
    DataLifecycleState,
    DeletionScope,
    IntegrationProvider,
    Organization,
    OrganizationMember,
    OrganizationStatus,
    Property,
    ProvisioningState,
    RetentionBasis,
    SecretReferenceState,
)
from realestate.domain.commercial.actors import NotFound
from realestate.domain.platform.authority import PlatformOperator
from realestate.domain.platform.bootstrap import (
    BOOTSTRAP_OPERATOR,
    BootstrapEnvironment,
    PlatformBootstrap,
)
from realestate.domain.platform.configuration import (
    ConfigurationMissing,
    InvalidConfiguration,
    OrganizationConfiguration,
    RecordConfiguration,
    validate_document,
)
from realestate.domain.platform.credentials import (
    IntegrationCredentials,
    InvalidReference,
    MissingCredential,
    RecordSecretReference,
    SecretResolver,
    bootstrap_organization_id,
    fingerprint_of,
    validate_reference,
)
from realestate.domain.platform.entitlements import (
    CAPABILITY_LABELS,
    Entitlements,
    tier_for,
)
from realestate.domain.platform.imports import (
    ImportPlan,
    ImportRefused,
    IncomingProperty,
    MAX_RECORDS,
    OrganizationImport,
    checksum_of,
)
from realestate.domain.platform.lifecycle import (
    DeleteOrganizationData,
    DeletionBlocked,
    ExportFailed,
    ExportOrganizationData,
    OrganizationDataLifecycle,
    RecordRetentionHold,
)
from realestate.domain.platform.provisioning import (
    DeprovisionOrganization,
    OrganizationProvisioning,
    ProvisionOrganization,
    ProvisioningRefused,
    STEP_ORGANIZATION,
    _describe,
)
from realestate.domain.platform.registry import all_organizations
from realestate.domain.platform.routing import (
    OrganizationRouting,
    UnroutableChannel,
)
from realestate.domain.platform.scoping import (
    ScopeKind,
    TableScope,
    mismatched_scope_columns,
    qualified_name,
    scope_for,
)
from realestate.domain.platform.support import (
    GrantSupportAccess,
    SupportAccess,
)
from realestate.domain.platform.usage import PlatformUsage, month_start, next_month
from realestate.hosts import host_of
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = [pytest.mark.anyio, requires_postgres]

OPERATOR = PlatformOperator(label="edges-tester")
SLUG = "bordes-test"
ADMIN = "dir@bordes.test"
REASON = "Prueba de bordes de la plataforma en la suite automatizada."


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def database():
    db = Database(DATABASE_URL)
    async with db.session_scope() as session:
        await commercial.forget_organization(session, SLUG)
    yield db
    async with db.session_scope() as session:
        await commercial.forget_organization(session, SLUG)
    await db.dispose()


async def _organization(database, resolver: SecretResolver | None = None):
    used = resolver or SecretResolver({"BORDES_TOKEN": "token-b"})
    async with database.session_scope() as session:
        result = await OrganizationProvisioning(session, resolver=used).provision(
            OPERATOR,
            ProvisionOrganization(
                slug=SLUG,
                display_name="Bordes",
                configuration={"brand": {"working_name": "Bordes"}},
                administrators=(ADMIN,),
                credentials=(),
                reason=REASON,
                command_key=f"edges:{uuid.uuid4().hex}",
            ),
        )
    assert result.operable, result.failure
    return result, used


# ---------------------------------------------------------------------------
# Pure functions and small guards.
# ---------------------------------------------------------------------------


def test_a_host_is_read_the_same_way_by_both_processes() -> None:
    """One definition, because two would disagree behind a proxy."""
    assert host_of("https://larevia.mx:443/catalogo") == "larevia.mx"
    assert host_of("larevia.mx") == "larevia.mx"
    assert host_of("Larevia.MX, proxy.internal") == "larevia.mx"
    assert host_of("") == ""


def test_a_month_boundary_has_one_definition() -> None:
    naive = datetime(2026, 12, 17, 5, 30)
    assert month_start(naive) == datetime(2026, 12, 1, tzinfo=UTC)
    assert next_month(month_start(naive)) == datetime(2027, 1, 1, tzinfo=UTC)
    assert next_month(datetime(2026, 3, 1, tzinfo=UTC)) == datetime(
        2026, 4, 1, tzinfo=UTC
    )


def test_an_unclassified_table_raises_with_the_remedy_in_the_message() -> None:
    """The failure a new table produces has to say what to do about it."""
    with pytest.raises(KeyError) as refusal:
        scope_for("una_tabla_que_nadie_clasifico")
    assert "scoping.SCOPES" in str(refusal.value)
    with pytest.raises(KeyError):
        qualified_name("una_tabla_que_no_existe")


def test_a_classification_the_schema_does_not_back_is_reported() -> None:
    """The guard, exercised by breaking it deliberately.

    ``mismatched_scope_columns`` is normally empty, so its reporting branch is
    only reachable by giving it something wrong to find.
    """
    from realestate.domain.platform import scoping

    broken = (
        *scoping.SCOPES,
        TableScope(table="tabla_inexistente", kind=ScopeKind.ORGANIZATION),
        TableScope(table="measurement_definitions", kind=ScopeKind.ORGANIZATION),
    )
    original = scoping.SCOPES
    try:
        scoping.SCOPES = broken  # type: ignore[misc]
        problems = mismatched_scope_columns()
    finally:
        scoping.SCOPES = original  # type: ignore[misc]
    assert "tabla_inexistente (not a mapped table)" in problems
    assert "measurement_definitions (no organization_id column)" in problems


def test_a_reference_is_never_the_material() -> None:
    assert validate_reference("secrets/acme/meta") == "secrets/acme/meta"
    for rejected in ("", "ab", "a" * 200, "tiene espacios", "{json:1}", 'con"quote'):
        with pytest.raises(InvalidReference):
            validate_reference(rejected)


def test_a_fingerprint_changes_with_the_value_and_hides_it() -> None:
    first = fingerprint_of("token-a")
    second = fingerprint_of("token-b")
    assert first != second
    assert "token-a" not in first
    assert len(first) == 64


def test_a_configuration_document_must_be_a_non_empty_mapping() -> None:
    for rejected in ({}, [], "brand", None):
        with pytest.raises(InvalidConfiguration):
            validate_document(rejected)  # type: ignore[arg-type]
    # A list nested inside a section is walked too: the credential check is
    # recursive through both mappings and sequences.
    with pytest.raises(InvalidConfiguration):
        validate_document({"channels": [{"api_key": "abc"}]})


def test_every_capability_has_a_spanish_label() -> None:
    """A refusal an operator cannot read is a stack trace with extra steps."""
    from realestate.db.models import Capability

    for capability in Capability:
        assert CAPABILITY_LABELS[capability]
        assert CAPABILITY_LABELS[capability][0].isupper()


def test_a_step_failure_is_described_in_a_readable_line() -> None:
    assert _describe(ProvisioningRefused("No se puede.")) == "No se puede."
    assert _describe(ValueError("roto")) == "ValueError: roto"


def test_an_import_checksum_ignores_nothing_that_matters() -> None:
    one = IncomingProperty(
        source_reference="A", property_key="a", name="A", property_type="House"
    )
    other = IncomingProperty(
        source_reference="A", property_key="a", name="B", property_type="House"
    )
    assert checksum_of((one,)) != checksum_of((other,))
    assert checksum_of((one,)) == checksum_of((one,))


# ---------------------------------------------------------------------------
# Routing refusals.
# ---------------------------------------------------------------------------


async def test_an_empty_identifier_is_refused_rather_than_matched(database) -> None:
    async with database.session_scope() as session:
        routing = OrganizationRouting(session)
        with pytest.raises(UnroutableChannel):
            await routing.resolve(ChannelBindingKind.WHATSAPP_PHONE_NUMBER, "   ")
        with pytest.raises(UnroutableChannel):
            await routing.bind(
                organization_id=await commercial.organization_id(session),
                kind=ChannelBindingKind.TELEGRAM_BOT,
                external_id="  ",
                recorded_by="edges",
            )


async def test_retiring_a_binding_nobody_holds_reports_false(database) -> None:
    async with database.session_scope() as session:
        assert (
            await OrganizationRouting(session).retire(
                organization_id=await commercial.organization_id(session),
                kind=ChannelBindingKind.TELEGRAM_BOT,
                external_id="no-existe",
            )
            is False
        )


async def test_bindings_can_be_read_for_one_kind(database) -> None:
    async with database.session_scope() as session:
        organization_id = await commercial.organization_id(session)
        hosts = await OrganizationRouting(session).bindings(
            organization_id, ChannelBindingKind.PUBLIC_SITE_HOST
        )
        assert {row.external_id for row in hosts} >= set(commercial.TEST_SITE_HOSTS)
        every = await OrganizationRouting(session).bindings(organization_id)
        assert len(every) > len(hosts)


# ---------------------------------------------------------------------------
# Credentials: the paths that only run when something is missing.
# ---------------------------------------------------------------------------


async def test_try_resolve_answers_none_where_absence_is_an_answer(
    database,
) -> None:
    """Health and the operator panel say "not configured"; use paths refuse."""
    result, resolver = await _organization(database)
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        assert (
            await credentials.try_resolve(
                result.organization_id, IntegrationProvider.EASYBROKER
            )
            is None
        )
        with pytest.raises(MissingCredential):
            await credentials.resolve(
                result.organization_id, IntegrationProvider.EASYBROKER
            )


async def test_recording_the_same_reference_twice_is_a_no_op(database) -> None:
    result, resolver = await _organization(database)
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        command = RecordSecretReference(
            organization_id=result.organization_id,
            provider=IntegrationProvider.EASYBROKER,
            reference="BORDES_TOKEN",
            command_key=f"credential:{uuid.uuid4().hex}",
            reason="Registro inicial de la credencial de EasyBroker.",
        )
        first = await credentials.record(OPERATOR, command)
        second = await credentials.record(OPERATOR, command)
        await session.commit()
        assert first.id == second.id
        rows = await session.scalar(
            text(
                "SELECT count(*) FROM organization_secret_references "
                "WHERE organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        assert rows == 1


async def test_a_second_rotation_revokes_the_one_already_in_flight(
    database,
) -> None:
    """Three candidate credentials would be a credential chosen by row order."""
    result, resolver = await _organization(database)
    resolver.record("BORDES_TOKEN_2", "token-b2")
    resolver.record("BORDES_TOKEN_3", "token-b3")
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        for reference in ("BORDES_TOKEN", "BORDES_TOKEN_2", "BORDES_TOKEN_3"):
            await credentials.record(
                OPERATOR,
                RecordSecretReference(
                    organization_id=result.organization_id,
                    provider=IntegrationProvider.EASYBROKER,
                    reference=reference,
                    command_key=f"credential:{uuid.uuid4().hex}",
                    reason="Rotación sucesiva del acceso a EasyBroker.",
                ),
            )
        await session.commit()
        states = dict(
            (
                await session.execute(
                    text(
                        "SELECT reference, state FROM organization_secret_references "
                        "WHERE organization_id = :org"
                    ).bindparams(org=result.organization_id)
                )
            ).all()
        )
    assert states["BORDES_TOKEN"] == SecretReferenceState.REVOKED.value
    assert states["BORDES_TOKEN_2"] == SecretReferenceState.ROTATING.value
    assert states["BORDES_TOKEN_3"] == SecretReferenceState.ACTIVE.value


async def test_revoking_keeps_the_rows_and_reports_how_many(database) -> None:
    """"We stopped having access on the 4th" is a fact somebody will need."""
    result, resolver = await _organization(database)
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        await credentials.record(
            OPERATOR,
            RecordSecretReference(
                organization_id=result.organization_id,
                provider=IntegrationProvider.EASYBROKER,
                reference="BORDES_TOKEN",
                command_key=f"credential:{uuid.uuid4().hex}",
                reason="Registro inicial de la credencial de EasyBroker.",
            ),
        )
        await session.commit()
        revoked = await credentials.revoke(
            OPERATOR,
            organization_id=result.organization_id,
            provider=IntegrationProvider.EASYBROKER,
            reason="El cliente terminó su contrato con EasyBroker.",
        )
        await session.commit()
        assert revoked == 1
        # Idempotent: nothing left to revoke, and no audit row for a no-op.
        assert (
            await credentials.revoke(
                OPERATOR,
                organization_id=result.organization_id,
                provider=IntegrationProvider.EASYBROKER,
                reason="Segunda revocación que no tiene nada que revocar.",
            )
            == 0
        )
        remaining = await session.scalar(
            text(
                "SELECT count(*) FROM organization_secret_references "
                "WHERE organization_id = :org"
            ).bindparams(org=result.organization_id)
        )
        assert remaining == 1


async def test_the_bootstrap_organization_is_none_when_the_slug_is_absent(
    database,
) -> None:
    """An installation provisioned from scratch gives nobody the environment."""
    async with database.session_scope() as session:
        assert await bootstrap_organization_id(session, "no-existe") is None
        assert (
            await bootstrap_organization_id(session, LAREVIA_SLUG)
            is not None
        )


# ---------------------------------------------------------------------------
# The bootstrap reconciliation.
# ---------------------------------------------------------------------------


async def test_the_bootstrap_binds_the_founding_organizations_channels(
    database,
) -> None:
    """The migration aid that keeps the existing local installation working."""
    resolver = SecretResolver({"BORDES_META_TOKEN": "token-meta"})
    # Both the binding and the reference are cleared first: the running
    # application's own bootstrap may already have recorded either, and a test
    # that depended on which would pass or fail by accident.
    async with database.session_scope() as session:
        founding = await commercial.organization_id(session)
        await session.execute(
            text(
                "DELETE FROM organization_channel_bindings "
                "WHERE kind = :kind AND external_id = :external"
            ).bindparams(
                kind=ChannelBindingKind.WHATSAPP_BUSINESS_ACCOUNT.value,
                external="777666555444333",
            )
        )
        await session.execute(
            text(
                "DELETE FROM organization_secret_references "
                "WHERE organization_id = :org AND provider = :provider"
            ).bindparams(org=founding, provider=IntegrationProvider.META_BUSINESS.value)
        )
        await session.commit()

    environment = BootstrapEnvironment(
        slug=LAREVIA_SLUG,
        whatsapp_business_account_id="777666555444333",
        credential_references={IntegrationProvider.META_BUSINESS: "BORDES_META_TOKEN"},
    )
    async with database.session_scope() as session:
        report = await PlatformBootstrap(session, resolver).reconcile(environment)
    assert report.organization_id is not None
    assert report.changed
    assert any("777666555444333" in item for item in report.bound)
    assert any("BORDES_META_TOKEN" in item for item in report.references)

    # Idempotent: a second run with the same environment changes nothing.
    async with database.session_scope() as session:
        again = await PlatformBootstrap(session, resolver).reconcile(environment)
    assert not again.changed

    async with database.session_scope() as session:
        await session.execute(
            text(
                "DELETE FROM organization_channel_bindings "
                "WHERE kind = :kind AND external_id = :external"
            ).bindparams(
                kind=ChannelBindingKind.WHATSAPP_BUSINESS_ACCOUNT.value,
                external="777666555444333",
            )
        )
        await session.execute(
            text(
                "DELETE FROM organization_secret_references "
                "WHERE organization_id = :org AND provider = :provider"
            ).bindparams(
                org=founding, provider=IntegrationProvider.META_BUSINESS.value
            )
        )
        await session.commit()


async def test_the_bootstrap_does_nothing_without_a_founding_organization(
    database,
) -> None:
    async with database.session_scope() as session:
        report = await PlatformBootstrap(session).reconcile(
            BootstrapEnvironment(slug="no-existe", whatsapp_phone_number_id="1")
        )
    assert report.organization_id is None
    assert not report.changed


async def test_the_bootstrap_leaves_another_organizations_identifier_alone(
    database, caplog
) -> None:
    """Quietly reassigning a number would misdirect somebody's customers."""
    import logging

    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        await OrganizationRouting(session).bind(
            organization_id=result.organization_id,
            kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
            external_id="333222111000999",
            recorded_by="edges",
        )
        await session.commit()

    with caplog.at_level(logging.ERROR, logger="realestate.domain.platform.bootstrap"):
        async with database.session_scope() as session:
            report = await PlatformBootstrap(session).reconcile(
                BootstrapEnvironment(
                    slug=LAREVIA_SLUG,
                    whatsapp_phone_number_id="333222111000999",
                )
            )
    assert report.skipped == ("WhatsAppPhoneNumberId:333222111000999",)
    assert not report.bound
    assert "belongs to a different" in caplog.text


async def test_the_bootstrap_never_activates_a_half_provisioned_organization(
    database,
) -> None:
    """Only the final provisioning step may make an Organization operable."""
    async with database.session_scope() as session:
        organization_id = await commercial.organization_id(session)
        organization = await session.get(Organization, organization_id)
        assert organization is not None
        previous = organization.status
        organization.status = OrganizationStatus.PROVISIONING.value
        await session.commit()
    async with database.session_scope() as session:
        await PlatformBootstrap(session).reconcile(
            BootstrapEnvironment(slug=LAREVIA_SLUG)
        )
    async with database.session_scope() as session:
        organization = await session.get(Organization, organization_id)
        assert organization is not None
        assert organization.status == OrganizationStatus.PROVISIONING.value
        organization.status = previous
        await session.commit()


def test_the_bootstrap_writes_history_as_the_platform() -> None:
    assert BOOTSTRAP_OPERATOR.actor_type == "Platform"
    assert BOOTSTRAP_OPERATOR.display_name


# ---------------------------------------------------------------------------
# Provisioning reporting and refusals.
# ---------------------------------------------------------------------------


async def test_provisioning_needs_a_command_key_and_an_administrator(
    database,
) -> None:
    async with database.session_scope() as session:
        provisioning = OrganizationProvisioning(session)
        with pytest.raises(ProvisioningRefused):
            await provisioning.provision(
                OPERATOR,
                ProvisionOrganization(
                    slug=SLUG,
                    display_name="Bordes",
                    configuration={"brand": {}},
                    administrators=(ADMIN,),
                    reason=REASON,
                    command_key="   ",
                ),
            )
        with pytest.raises(ProvisioningRefused):
            await provisioning.provision(
                OPERATOR,
                ProvisionOrganization(
                    slug=SLUG,
                    display_name="Bordes",
                    configuration={"brand": {}},
                    administrators=(),
                    reason=REASON,
                    command_key=f"edges:{uuid.uuid4().hex}",
                ),
            )


async def test_one_command_key_cannot_serve_two_different_runs(database) -> None:
    result, resolver = await _organization(database)
    async with database.session_scope() as session:
        key = await session.scalar(
            text(
                "SELECT command_key FROM organization_provisioning_runs "
                "WHERE id = :id"
            ).bindparams(id=result.run_id)
        )
    async with database.session_scope() as session:
        with pytest.raises(ProvisioningRefused):
            await OrganizationProvisioning(session, resolver=resolver).provision(
                OPERATOR,
                ProvisionOrganization(
                    slug="otro-slug",
                    display_name="Otro",
                    configuration={"brand": {}},
                    administrators=(ADMIN,),
                    reason=REASON,
                    command_key=key,
                ),
            )


async def test_the_runs_and_their_steps_are_readable_afterwards(database) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        provisioning = OrganizationProvisioning(session)
        runs = await provisioning.runs(slug=SLUG)
        assert [run.id for run in runs] == [result.run_id]
        assert await provisioning.runs()
        steps = await provisioning.steps_of(result.run_id)
        assert [step.name for step in steps][0] == STEP_ORGANIZATION
        assert all(
            step.state == ProvisioningState.COMPLETED.value for step in steps
        )
        assert await provisioning.count() >= 2


async def test_lifecycle_changes_refuse_an_organization_that_does_not_exist(
    database,
) -> None:
    absent = uuid.uuid4()
    async with database.session_scope() as session:
        provisioning = OrganizationProvisioning(session)
        for call in (
            provisioning.suspend(
                OPERATOR, organization_id=absent, reason=REASON
            ),
            provisioning.resume(OPERATOR, organization_id=absent, reason=REASON),
            provisioning.deprovision(
                OPERATOR,
                DeprovisionOrganization(
                    organization_id=absent,
                    reason=REASON,
                    command_key=f"edges:{uuid.uuid4().hex}",
                ),
            ),
        ):
            with pytest.raises(NotFound):
                await call


async def test_deprovisioning_twice_replays_rather_than_repeating(database) -> None:
    result, _resolver = await _organization(database)
    key = f"edges-deprovision:{uuid.uuid4().hex}"
    command = DeprovisionOrganization(
        organization_id=result.organization_id, reason=REASON, command_key=key
    )
    async with database.session_scope() as session:
        first = await OrganizationProvisioning(session).deprovision(OPERATOR, command)
    async with database.session_scope() as session:
        again = await OrganizationProvisioning(session).deprovision(OPERATOR, command)
    assert first.state is ProvisioningState.COMPLETED
    assert again.state is ProvisioningState.COMPLETED
    assert again.steps == ()


# ---------------------------------------------------------------------------
# Configuration and entitlement edges.
# ---------------------------------------------------------------------------


async def test_reading_a_configuration_section_tolerates_an_absent_one(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        view = await OrganizationConfiguration(session).current(
            result.organization_id
        )
        assert view.section("brand") == {"working_name": "Bordes"}
        # Absent, and absent is a valid document rather than an error.
        assert view.section("limits") == {}


async def test_an_administrator_reads_their_own_configuration_only(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        from realestate.domain.commercial.organization import OrganizationDirectory

        actor = await OrganizationDirectory(session).resolve_actor(ADMIN)
        view = await OrganizationConfiguration(session).read_for(actor)
        assert view.organization_id == result.organization_id
        # And the founding Organization's configuration is unreachable from here:
        # ``read_for`` takes no identifier at all.
        assert view.version == 1


async def test_try_current_answers_none_and_current_refuses(database) -> None:
    async with database.session_scope() as session:
        configuration = OrganizationConfiguration(session)
        assert await configuration.try_current(uuid.uuid4()) is None
        with pytest.raises(ConfigurationMissing):
            await configuration.current(uuid.uuid4())


async def test_a_replayed_configuration_command_returns_its_own_version(
    database,
) -> None:
    result, _resolver = await _organization(database)
    key = f"configuration:{uuid.uuid4().hex}"
    async with database.session_scope() as session:
        configuration = OrganizationConfiguration(session)
        first = await configuration.record(
            OPERATOR,
            RecordConfiguration(
                organization_id=result.organization_id,
                document={"brand": {"working_name": "Bordes"}, "notes": {"a": "b"}},
                reason="Se añade una nota operativa a la configuración.",
                command_key=key,
            ),
        )
        await session.commit()
        replay = await configuration.record(
            OPERATOR,
            RecordConfiguration(
                organization_id=result.organization_id,
                # A different document under the same key replays the first.
                document={"brand": {"working_name": "Otro"}},
                reason="Reenvío del mismo formulario.",
                command_key=key,
            ),
        )
    assert replay.version == first.version
    assert replay.checksum == first.checksum


async def test_entitlement_history_reads_across_capabilities(database) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        every = await Entitlements(session).history(result.organization_id)
        assert len(every) >= len(CAPABILITY_LABELS)


def test_the_largest_tier_covers_an_operation_that_outgrew_the_table() -> None:
    from realestate.domain.platform.entitlements import TIERS

    assert tier_for(0).name == TIERS[0].name
    assert tier_for(TIERS[-1].advisor_seats + 100).name == TIERS[-1].name


# ---------------------------------------------------------------------------
# Import edges.
# ---------------------------------------------------------------------------


def _record(index: int, **overrides) -> IncomingProperty:
    fields = {
        "source_reference": f"XLS-{index}",
        "property_key": f"casa-borde-{index}",
        "name": f"Casa Borde {index}",
        "property_type": "House",
        "facts": {},
    }
    fields.update(overrides)
    return IncomingProperty(**fields)


def _plan(organization_id, records, **overrides) -> ImportPlan:
    fields = {
        "organization_id": organization_id,
        "source": "Bordes.xlsx",
        "records": records,
        "reason": "Migración inicial de bordes.",
        "command_key": f"import:{uuid.uuid4().hex}",
    }
    fields.update(overrides)
    return ImportPlan(**fields)


async def test_an_import_refuses_an_empty_or_oversized_batch(database) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        importer = OrganizationImport(session)
        with pytest.raises(ImportRefused):
            await importer.plan(OPERATOR, _plan(result.organization_id, ()))
        with pytest.raises(ImportRefused):
            await importer.plan(
                OPERATOR,
                _plan(
                    result.organization_id,
                    tuple(_record(index) for index in range(MAX_RECORDS + 1)),
                ),
            )


async def test_an_import_refuses_an_unknown_or_deprovisioned_organization(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await OrganizationImport(session).plan(
                OPERATOR, _plan(uuid.uuid4(), (_record(1),))
            )
    async with database.session_scope() as session:
        await OrganizationProvisioning(session).deprovision(
            OPERATOR,
            DeprovisionOrganization(
                organization_id=result.organization_id,
                reason=REASON,
                command_key=f"edges:{uuid.uuid4().hex}",
            ),
        )
    async with database.session_scope() as session:
        with pytest.raises(ImportRefused):
            await OrganizationImport(session).plan(
                OPERATOR, _plan(result.organization_id, (_record(1),))
            )


async def test_a_replayed_import_command_returns_its_first_report(database) -> None:
    result, _resolver = await _organization(database)
    plan = _plan(result.organization_id, (_record(1),))
    async with database.session_scope() as session:
        first = await OrganizationImport(session).plan(OPERATOR, plan)
    async with database.session_scope() as session:
        again = await OrganizationImport(session).plan(OPERATOR, plan)
    assert again.run_id == first.run_id
    assert again.matches(first)


async def test_rolling_back_a_dry_run_or_an_unknown_run_is_refused(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        dry = await OrganizationImport(session).plan(
            OPERATOR, _plan(result.organization_id, (_record(1),))
        )
    async with database.session_scope() as session:
        importer = OrganizationImport(session)
        with pytest.raises(ImportRefused):
            await importer.roll_back(
                OPERATOR, run_id=dry.run_id, reason="Nada que revertir."
            )
        with pytest.raises(NotFound):
            await importer.roll_back(
                OPERATOR,
                run_id=uuid.uuid4(),
                reason="Reversión de una importación inexistente.",
            )
        with pytest.raises(NotFound):
            await importer.report(uuid.uuid4())
        assert (await importer.report(dry.run_id)).run_id == dry.run_id
        assert await importer.runs(result.organization_id)


async def test_a_rollback_leaves_a_referenced_record_in_place_and_reports_it(
    database, caplog
) -> None:
    """Cascading through a confirmed visit would be damage, not a rollback."""
    import logging

    result, _resolver = await _organization(database)
    records = (_record(1),)
    async with database.session_scope() as session:
        await OrganizationImport(session).plan(
            OPERATOR, _plan(result.organization_id, records)
        )
    async with database.session_scope() as session:
        applied = await OrganizationImport(session).apply(
            OPERATOR, _plan(result.organization_id, records)
        )
    created = applied.findings[0].created_record_id
    assert created is not None

    # Somebody books a visit against the imported Property.
    async with database.session_scope() as session:
        lead = await commercial.make_lead(session, "5213366666666")
        lead.organization_id = result.organization_id
        conversation = await commercial.make_conversation(session, lead)
        starts = datetime.now(tz=UTC) + timedelta(days=3)
        session.add(
            Appointment(
                organization_id=result.organization_id,
                conversation_id=conversation.id,
                lead_id=lead.id,
                property_uuid=created,
                reference=f"V-{uuid.uuid4().hex[:6]}",
                idempotency_key=f"edges:{uuid.uuid4().hex}",
                starts_at=starts,
                ends_at=starts + timedelta(minutes=90),
                status=AppointmentStatus.CONFIRMED.value,
            )
        )
        await session.commit()

    with caplog.at_level(logging.WARNING, logger="realestate.domain.platform.imports"):
        async with database.session_scope() as session:
            rolled = await OrganizationImport(session).roll_back(
                OPERATOR,
                run_id=applied.run_id,
                reason="El cliente pidió revertir la carga inicial.",
            )
    assert rolled.state.value == "RolledBack"
    assert "left 1 record(s) in place" in caplog.text
    async with database.session_scope() as session:
        still_there = await session.get(Property, created)
        assert still_there is not None


async def test_an_import_record_missing_its_source_reference_is_invalid(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        report = await OrganizationImport(session).plan(
            OPERATOR,
            _plan(
                result.organization_id,
                (
                    _record(1, source_reference="  "),
                    _record(2, name="   "),
                    _record(3, property_type="Palacio"),
                ),
            ),
        )
    kinds = {item.kind.value for item in report.findings}
    assert kinds == {"Invalid"}
    assert all(item.detail for item in report.findings)


# ---------------------------------------------------------------------------
# Lifecycle edges.
# ---------------------------------------------------------------------------


async def test_the_lifecycle_refuses_an_organization_that_does_not_exist(
    database,
) -> None:
    absent = uuid.uuid4()
    async with database.session_scope() as session:
        lifecycle = OrganizationDataLifecycle(session)
        with pytest.raises(NotFound):
            await lifecycle.export(
                OPERATOR,
                ExportOrganizationData(
                    organization_id=absent,
                    reason=REASON,
                    command_key=f"edges:{uuid.uuid4().hex}",
                ),
            )
        with pytest.raises(NotFound):
            await lifecycle.delete(
                OPERATOR,
                DeleteOrganizationData(
                    organization_id=absent,
                    scope=DeletionScope.EVERYTHING,
                    reason=REASON,
                    command_key=f"edges:{uuid.uuid4().hex}",
                ),
            )
        with pytest.raises(NotFound):
            await lifecycle.release_hold(
                OPERATOR, hold_id=uuid.uuid4(), reason=REASON
            )


async def test_an_export_that_cannot_be_written_is_recorded_as_failed(
    database, tmp_path
) -> None:
    """The artifact is a customer deliverable; a silent failure is not an option."""
    result, _resolver = await _organization(database)
    blocked = tmp_path / "no-escribible"
    blocked.write_text("soy un archivo, no un directorio")
    async with database.session_scope() as session:
        with pytest.raises(ExportFailed):
            await OrganizationDataLifecycle(session, root=blocked).export(
                OPERATOR,
                ExportOrganizationData(
                    organization_id=result.organization_id,
                    reason="Entrega que no se puede escribir.",
                    command_key=f"export:{uuid.uuid4().hex}",
                ),
            )
    async with database.session_scope() as session:
        rows = await OrganizationDataLifecycle(session).exports(
            result.organization_id
        )
        assert rows[0].state == DataLifecycleState.FAILED.value
        assert rows[0].failure


async def test_a_hold_needs_an_authority_and_releases_only_once(database) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        lifecycle = OrganizationDataLifecycle(session)
        with pytest.raises(DeletionBlocked):
            await lifecycle.record_hold(
                OPERATOR,
                RecordRetentionHold(
                    organization_id=result.organization_id,
                    basis=RetentionBasis.DISPUTE,
                    authority="  ",
                    description="Retención sin autoridad nombrada.",
                ),
            )
        hold = await lifecycle.record_hold(
            OPERATOR,
            RecordRetentionHold(
                organization_id=result.organization_id,
                basis=RetentionBasis.DISPUTE,
                authority="Expediente 44/2026",
                description="Conservar mientras dure la controversia.",
                # Already lapsed, so it does not block a deletion.
                expires_at=datetime.now(tz=UTC) - timedelta(days=1),
            ),
        )
    async with database.session_scope() as session:
        lifecycle = OrganizationDataLifecycle(session)
        # A lapsed hold releases itself.
        assert await lifecycle.live_holds(result.organization_id) == []
        first = await lifecycle.release_hold(
            OPERATOR, hold_id=hold.id, reason="Se cierra la controversia."
        )
        again = await lifecycle.release_hold(
            OPERATOR, hold_id=hold.id, reason="Segunda liberación, sin efecto."
        )
        assert first.released_at == again.released_at


async def test_a_replayed_export_or_deletion_command_returns_its_record(
    database, tmp_path
) -> None:
    result, _resolver = await _organization(database)
    key = f"delete:{uuid.uuid4().hex}"
    command = DeleteOrganizationData(
        organization_id=result.organization_id,
        scope=DeletionScope.OPERATIONAL_CONTENT,
        reason="Solicitud de eliminación de conversaciones.",
        command_key=key,
    )
    async with database.session_scope() as session:
        first = await OrganizationDataLifecycle(session).delete(OPERATOR, command)
    async with database.session_scope() as session:
        again = await OrganizationDataLifecycle(session).delete(OPERATOR, command)
    assert first.deletion_id == again.deletion_id
    assert again.state is DataLifecycleState.COMPLETED
    async with database.session_scope() as session:
        assert await OrganizationDataLifecycle(session).deletions(
            result.organization_id
        )


async def test_a_blocked_deletion_replays_as_blocked(database) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        await OrganizationDataLifecycle(session).record_hold(
            OPERATOR,
            RecordRetentionHold(
                organization_id=result.organization_id,
                basis=RetentionBasis.LEGAL_OBLIGATION,
                authority="Requerimiento 99/2026",
                description="Conservar el registro comercial completo.",
            ),
        )
    key = f"delete:{uuid.uuid4().hex}"
    command = DeleteOrganizationData(
        organization_id=result.organization_id,
        scope=DeletionScope.EVERYTHING,
        reason="Solicitud de eliminación con retención vigente.",
        command_key=key,
    )
    async with database.session_scope() as session:
        first = await OrganizationDataLifecycle(session).delete(OPERATOR, command)
    async with database.session_scope() as session:
        again = await OrganizationDataLifecycle(session).delete(OPERATOR, command)
    assert first.state is DataLifecycleState.BLOCKED
    assert again.state is DataLifecycleState.BLOCKED
    assert again.blocked_reason == first.blocked_reason


# ---------------------------------------------------------------------------
# Support and usage edges.
# ---------------------------------------------------------------------------


async def test_a_support_grant_refuses_an_unknown_organization(database) -> None:
    async with database.session_scope() as session:
        with pytest.raises(NotFound):
            await SupportAccess(session).grant(
                OPERATOR,
                GrantSupportAccess(
                    organization_id=uuid.uuid4(),
                    engineer_login="gerardo",
                    reason="Acceso a una organización que no existe.",
                    command_key=f"support:{uuid.uuid4().hex}",
                ),
            )


async def test_a_replayed_support_command_returns_its_own_grant(database) -> None:
    result, _resolver = await _organization(database)
    key = f"support:{uuid.uuid4().hex}"
    command = GrantSupportAccess(
        organization_id=result.organization_id,
        engineer_login="gerardo",
        reason="El cliente reporta un problema con su bandeja.",
        command_key=key,
    )
    async with database.session_scope() as session:
        support = SupportAccess(session)
        first = await support.grant(OPERATOR, command)
        await session.commit()
        again = await support.grant(OPERATOR, command)
    assert first.grant_id == again.grant_id
    assert first.live(datetime.now(tz=UTC))
    assert first.state == "Vigente"


async def test_an_expired_grant_does_not_block_the_next_investigation(
    database,
) -> None:
    """A second investigation starts immediately after the first one lapsed."""
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        support = SupportAccess(session)
        lapsed = await support.grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Primera investigación, ya vencida.",
                command_key=f"support:{uuid.uuid4().hex}",
                hours=1,
            ),
            at=datetime.now(tz=UTC) - timedelta(hours=4),
        )
        await session.commit()
        second = await support.grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Segunda investigación tras vencer la primera.",
                command_key=f"support:{uuid.uuid4().hex}",
            ),
        )
        await session.commit()
    assert second.grant_id != lapsed.grant_id
    assert not lapsed.live(datetime.now(tz=UTC))
    assert lapsed.state == "Expirado"


async def test_a_non_support_login_is_not_treated_as_a_grant(database) -> None:
    async with database.session_scope() as session:
        assert (
            await SupportAccess(session).live_for_login(commercial.ADMIN_LOGIN) is None
        )
        assert (
            await SupportAccess(session).live_for_login("soporte:nadie:nunca") is None
        )


async def test_revoking_the_same_grant_twice_reports_the_first_revocation(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        support = SupportAccess(session)
        grant = await support.grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Investigación que se revoca dos veces.",
                command_key=f"support:{uuid.uuid4().hex}",
            ),
        )
        await session.commit()
        first = await support.revoke(
            OPERATOR, grant_id=grant.grant_id, reason="Diagnóstico terminado."
        )
        await session.commit()
        again = await support.revoke(
            OPERATOR,
            grant_id=grant.grant_id,
            reason="Segunda revocación, sin efecto.",
        )
    assert first.revoked_at == again.revoked_at
    async with database.session_scope() as session:
        member = await session.scalar(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == result.organization_id)
            .where(OrganizationMember.login == grant.subject_login)
        )
        assert member is not None
        assert member.active is False


async def test_a_grant_reuses_a_previous_investigations_member_row(
    database,
) -> None:
    """Assignments and audit rows may reference it; history has to stay readable."""
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        support = SupportAccess(session)
        first = await support.grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Primera investigación sobre el canal del cliente.",
                command_key=f"support:{uuid.uuid4().hex}",
            ),
        )
        await session.commit()
        await support.revoke(
            OPERATOR, grant_id=first.grant_id, reason="Diagnóstico terminado."
        )
        await session.commit()
        second = await support.grant(
            OPERATOR,
            GrantSupportAccess(
                organization_id=result.organization_id,
                engineer_login="gerardo",
                reason="Segunda investigación una semana después.",
                command_key=f"support:{uuid.uuid4().hex}",
            ),
        )
        await session.commit()
    assert second.subject_login == first.subject_login
    async with database.session_scope() as session:
        members = await session.scalar(
            select(func.count(OrganizationMember.id))
            .where(OrganizationMember.organization_id == result.organization_id)
            .where(OrganizationMember.login == first.subject_login)
        )
        assert members == 1


async def test_usage_reads_an_organization_with_no_stored_month_as_zero(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        usage = await PlatformUsage(session).read(result.organization_id)
        assert usage.slug == SLUG
        assert all(item.quantity == 0 for item in usage.readings)
        assert usage.of(next(iter(usage.readings)).metric) is not None


async def test_the_registry_lists_every_organization_whatever_its_state(
    database,
) -> None:
    result, _resolver = await _organization(database)
    async with database.session_scope() as session:
        await OrganizationProvisioning(session).suspend(
            OPERATOR,
            organization_id=result.organization_id,
            reason="Pausa para la prueba del registro.",
        )
        await session.commit()
    async with database.session_scope() as session:
        every = {item.slug: item for item in await all_organizations(session)}
        assert every[SLUG].status is OrganizationStatus.SUSPENDED
        from realestate.domain.platform.registry import operating_organization_ids

        assert result.organization_id not in await operating_organization_ids(session)

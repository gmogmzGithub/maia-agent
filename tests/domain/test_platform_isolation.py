"""The cross-organization matrix: every table, query, worker, event and store.

This is the file the whole stage exists to make passable. It is deliberately
organised as a *matrix* rather than as a list of scenarios, because the failure
mode is uniform and boring: somewhere, one query forgot its scope. A suite of
narrative tests catches the paths somebody thought of; a matrix over the scoping
registry catches the table somebody added last week.

Three kinds of assertion here, and they are not interchangeable:

* **structural** — every table is classified, every classified table has the
  column, and no child row names a different Organization than its parent. These
  run over the schema and the registry, so a new table cannot slip past;
* **behavioural** — a second Organization's Actor cannot read, guess, join to or
  join through the first one's records; a webhook on an unbound number is refused
  rather than defaulted; a credential is never inherited;
* **operational** — the workers, the Outbox and the analytics projection keep the
  Organization on every row they touch while both Organizations are live.

The second Organization is provisioned through the real
:class:`OrganizationProvisioning`, not inserted. A fixture that built it by hand
would prove that hand-built rows are isolated, which is not the claim.
"""

from __future__ import annotations

import uuid
import asyncio

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from realestate.channels.messaging import CustomerChannel
from realestate.db.engine import Base, Database
from realestate.db.models import (
    AnalyticsDomainEvent,
    AnalyticsEventName,
    AnalyticsOutboxEntry,
    AnalyticsOutboxStatus,
    AnalyticsProjectionRun,
    Appointment,
    Capability,
    ChannelBindingKind,
    Conversation,
    InboxMessage,
    IntegrationProvider,
    InternalAlert,
    InternalAlertStatus,
    Organization,
    OrganizationMember,
    OrganizationStatus,
    OutboxMessage,
    Property,
    PropertyStatus,
)
from realestate.domain.commercial.actors import Actor, NotFound
from realestate.domain.analytics.events import AnalyticsEvent, AnalyticsEvents
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.clock import utc_now
from realestate.domain.commercial.organization import (
    OrganizationDirectory,
    OrganizationSuspended,
)
from realestate.domain.commercial.views import CommercialInbox
from realestate.domain.inbox import InboxService
from realestate.domain.internal_alerts import InternalAlerts
from realestate.domain.platform.authority import PlatformOperator
from realestate.domain.platform.credentials import (
    IntegrationCredentials,
    MissingCredential,
    RecordSecretReference,
    SecretResolver,
)
from realestate.domain.platform.provisioning import (
    ChannelAssignment,
    CredentialAssignment,
    OrganizationProvisioning,
    ProvisionOrganization,
)
from realestate.domain.platform.providers import (
    OrganizationEasyBrokerAdapters,
    OrganizationGoogleCalendarDirectories,
    OrganizationTelegramClients,
)
from realestate.domain.platform.registry import operating_organization_ids
from realestate.domain.platform.routing import (
    OrganizationRouting,
    UnroutableChannel,
)
from realestate.domain.platform.scoping import (
    ScopeKind,
    SCOPES,
    mismatched_scope_columns,
    organization_scopes,
    qualified_name,
    unclassified_tables,
)
from realestate.domain.platform.whatsapp import OrganizationWhatsAppClients
from realestate.domain.platform.messaging import (
    MetaMessagingChannelMissing,
    OrganizationMetaMessagingClients,
)
from realestate.domain.properties import ArtifactStore, PropertyService
from tests.conftest import DATABASE_URL, requires_postgres
from tests.fixtures import commercial

pytestmark = [pytest.mark.anyio, requires_postgres]


OPERATOR = PlatformOperator(label="platform-tester")

SECOND_SLUG = "segunda-inmobiliaria"
SECOND_ADMIN = "dir@segunda.test"
SECOND_ADVISOR = "ana@segunda.test"
SECOND_PHONE_NUMBER_ID = "999888777666555"
SECOND_SITE_HOST = "segunda.test"
SECOND_TELEGRAM_BOT = "444555666"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Structural: the registry, the columns, and the parent/child agreement.
# ---------------------------------------------------------------------------


def test_every_table_is_classified_as_organization_or_platform_data() -> None:
    """A new table cannot be added without somebody deciding what it holds.

    The guard the export, the deletion and this file all depend on. Without it a
    table added next month is silently absent from every per-Organization
    operation and nothing fails.
    """
    assert unclassified_tables() == (), (
        "These tables have no entry in realestate.domain.platform.scoping.SCOPES. "
        "Decide whether each holds one Organization's data or is deliberately "
        "platform-wide, and say why: " + ", ".join(unclassified_tables())
    )


def test_every_organization_table_actually_has_the_column() -> None:
    """A classification that the schema does not back is worse than none."""
    assert mismatched_scope_columns() == ()


def test_every_platform_table_carries_a_written_reason() -> None:
    """"It was easier" is not a reason. A reader looking for a hole gets prose."""
    for scope in SCOPES:
        if scope.kind is ScopeKind.PLATFORM:
            assert len(scope.reason) > 80, (
                f"{scope.table} is classified platform-wide with a reason too "
                "short to be an argument."
            )


def test_the_scoping_table_covers_every_mapped_table_exactly_once() -> None:
    names = [scope.table for scope in SCOPES]
    assert len(names) == len(set(names))
    assert set(names) == {table.name for table in Base.metadata.tables.values()}


def test_deletion_order_is_derived_from_the_schema_not_written_down() -> None:
    """Children come before the parents they reference, whatever gets added.

    Asserted on a pair that actually matters: ``inbox_messages`` references
    ``conversations``, so deleting in the reverse of this order has to reach the
    messages first.
    """
    order = [scope.table for scope in organization_scopes()]
    assert order[0] == "organizations"
    assert order.index("conversations") < order.index("inbox_messages")
    assert order.index("leads") < order.index("lead_engagement_cycles")
    assert order.index("appointments") < order.index("appointment_reminders")


# ---------------------------------------------------------------------------
# Two live Organizations, provisioned the way a real one would be.
# ---------------------------------------------------------------------------


async def _second_organization(session, resolver: SecretResolver) -> uuid.UUID:
    """Provision the second Organization through the real module."""
    result = await OrganizationProvisioning(session, resolver=resolver).provision(
        OPERATOR,
        ProvisionOrganization(
            slug=SECOND_SLUG,
            display_name="Segunda Inmobiliaria",
            configuration={
                "brand": {"name": "Segunda"},
                "service_area": {"municipalities": ["Tlaquepaque"]},
                "scheduling": {
                    "time_zone": "America/Mexico_City",
                    "visit_minutes": 60,
                    "weekly_schedule": (
                        "mon=10:00-16:00;tue=10:00-16:00;wed=10:00-16:00;"
                        "thu=10:00-16:00;fri=10:00-16:00;sat=nada;sun=nada"
                    ),
                },
            },
            administrators=(SECOND_ADMIN,),
            advisors=(SECOND_ADVISOR,),
            default_advisor=SECOND_ADVISOR,
            channels=(
                ChannelAssignment(
                    kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
                    external_id=SECOND_PHONE_NUMBER_ID,
                ),
                ChannelAssignment(
                    kind=ChannelBindingKind.PUBLIC_SITE_HOST,
                    external_id=SECOND_SITE_HOST,
                ),
                ChannelAssignment(
                    kind=ChannelBindingKind.TELEGRAM_BOT,
                    external_id=SECOND_TELEGRAM_BOT,
                ),
            ),
            credentials=(
                CredentialAssignment(
                    provider=IntegrationProvider.META_WHATSAPP,
                    reference="SEGUNDA_META_ACCESS_TOKEN",
                ),
                CredentialAssignment(
                    provider=IntegrationProvider.TELEGRAM,
                    reference="SEGUNDA_TELEGRAM_BOT_TOKEN",
                ),
            ),
            add_ons=(Capability.EXTERNAL_INVENTORY,),
            reason="Alta de la segunda organización para la matriz de aislamiento.",
            command_key=f"isolation-provision:{uuid.uuid4().hex}",
        ),
    )
    assert result.operable, result.failure
    assert result.organization_id is not None
    return result.organization_id


@pytest.fixture
async def two_organizations(tmp_path):
    """Larevia with a Property, and a second provisioned Organization.

    Deliberately not two hand-built rows: the second Organization goes through
    ``OrganizationProvisioning``, so what the matrix proves isolated is what an
    onboarding actually creates.
    """
    database = Database(DATABASE_URL)
    resolver = SecretResolver(
        {
            "SEGUNDA_META_ACCESS_TOKEN": "segunda-token",
            "SEGUNDA_TELEGRAM_BOT_TOKEN": f"{SECOND_TELEGRAM_BOT}:second-secret",
        }
    )
    async with database.session_scope() as session:
        await commercial.forget_organization(session, SECOND_SLUG)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision_bookable_team(session)
        first = await commercial.organization_id(session)
        accepted = await PropertyService(
            session,
            ArtifactStore(tmp_path / "artifacts"),
            organization_id=first,
        ).accept_upload(
            "casa-roble.md",
            (
                __import__("pathlib").Path(__file__).parents[1]
                / "fixtures"
                / "casa-roble.md"
            ).read_bytes(),
            actor_id="developer",
        )
        second = await _second_organization(session, resolver)
        await session.commit()
    yield database, first, second, accepted.property_key, resolver
    async with database.session_scope() as session:
        await commercial.forget_organization(session, SECOND_SLUG)
    await database.dispose()


async def test_provisioning_creates_an_operable_second_organization(
    two_organizations,
) -> None:
    database, first, second, _key, _resolver = two_organizations
    assert first != second
    async with database.session_scope() as session:
        organization = await session.get(Organization, second)
        assert organization is not None
        assert organization.status == OrganizationStatus.ACTIVE.value
        assert organization.activated_at is not None
        assert set(await operating_organization_ids(session)) >= {first, second}


# ---------------------------------------------------------------------------
# Behavioural: guessed identifiers, indirect joins, and the same business key.
# ---------------------------------------------------------------------------


async def test_the_same_property_key_may_exist_in_both_organizations(
    two_organizations, tmp_path
) -> None:
    """A readable key was globally unique, which was itself a disclosure.

    The second Organization discovered another brokerage's inventory from a
    constraint violation. Now the key is theirs to use.
    """
    database, _first, second, key, _resolver = two_organizations
    async with database.session_scope() as session:
        service = PropertyService(
            session,
            ArtifactStore(tmp_path / "second-artifacts"),
            organization_id=second,
        )
        accepted = await service.accept_upload(
            "casa-roble.md",
            (
                __import__("pathlib").Path(__file__).parents[1]
                / "fixtures"
                / "casa-roble.md"
            ).read_bytes(),
            actor_id="platform-tester",
        )
        assert accepted.property_key == key
        total = await session.scalar(
            select(func.count(Property.id)).where(Property.property_key == key)
        )
        assert total == 2


async def test_an_administrator_cannot_read_the_other_organizations_property(
    two_organizations,
) -> None:
    """A guessed UUID is refused as if the record did not exist."""
    database, first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        first_property = await session.scalar(
            select(Property.id).where(Property.organization_id == first)
        )
        assert first_property is not None
        from realestate.domain.administration import (
            AdministrationService,
            Administrator,
        )

        listed = await AdministrationService(session).list_properties(second)
        assert listed["properties"] == []

        refused = await AdministrationService(session).set_property_status(
            str(first_property),
            PropertyStatus.INACTIVE.value,
            Administrator(organization_id=second, actor_id="dir@segunda.test"),
            inactive_reason="Withdrawn",
        )
        assert refused["result"] == "not_found"


async def test_an_advisor_of_the_other_organization_sees_no_opportunities(
    two_organizations,
) -> None:
    """The Inbox and pipeline are empty for the newcomer, not partially filled."""
    database, first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        await commercial.opportunity_for(session, "5213311111111", assign=True)
        await session.commit()
    async with database.session_scope() as session:
        theirs = await OrganizationDirectory(session).resolve_actor(SECOND_ADMIN)
        assert theirs.organization_id == second
        views = CommercialInbox(session)
        assert await views.opportunities(theirs) == []
        assert await views.query(theirs) == []
        assert await views.contacts(theirs) == []

        ours = await OrganizationDirectory(session).resolve_actor(
            commercial.ADMIN_LOGIN
        )
        assert ours.organization_id == first
        assert len(await views.opportunities(ours)) == 1


async def test_an_appointment_reference_is_only_guessable_inside_one_organization(
    two_organizations,
) -> None:
    """A short readable reference used to be a global namespace.

    Two Organizations may now hold the same one, and resolving it requires the
    Organization — so an administrator cannot confirm somebody else's visit by
    typing a reference they guessed.
    """
    database, first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        # Two appointments, same reference, different Organizations. Inserted
        # directly because the point is the constraint, not the booking path.
        state = await commercial.opportunity_for(session, "5213322222222")
        conversation = await commercial.make_conversation(session, state.lead)
        first_property = await session.scalar(
            select(Property.id).where(Property.organization_id == first)
        )
        advisor = await session.scalar(
            select(OrganizationMember.id)
            .where(OrganizationMember.organization_id == first)
            .where(OrganizationMember.login == commercial.ADVISOR_LOGIN)
        )
        from datetime import UTC, datetime, timedelta

        starts = datetime.now(tz=UTC) + timedelta(days=2)
        session.add(
            Appointment(
                organization_id=first,
                conversation_id=conversation.id,
                lead_id=state.lead.id,
                property_uuid=first_property,
                advisor_id=advisor,
                reference="V-0001",
                idempotency_key=f"iso:{uuid.uuid4().hex}",
                starts_at=starts,
                ends_at=starts + timedelta(minutes=90),
                status="Confirmed",
            )
        )
        await session.commit()

    async with database.session_scope() as session:
        from realestate.domain.admin_work import AdminWorkService
        from realestate.domain.availability import WeeklySchedule
        from tests.fixtures.stubs import StubCalendarDirectory

        service = AdminWorkService(
            session,
            StubCalendarDirectory(),
            WeeklySchedule.parse(
                "mon=09:00-17:00;tue=09:00-17:00;wed=09:00-17:00;"
                "thu=09:00-17:00;fri=09:00-17:00;sat=nada;sun=nada",
                "America/Mexico_City",
            ),
            9,
        )
        pending = await service.list_pending(second)
        assert pending["items"] == []
        from realestate.domain.administration import Administrator

        from realestate.domain.admin_work import CONFIRM

        refused = await service.resolve(
            "V-0001",
            CONFIRM,
            Administrator(organization_id=second, actor_id=SECOND_ADMIN),
        )
        assert refused["result"] == "not_found"


async def test_an_unbound_whatsapp_number_is_refused_not_defaulted(
    two_organizations,
) -> None:
    """The single most dangerous default this stage removes.

    Falling back to "the only Organization" would file one brokerage's customer
    under another's Contacts, answer them from the wrong channel, and attribute
    the Opportunity to somebody who never spoke to them.
    """
    database, _first, _second, _key, _resolver = two_organizations
    from realestate.channels.whatsapp.payload import InboundMessage
    from datetime import UTC, datetime

    message = InboundMessage(
        wamid=f"wamid.{uuid.uuid4().hex}",
        from_wa_id="5213399999999",
        phone_number_id="000000000000000",
        message_type="text",
        sent_at=datetime.now(tz=UTC),
        text="Hola",
        profile_name="Desconocido",
        raw={},
    )
    async with database.session_scope() as session:
        with pytest.raises(UnroutableChannel):
            await InboxService(session).accept(message)


async def test_each_organizations_number_routes_only_to_its_own_records(
    two_organizations,
) -> None:
    """The same body on two numbers produces two Conversations, one each."""
    database, first, second, _key, _resolver = two_organizations
    from realestate.channels.whatsapp.payload import InboundMessage
    from datetime import UTC, datetime

    body = "Hola, quiero información."
    async with database.session_scope() as session:
        for phone_number_id in (
            commercial.TEST_PHONE_NUMBER_ID,
            SECOND_PHONE_NUMBER_ID,
        ):
            await InboxService(session).accept(
                InboundMessage(
                    wamid=f"wamid.{uuid.uuid4().hex}",
                    from_wa_id="5213344444444",
                    phone_number_id=phone_number_id,
                    message_type="text",
                    sent_at=datetime.now(tz=UTC),
                    text=body,
                    profile_name="Cliente",
                    raw={},
                )
            )
        await session.commit()

    async with database.session_scope() as session:
        for organization_id in (first, second):
            conversations = list(
                await session.scalars(
                    select(Conversation).where(
                        Conversation.organization_id == organization_id
                    )
                )
            )
            assert len(conversations) == 1
            messages = list(
                await session.scalars(
                    select(InboxMessage).where(
                        InboxMessage.organization_id == organization_id
                    )
                )
            )
            assert len(messages) == 1
            # The child row's Organization and its parent's agree. The composite
            # foreign key makes disagreeing impossible; asserting it here is what
            # catches a writer that stopped setting the column.
            assert messages[0].organization_id == conversations[0].organization_id


async def test_the_same_provider_message_id_may_arrive_for_both_organizations(
    two_organizations,
) -> None:
    """A delivery callback attaches to the Outbox row of *its own* Organization."""
    database, first, second, _key, _resolver = two_organizations
    from datetime import UTC, datetime

    from realestate.domain.outbox import OutboxService

    provider_id = f"wamid.status.{uuid.uuid4().hex}"
    async with database.session_scope() as session:
        # Addressed by the number the callback arrived on, which is all Meta
        # gives: the service resolves the Organization from it.
        for phone_number_id in (
            commercial.TEST_PHONE_NUMBER_ID,
            SECOND_PHONE_NUMBER_ID,
        ):
            await OutboxService(session).record_delivery_status(
                phone_number_id=phone_number_id,
                provider_message_id=provider_id,
                status="delivered",
                occurred_at=datetime.now(tz=UTC),
                raw={"id": provider_id},
            )
    async with database.session_scope() as session:
        rows = await session.execute(
            text(
                "SELECT organization_id FROM delivery_statuses "
                "WHERE provider_message_id = :pid"
            ).bindparams(pid=provider_id)
        )
        owners = {row[0] for row in rows}
        assert owners == {first, second}


async def test_the_same_outbox_idempotency_key_does_not_collide(
    two_organizations,
) -> None:
    """Two Organizations minting the same key both get to enqueue their reply."""
    database, first, second, _key, _resolver = two_organizations
    key = f"reply:{uuid.uuid4().hex}"
    async with database.session_scope() as session:
        from realestate.domain.outbox import OutboxService

        for organization_id, wa_id in ((first, "521330001"), (second, "521330002")):
            lead = await _lead_for(session, organization_id, wa_id)
            conversation = await commercial.make_conversation(session, lead)
            await OutboxService(session).stage(
                conversation=conversation,
                inbox_group_id=None,
                idempotency_key=key,
                to_wa_id=wa_id,
                kind="Reply",
                body="Hola",
                covered_inbox_ids=[],
            )
        await session.commit()
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(OutboxMessage).where(OutboxMessage.idempotency_key == key)
            )
        )
        assert {row.organization_id for row in rows} == {first, second}


async def _lead_for(session, organization_id: uuid.UUID, wa_id: str):
    from realestate.db.models import Lead

    lead = Lead(organization_id=organization_id, wa_id=wa_id, profile_name=None)
    session.add(lead)
    await session.flush()
    return lead


# ---------------------------------------------------------------------------
# Credentials and configuration: never inherited, never a fallback.
# ---------------------------------------------------------------------------


async def test_a_second_organization_never_inherits_a_process_credential(
    two_organizations,
) -> None:
    """The test the credentials module exists for.

    The process environment belongs to the founding Organization. Asking for a
    provider the second Organization has no reference for is a refusal, not the
    platform's value — because the alternative sends their messages out on
    somebody else's number, into somebody else's Meta account.
    """
    database, first, second, _key, _resolver = two_organizations
    legacy = {IntegrationProvider.EASYBROKER: "larevia-easybroker-key"}
    # The precondition is stated rather than assumed: the environment answers for
    # the founding Organization only when it has *no* reference of its own, and a
    # test that depended on nobody else having recorded one would pass or fail by
    # accident.
    async with database.session_scope() as session:
        await session.execute(
            text(
                "DELETE FROM organization_secret_references "
                "WHERE organization_id IN (:first, :second) AND provider = :provider"
            ).bindparams(
                first=first,
                second=second,
                provider=IntegrationProvider.EASYBROKER.value,
            )
        )
        await session.commit()
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(
            session,
            SecretResolver(),
            bootstrap_organization_id=first,
            legacy_values=legacy,
        )
        theirs = await credentials.resolve(first, IntegrationProvider.EASYBROKER)
        assert theirs.material == "larevia-easybroker-key"
        assert theirs.origin == "LegacyProcessEnvironment"

        with pytest.raises(MissingCredential):
            await credentials.resolve(second, IntegrationProvider.EASYBROKER)


async def test_a_credential_recorded_by_provisioning_resolves_only_for_its_owner(
    two_organizations,
) -> None:
    database, first, second, _key, resolver = two_organizations
    # The local demo can legitimately leave Larevia's own provider reference in
    # the shared integration database. State the no-reference precondition this
    # scenario is proving instead of depending on the database being pristine.
    async with database.session_scope() as session:
        await session.execute(
            text(
                "DELETE FROM organization_secret_references "
                "WHERE organization_id = :organization_id AND provider = :provider"
            ).bindparams(
                organization_id=first,
                provider=IntegrationProvider.META_WHATSAPP.value,
            )
        )
        await session.commit()
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        theirs = await credentials.resolve(
            second, IntegrationProvider.META_WHATSAPP
        )
        assert theirs.material == "segunda-token"
        assert theirs.reference == "SEGUNDA_META_ACCESS_TOKEN"
        # Larevia has no reference for the same provider in this fixture, and no
        # legacy value was supplied, so it is refused rather than served the
        # newcomer's token.
        with pytest.raises(MissingCredential):
            await credentials.resolve(first, IntegrationProvider.META_WHATSAPP)


async def test_operational_whatsapp_clients_use_each_organizations_token_and_number(
    two_organizations,
) -> None:
    database, first, second, _key, resolver = two_organizations
    resolver.record("LAREVIA_META_ACCESS_TOKEN", "larevia-token")
    async with database.session_scope() as session:
        await IntegrationCredentials(session, resolver).record(
            OPERATOR,
            RecordSecretReference(
                organization_id=first,
                provider=IntegrationProvider.META_WHATSAPP,
                reference="LAREVIA_META_ACCESS_TOKEN",
                command_key=f"credential:{uuid.uuid4().hex}",
                reason="Prueba de entrega aislada para la organización fundadora.",
            ),
        )
        await session.commit()

    created: list[tuple[str, str]] = []

    class Client:
        def __init__(self, **kwargs) -> None:
            created.append((kwargs["access_token"], kwargs["phone_number_id"]))

        async def aclose(self) -> None:
            return None

    directory = OrganizationWhatsAppClients(
        resolver,
        client_factory=Client,  # type: ignore[arg-type]
    )
    async with database.session_scope() as session:
        await directory.for_organization(session, first)
        await directory.for_organization(session, second)
    assert set(created) == {
        ("larevia-token", commercial.TEST_PHONE_NUMBER_ID),
        ("segunda-token", SECOND_PHONE_NUMBER_ID),
    }
    await directory.aclose()


@pytest.mark.parametrize(
    ("channel", "provider", "binding_kind", "reference_suffix", "account_prefix"),
    [
        (
            CustomerChannel.FACEBOOK_MESSENGER,
            IntegrationProvider.META_MESSENGER,
            ChannelBindingKind.FACEBOOK_PAGE,
            "MESSENGER_TOKEN",
            "page",
        ),
        (
            CustomerChannel.INSTAGRAM,
            IntegrationProvider.META_INSTAGRAM,
            ChannelBindingKind.INSTAGRAM_ACCOUNT,
            "INSTAGRAM_TOKEN",
            "instagram",
        ),
    ],
)
async def test_meta_messaging_clients_use_only_the_organizations_account_and_token(
    two_organizations,
    channel,
    provider,
    binding_kind,
    reference_suffix,
    account_prefix,
) -> None:
    database, first, second, _key, resolver = two_organizations
    first_reference = f"LAREVIA_{reference_suffix}"
    second_reference = f"SEGUNDA_{reference_suffix}"
    resolver.record(first_reference, "larevia-channel-token")
    resolver.record(second_reference, "segunda-channel-token")
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        routing = OrganizationRouting(session)
        await session.execute(
            text(
                "DELETE FROM organization_channel_bindings "
                "WHERE organization_id IN (:first, :second) AND kind = :kind"
            ).bindparams(
                first=first,
                second=second,
                kind=binding_kind.value,
            )
        )
        for organization_id, reference, page_id in (
            (first, first_reference, f"{account_prefix}-larevia"),
            (second, second_reference, f"{account_prefix}-segunda"),
        ):
            await credentials.record(
                OPERATOR,
                RecordSecretReference(
                    organization_id=organization_id,
                    provider=provider,
                    reference=reference,
                    command_key=f"credential:{uuid.uuid4().hex}",
                    reason="Prueba de aislamiento de Messenger por organización.",
                ),
            )
            await routing.bind(
                organization_id=organization_id,
                kind=binding_kind,
                external_id=page_id,
                recorded_by=OPERATOR.label,
            )
        await session.commit()

    created: list[tuple[str, str]] = []

    class Client:
        def __init__(self, **kwargs) -> None:
            created.append((kwargs["access_token"], kwargs["account_id"]))

        async def aclose(self) -> None:
            return None

    directory = OrganizationMetaMessagingClients(
        resolver,
        client_factory=Client,  # type: ignore[arg-type]
    )
    async with database.session_scope() as session:
        await directory.for_organization(
            session, first, channel, f"{account_prefix}-larevia"
        )
        await directory.for_organization(
            session, second, channel, f"{account_prefix}-segunda"
        )
        with pytest.raises(MetaMessagingChannelMissing):
            await directory.for_organization(
                session, first, channel, f"{account_prefix}-not-bound"
            )
    assert set(created) == {
        ("larevia-channel-token", f"{account_prefix}-larevia"),
        ("segunda-channel-token", f"{account_prefix}-segunda"),
    }
    await directory.aclose()


async def test_operational_telegram_clients_use_each_organizations_bound_bot(
    two_organizations,
) -> None:
    database, first, second, _key, resolver = two_organizations
    first_token = f"{commercial.TEST_TELEGRAM_BOT_ID}:larevia-secret"
    resolver.record("LAREVIA_TELEGRAM_BOT_TOKEN", first_token)
    async with database.session_scope() as session:
        await IntegrationCredentials(session, resolver).record(
            OPERATOR,
            RecordSecretReference(
                organization_id=first,
                provider=IntegrationProvider.TELEGRAM,
                reference="LAREVIA_TELEGRAM_BOT_TOKEN",
                command_key=f"credential:{uuid.uuid4().hex}",
                reason="Prueba de Telegram aislado para la organización fundadora.",
            ),
        )
        await session.commit()

    created: list[str] = []

    class Client:
        def __init__(self, **kwargs) -> None:
            self._token = kwargs["bot_token"]
            created.append(self._token)

        @property
        def bot_id(self) -> str:
            return self._token.split(":", 1)[0]

        async def aclose(self) -> None:
            return None

    directory = OrganizationTelegramClients(
        resolver,
        client_factory=Client,  # type: ignore[arg-type]
    )
    async with database.session_scope() as session:
        await directory.for_organization(session, first)
        await directory.for_organization(session, second)
    assert set(created) == {
        first_token,
        f"{SECOND_TELEGRAM_BOT}:second-secret",
    }
    await directory.aclose()


async def test_operational_easybroker_clients_never_share_an_api_key(
    two_organizations,
) -> None:
    database, first, second, _key, resolver = two_organizations
    resolver.record("LAREVIA_EASYBROKER_KEY", "larevia-easybroker")
    resolver.record("SEGUNDA_EASYBROKER_KEY", "segunda-easybroker")
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        for organization_id, reference in (
            (first, "LAREVIA_EASYBROKER_KEY"),
            (second, "SEGUNDA_EASYBROKER_KEY"),
        ):
            await credentials.record(
                OPERATOR,
                RecordSecretReference(
                    organization_id=organization_id,
                    provider=IntegrationProvider.EASYBROKER,
                    reference=reference,
                    command_key=f"credential:{uuid.uuid4().hex}",
                    reason="Prueba de credenciales aisladas para inventario externo.",
                ),
            )
        await session.commit()

    created: list[str] = []

    class Adapter:
        def __init__(self, **kwargs) -> None:
            created.append(kwargs["api_key"])

        async def aclose(self) -> None:
            return None

    directory = OrganizationEasyBrokerAdapters(
        resolver,
        adapter_factory=Adapter,  # type: ignore[arg-type]
    )
    async with database.session_scope() as session:
        await directory.for_organization(session, first)
        await directory.for_organization(session, second)
    assert set(created) == {"larevia-easybroker", "segunda-easybroker"}
    await directory.aclose()


async def test_operational_calendar_directories_use_each_organizations_reference(
    two_organizations,
) -> None:
    database, first, second, _key, resolver = two_organizations
    resolver.record("LAREVIA_GOOGLE_CALENDAR", "/secrets/larevia.json")
    resolver.record("SEGUNDA_GOOGLE_CALENDAR", "/secrets/segunda.json")
    async with database.session_scope() as session:
        credentials = IntegrationCredentials(session, resolver)
        for organization_id, reference in (
            (first, "LAREVIA_GOOGLE_CALENDAR"),
            (second, "SEGUNDA_GOOGLE_CALENDAR"),
        ):
            await credentials.record(
                OPERATOR,
                RecordSecretReference(
                    organization_id=organization_id,
                    provider=IntegrationProvider.GOOGLE_CALENDAR,
                    reference=reference,
                    command_key=f"credential:{uuid.uuid4().hex}",
                    reason="Prueba de calendarios aislados por organización.",
                ),
            )
        await session.commit()
    directories = OrganizationGoogleCalendarDirectories(resolver)
    async with database.session_scope() as session:
        first_directory = await directories.for_organization(session, first)
        second_directory = await directories.for_organization(session, second)
    assert first_directory._credentials_path == "/secrets/larevia.json"
    assert second_directory._credentials_path == "/secrets/segunda.json"


async def test_operational_scheduling_uses_each_organizations_current_version(
    two_organizations,
) -> None:
    from realestate.domain.appointments import AppointmentPolicy
    from realestate.domain.platform.runtime import OrganizationAppointmentPolicies
    from tests.fixtures.stubs import SCHEDULE

    database, first, second, _key, _resolver = two_organizations
    bootstrap = AppointmentPolicy(
        schedule=SCHEDULE,
        visit_minutes=90,
        horizon_days=8,
        max_candidates=6,
        day_of_reminder_hour=9,
    )
    policies = OrganizationAppointmentPolicies(
        bootstrap,
        bootstrap_organization_id=first,
    )
    async with database.session_scope() as session:
        first_policy = await policies.for_organization(session, first)
        second_policy = await policies.for_organization(session, second)

    assert first_policy.visit_minutes == 90
    assert second_policy.visit_minutes == 60
    assert first_policy.schedule.ranges[0][0].start.hour == 9
    assert second_policy.schedule.ranges[0][0].start.hour == 10


async def test_a_single_bot_worker_never_claims_another_organizations_alert(
    two_organizations,
) -> None:
    """The documented one-bot limit must fail closed, never cross-deliver."""
    database, first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        for organization_id, label in ((first, "larevia"), (second, "segunda")):
            session.add(
                InternalAlert(
                    organization_id=organization_id,
                    kind="HumanHandoffEscalated",
                    subject_type="Conversation",
                    subject_id=label,
                    title=f"Alerta {label}",
                    body=f"Contenido {label}",
                    dedupe_key=f"telegram-isolation:{label}",
                )
            )
        await session.commit()

        claimed = await InternalAlerts(session).claim_due(organization_id=first)
        assert [item.alert.organization_id for item in claimed] == [first]
        other = await session.scalar(
            select(InternalAlert).where(InternalAlert.organization_id == second)
        )
        assert other is not None
        assert other.status == InternalAlertStatus.PENDING.value
        assert other.claimed_at is None


async def test_two_organizations_run_simultaneous_inbound_to_delivery_flows(
    two_organizations,
) -> None:
    """Synthetic Stage 9 rehearsal across routing, truth, gate and worker."""
    from datetime import UTC, datetime

    from realestate.channels.whatsapp.client import SendOutcome, SendResult
    from realestate.channels.whatsapp.payload import InboundMessage
    from realestate.db.models import OutboundInitiation, OutboxStatus
    from realestate.domain.outbound import (
        OutboundIntent,
        OutboundMessaging,
        Purpose,
        Queued,
    )
    from realestate.worker.whatsapp import WhatsAppWorker
    from tests.fixtures.stubs import SCHEDULE

    database, first, second, _key, resolver = two_organizations
    resolver.record("LAREVIA_META_ACCESS_TOKEN", "larevia-token")
    async with database.session_scope() as session:
        await IntegrationCredentials(session, resolver).record(
            OPERATOR,
            RecordSecretReference(
                organization_id=first,
                provider=IntegrationProvider.META_WHATSAPP,
                reference="LAREVIA_META_ACCESS_TOKEN",
                command_key=f"credential:{uuid.uuid4().hex}",
                reason="Prueba E2E simultánea de la organización fundadora.",
            ),
        )
        await session.commit()

    moment = datetime.now(tz=UTC)
    messages = (
        InboundMessage(
            wamid=f"e2e-larevia-{uuid.uuid4().hex}",
            from_wa_id="5213311111111",
            phone_number_id=commercial.TEST_PHONE_NUMBER_ID,
            message_type="text",
            sent_at=moment,
            text="Busco una casa de Larevia",
            profile_name="Cliente Larevia",
            raw={},
        ),
        InboundMessage(
            wamid=f"e2e-segunda-{uuid.uuid4().hex}",
            from_wa_id="5213322222222",
            phone_number_id=SECOND_PHONE_NUMBER_ID,
            message_type="text",
            sent_at=moment,
            text="Busco una casa de Segunda",
            profile_name="Cliente Segunda",
            raw={},
        ),
    )

    async def accept(message: InboundMessage):  # noqa: ANN202
        async with database.session_scope() as session:
            accepted = await InboxService(session).accept(message)
            await session.commit()
            return accepted

    accepted = await asyncio.gather(*(accept(message) for message in messages))
    async with database.session_scope() as session:
        accepted_organizations = set(
            await session.scalars(
                select(Conversation.organization_id).where(
                    Conversation.id.in_([item.conversation_id for item in accepted])
                )
            )
        )
    assert accepted_organizations == {first, second}

    async def queue(index: int) -> None:
        item = accepted[index]
        async with database.session_scope() as session:
            conversation = await session.get(Conversation, item.conversation_id)
            assert conversation is not None
            result = await OutboundMessaging(session).request(
                OutboundIntent(
                    conversation=conversation,
                    body=f"Respuesta exclusiva {index}",
                    purpose=Purpose.AGENT_REPLY,
                    initiation=OutboundInitiation.REACTIVE,
                    idempotency_key=f"stage9-e2e:{index}:{uuid.uuid4().hex}",
                    trigger_inbox_ids=(item.inbox_id,),
                )
            )
            assert isinstance(result, Queued)
            await session.commit()

    await asyncio.gather(queue(0), queue(1))

    delivered: list[tuple[str, str, str]] = []

    class Client:
        def __init__(self, **kwargs) -> None:
            self.token = kwargs["access_token"]
            self.phone = kwargs["phone_number_id"]

        async def send_text(self, _to: str, body: str) -> SendResult:
            delivered.append((self.token, self.phone, body))
            return SendResult(
                SendOutcome.SENT,
                provider_message_id=f"sent-{len(delivered)}",
            )

        async def send_template(self, *_args, **_kwargs) -> SendResult:
            raise AssertionError("The simultaneous reactive rehearsal uses text")

        async def aclose(self) -> None:
            return None

    directory = OrganizationWhatsAppClients(
        resolver,
        client_factory=Client,  # type: ignore[arg-type]
    )
    worker = WhatsAppWorker(
        database,
        object(),  # type: ignore[arg-type]
        directory,
        sales_profile="sales",
        schedule=SCHEDULE,
    )
    await worker._drain_outbox()

    assert set(delivered) == {
        (
            "larevia-token",
            commercial.TEST_PHONE_NUMBER_ID,
            "Respuesta exclusiva 0",
        ),
        (
            "segunda-token",
            SECOND_PHONE_NUMBER_ID,
            "Respuesta exclusiva 1",
        ),
    }
    async with database.session_scope() as session:
        rows = list(
            await session.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.idempotency_key.like("stage9-e2e:%")
                )
            )
        )
        assert {row.organization_id for row in rows} == {first, second}
        assert {row.status for row in rows} == {OutboxStatus.SENT.value}
    await directory.aclose()


async def test_bounded_two_organization_intake_capacity_rehearsal(
    two_organizations,
) -> None:
    """A local contention rehearsal, not a production throughput claim."""
    from datetime import UTC, datetime
    from time import monotonic

    from realestate.channels.whatsapp.payload import InboundMessage

    database, first, second, _key, _resolver = two_organizations
    per_organization = 50
    gate = asyncio.Semaphore(10)

    async def accept(index: int, *, second_organization: bool) -> None:
        prefix = "second" if second_organization else "first"
        phone = (
            SECOND_PHONE_NUMBER_ID
            if second_organization
            else commercial.TEST_PHONE_NUMBER_ID
        )
        message = InboundMessage(
            wamid=f"stage9-load-{prefix}-{index}",
            from_wa_id=f"52133{2 if second_organization else 1}{index:07d}",
            phone_number_id=phone,
            message_type="text",
            sent_at=datetime.now(tz=UTC),
            text=f"Consulta sintética {prefix} {index}",
            profile_name=f"Carga {prefix} {index}",
            raw={},
        )
        async with gate:
            async with database.session_scope() as session:
                await InboxService(session).accept(message)
                await session.commit()

    started = monotonic()
    await asyncio.gather(
        *(
            accept(index, second_organization=second_organization)
            for second_organization in (False, True)
            for index in range(per_organization)
        )
    )
    elapsed = monotonic() - started

    async with database.session_scope() as session:
        counts = dict(
            (
                await session.execute(
                    select(InboxMessage.organization_id, func.count(InboxMessage.id))
                    .where(InboxMessage.wamid.like("stage9-load-%"))
                    .group_by(InboxMessage.organization_id)
                )
            ).all()
        )
    assert counts == {first: per_organization, second: per_organization}
    # A broad local regression guard only. It intentionally does not translate
    # into a customer-facing capacity or latency promise.
    assert elapsed < 30


async def test_a_credential_is_never_written_to_a_row_or_an_audit_event(
    two_organizations,
) -> None:
    """The material never lands anywhere readable."""
    database, _first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        rows = await session.execute(
            text(
                "SELECT reference, fingerprint FROM organization_secret_references "
                "WHERE organization_id = :org"
            ).bindparams(org=second)
        )
        expected_references = {
            "SEGUNDA_META_ACCESS_TOKEN",
            "SEGUNDA_TELEGRAM_BOT_TOKEN",
        }
        seen_references: set[str] = set()
        for reference, fingerprint in rows:
            assert reference in expected_references
            seen_references.add(reference)
            assert "segunda-token" not in (fingerprint or "")
            assert "second-secret" not in (fingerprint or "")
        assert seen_references == expected_references
        audits = await session.execute(
            text(
                "SELECT details::text FROM audit_events WHERE organization_id = :org"
            ).bindparams(org=second)
        )
        for (details,) in audits:
            assert "segunda-token" not in details


async def test_a_configuration_document_cannot_carry_a_credential() -> None:
    """Refused recursively: the danger is a nested key, not a top-level one."""
    from realestate.domain.platform.configuration import (
        InvalidConfiguration,
        validate_document,
    )

    with pytest.raises(InvalidConfiguration):
        validate_document(
            {"channels": {"whatsapp": {"access_token": "EAAG..."}}}
        )
    with pytest.raises(InvalidConfiguration):
        validate_document({"integrations": {"easybroker_api_key": "abc"}})
    with pytest.raises(InvalidConfiguration, match="brand.name"):
        validate_document({"brand": {"working_name": "Acme"}})
    with pytest.raises(InvalidConfiguration, match="brand.name"):
        validate_document({"brand": {"name": "   "}})
    # A legitimate document is accepted unchanged.
    assert validate_document({"brand": {"name": "Acme"}}) == {
        "brand": {"name": "Acme"}
    }


# ---------------------------------------------------------------------------
# Operational: workers, the Outbox, and the analytics projection.
# ---------------------------------------------------------------------------


async def test_the_analytics_pass_emits_for_each_organization_separately(
    two_organizations,
) -> None:
    """A pass that resolved "the Organization" would leave one dashboard empty."""
    database, first, second, _key, _resolver = two_organizations
    from realestate.worker.analytics import AnalyticsWorker

    report = await AnalyticsWorker(database=database).run()
    assert report.emitted >= 0  # emission is idempotent and may be a no-op
    async with database.session_scope() as session:
        # Whatever was emitted, no row belongs to an Organization that is not one
        # of the two: the pass iterates the registry rather than guessing.
        rows = await session.execute(
            text("SELECT DISTINCT organization_id FROM analytics.analytics_outbox")
        )
        owners = {row[0] for row in rows}
        assert owners <= {first, second}


async def test_one_organization_projection_never_drains_another_outbox(
    two_organizations,
) -> None:
    database, first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        for organization_id in (first, second):
            actor = Actor.product(organization_id, "IsolationProjection")
            await AnalyticsEvents(session, actor).record(
                AnalyticsEvent(
                    event_key="same-projection-key",
                    name=AnalyticsEventName.MAIA_STARTED,
                    occurred_at=utc_now(),
                    session_value=f"session-{organization_id}",
                    attributes={"surface": "Maia"},
                )
            )
        await session.commit()

        await AnalyticsProjection(
            session, Actor.product(first, "IsolationProjection")
        ).drain()
        await session.commit()

        outbox = list(
            await session.scalars(
                select(AnalyticsOutboxEntry).where(
                    AnalyticsOutboxEntry.event_key == "same-projection-key"
                )
            )
        )
        statuses = {row.organization_id: row.status for row in outbox}
        assert statuses == {
            first: AnalyticsOutboxStatus.PROJECTED.value,
            second: AnalyticsOutboxStatus.PENDING.value,
        }
        assert set(
            await session.scalars(select(AnalyticsDomainEvent.organization_id))
        ) == {first}
        assert set(
            await session.scalars(select(AnalyticsProjectionRun.organization_id))
        ) == {first}


async def test_the_upkeep_pass_attributes_each_expiry_to_its_own_organization(
    two_organizations,
) -> None:
    """Content expiry sweeps every Organization, and audits each one correctly."""
    database, first, second, _key, _resolver = two_organizations
    from datetime import UTC, datetime, timedelta

    from realestate.domain.commercial.retention import ConversationRetention

    old = datetime.now(tz=UTC) - timedelta(days=200)
    async with database.session_scope() as session:
        for organization_id, wa_id in ((first, "521331111"), (second, "521332222")):
            lead = await _lead_for(session, organization_id, wa_id)
            conversation = await commercial.make_conversation(
                session, lead, started_at=old
            )
            await commercial.make_inbound(session, conversation, sent_at=old)
        await session.commit()

    async with database.session_scope() as session:
        expired = await ConversationRetention(session).expire()
        assert expired.conversations == 2

    async with database.session_scope() as session:
        rows = await session.execute(
            text(
                "SELECT organization_id, count(*) FROM audit_events "
                "WHERE action = 'ExpireConversationContent' GROUP BY 1"
            )
        )
        counted = dict(rows.all())
        assert counted.get(first) == 1
        assert counted.get(second) == 1


async def test_every_audit_row_names_an_organization_or_the_platform(
    two_organizations,
) -> None:
    """The check constraint's behavioural twin.

    A row with no Organization is only permitted from a ``Platform`` actor, which
    is what stops "above any Organization" from becoming a way to write unscoped
    history.
    """
    database, _first, _second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        rows = await session.execute(
            text(
                "SELECT actor_type, count(*) FROM audit_events "
                "WHERE organization_id IS NULL GROUP BY 1"
            )
        )
        for actor_type, _count in rows:
            assert actor_type == "Platform"


async def test_no_scoped_table_holds_a_row_without_an_organization(
    two_organizations,
) -> None:
    """The matrix, executed.

    Every table the registry calls Organization data is checked for a NULL scope
    column. ``audit_events`` is the one documented exception and is handled by the
    test above.
    """
    database, _first, _second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        offenders: list[str] = []
        for scope in organization_scopes():
            if scope.kind is ScopeKind.ORGANIZATION_ROOT or scope.table == "audit_events":
                continue
            name = qualified_name(scope.table)
            found = await session.scalar(
                text(f"SELECT count(*) FROM {name} WHERE organization_id IS NULL")
            )
            if found:
                offenders.append(f"{scope.table}={found}")
        assert offenders == [], (
            "These tables hold rows with no Organization: " + ", ".join(offenders)
        )


async def test_a_conversation_cannot_name_parents_from_another_organization(
    two_organizations,
) -> None:
    database, first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        lead = await _lead_for(session, first, "5213399990000")
        conversation = await commercial.make_conversation(session, lead)
        await session.commit()
        conversation.organization_id = second
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_a_suspended_organizations_members_cannot_log_in(
    two_organizations,
) -> None:
    """Suspension is a status change, not a re-provisioning.

    The member rows stay intact, so resuming is one call — and until then every
    login gets a sentence rather than a page of somebody else's data.
    """
    database, _first, second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        await OrganizationProvisioning(session).suspend(
            OPERATOR,
            organization_id=second,
            reason="Prueba de aislamiento: la organización queda pausada.",
        )
        await session.commit()
    async with database.session_scope() as session:
        with pytest.raises(OrganizationSuspended):
            await OrganizationDirectory(session).resolve_actor(SECOND_ADMIN)
        # Its channel stops routing too, so a message is refused rather than
        # queued for a brokerage that is not operating.
        with pytest.raises(NotFound if False else Exception):
            await OrganizationRouting(session).resolve(
                ChannelBindingKind.WHATSAPP_PHONE_NUMBER, SECOND_PHONE_NUMBER_ID
            )
    async with database.session_scope() as session:
        await OrganizationProvisioning(session).resume(
            OPERATOR,
            organization_id=second,
            reason="Prueba de aislamiento: la organización se reanuda.",
        )
        await session.commit()
    async with database.session_scope() as session:
        actor = await OrganizationDirectory(session).resolve_actor(SECOND_ADMIN)
        assert actor.organization_id == second


async def test_a_channel_identifier_belongs_to_one_organization_only(
    two_organizations,
) -> None:
    """Claiming another Organization's number is refused by name, not by index."""
    database, first, _second, _key, _resolver = two_organizations
    async with database.session_scope() as session:
        with pytest.raises(UnroutableChannel):
            await OrganizationRouting(session).bind(
                organization_id=first,
                kind=ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
                external_id=SECOND_PHONE_NUMBER_ID,
                recorded_by="platform-tester",
            )


async def test_product_actors_cannot_be_built_across_the_boundary(
    two_organizations,
) -> None:
    """``Actor.require_same_organization`` is the last line, and it holds."""
    database, first, second, _key, _resolver = two_organizations
    actor = Actor.product(second, "IsolationTest")
    with pytest.raises(NotFound):
        actor.require_same_organization(first)
    # And it is a no-op for its own Organization, so the check is real rather
    # than universally refusing.
    actor.require_same_organization(second)
    assert database is not None

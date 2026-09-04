"""Keeping the founding Organization working after the platform arrives.

Stage 9 stops the product from resolving "the Organization" by slug. Every inbound
path now looks up a channel binding, and an unbound identifier is refused. That is
the correct behaviour and it would break the existing local installation on the
first restart: Larevia's WhatsApp number, Telegram bot and public hostname live in
``.env``, and nothing has ever written them into a binding table.

This module is that write, and it is deliberately shaped like the directory
reconciliation ADR-0047 already established:

* **idempotent** — a second run with the same environment changes nothing and
  logs nothing;
* **bounded to one Organization** — the founding one, named by
  ``PLATFORM_BOOTSTRAP_ORGANIZATION_SLUG``. It cannot bind anything for anybody
  else, so it is not a back door into a provisioned Organization's channels;
* **non-destructive** — it never retires a binding an operator created, because
  the absence of an environment variable is not an instruction (the same rule the
  member reconciliation follows);
* **best-effort at startup** — an unmigrated or unreachable database logs and
  continues, so an operator can still reach ``/health`` and read why.

It also records the founding Organization's provider credentials as *references*
pointing at the environment variable names they already use. That turns the
Stage 0 credential story into the Stage 9 one without moving a single secret: the
value stays exactly where it is, and Product now knows the name it lives under.

The whole module is a migration aid with a clear end. Once the founding
Organization has been provisioned like any other — bindings recorded by an
operator, references pointing at a real secret store — nothing here does anything,
and the environment-variable path can be deleted.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.db.models import (
    ChannelBindingKind,
    IntegrationProvider,
    Organization,
    OrganizationChannelBinding,
)
from realestate.domain.audit import record_audit
from realestate.domain.clock import utc_now
from realestate.domain.platform.authority import PlatformOperator
from realestate.domain.platform.credentials import (
    IntegrationCredentials,
    RecordSecretReference,
    SecretResolver,
)
from realestate.domain.platform.routing import OrganizationRouting

logger = logging.getLogger(__name__)

#: Who the bootstrap writes history as. A platform actor, because binding the
#: founding Organization's channels is a platform act performed before anybody
#: could have authorised it from inside the Organization.
BOOTSTRAP_OPERATOR = PlatformOperator(
    label="Platform:Bootstrap", display_name="Arranque de la plataforma"
)


@dataclass(frozen=True)
class BootstrapEnvironment:
    """The founding Organization's identifiers and credential names.

    Assembled from :class:`~realestate.config.Settings` by the caller rather
    than read here, so this module has no dependency on configuration and the
    suites can drive it with values of their own.
    """

    slug: str
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    facebook_page_id: str = ""
    instagram_account_id: str = ""
    telegram_bot_id: str = ""
    public_site_host: str = ""
    #: ``provider -> environment variable name``. The *names*, never the values.
    credential_references: dict[IntegrationProvider, str] = field(
        default_factory=dict
    )

    @property
    def bindings(self) -> tuple[tuple[ChannelBindingKind, str], ...]:
        return tuple(
            (kind, value)
            for kind, value in (
                (
                    ChannelBindingKind.WHATSAPP_PHONE_NUMBER,
                    self.whatsapp_phone_number_id,
                ),
                (
                    ChannelBindingKind.WHATSAPP_BUSINESS_ACCOUNT,
                    self.whatsapp_business_account_id,
                ),
                (ChannelBindingKind.FACEBOOK_PAGE, self.facebook_page_id),
                (ChannelBindingKind.INSTAGRAM_ACCOUNT, self.instagram_account_id),
                (ChannelBindingKind.TELEGRAM_BOT, self.telegram_bot_id),
                (ChannelBindingKind.PUBLIC_SITE_HOST, self.public_site_host),
            )
            if value.strip()
        )


@dataclass(frozen=True)
class BootstrapReport:
    """What the reconciliation changed. Logged at startup, asserted in tests."""

    organization_id: uuid.UUID | None = None
    bound: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.bound or self.references)


class PlatformBootstrap:
    """Bind the founding Organization's channels and name its credentials.

    Hides: which environment values map to which binding kind, the idempotency,
    the conflict when another Organization already holds an identifier, and the
    fact that none of it applies to anybody but the founding Organization.
    """

    def __init__(
        self, session: AsyncSession, resolver: SecretResolver | None = None
    ) -> None:
        self._session = session
        self._resolver = resolver or SecretResolver()

    async def organization_id(self, slug: str) -> uuid.UUID | None:
        """The founding Organization's id, or ``None`` if it does not exist.

        ``None`` is a legitimate answer: an installation provisioned from scratch
        has no founding Organization, and on that installation nothing here — nor
        any environment fallback anywhere else — applies to anybody.
        """
        found: uuid.UUID | None = await self._session.scalar(
            select(Organization.id).where(Organization.slug == slug)
        )
        return found

    async def reconcile(
        self, environment: BootstrapEnvironment, *, at: datetime | None = None
    ) -> BootstrapReport:
        """Make the founding Organization's bindings match the process. Commits.

        A binding another Organization already holds is *skipped and reported*,
        not stolen. That case means somebody pointed the environment at a number
        a provisioned Organization owns, and quietly reassigning it would send
        their customers' messages to the wrong brokerage.
        """
        moment = at or utc_now()
        organization_id = await self.organization_id(environment.slug)
        if organization_id is None:
            logger.info(
                "No founding Organization %r on this installation; nothing to "
                "bootstrap",
                environment.slug,
            )
            return BootstrapReport()

        routing = OrganizationRouting(self._session)
        bound: list[str] = []
        skipped: list[str] = []
        for kind, external_id in environment.bindings:
            held: OrganizationChannelBinding | None = await self._session.scalar(
                select(OrganizationChannelBinding)
                .where(OrganizationChannelBinding.kind == kind.value)
                .where(OrganizationChannelBinding.external_id == external_id.strip())
                .where(OrganizationChannelBinding.state == "Active")
            )
            if held is not None:
                if held.organization_id != organization_id:
                    skipped.append(f"{kind.value}:{external_id}")
                    logger.error(
                        "The configured %s %r belongs to a different "
                        "Organization; leaving it alone. Fix the environment or "
                        "retire the binding.",
                        kind.value,
                        external_id,
                    )
                continue
            await routing.bind(
                organization_id=organization_id,
                kind=kind,
                external_id=external_id,
                recorded_by=BOOTSTRAP_OPERATOR.label,
            )
            bound.append(f"{kind.value}:{external_id}")

        credentials = IntegrationCredentials(self._session, self._resolver)
        named: list[str] = []
        for provider, reference in environment.credential_references.items():
            if not reference.strip():
                continue
            existing = await credentials.try_resolve(organization_id, provider)
            if existing is not None and existing.origin.startswith("SecretReference"):
                continue
            await credentials.record(
                BOOTSTRAP_OPERATOR,
                RecordSecretReference(
                    organization_id=organization_id,
                    provider=provider,
                    reference=reference,
                    command_key=f"bootstrap:credential:{provider.value}",
                    reason=(
                        "Arranque de la plataforma: se registra el nombre de la "
                        "variable de entorno que ya contiene esta credencial."
                    ),
                ),
                at=moment,
            )
            named.append(f"{provider.value}:{reference}")

        if bound or named:
            await record_audit(
                self._session,
                organization_id=organization_id,
                actor_type=BOOTSTRAP_OPERATOR.actor_type,
                actor_id=BOOTSTRAP_OPERATOR.label,
                action="BootstrapPlatformBindings",
                subject_type="Organization",
                subject_id=str(organization_id),
                details={
                    "bound": bound,
                    "credential_references": named,
                    "skipped": skipped,
                },
                commit=False,
            )
        await self._session.commit()
        return BootstrapReport(
            organization_id=organization_id,
            bound=tuple(bound),
            references=tuple(named),
            skipped=tuple(skipped),
        )

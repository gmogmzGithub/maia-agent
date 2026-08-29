"""Organization-scoped clients for provider integrations outside Meta."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from realestate.channels.telegram.client import TelegramClient
from realestate.db.models import IntegrationProvider
from realestate.db.models import (
    ChannelBindingKind,
    ChannelBindingState,
    MemberRole,
    OrganizationChannelBinding,
    OrganizationMember,
)
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.external_inventory.easybroker import EasyBrokerAdapter
from realestate.domain.platform.configuration import OrganizationConfiguration
from realestate.domain.platform.credentials import IntegrationCredentials, SecretResolver
from realestate.domain.scheduling.calendars import GoogleCalendarDirectory


class TelegramChannelMissing(CommercialError):
    message = (
        "Esta organización no tiene exactamente un bot de Telegram activo. "
        "Asígnalo antes de iniciar el canal administrativo."
    )


class TelegramBindingMismatch(CommercialError):
    message = (
        "El token de Telegram no pertenece al bot asignado a esta organización."
    )


class OrganizationTelegramClients:
    """Resolve one Organization's bot token and verify its bound public id."""

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_bot_token: str = "",
        base_url: str = "https://api.telegram.org",
        client_factory: Callable[..., TelegramClient] = TelegramClient,
    ) -> None:
        self._resolver = resolver
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values: Mapping[IntegrationProvider, str] = {
            IntegrationProvider.TELEGRAM: legacy_bot_token
        }
        self._base_url = base_url
        self._client_factory = client_factory
        self._clients: dict[uuid.UUID, tuple[str, str, TelegramClient]] = {}

    async def for_organization(
        self, session: AsyncSession, organization_id: uuid.UUID
    ) -> TelegramClient:
        credential = await IntegrationCredentials(
            session,
            self._resolver,
            bootstrap_organization_id=self._bootstrap_organization_id,
            legacy_values=self._legacy_values,
        ).resolve(organization_id, IntegrationProvider.TELEGRAM)
        bindings = list(
            await session.scalars(
                select(OrganizationChannelBinding)
                .where(OrganizationChannelBinding.organization_id == organization_id)
                .where(
                    OrganizationChannelBinding.kind
                    == ChannelBindingKind.TELEGRAM_BOT.value
                )
                .where(
                    OrganizationChannelBinding.state
                    == ChannelBindingState.ACTIVE.value
                )
            )
        )
        if len(bindings) != 1:
            raise TelegramChannelMissing()
        bot_id = bindings[0].external_id
        cached = self._clients.get(organization_id)
        if cached is not None:
            fingerprint, cached_bot, client = cached
            if fingerprint == credential.fingerprint and cached_bot == bot_id:
                return client
            await client.aclose()
        client = self._client_factory(
            bot_token=credential.material,
            base_url=self._base_url,
        )
        if client.bot_id != bot_id:
            await client.aclose()
            raise TelegramBindingMismatch()
        self._clients[organization_id] = (
            credential.fingerprint,
            bot_id,
            client,
        )
        return client

    async def aclose(self) -> None:
        for _fingerprint, _bot, client in self._clients.values():
            await client.aclose()
        self._clients.clear()


async def organization_administrator_chat_ids(
    session: AsyncSession, organization_id: uuid.UUID
) -> frozenset[str]:
    """Active administrator Telegram identities for one Organization only."""
    return frozenset(
        value
        for value in await session.scalars(
            select(OrganizationMember.telegram_chat_id)
            .where(OrganizationMember.organization_id == organization_id)
            .where(OrganizationMember.active.is_(True))
            .where(OrganizationMember.role == MemberRole.ADMINISTRATOR.value)
            .where(OrganizationMember.telegram_chat_id.is_not(None))
        )
        if value
    )


class OrganizationEasyBrokerAdapters:
    """Build an EasyBroker adapter from one Organization's own key and policy."""

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_api_key: str = "",
        legacy_mls_access_confirmed: bool = False,
        legacy_retention_permission_confirmed: bool = False,
        base_url: str = "https://api.easybroker.com/v1",
        adapter_factory: Callable[..., EasyBrokerAdapter] = EasyBrokerAdapter,
    ) -> None:
        self._resolver = resolver
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values: Mapping[IntegrationProvider, str] = {
            IntegrationProvider.EASYBROKER: legacy_api_key
        }
        self._legacy_mls = legacy_mls_access_confirmed
        self._legacy_retention = legacy_retention_permission_confirmed
        self._base_url = base_url
        self._adapter_factory = adapter_factory
        self._adapters: dict[
            uuid.UUID, tuple[str, bool, bool, EasyBrokerAdapter]
        ] = {}

    async def for_organization(
        self, session: AsyncSession, organization_id: uuid.UUID
    ) -> EasyBrokerAdapter:
        credential = await IntegrationCredentials(
            session,
            self._resolver,
            bootstrap_organization_id=self._bootstrap_organization_id,
            legacy_values=self._legacy_values,
        ).try_resolve(organization_id, IntegrationProvider.EASYBROKER)
        api_key = credential.material if credential is not None else ""
        fingerprint = credential.fingerprint if credential is not None else "missing"

        configuration = await OrganizationConfiguration(
            session,
            bootstrap_organization_id=self._bootstrap_organization_id,
        ).try_current(organization_id)
        integrations = configuration.section("integrations") if configuration else {}
        easybroker = integrations.get("easybroker")
        values = easybroker if isinstance(easybroker, Mapping) else {}
        is_bootstrap = organization_id == self._bootstrap_organization_id
        configured_mls = values.get(
            "mls_access_confirmed",
            self._legacy_mls if is_bootstrap else False,
        )
        configured_retention = values.get(
            "retention_permission_confirmed",
            self._legacy_retention if is_bootstrap else False,
        )
        # Provider/legal gates are booleans, not merely truthy JSON values. A
        # string such as ``"false"`` must fail closed rather than activate MLS
        # or retention permission by accident.
        mls = configured_mls if isinstance(configured_mls, bool) else False
        retention = (
            configured_retention
            if isinstance(configured_retention, bool)
            else False
        )
        cached = self._adapters.get(organization_id)
        if cached is not None:
            old_fingerprint, old_mls, old_retention, adapter = cached
            if (old_fingerprint, old_mls, old_retention) == (
                fingerprint,
                mls,
                retention,
            ):
                return adapter
            await adapter.aclose()
        adapter = self._adapter_factory(
            api_key=api_key,
            base_url=self._base_url,
            mls_access_confirmed=mls,
            retention_permission_confirmed=retention,
        )
        self._adapters[organization_id] = (
            fingerprint,
            mls,
            retention,
            adapter,
        )
        return adapter

    async def aclose(self) -> None:
        for _fingerprint, _mls, _retention, adapter in self._adapters.values():
            await adapter.aclose()
        self._adapters.clear()


class OrganizationGoogleCalendarDirectories:
    """Resolve one Organization's service-account reference before scheduling."""

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_credentials_path: str = "",
    ) -> None:
        self._resolver = resolver
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values: Mapping[IntegrationProvider, str] = {
            IntegrationProvider.GOOGLE_CALENDAR: legacy_credentials_path
        }
        self._directories: dict[
            uuid.UUID, tuple[str, GoogleCalendarDirectory]
        ] = {}

    async def for_organization(
        self, session: AsyncSession, organization_id: uuid.UUID
    ) -> GoogleCalendarDirectory:
        credential = await IntegrationCredentials(
            session,
            self._resolver,
            bootstrap_organization_id=self._bootstrap_organization_id,
            legacy_values=self._legacy_values,
        ).try_resolve(organization_id, IntegrationProvider.GOOGLE_CALENDAR)
        fingerprint = credential.fingerprint if credential is not None else "missing"
        cached = self._directories.get(organization_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        directory = GoogleCalendarDirectory(
            credentials_path=credential.material if credential is not None else ""
        )
        self._directories[organization_id] = (fingerprint, directory)
        return directory

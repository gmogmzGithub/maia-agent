"""Organization-scoped Facebook Messenger and Instagram delivery clients."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.messaging import CustomerChannel
from realestate.channels.meta.client import MetaMessagingClient
from realestate.db.models import (
    ChannelBindingKind,
    ChannelBindingState,
    IntegrationProvider,
    OrganizationChannelBinding,
)
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.platform.credentials import IntegrationCredentials, SecretResolver


class MetaMessagingChannelMissing(CommercialError):
    message = (
        "Esta organización no tiene exactamente una cuenta activa para ese "
        "canal de mensajería. Asígnala antes de entregar mensajes."
    )


_PROVIDER: dict[CustomerChannel, IntegrationProvider] = {
    CustomerChannel.FACEBOOK_MESSENGER: IntegrationProvider.META_MESSENGER,
    CustomerChannel.INSTAGRAM: IntegrationProvider.META_INSTAGRAM,
}
_BINDING: dict[CustomerChannel, ChannelBindingKind] = {
    CustomerChannel.FACEBOOK_MESSENGER: ChannelBindingKind.FACEBOOK_PAGE,
    CustomerChannel.INSTAGRAM: ChannelBindingKind.INSTAGRAM_ACCOUNT,
}


class OrganizationMetaMessagingClients:
    """Resolve an Organization's token and receiving account as one client.

    Connect-ready, but not yet validated with real Meta credentials: supplying
    the account bindings and credential references activates the existing
    Messenger and Instagram delivery wiring.
    """

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_messenger_access_token: str = "",
        legacy_instagram_access_token: str = "",
        graph_version: str = "v25.0",
        messenger_base_url: str = "https://graph.facebook.com",
        instagram_base_url: str = "https://graph.instagram.com",
        client_factory: Callable[..., MetaMessagingClient] = MetaMessagingClient,
    ) -> None:
        self._resolver = resolver
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values: Mapping[IntegrationProvider, str] = {
            IntegrationProvider.META_MESSENGER: legacy_messenger_access_token,
            IntegrationProvider.META_INSTAGRAM: legacy_instagram_access_token,
        }
        self._graph_version = graph_version
        self._base_urls = {
            CustomerChannel.FACEBOOK_MESSENGER: messenger_base_url,
            CustomerChannel.INSTAGRAM: instagram_base_url,
        }
        self._client_factory = client_factory
        self._clients: dict[
            tuple[uuid.UUID, CustomerChannel], tuple[str, str, MetaMessagingClient]
        ] = {}

    async def for_organization(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        channel: CustomerChannel,
        account_id: str,
    ) -> MetaMessagingClient:
        if channel not in _PROVIDER:
            raise MetaMessagingChannelMissing(
                "Este directorio solo entrega clientes de Messenger e Instagram."
            )
        credential = await IntegrationCredentials(
            session,
            self._resolver,
            bootstrap_organization_id=self._bootstrap_organization_id,
            legacy_values=self._legacy_values,
        ).resolve(organization_id, _PROVIDER[channel])
        bindings = list(
            await session.scalars(
                select(OrganizationChannelBinding)
                .where(OrganizationChannelBinding.organization_id == organization_id)
                .where(OrganizationChannelBinding.kind == _BINDING[channel].value)
                .where(OrganizationChannelBinding.external_id == account_id)
                .where(OrganizationChannelBinding.state == ChannelBindingState.ACTIVE.value)
            )
        )
        if len(bindings) != 1:
            raise MetaMessagingChannelMissing()
        key = (organization_id, channel)
        cached = self._clients.get(key)
        if cached is not None:
            fingerprint, cached_account, client = cached
            if (
                fingerprint == credential.fingerprint
                and cached_account == account_id
            ):
                return client
            await client.aclose()
        client = self._client_factory(
            access_token=credential.material,
            account_id=account_id,
            channel=channel,
            graph_version=self._graph_version,
            base_url=self._base_urls[channel],
        )
        self._clients[key] = (credential.fingerprint, account_id, client)
        return client

    async def aclose(self) -> None:
        for _fingerprint, _account, client in self._clients.values():
            await client.aclose()
        self._clients.clear()

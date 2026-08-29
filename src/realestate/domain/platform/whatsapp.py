"""Organization-scoped access to Meta WhatsApp delivery clients."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.channels.whatsapp.client import WhatsAppClient
from realestate.channels.whatsapp.templates import MetaTemplateSource
from realestate.db.models import (
    ChannelBindingKind,
    ChannelBindingState,
    IntegrationProvider,
    OrganizationChannelBinding,
)
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.platform.credentials import (
    IntegrationCredentials,
    SecretResolver,
)


class WhatsAppChannelMissing(CommercialError):
    message = (
        "Esta organización no tiene exactamente un número de WhatsApp activo. "
        "Asigna uno antes de entregar mensajes."
    )


class OrganizationWhatsAppClients:
    """Resolve both the token and sending number for one Organization.

    The cache is keyed by Organization and invalidated by either a credential
    fingerprint or phone-number change. No operational path reads another
    Organization's client or the process-wide bootstrap client.
    """

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_access_token: str = "",
        graph_version: str = "v25.0",
        base_url: str = "https://graph.facebook.com",
        client_factory: Callable[..., WhatsAppClient] = WhatsAppClient,
    ) -> None:
        self._resolver = resolver
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values: Mapping[IntegrationProvider, str] = {
            IntegrationProvider.META_WHATSAPP: legacy_access_token
        }
        self._graph_version = graph_version
        self._base_url = base_url
        self._client_factory = client_factory
        self._clients: dict[
            uuid.UUID, tuple[str, str, WhatsAppClient]
        ] = {}

    async def for_organization(
        self, session: AsyncSession, organization_id: uuid.UUID
    ) -> WhatsAppClient:
        credential = await IntegrationCredentials(
            session,
            self._resolver,
            bootstrap_organization_id=self._bootstrap_organization_id,
            legacy_values=self._legacy_values,
        ).resolve(organization_id, IntegrationProvider.META_WHATSAPP)
        bindings = list(
            await session.scalars(
                select(OrganizationChannelBinding)
                .where(OrganizationChannelBinding.organization_id == organization_id)
                .where(
                    OrganizationChannelBinding.kind
                    == ChannelBindingKind.WHATSAPP_PHONE_NUMBER.value
                )
                .where(
                    OrganizationChannelBinding.state
                    == ChannelBindingState.ACTIVE.value
                )
            )
        )
        if len(bindings) != 1:
            raise WhatsAppChannelMissing()
        phone_number_id = bindings[0].external_id
        cached = self._clients.get(organization_id)
        if cached is not None:
            fingerprint, phone, client = cached
            if fingerprint == credential.fingerprint and phone == phone_number_id:
                return client
            await client.aclose()
        client = self._client_factory(
            access_token=credential.material,
            phone_number_id=phone_number_id,
            graph_version=self._graph_version,
            base_url=self._base_url,
        )
        self._clients[organization_id] = (
            credential.fingerprint,
            phone_number_id,
            client,
        )
        return client

    async def aclose(self) -> None:
        for _fingerprint, _phone, client in self._clients.values():
            await client.aclose()
        self._clients.clear()


class OrganizationMetaTemplateSources:
    """Resolve the Meta Business token and WABA for one Organization."""

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        bootstrap_organization_id: uuid.UUID | None = None,
        legacy_access_token: str = "",
        graph_version: str = "v25.0",
        base_url: str = "https://graph.facebook.com",
        source_factory: Callable[..., MetaTemplateSource] = MetaTemplateSource,
    ) -> None:
        self._resolver = resolver
        self._bootstrap_organization_id = bootstrap_organization_id
        self._legacy_values: Mapping[IntegrationProvider, str] = {
            IntegrationProvider.META_BUSINESS: legacy_access_token
        }
        self._graph_version = graph_version
        self._base_url = base_url
        self._source_factory = source_factory
        self._sources: dict[
            uuid.UUID, tuple[str, str, MetaTemplateSource]
        ] = {}

    async def for_organization(
        self, session: AsyncSession, organization_id: uuid.UUID
    ) -> MetaTemplateSource:
        credential = await IntegrationCredentials(
            session,
            self._resolver,
            bootstrap_organization_id=self._bootstrap_organization_id,
            legacy_values=self._legacy_values,
        ).resolve(organization_id, IntegrationProvider.META_BUSINESS)
        bindings = list(
            await session.scalars(
                select(OrganizationChannelBinding)
                .where(OrganizationChannelBinding.organization_id == organization_id)
                .where(
                    OrganizationChannelBinding.kind
                    == ChannelBindingKind.WHATSAPP_BUSINESS_ACCOUNT.value
                )
                .where(
                    OrganizationChannelBinding.state
                    == ChannelBindingState.ACTIVE.value
                )
            )
        )
        if len(bindings) != 1:
            raise WhatsAppChannelMissing(
                "Esta organización no tiene exactamente una cuenta de WhatsApp "
                "Business activa. Asígnala antes de consultar plantillas."
            )
        waba_id = bindings[0].external_id
        cached = self._sources.get(organization_id)
        if cached is not None:
            fingerprint, cached_waba, source = cached
            if fingerprint == credential.fingerprint and cached_waba == waba_id:
                return source
            await source.aclose()
        source = self._source_factory(
            access_token=credential.material,
            waba_id=waba_id,
            graph_version=self._graph_version,
            base_url=self._base_url,
        )
        self._sources[organization_id] = (
            credential.fingerprint,
            waba_id,
            source,
        )
        return source

    async def aclose(self) -> None:
        for _fingerprint, _waba, source in self._sources.values():
            await source.aclose()
        self._sources.clear()

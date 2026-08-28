"""Read-only Meta Business Management API adapter for Message Templates."""

from __future__ import annotations

from typing import Any

import httpx

from realestate.domain.engagement.templates import TemplateObservation


class MetaTemplateSource:
    def __init__(
        self,
        *,
        access_token: str,
        waba_id: str,
        graph_version: str,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = access_token
        self._waba_id = waba_id
        self._version = graph_version
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {access_token}"},
            transport=transport,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token and self._waba_id)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def list_templates(self) -> tuple[TemplateObservation, ...]:
        if not self.configured:
            raise RuntimeError("Meta template source is not configured")
        url: str | None = (
            f"{self._base_url}/{self._version}/{self._waba_id}/message_templates"
        )
        params: dict[str, str] | None = {
            "fields": "id,name,status,category,language,components,quality_score",
            "limit": "100",
        }
        observations: list[TemplateObservation] = []
        pages = 0
        while url is not None:
            pages += 1
            if pages > 20:
                raise RuntimeError("Meta template pagination exceeded safety limit")
            response = await self._http.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Meta returned an unreadable template page")
            data = payload.get("data")
            if not isinstance(data, list):
                raise RuntimeError("Meta template page did not contain data")
            for raw in data:
                if not isinstance(raw, dict):
                    continue
                components = raw.get("components")
                if not isinstance(components, list):
                    components = []
                quality = raw.get("quality_score")
                if isinstance(quality, dict):
                    quality = quality.get("score")
                observations.append(
                    TemplateObservation(
                        waba_id=self._waba_id,
                        provider_template_id=(
                            str(raw["id"]) if raw.get("id") is not None else None
                        ),
                        name=str(raw.get("name", "")),
                        language=str(raw.get("language", "")),
                        category=str(raw.get("category", "")),
                        status=str(raw.get("status", "")),
                        components=tuple(
                            component
                            for component in components
                            if isinstance(component, dict)
                        ),
                        quality=str(quality) if quality is not None else None,
                        provider_api_version=self._version,
                    )
                )
            paging = payload.get("paging")
            next_url: Any = paging.get("next") if isinstance(paging, dict) else None
            if next_url is not None and not str(next_url).startswith(
                f"{self._base_url}/"
            ):
                raise RuntimeError("Meta returned an unexpected pagination host")
            url = str(next_url) if next_url else None
            params = None
        return tuple(observations)

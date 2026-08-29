"""What every authenticated Developer/Administrator write route shares (P-051).

Two things, both of which used to be restated per route: the one HTTP Basic
credential that guards this surface, and how a Property writer is assembled from
the application state. CORS stays disabled, so these routes are safe even while
the separate Meta webhook route is exposed through the HTTPS tunnel; the webhook
authenticates with Meta's signature instead.
"""

from __future__ import annotations

import hmac
import json

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.config import get_settings
from realestate.domain.commercial.actors import Actor
from realestate.domain.properties import PropertyService

_basic = HTTPBasic(auto_error=False)


def _configured_developers() -> dict[str, str]:
    """Read local credential secrets without inventing a product role model."""
    settings = get_settings()
    configured = settings.developer_basic_credentials_json.strip()
    if configured:
        try:
            accounts = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DEVELOPER_BASIC_CREDENTIALS_JSON no contiene JSON válido.",
            ) from exc
        if not isinstance(accounts, dict) or not accounts:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DEVELOPER_BASIC_CREDENTIALS_JSON debe ser un objeto no vacío.",
            )
        if not all(
            isinstance(username, str)
            and username
            and isinstance(password, str)
            and password
            for username, password in accounts.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DEVELOPER_BASIC_CREDENTIALS_JSON contiene una cuenta inválida.",
            )
        return accounts
    if settings.developer_basic_user and settings.developer_basic_password:
        return {settings.developer_basic_user: settings.developer_basic_password}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Configura DEVELOPER_BASIC_CREDENTIALS_JSON o "
            "DEVELOPER_BASIC_USER / DEVELOPER_BASIC_PASSWORD."
        ),
    )


def require_developer(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Se requieren credenciales de Developer.",
        headers={"WWW-Authenticate": "Basic"},
    )
    if credentials is None:
        raise unauthorized
    authenticated = any(
        hmac.compare_digest(
            credentials.username.encode("utf-8"), username.encode("utf-8")
        )
        and hmac.compare_digest(
            credentials.password.encode("utf-8"), password.encode("utf-8")
        )
        for username, password in _configured_developers().items()
    )
    if not authenticated:
        raise unauthorized
    return credentials.username


def property_writer(
    request: Request, session: AsyncSession, actor: Actor
) -> PropertyService:
    """A ``PropertyService`` that always writes to both stores.

    Assembled here rather than at each route because forgetting the catalog is
    silent: accepted documents simply stop reaching ``src/properties`` with no
    error anywhere.

    Takes the ``Actor`` rather than an Organization id so a route cannot supply
    one the caller does not belong to: the only Organization reachable through
    this helper is the authenticated member's own (ADR-0050).
    """
    return PropertyService(
        session,
        request.app.state.artifacts,
        request.app.state.property_catalog,
        organization_id=actor.organization_id,
    )

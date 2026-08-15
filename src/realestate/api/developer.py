"""What every authenticated Developer/Administrator write route shares (P-051).

Two things, both of which used to be restated per route: the one HTTP Basic
credential that guards this surface, and how a Property writer is assembled from
the application state. CORS stays disabled, so these routes are safe even while
the separate Meta webhook route is exposed through the HTTPS tunnel; the webhook
authenticates with Meta's signature instead.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.config import get_settings
from realestate.domain.properties import PropertyService

_basic = HTTPBasic(auto_error=False)


def require_developer(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    settings = get_settings()
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Developer credentials required.",
        headers={"WWW-Authenticate": "Basic"},
    )
    if not settings.developer_basic_user or not settings.developer_basic_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEVELOPER_BASIC_USER / DEVELOPER_BASIC_PASSWORD are not configured.",
        )
    if credentials is None:
        raise unauthorized
    # Compared as bytes: hmac.compare_digest raises TypeError on str inputs that
    # are not pure ASCII, which would turn a bad credential into a 500.
    user_ok = hmac.compare_digest(
        credentials.username.encode("utf-8"), settings.developer_basic_user.encode("utf-8")
    )
    password_ok = hmac.compare_digest(
        credentials.password.encode("utf-8"),
        settings.developer_basic_password.encode("utf-8"),
    )
    if not (user_ok and password_ok):
        raise unauthorized
    return credentials.username


def property_writer(request: Request, session: AsyncSession) -> PropertyService:
    """A ``PropertyService`` that always writes to both stores.

    Assembled here rather than at each route because forgetting the catalog is
    silent: accepted documents simply stop reaching ``src/properties`` with no
    error anywhere.
    """
    return PropertyService(
        session,
        request.app.state.artifacts,
        request.app.state.property_catalog,
    )

"""Operator-facing health surface.

Reports each Stage 0 dependency separately so an operator can tell *which* piece
is missing. In particular, an unavailable or version-incompatible Hermes Runtime
is reported as such rather than as a generic failure.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response, status

from realestate.hermes.client import HermesClient

router = APIRouter(tags=["health"])


@router.get("/live", include_in_schema=False)
async def live() -> dict[str, str]:
    """Cheap container liveness probe with no external network calls."""
    return {"status": "ok"}


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, object]:
    state = request.app.state
    # Six independent dependencies, each a network round trip. Probed
    # concurrently so an operator waits for the slowest, not for their sum.
    database, hermes, media_storage, whatsapp, telegram, calendar = await asyncio.gather(
        state.database.check_health(),
        state.hermes.check_health(),
        state.media_storage.check_health(),
        state.whatsapp.check_health(),
        state.telegram.check_health(),
        state.calendar.check_health(),
    )
    loop_state = request.app.state.background_loop.state

    # WhatsApp is reported but does not gate the aggregate: an expired
    # test-number token is an expected Stage 0 condition, not an outage, and the
    # rest of the system stays usable without it.
    healthy = database.ok and hermes.ok and media_storage.ok and loop_state.running
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if healthy else "degraded",
        "components": {
            "database": database.as_dict(),
            "hermes": hermes.as_dict(),
            "media_storage": media_storage.as_dict(),
            "whatsapp": whatsapp,
            "telegram": telegram,
            "calendar": calendar,
            "background_loop": loop_state.as_dict(),
        },
    }


@router.get("/health/hermes")
async def hermes_health(request: Request, response: Response) -> dict[str, object]:
    # ``app.state`` is untyped by design in Starlette, so the client is named
    # here rather than letting Any leak into the response body's type.
    hermes: HermesClient = request.app.state.hermes
    result = await hermes.check_health()
    if not result.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result.as_dict()

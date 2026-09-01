"""The operator health surface reports each dependency separately."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from httpx import ASGITransport

from realestate.app import create_app
from realestate.config import Settings
from realestate.db.engine import DatabaseHealth
from realestate.hermes import HermesHealth, HermesStatus
from realestate.domain.catalog.storage import MediaStorageHealth
from realestate.worker.loop import BackgroundLoopState


@dataclass
class StubDatabase:
    health: DatabaseHealth

    async def check_health(self) -> DatabaseHealth:
        return self.health

    async def dispose(self) -> None:
        return None


@dataclass
class StubHermes:
    health: HermesHealth

    async def check_health(self) -> HermesHealth:
        return self.health


@dataclass
class StubChannel:
    """Stands in for either external channel; both report a plain dict."""

    health: dict

    async def check_health(self) -> dict:
        return self.health


class StubLoop:
    def __init__(self, running: bool = True) -> None:
        self.state = BackgroundLoopState(running=running, ticks=3)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.state.running = False


HEALTHY_WHATSAPP = {"status": "ok", "detail": "token valid, no expiry"}
HEALTHY_TELEGRAM = {"status": "ok", "detail": "bot @realestate_bot reachable"}
HEALTHY_CALENDAR = {"status": "ok", "detail": "El Men (America/Mexico_City)"}


def build_client(
    *,
    database: DatabaseHealth,
    hermes: HermesHealth,
    loop_running: bool = True,
    whatsapp: dict | None = None,
    media_storage: MediaStorageHealth | None = None,
) -> httpx.AsyncClient:
    """An app wired to stub dependencies.

    ASGITransport does not run the lifespan protocol, so the dependencies the
    lifespan would build are injected directly. That is the point: this suite
    tests the reporting logic, not the real PostgreSQL or Hermes connections.
    """
    app = create_app(Settings(WORKER_ENABLED=False))  # type: ignore[call-arg]
    app.state.database = StubDatabase(database)
    app.state.hermes = StubHermes(hermes)
    app.state.media_storage = StubChannel(
        media_storage or MediaStorageHealth(True, "Object storage available")
    )
    app.state.whatsapp = StubChannel(whatsapp or HEALTHY_WHATSAPP)
    app.state.telegram = StubChannel(HEALTHY_TELEGRAM)
    app.state.calendar = StubChannel(HEALTHY_CALENDAR)
    app.state.background_loop = StubLoop(loop_running)

    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    )


HEALTHY_DB = DatabaseHealth(ok=True, detail="PostgreSQL reachable")
HEALTHY_HERMES = HermesHealth(
    status=HermesStatus.OK, detail="all good", version="0.20.0", pinned_version="0.20.0"
)


async def test_liveness_does_not_require_dependency_state() -> None:
    app = create_app(Settings(WORKER_ENABLED=False))  # type: ignore[call-arg]
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        response = await client.get("/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_is_ok_when_every_component_is_ok() -> None:
    async with build_client(database=HEALTHY_DB, hermes=HEALTHY_HERMES) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["hermes"]["status"] == "ok"
    assert body["components"]["media_storage"]["status"] == "ok"
    assert body["components"]["background_loop"]["running"] is True


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (HermesStatus.UNREACHABLE, "not running"),
        (HermesStatus.INCOMPATIBLE, "version"),
        (HermesStatus.UNAUTHENTICATED, "token"),
    ],
)
async def test_an_unusable_hermes_makes_health_degraded(
    status: HermesStatus, fragment: str
) -> None:
    unhealthy = HermesHealth(status=status, detail=f"Hermes {fragment} problem")

    async with build_client(database=HEALTHY_DB, hermes=unhealthy) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["hermes"]["status"] == status.value
    assert body["components"]["database"]["status"] == "ok", (
        "a Hermes fault must not be reported as a database fault"
    )


async def test_an_unavailable_database_makes_health_degraded() -> None:
    down = DatabaseHealth(ok=False, detail="PostgreSQL is not reachable")

    async with build_client(database=down, hermes=HEALTHY_HERMES) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["components"]["database"]["status"] == "unavailable"


async def test_unavailable_object_storage_makes_health_degraded() -> None:
    unavailable = MediaStorageHealth(False, "Object storage is not reachable")

    async with build_client(
        database=HEALTHY_DB,
        hermes=HEALTHY_HERMES,
        media_storage=unavailable,
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    component = response.json()["components"]["media_storage"]
    assert component == {
        "status": "unavailable",
        "detail": "Object storage is not reachable",
    }


async def test_a_stopped_background_loop_makes_health_degraded() -> None:
    async with build_client(
        database=HEALTHY_DB, hermes=HEALTHY_HERMES, loop_running=False
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["components"]["background_loop"]["running"] is False


async def test_an_expired_whatsapp_token_is_reported_but_does_not_degrade() -> None:
    # Stage 0 runs on 24-hour test-number tokens, so an expiry is an expected
    # condition. It must be visible without making the whole system look down.
    expired = {"status": "expired", "detail": "META_ACCESS_TOKEN expired at ..."}

    async with build_client(
        database=HEALTHY_DB, hermes=HEALTHY_HERMES, whatsapp=expired
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["whatsapp"]["status"] == "expired"


async def test_the_hermes_detail_endpoint_reports_the_reason() -> None:
    incompatible = HermesHealth(
        status=HermesStatus.INCOMPATIBLE,
        detail="Hermes reports version '0.19.0' but the product is pinned to '0.20.0'.",
        version="0.19.0",
        pinned_version="0.20.0",
    )

    async with build_client(database=HEALTHY_DB, hermes=incompatible) as client:
        response = await client.get("/health/hermes")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "incompatible"
    assert body["version"] == "0.19.0"
    assert body["pinned_version"] == "0.20.0"

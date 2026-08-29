"""The pinned Hermes Runtime boundary (ADR-0008).

Checkpoint 0's exit condition requires that the application "detects an
unavailable or incompatible Hermes Runtime and reports it clearly". Each
detection path below is asserted separately.
"""

from __future__ import annotations

import pytest

from realestate.config import Settings
from realestate.hermes import REQUIRED_METHODS, HermesClient, HermesStatus
from tests.conftest import HERMES_BASE_URL, requires_hermes

PINNED = "0.20.0"
_CLIENTS: list[HermesClient] = []


@pytest.fixture(autouse=True)
async def close_clients() -> None:
    """The production client is pooled; tests must close every constructed pool."""
    yield
    while _CLIENTS:
        await _CLIENTS.pop().aclose()


def client(**overrides: object) -> HermesClient:
    kwargs: dict[str, object] = {
        "base_url": HERMES_BASE_URL,
        "session_token": "unused",
        "pinned_version": PINNED,
        "timeout_seconds": 5.0,
    }
    kwargs.update(overrides)
    instance = HermesClient(**kwargs)  # type: ignore[arg-type]
    _CLIENTS.append(instance)
    return instance


# --- Offline ----------------------------------------------------------------


def test_ws_url_carries_the_local_token() -> None:
    assert client(session_token="abc123").ws_url.endswith("/api/ws?token=abc123")


def test_settings_derive_the_websocket_url() -> None:
    settings = Settings(HERMES_BASE_URL="http://127.0.0.1:9119")  # type: ignore[call-arg]
    assert settings.hermes_ws_url == "ws://127.0.0.1:9119/api/ws"


async def test_missing_token_is_reported_as_unauthenticated() -> None:
    health = await client(session_token="").check_health()

    assert health.status is HermesStatus.UNAUTHENTICATED
    assert "HERMES_DASHBOARD_SESSION_TOKEN" in health.detail
    assert not health.ok


async def test_absent_runtime_is_reported_as_unreachable() -> None:
    # Port 9 (discard) is reserved and never serves HTTP.
    health = await client(base_url="http://127.0.0.1:9").check_health()

    assert health.status is HermesStatus.UNREACHABLE
    assert "docker compose up hermes" in health.detail


# --- Live -------------------------------------------------------------------


@requires_hermes
async def test_running_runtime_is_healthy_and_capable(hermes_token: str) -> None:
    health = await client(session_token=hermes_token).check_health()

    assert health.status is HermesStatus.OK, health.detail
    assert health.version == PINNED
    assert health.missing_methods == ()
    assert str(len(REQUIRED_METHODS)) in health.detail


@requires_hermes
async def test_version_mismatch_is_reported_as_incompatible(hermes_token: str) -> None:
    health = await client(
        session_token=hermes_token, pinned_version="99.0.0"
    ).check_health()

    assert health.status is HermesStatus.INCOMPATIBLE
    assert health.version == PINNED
    assert "pinned to '99.0.0'" in health.detail


@requires_hermes
async def test_wrong_token_is_reported_as_unauthenticated() -> None:
    health = await client(session_token="not-the-real-token").check_health()

    assert health.status is HermesStatus.UNAUTHENTICATED, health.detail
    assert not health.ok


@requires_hermes
@pytest.mark.parametrize("method", REQUIRED_METHODS)
async def test_each_required_method_exists(hermes_token: str, method: str) -> None:
    async with client(session_token=hermes_token).session() as rpc:
        assert await rpc.method_exists(method)


@requires_hermes
async def test_an_unknown_method_is_detected_as_missing(hermes_token: str) -> None:
    # Proves the probe distinguishes a present method from an absent one rather
    # than always answering True.
    async with client(session_token=hermes_token).session() as rpc:
        assert not await rpc.method_exists("realestate.method.that.does.not.exist")

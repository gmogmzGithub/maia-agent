"""The Hermes JSON-RPC transport, driven against a scripted WebSocket.

``test_hermes_client.py`` proves these paths against the runtime that happens to
be running. These prove the ones a healthy runtime never produces: a rejected
upgrade, a 4401 close after accept, a silent socket, a non-JSON frame, a version
that does not match the pin.

Every one of them has to resolve to a *named* status rather than an exception,
because that status is the whole point of the module: the operator's next action
is different for "start it", "fix the token", and "re-pin the version".
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError, WebSocketException

import realestate.hermes.client as client_module
from realestate.config import Settings
from realestate.hermes.client import (
    REQUIRED_METHODS,
    HermesClient,
    HermesHealth,
    HermesStatus,
    HermesUnavailable,
)

PINNED = "0.20.0"
READY = {"method": "event", "params": {"type": "gateway.ready"}}


class FakeSocket:
    """Replays scripted frames; records what the product sent.

    A frame may be a dict (encoded to JSON), a raw string, or an exception to
    raise. ``None`` means "stay silent", which is how a timeout is provoked.
    """

    def __init__(self, frames: list, close_code: int | None = None) -> None:
        self._frames = list(frames)
        self.close_code = close_code
        self.sent: list[dict] = []
        self.closed = False

    async def recv(self) -> str:
        if not self._frames:
            raise AssertionError("the product read past the end of the script")
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        if frame is None:
            await asyncio.sleep(10)  # never resolves inside the test's timeout
        return frame if isinstance(frame, str) else json.dumps(frame)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


def connecting(monkeypatch: pytest.MonkeyPatch, socket_or_error) -> None:
    """Point ``ws_connect`` at *socket_or_error* instead of a real runtime."""

    async def fake_connect(url: str, open_timeout: float | None = None):  # noqa: ANN202
        if isinstance(socket_or_error, Exception):
            raise socket_or_error
        return socket_or_error

    monkeypatch.setattr(client_module, "ws_connect", fake_connect)


def client(**overrides: object) -> HermesClient:
    kwargs: dict[str, object] = {
        "base_url": "http://127.0.0.1:9119",
        "session_token": "local-token",
        "pinned_version": PINNED,
        "timeout_seconds": 0.2,
    }
    kwargs.update(overrides)
    return HermesClient(**kwargs)  # type: ignore[arg-type]


def http(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def answering(instance: HermesClient, handler) -> HermesClient:  # noqa: ANN001
    instance._http = http(handler)
    return instance


def ok_health(version: str = PINNED, **extra: object) -> httpx.Response:
    return httpx.Response(200, json={"version": version, **extra})


# -- Construction -------------------------------------------------------------


def test_the_client_is_built_from_settings_so_one_change_reaches_every_caller() -> None:
    settings = Settings(  # type: ignore[call-arg]
        HERMES_BASE_URL="http://127.0.0.1:9119",
        HERMES_DASHBOARD_SESSION_TOKEN="abc123",
        HERMES_PINNED_VERSION="0.20.0",
        HERMES_TIMEOUT_SECONDS=7.5,
    )

    built = HermesClient.from_settings(settings)

    assert built.ws_url == "ws://127.0.0.1:9119/api/ws?token=abc123"
    assert built._pinned_version == "0.20.0"
    assert built._timeout == 7.5


def test_an_https_runtime_gets_a_secure_websocket_scheme() -> None:
    assert client(base_url="https://hermes.example/").ws_url.startswith(
        "wss://hermes.example/api/ws"
    )


async def test_the_liveness_probe_reuses_one_pooled_client() -> None:
    """The probe runs on every /health poll; a client per probe is a handshake
    per poll."""
    instance = client()
    try:
        first = instance._client()
        assert instance._client() is first
    finally:
        await instance.aclose()
    assert instance._http is None
    # Closing twice is safe: shutdown releases every dependency in turn.
    await instance.aclose()


# -- The HTTP liveness half ---------------------------------------------------


async def test_a_non_200_health_endpoint_is_unreachable_not_incompatible() -> None:
    instance = answering(client(), lambda request: httpx.Response(503, text="nope"))
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.UNREACHABLE
    assert "HTTP 503" in health.detail


async def test_a_non_json_health_body_is_a_protocol_error() -> None:
    instance = answering(client(), lambda request: httpx.Response(200, text="<html>"))
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.PROTOCOL_ERROR
    assert "did not return JSON" in health.detail


async def test_a_version_that_does_not_match_the_pin_is_incompatible() -> None:
    instance = answering(client(), lambda request: ok_health("0.21.0"))
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.INCOMPATIBLE
    assert health.version == "0.21.0"
    assert health.pinned_version == PINNED
    assert "HERMES_PINNED_VERSION" in health.detail


async def test_a_gated_dashboard_auth_runtime_is_reported_as_unauthenticated() -> None:
    """Stage 0 expects a local ``hermes serve`` without the auth gate."""
    instance = answering(client(), lambda request: ok_health(auth_required=True))
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.UNAUTHENTICATED
    assert "dashboard-auth mode" in health.detail


async def test_an_unexpected_fault_is_itself_the_report_not_a_crash() -> None:
    """The health surface must always answer; /health gathers this with others."""

    def explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("something nobody anticipated")

    instance = answering(client(), explode)
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.PROTOCOL_ERROR
    assert "RuntimeError" in health.detail


# -- The capability half ------------------------------------------------------


async def test_every_required_method_present_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [READY]
        + [{"id": n + 1, "result": {"error": "session not found"}} for n in range(len(REQUIRED_METHODS))]
    )
    connecting(monkeypatch, socket)
    instance = answering(client(), lambda request: ok_health())
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.OK
    assert health.missing_methods == ()
    assert f"all {len(REQUIRED_METHODS)} required" in health.detail
    # Probed with an id that cannot exist, so a present method does no work.
    assert {call["params"]["session_id"] for call in socket.sent} == {
        client_module._PROBE_SESSION_ID
    }


async def test_a_missing_method_is_named_in_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = [READY]
    for index, name in enumerate(REQUIRED_METHODS, start=1):
        if name == "session.redirect":
            frames.append({"id": index, "error": {"code": -32601}})
        else:
            frames.append({"id": index, "result": {}})
    connecting(monkeypatch, FakeSocket(frames))
    instance = answering(client(), lambda request: ok_health())
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.INCOMPATIBLE
    assert health.missing_methods == ("session.redirect",)
    assert "session.redirect" in health.detail


async def test_a_capability_probe_that_cannot_connect_reports_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(monkeypatch, OSError("connection refused"))
    instance = answering(client(), lambda request: ok_health())
    try:
        health = await instance.check_health()
    finally:
        await instance.aclose()

    assert health.status is HermesStatus.UNREACHABLE
    assert "OSError" in health.detail


# -- Opening the socket -------------------------------------------------------


async def test_a_refused_upgrade_is_an_authentication_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status_code = 403

    connecting(monkeypatch, client_module.InvalidStatus(FakeResponse()))
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session():
            pass

    assert raised.value.health.status is HermesStatus.UNAUTHENTICATED
    assert "HTTP 403" in raised.value.health.detail
    await instance.aclose()


@pytest.mark.parametrize(
    "failure",
    [
        WebSocketException("handshake failed"),
        OSError("no route to host"),
        asyncio.TimeoutError(),
    ],
)
async def test_a_transport_failure_opening_the_socket_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    connecting(monkeypatch, failure)
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session():
            pass

    assert raised.value.health.status is HermesStatus.UNREACHABLE
    await instance.aclose()


async def test_a_socket_closed_with_4401_after_accept_is_a_rejected_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime accepts the upgrade first and rejects the credential after,
    so an immediate close is an auth failure rather than a transport fault."""
    socket = FakeSocket([ConnectionClosedError(None, None)], close_code=4401)
    connecting(monkeypatch, socket)
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session():
            pass

    assert raised.value.health.status is HermesStatus.UNAUTHENTICATED
    assert "code=4401" in raised.value.health.detail
    # The half-open socket is released rather than leaked.
    assert socket.closed
    await instance.aclose()


async def test_a_socket_closed_for_another_reason_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(
        monkeypatch, FakeSocket([ConnectionClosedError(None, None)], close_code=1011)
    )
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session():
            pass

    assert raised.value.health.status is HermesStatus.UNREACHABLE
    await instance.aclose()


async def test_an_accepted_socket_that_says_nothing_is_a_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(monkeypatch, FakeSocket([None]))
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session():
            pass

    assert raised.value.health.status is HermesStatus.PROTOCOL_ERROR
    assert "sent no response in time" in raised.value.health.detail
    await instance.aclose()


async def test_a_frame_that_is_not_json_is_a_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(monkeypatch, FakeSocket(["not json at all"]))
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session():
            pass

    assert raised.value.health.status is HermesStatus.PROTOCOL_ERROR
    assert "not JSON-RPC" in raised.value.health.detail
    await instance.aclose()


async def test_frames_before_gateway_ready_are_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            {"method": "event", "params": {"type": "gateway.hello"}},
            {"method": "event", "params": "not-a-dict"},
            {"jsonrpc": "2.0", "id": 99, "result": {}},
            READY,
            {"id": 1, "result": {"ok": True}},
        ]
    )
    connecting(monkeypatch, socket)
    instance = client()

    async with instance.session() as rpc:
        assert await rpc.call("session.status") == {"id": 1, "result": {"ok": True}}

    assert socket.closed
    await instance.aclose()


# -- Calls and events on an open socket ---------------------------------------


async def test_a_call_skips_frames_that_are_not_its_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Events interleave freely; the caller gets the frame whose id matches."""
    socket = FakeSocket(
        [
            READY,
            {"method": "event", "params": {"type": "message.delta"}},
            {"id": 99, "result": "someone else's"},
            {"id": 1, "result": "mine"},
        ]
    )
    connecting(monkeypatch, socket)
    instance = client()

    async with instance.session() as rpc:
        assert (await rpc.call("prompt.submit", {"text": "hola"}))["result"] == "mine"

    assert socket.sent[0] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "prompt.submit",
        "params": {"text": "hola"},
    }
    await instance.aclose()


async def test_a_call_without_params_still_sends_an_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(monkeypatch, FakeSocket([READY, {"id": 1, "result": {}}]))
    instance = client()

    async with instance.session() as rpc:
        await rpc.call("session.list")
        assert rpc._ws.sent[0]["params"] == {}

    await instance.aclose()


async def test_request_ids_increment_so_two_calls_do_not_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket([READY, {"id": 1, "result": "a"}, {"id": 2, "result": "b"}])
    connecting(monkeypatch, socket)
    instance = client()

    async with instance.session() as rpc:
        await rpc.call("session.status")
        await rpc.call("session.status")

    assert [frame["id"] for frame in socket.sent] == [1, 2]
    await instance.aclose()


async def test_a_quiet_socket_polls_to_none_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is what lets the worker adopt late messages while a turn runs."""
    connecting(monkeypatch, FakeSocket([READY, None]))
    instance = client()

    async with instance.session() as rpc:
        assert await rpc.receive_event_or_none(0.05) is None

    await instance.aclose()


async def test_an_event_poll_returns_the_event_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(
        monkeypatch,
        FakeSocket([READY, {"method": "event", "params": {"type": "tool.start"}}]),
    )
    instance = client()

    async with instance.session() as rpc:
        assert await rpc.receive_event_or_none(0.2) == {"type": "tool.start"}

    await instance.aclose()


@pytest.mark.parametrize(
    "frame",
    [
        "not json",
        {"id": 7, "result": {}},
        {"method": "event", "params": "not-a-dict"},
    ],
)
async def test_a_poll_that_is_not_an_event_yields_none(
    monkeypatch: pytest.MonkeyPatch, frame: object
) -> None:
    connecting(monkeypatch, FakeSocket([READY, frame]))
    instance = client()

    async with instance.session() as rpc:
        assert await rpc.receive_event_or_none(0.2) is None

    await instance.aclose()


async def test_a_socket_closed_mid_turn_is_reported_as_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connecting(
        monkeypatch, FakeSocket([READY, ConnectionClosedError(None, None)])
    )
    instance = client()

    with pytest.raises(HermesUnavailable) as raised:
        async with instance.session() as rpc:
            await rpc.receive_event_or_none(0.2)

    assert raised.value.health.status is HermesStatus.UNREACHABLE
    assert "mid-turn" in raised.value.health.detail
    await instance.aclose()


# -- Reporting shapes ---------------------------------------------------------


def test_health_serialises_for_the_health_endpoint() -> None:
    health = HermesHealth(
        status=HermesStatus.INCOMPATIBLE,
        detail="missing methods",
        version="0.19.0",
        pinned_version=PINNED,
        missing_methods=("session.redirect",),
    )

    assert health.as_dict() == {
        "status": "incompatible",
        "detail": "missing methods",
        "version": "0.19.0",
        "pinned_version": PINNED,
        "missing_methods": ["session.redirect"],
    }
    assert not health.ok


def test_the_unavailable_error_states_the_status_and_carries_the_report() -> None:
    health = HermesHealth(status=HermesStatus.UNREACHABLE, detail="nothing answered")

    error = HermesUnavailable(health)

    assert str(error) == "unreachable: nothing answered"
    assert error.health is health

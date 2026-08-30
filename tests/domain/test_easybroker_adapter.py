"""Contract tests for the read-only EasyBroker HTTP adapter."""

from __future__ import annotations

import httpx
import pytest

from realestate.db.models import ExternalInventoryScope
from realestate.domain.external_inventory.easybroker import EasyBrokerAdapter
from realestate.domain.external_inventory.ports import (
    InventorySourceError,
    SourceAccessDenied,
)
from tests.fixtures.external_inventory import easybroker_property


async def test_page_contract_uses_get_auth_header_and_official_pagination_shape() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "pagination": {"page": 1, "total_pages": 2},
                "content": [{"public_id": "EB-1"}],
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    adapter = EasyBrokerAdapter(
        api_key="secret-test-key",
        mls_access_confirmed=True,
        client=client,
        sleep=_no_sleep,
    )
    page = await adapter.list_page(
        ExternalInventoryScope.COLLABORATOR, cursor=None, limit=50
    )

    assert [row["public_id"] for row in page.records] == ["EB-1"]
    assert page.next_cursor == "2"
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/mls_properties"
    assert dict(requests[0].url.params) == {"page": "1", "limit": "50"}
    assert requests[0].headers["X-Authorization"] == "secret-test-key"
    await client.aclose()


async def test_detail_contract_preserves_the_sanitized_official_shape() -> None:
    payload = easybroker_property()
    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    adapter = EasyBrokerAdapter(
        api_key="test", mls_access_confirmed=True, client=client, sleep=_no_sleep
    )

    assert await adapter.retrieve(
        ExternalInventoryScope.COLLABORATOR, "EB-FAKE-001"
    ) == payload
    await client.aclose()


async def test_rate_limit_honors_retry_after_then_succeeds() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"pagination": {}, "content": []}),
        ]
    )
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(lambda request: next(responses)),
    )
    adapter = EasyBrokerAdapter(
        api_key="test",
        mls_access_confirmed=True,
        client=client,
        sleep=sleep,
        max_attempts=2,
    )

    assert (
        await adapter.list_page(
            ExternalInventoryScope.COLLABORATOR, cursor=None, limit=20
        )
    ).records == ()
    assert 2.0 in sleeps
    await client.aclose()


async def test_timeout_retries_and_returns_a_sanitized_error_without_the_key() -> None:
    calls = 0

    def timeout(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("contains secret-test-key", request=request)

    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1", transport=httpx.MockTransport(timeout)
    )
    adapter = EasyBrokerAdapter(
        api_key="secret-test-key",
        mls_access_confirmed=True,
        client=client,
        sleep=_no_sleep,
        max_attempts=3,
    )

    with pytest.raises(InventorySourceError) as raised:
        await adapter.retrieve(ExternalInventoryScope.COLLABORATOR, "EB-1")
    assert calls == 3
    assert raised.value.code == "timeout"
    assert "secret-test-key" not in str(raised.value)
    await client.aclose()


async def test_collaborator_endpoint_is_refused_before_network_without_confirmed_mls() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"network called: {request.url}")

    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(unexpected),
    )
    adapter = EasyBrokerAdapter(api_key="test", client=client)

    with pytest.raises(SourceAccessDenied) as raised:
        await adapter.list_page(
            ExternalInventoryScope.COLLABORATOR, cursor=None, limit=20
        )
    assert raised.value.code == "mls_not_confirmed"
    await client.aclose()


async def test_invalid_json_is_a_contract_error() -> None:
    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        ),
    )
    adapter = EasyBrokerAdapter(
        api_key="test", mls_access_confirmed=True, client=client, sleep=_no_sleep
    )
    with pytest.raises(InventorySourceError) as raised:
        await adapter.retrieve(ExternalInventoryScope.COLLABORATOR, "EB-1")
    assert raised.value.code == "invalid_response"
    await client.aclose()


@pytest.mark.parametrize(
    ("pagination", "expected"),
    [
        ({"next_page": "2"}, "2"),
        ({"has_next_page": True}, "2"),
        ({"page": 1, "total_pages": 1}, None),
    ],
)
async def test_supported_pagination_variants(
    pagination: dict[str, object], expected: str | None
) -> None:
    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"pagination": pagination, "content": []}
            )
        ),
    )
    adapter = EasyBrokerAdapter(
        api_key="test", mls_access_confirmed=True, client=client, sleep=_no_sleep
    )

    assert (
        await adapter.list_page(
            ExternalInventoryScope.COLLABORATOR, cursor=None, limit=20
        )
    ).next_cursor == expected
    await client.aclose()


async def test_invalid_collection_shape_and_cursor_are_rejected() -> None:
    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"content": None})
        ),
    )
    adapter = EasyBrokerAdapter(
        api_key="test", mls_access_confirmed=True, client=client, sleep=_no_sleep
    )

    with pytest.raises(InventorySourceError, match="content list"):
        await adapter.list_page(
            ExternalInventoryScope.COLLABORATOR, cursor=None, limit=20
        )
    with pytest.raises(InventorySourceError) as raised:
        await adapter.list_page(
            ExternalInventoryScope.COLLABORATOR, cursor="not-a-page", limit=20
        )
    assert raised.value.code == "invalid_cursor"
    await client.aclose()


async def test_missing_credential_is_refused_before_network() -> None:
    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"network called: {request.url}")
        ),
    )
    adapter = EasyBrokerAdapter(api_key="", client=client)

    with pytest.raises(SourceAccessDenied) as raised:
        await adapter.retrieve(ExternalInventoryScope.ORGANIZATION, "EB-1")
    assert raised.value.code == "credential_missing"
    await client.aclose()


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (404, "not_found"),
        (401, "invalid_credential"),
        (403, "plan_or_permission_denied"),
        (400, "http_400"),
        (500, "provider_error"),
    ],
)
async def test_http_failures_are_sanitized(status: int, expected_code: str) -> None:
    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="secret provider body")
        ),
    )
    adapter = EasyBrokerAdapter(
        api_key="test", mls_access_confirmed=True, client=client, max_attempts=1
    )

    with pytest.raises(InventorySourceError) as raised:
        await adapter.retrieve(ExternalInventoryScope.COLLABORATOR, "EB-1")
    assert raised.value.code == expected_code
    assert "secret provider body" not in str(raised.value)
    await client.aclose()


async def test_transport_and_non_object_responses_are_contract_errors() -> None:
    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    failing = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(transport_error),
    )
    adapter = EasyBrokerAdapter(
        api_key="test",
        mls_access_confirmed=True,
        client=failing,
        max_attempts=1,
    )
    with pytest.raises(InventorySourceError) as raised:
        await adapter.retrieve(ExternalInventoryScope.COLLABORATOR, "EB-1")
    assert raised.value.code == "transport"
    await failing.aclose()

    non_object = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=["not", "an", "object"])
        ),
    )
    adapter = EasyBrokerAdapter(
        api_key="test", mls_access_confirmed=True, client=non_object
    )
    with pytest.raises(InventorySourceError) as raised:
        await adapter.retrieve(ExternalInventoryScope.COLLABORATOR, "EB-1")
    assert raised.value.code == "invalid_response"
    await non_object.aclose()


async def test_invalid_retry_after_uses_the_safe_default() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "later"}),
            httpx.Response(200, json={"pagination": {}, "content": []}),
        ]
    )
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = httpx.AsyncClient(
        base_url="https://api.example.test/v1",
        transport=httpx.MockTransport(lambda request: next(responses)),
    )
    adapter = EasyBrokerAdapter(
        api_key="test",
        mls_access_confirmed=True,
        client=client,
        sleep=sleep,
        max_attempts=2,
    )

    await adapter.list_page(
        ExternalInventoryScope.COLLABORATOR, cursor=None, limit=20
    )
    assert 1.0 in sleeps
    await client.aclose()


async def _no_sleep(seconds: float) -> None:
    del seconds

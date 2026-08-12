"""The outbound channel clients, driven over HTTP through a mock transport.

These exist because the credential header and the retry classification are the
difference between a Lead getting a reply and the Outbox silently retiring one.
Both now live on a process-lifetime ``httpx.AsyncClient`` rather than on each
request, so they are asserted here against real client machinery instead of a
stub sender.
"""

from __future__ import annotations

import httpx
import pytest

from realestate.channels.telegram.client import TelegramClient
from realestate.channels.whatsapp.client import (
    SendOutcome,
    WhatsAppClient,
    normalize_recipient,
)

TOKEN = "test-access-token"
PHONE_ID = "1234567890"


def whatsapp(handler) -> WhatsAppClient:  # noqa: ANN001
    return WhatsAppClient(
        access_token=TOKEN,
        phone_number_id=PHONE_ID,
        transport=httpx.MockTransport(handler),
    )


def accepted(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]})


# -- The credential header ----------------------------------------------------


async def test_the_send_carries_the_bearer_credential() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return accepted(request)

    client = whatsapp(handler)
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.SENT
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


async def test_the_token_check_carries_the_bearer_credential() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 0}})

    client = whatsapp(handler)
    try:
        assert (await client.check_health())["status"] == "ok"
    finally:
        await client.aclose()

    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


async def test_the_send_targets_the_configured_phone_number() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return accepted(request)

    client = whatsapp(handler)
    try:
        await client.send_text("5215550001112", "hola")
    finally:
        await client.aclose()

    assert seen[0].url.path.endswith(f"/{PHONE_ID}/messages")
    body = seen[0].read().decode()
    # The recipient is normalised on the way out (Mexican 521 prefix).
    assert normalize_recipient("5215550001112") in body


# -- Status classification ----------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, SendOutcome.FAILED_PERMANENT),
        (403, SendOutcome.FAILED_PERMANENT),
        (422, SendOutcome.FAILED_PERMANENT),
        (429, SendOutcome.FAILED_RETRYABLE),
        (500, SendOutcome.FAILED_RETRYABLE),
        (503, SendOutcome.FAILED_RETRYABLE),
        # Unrecognised: retryable, never silently permanent.
        (418, SendOutcome.FAILED_RETRYABLE),
        (301, SendOutcome.FAILED_RETRYABLE),
    ],
)
async def test_each_status_keeps_its_outcome(
    status_code: int, expected: SendOutcome
) -> None:
    client = whatsapp(lambda request: httpx.Response(status_code, json={}))
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()
    assert result.outcome is expected


async def test_a_retry_after_instruction_is_honoured() -> None:
    client = whatsapp(
        lambda request: httpx.Response(429, json={}, headers={"Retry-After": "42"})
    )
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()
    assert result.outcome is SendOutcome.FAILED_RETRYABLE
    assert result.retry_after_seconds == 42


async def test_a_200_without_a_message_id_is_inconclusive() -> None:
    """Never reported as sent: Meta may or may not have accepted it."""
    client = whatsapp(lambda request: httpx.Response(200, json={"messages": []}))
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()
    assert result.outcome is SendOutcome.UNKNOWN


@pytest.mark.parametrize("body", ["null", "[]", '"text"'])
async def test_a_non_object_successful_send_is_inconclusive(body: str) -> None:
    """A malformed success cannot escape the Outbox worker or count as sent."""
    client = whatsapp(
        lambda request: httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()
    assert result.outcome is SendOutcome.UNKNOWN


@pytest.mark.parametrize("body", ["null", "[]", '"text"'])
async def test_a_non_object_error_response_remains_retryable(body: str) -> None:
    client = whatsapp(
        lambda request: httpx.Response(
            503, content=body, headers={"Content-Type": "application/json"}
        )
    )
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()
    assert result.outcome is SendOutcome.FAILED_RETRYABLE


async def test_an_unreachable_meta_is_retryable_not_inconclusive() -> None:
    """The request never went out, so replaying it cannot duplicate a message."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client = whatsapp(handler)
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()
    assert result.outcome is SendOutcome.FAILED_RETRYABLE


# -- Health probes never raise ------------------------------------------------


@pytest.mark.parametrize("body", ["null", "[]", '"text"'])
async def test_a_non_object_token_response_is_reported_not_raised(body: str) -> None:
    """A probe is gathered with the others; an escape would fail all of /health."""
    client = whatsapp(
        lambda request: httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )
    try:
        assert (await client.check_health())["status"] in {"unknown", "invalid"}
    finally:
        await client.aclose()


async def test_an_unreachable_meta_is_reported_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client = whatsapp(handler)
    try:
        assert (await client.check_health())["status"] == "unknown"
    finally:
        await client.aclose()


# -- Telegram -----------------------------------------------------------------


def telegram(handler) -> TelegramClient:  # noqa: ANN001
    return TelegramClient(bot_token="test-bot-token", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("body", ["null", "[]"])
async def test_a_non_object_getme_response_is_reported_not_raised(body: str) -> None:
    client = telegram(
        lambda request: httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )
    try:
        assert (await client.check_health())["status"] == "unknown"
    finally:
        await client.aclose()


async def test_a_rejected_bot_token_is_reported() -> None:
    client = telegram(lambda request: httpx.Response(200, json={"ok": False}))
    try:
        assert (await client.check_health())["status"] == "invalid"
    finally:
        await client.aclose()


async def test_a_failed_poll_returns_no_updates_rather_than_raising() -> None:
    """A Telegram outage must not stop the loop that also serves WhatsApp."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = telegram(handler)
    try:
        assert await client.get_updates(offset=0) == []
    finally:
        await client.aclose()


async def test_a_non_200_poll_returns_no_updates() -> None:
    client = telegram(lambda request: httpx.Response(502, text="bad gateway"))
    try:
        assert await client.get_updates(offset=0) == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("body", ["null", "[]", '"text"'])
async def test_a_non_object_poll_returns_no_updates(body: str) -> None:
    client = telegram(
        lambda request: httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )
    try:
        assert await client.get_updates(offset=0) == []
    finally:
        await client.aclose()


async def test_one_malformed_update_does_not_hide_a_valid_sibling() -> None:
    payload = {
        "ok": True,
        "result": [
            {"message": {"chat": {"id": 1}, "from": {"id": 2}, "text": "bad"}},
            {
                "update_id": 42,
                "message": {
                    "chat": {"id": 1},
                    "from": {"id": 2, "username": "broker"},
                    "date": 1_700_000_000,
                    "text": "desactiva Casa Roble",
                },
            },
        ],
    }
    client = telegram(lambda request: httpx.Response(200, json=payload))
    try:
        updates = await client.get_updates(offset=0)
    finally:
        await client.aclose()
    assert [update.update_id for update in updates] == [42]


async def test_the_client_is_reused_across_calls() -> None:
    """One pool for the whole process: the point of the lazily built client."""
    client = telegram(lambda request: httpx.Response(200, json={"ok": True, "result": []}))
    try:
        await client.get_updates(offset=0)
        first = client._http
        await client.get_updates(offset=1)
        assert client._http is first
    finally:
        await client.aclose()
    assert client._http is None


# -- WhatsApp: nothing configured ----------------------------------------------


def unconfigured_whatsapp() -> WhatsAppClient:
    return WhatsAppClient(access_token="", phone_number_id="")


@pytest.mark.parametrize(
    ("token", "phone_id", "expected"),
    [("t", "1", True), ("", "1", False), ("t", "", False), ("", "", False)],
)
def test_both_halves_of_the_meta_credential_are_required(
    token: str, phone_id: str, expected: bool
) -> None:
    assert WhatsAppClient(access_token=token, phone_number_id=phone_id).configured is expected


async def test_an_unconfigured_client_reports_itself_rather_than_probing() -> None:
    report = await unconfigured_whatsapp().check_health()

    assert report["status"] == "unconfigured"
    assert "META_ACCESS_TOKEN" in report["detail"]


async def test_an_unconfigured_send_fails_permanently_rather_than_retrying() -> None:
    """No credential is not a transient fault; replaying it would never help."""
    result = await unconfigured_whatsapp().send_text("521555000111", "hola")

    assert result.outcome is SendOutcome.FAILED_PERMANENT
    assert result.conclusive


# -- WhatsApp: how long the token has left --------------------------------------


def token_check(**data: object):  # noqa: ANN202
    return lambda request: httpx.Response(200, json={"data": {"is_valid": True, **data}})


async def test_a_token_with_no_expiry_is_simply_ok() -> None:
    client = whatsapp(token_check(expires_at=0))
    try:
        assert await client.check_health() == {
            "status": "ok",
            "detail": "token valid, no expiry",
        }
    finally:
        await client.aclose()


async def test_a_token_with_a_missing_expiry_field_is_simply_ok() -> None:
    client = whatsapp(token_check())
    try:
        assert (await client.check_health())["status"] == "ok"
    finally:
        await client.aclose()


async def test_an_expired_token_is_named_as_the_cause() -> None:
    """Otherwise it shows up as a run of opaque Outbox failures."""
    from datetime import UTC, datetime, timedelta

    past = int((datetime.now(tz=UTC) - timedelta(hours=2)).timestamp())
    client = whatsapp(token_check(expires_at=past))
    try:
        report = await client.check_health()
    finally:
        await client.aclose()

    assert report["status"] == "expired"
    assert "update .env" in report["detail"]


async def test_a_token_inside_its_last_hour_is_reported_as_expiring() -> None:
    from datetime import UTC, datetime, timedelta

    soon = int((datetime.now(tz=UTC) + timedelta(minutes=30)).timestamp())
    client = whatsapp(token_check(expires_at=soon))
    try:
        report = await client.check_health()
    finally:
        await client.aclose()

    assert report["status"] == "expiring"
    assert "expires_at" in report


async def test_a_token_with_hours_left_is_ok_and_says_how_many() -> None:
    from datetime import UTC, datetime, timedelta

    later = int((datetime.now(tz=UTC) + timedelta(hours=20)).timestamp())
    client = whatsapp(token_check(expires_at=later))
    try:
        report = await client.check_health()
    finally:
        await client.aclose()

    assert report["status"] == "ok"
    assert "h left" in report["detail"]


# -- WhatsApp: classifying an ambiguous answer ----------------------------------


async def test_a_transport_fault_after_the_request_went_out_is_inconclusive() -> None:
    """Meta may already have accepted it, so it is never replayed (P-036)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    client = whatsapp(handler)
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.UNKNOWN
    assert not result.conclusive


async def test_a_connect_timeout_is_retryable_because_nothing_was_sent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("never opened", request=request)

    client = whatsapp(handler)
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.FAILED_RETRYABLE


async def test_a_200_with_an_unreadable_body_is_inconclusive() -> None:
    client = whatsapp(
        lambda request: httpx.Response(
            200, content=b"<html>", headers={"Content-Type": "application/json"}
        )
    )
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.UNKNOWN
    assert "unreadable" in result.detail


async def test_a_meta_error_code_is_carried_into_the_outbox_detail() -> None:
    client = whatsapp(
        lambda request: httpx.Response(
            400,
            json={"error": {"code": 131030, "message": "Recipient not in allowed list"}},
        )
    )
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.FAILED_PERMANENT
    assert "code=131030" in result.detail
    assert "Recipient not in allowed list" in result.detail


async def test_an_unreadable_error_body_falls_back_to_the_raw_text() -> None:
    client = whatsapp(lambda request: httpx.Response(502, text="upstream exploded"))
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert "HTTP 502" in result.detail
    assert "upstream exploded" in result.detail


async def test_a_non_object_error_field_does_not_break_the_detail() -> None:
    client = whatsapp(lambda request: httpx.Response(500, json={"error": "a string"}))
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.FAILED_RETRYABLE
    assert "HTTP 500" in result.detail


async def test_an_unparseable_retry_after_is_ignored_rather_than_fatal() -> None:
    client = whatsapp(
        lambda request: httpx.Response(
            429, json={}, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
        )
    )
    try:
        result = await client.send_text("521555000111", "hola")
    finally:
        await client.aclose()

    assert result.outcome is SendOutcome.FAILED_RETRYABLE
    # The Outbox falls back to its own delay curve.
    assert result.retry_after_seconds is None


# -- Telegram: nothing configured ------------------------------------------------


def unconfigured_telegram() -> TelegramClient:
    return TelegramClient(bot_token="")


def test_a_bot_token_is_what_makes_telegram_configured() -> None:
    assert TelegramClient(bot_token="t").configured
    assert not unconfigured_telegram().configured


async def test_an_unconfigured_poll_returns_no_updates_without_a_request() -> None:
    assert await unconfigured_telegram().get_updates(offset=0) == []


async def test_an_unconfigured_send_reports_failure_without_a_request() -> None:
    assert await unconfigured_telegram().send_message("12345", "hola") is False


async def test_an_unconfigured_telegram_reports_itself() -> None:
    report = await unconfigured_telegram().check_health()

    assert report["status"] == "unconfigured"
    assert "TELEGRAM_BOT_TOKEN" in report["detail"]


# -- Telegram: sending -----------------------------------------------------------


async def test_a_sent_administrative_reply_targets_the_chat_it_came_from() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = telegram(handler)
    try:
        assert await client.send_message("12345", "listo") is True
    finally:
        await client.aclose()

    assert seen[0].url.path.endswith("/sendMessage")
    body = seen[0].read().decode()
    assert '"chat_id": "12345"' in body or '"chat_id":"12345"' in body


async def test_a_rejected_send_is_reported_rather_than_assumed_delivered() -> None:
    """A rejected send would otherwise look identical to a delivered one."""
    client = telegram(lambda request: httpx.Response(403, json={"ok": False}))
    try:
        assert await client.send_message("12345", "listo") is False
    finally:
        await client.aclose()


async def test_an_unreachable_telegram_send_reports_failure_rather_than_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = telegram(handler)
    try:
        assert await client.send_message("12345", "listo") is False
    finally:
        await client.aclose()


async def test_a_reachable_bot_is_named_in_the_health_report() -> None:
    client = telegram(
        lambda request: httpx.Response(
            200, json={"ok": True, "result": {"username": "mens_concierge_bot"}}
        )
    )
    try:
        report = await client.check_health()
    finally:
        await client.aclose()

    assert report == {"status": "ok", "detail": "bot @mens_concierge_bot reachable"}


async def test_a_health_response_without_a_result_still_reports_ok() -> None:
    client = telegram(lambda request: httpx.Response(200, json={"ok": True}))
    try:
        assert (await client.check_health())["status"] == "ok"
    finally:
        await client.aclose()


# -- Telegram: parsing what long polling returns ---------------------------------


def parsed(payload: object):  # noqa: ANN202
    from realestate.channels.telegram.client import parse_updates

    return parse_updates(payload)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not-a-dict",
        [],
        {"ok": True},
        {"result": None},
        {"result": "not-a-list"},
        {"result": ["not-a-dict"]},
        {"result": [{"edited_message": {}}]},
        {"result": [{"message": "not-a-dict"}]},
        {"result": [{"message": {"chat": "not-a-dict", "from": {"id": 1}}}]},
        {"result": [{"message": {"chat": {"id": 1}, "from": "not-a-dict"}}]},
        {"result": [{"update_id": 1, "message": {"chat": {}, "from": {"id": 2}}}]},
        {"result": [{"update_id": 1, "message": {"chat": {"id": 1}, "from": {}}}]},
    ],
)
def test_anything_that_is_not_an_administrative_message_is_ignored(payload: object) -> None:
    """Edits, channel posts, callbacks and malformed items are not commands."""
    assert parsed(payload) == []


def test_a_message_with_no_date_falls_back_to_now() -> None:
    from datetime import UTC, datetime, timedelta

    before = datetime.now(tz=UTC) - timedelta(seconds=1)

    updates = parsed(
        {"result": [{"update_id": 7, "message": {"chat": {"id": 1}, "from": {"id": 2}}}]}
    )

    assert len(updates) == 1
    assert before <= updates[0].sent_at <= datetime.now(tz=UTC)


@pytest.mark.parametrize(
    "date",
    [
        # OverflowError…
        2**63,
        # …and OSError, which the platform raises past its time_t range. Missing
        # it escaped get_updates entirely and failed the whole background tick.
        10**18,
        "not-a-number",
        {"seconds": 1},
    ],
)
def test_an_unusable_date_does_not_discard_the_whole_response(date: object) -> None:
    payload = {
        "result": [
            {
                "update_id": 1,
                "message": {"chat": {"id": 1}, "from": {"id": 2}, "date": date},
            },
            {
                "update_id": 2,
                "message": {
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "date": 1770000000,
                    "text": "lista propiedades",
                },
            },
        ]
    }

    assert [u.update_id for u in parsed(payload)] == [2]


def test_a_non_text_message_is_kept_so_the_attempt_is_still_recorded() -> None:
    updates = parsed(
        {
            "result": [
                {
                    "update_id": 3,
                    "message": {
                        "chat": {"id": 1},
                        "from": {"id": 2},
                        "date": 1770000000,
                        "photo": [],
                    },
                }
            ]
        }
    )

    assert updates[0].text is None


def test_identities_are_carried_as_strings_for_the_allowlist_comparison() -> None:
    updates = parsed(
        {
            "result": [
                {
                    "update_id": 4,
                    "message": {
                        "chat": {"id": -100200},
                        "from": {"id": 12345, "username": "broker"},
                        "date": 1770000000,
                        "text": "desactiva Casa Roble",
                    },
                }
            ]
        }
    )

    assert (updates[0].chat_id, updates[0].from_user_id) == ("-100200", "12345")
    assert updates[0].from_username == "broker"
    # The whole update is retained for the audit record.
    assert updates[0].raw["update_id"] == 4


def test_a_poll_asks_from_the_persisted_cursor() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": []})

    async def run() -> None:
        client = telegram(handler)
        try:
            await client.get_updates(offset=42, limit=5)
        finally:
            await client.aclose()

    import asyncio

    asyncio.run(run())

    assert seen[0].url.params["offset"] == "42"
    assert seen[0].url.params["limit"] == "5"

"""Read-only, one-request batches. No network call runs in a SQL transaction."""

import json
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import httpx
from django.core.exceptions import ValidationError
from django.utils import timezone

from datalayer.easybroker import sync
from datalayer.easybroker.connections import decrypt
from datalayer.easybroker.normalization import public_id, timestamp

HOSTS = {"sandbox": "https://api.stagingeb.com/v1", "production": "https://api.easybroker.com/v1"}


class ProviderError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


def invalid_json_constant(value):
    raise ValueError("invalid_json_constant")


class Client:
    def __init__(self, connection, transport=None):
        self.base = HOSTS[connection.environment]
        self.key = decrypt(connection)
        self.transport = transport

    def get(self, path, params=None):
        # Only these two ordinary API routes can receive a credential.
        if path != "/listing_statuses" and not path.startswith("/properties/"):
            raise ProviderError("invalid_route")
        try:
            started = monotonic()
            with httpx.Client(
                transport=self.transport, timeout=5, follow_redirects=False
            ) as client:
                with client.stream(
                    "GET",
                    self.base + path,
                    params=params,
                    headers={"X-Authorization": self.key, "Accept": "application/json"},
                ) as response:
                    if response.status_code in {401, 403}:
                        raise ProviderError("authentication")
                    if response.status_code == 429:
                        retry = response.headers.get("Retry-After", "")
                        delay = int(retry) if retry.isdigit() else 30
                        if not retry.isdigit():
                            from email.utils import parsedate_to_datetime

                            try:
                                delay = int(
                                    (parsedate_to_datetime(retry) - timezone.now()).total_seconds()
                                )
                            except (ValueError, TypeError, OverflowError):
                                pass
                        raise ProviderError("rate_limit", max(1, min(delay, 3600)))
                    if response.status_code == 404:
                        raise ProviderError("not_found")
                    if response.status_code >= 500:
                        raise ProviderError("provider_unavailable", 30)
                    if response.status_code != 200:
                        raise ProviderError("invalid_response")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        if monotonic() - started > 8:
                            raise ProviderError("transport_or_schema", 15)
                        size += len(chunk)
                        if size > 2_000_000:
                            raise ProviderError("response_too_large")
                        chunks.append(chunk)
                    # Preserve decimal digits without a float round-trip in JSONField.
                    return json.loads(
                        b"".join(chunks), parse_float=str, parse_constant=invalid_json_constant
                    )
        except (httpx.HTTPError, UnicodeError, ValueError):
            raise ProviderError("transport_or_schema", 15) from None

    def statuses(self, page):
        raw = self.get("/listing_statuses", {"page": page, "limit": 100})
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("content"), list)
            or len(raw["content"]) > 100
        ):
            raise ProviderError("invalid_page")
        pagination = raw.get("pagination")
        if (
            not isinstance(pagination, dict)
            or pagination.get("page") != page
            or "next_page" not in pagination
        ):
            raise ProviderError("invalid_pagination")
        if (
            type(pagination.get("limit")) is not int
            or not 1 <= pagination["limit"] <= 100
            or type(pagination.get("total")) is not int
            or pagination["total"] < 0
            or len(raw["content"]) > pagination["limit"]
        ):
            raise ProviderError("invalid_pagination")
        following = pagination["next_page"]
        next_page = None
        if following is not None:
            if not isinstance(following, str):
                raise ProviderError("invalid_pagination")
            parts = urlsplit(following)
            base = urlsplit(self.base)
            query = parse_qs(parts.query)
            if (parts.scheme, parts.netloc, parts.path) != (
                base.scheme,
                base.netloc,
                "/v1/listing_statuses",
            ) or parts.fragment:
                raise ProviderError("invalid_pagination")
            if query.get("page") != [str(page + 1)] or page >= 10000 or not raw["content"]:
                raise ProviderError("invalid_pagination")
            next_page = page + 1
        for item in raw["content"]:
            if not isinstance(item, dict):
                raise ProviderError("invalid_status")
            public_id(item.get("public_id"))
            timestamp(item.get("updated_at"))
            if not isinstance(item.get("status"), str):
                raise ProviderError("invalid_status")
        return raw["content"], next_page

    def detail(self, external_id):
        return self.get("/properties/" + public_id(external_id))


def process(run_id, client=None):
    batch = sync.claim(run_id)
    if not batch:
        return
    try:
        client = client or Client(batch.connection)
        if batch.kind == "statuses":
            result = client.statuses(batch.target)
        elif batch.kind in {"detail", "continuity"} and batch.target is not None:
            result = client.detail(batch.target)
        else:
            result = None
        sync.accept(batch, result)
    except sync.StaleRun:
        return
    except (
        ProviderError,
        sync.BatchError,
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        code = (
            exc.code
            if isinstance(exc, (ProviderError, sync.BatchError))
            else "credential_unavailable"
            if isinstance(exc, ValidationError)
            else "invalid_detail"
        )
        try:
            sync.fail(batch, code, retry_after=getattr(exc, "retry_after", 15) or 15)
        except sync.StaleRun:
            pass

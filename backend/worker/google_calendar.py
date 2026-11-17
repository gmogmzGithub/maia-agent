"""Google transport. No network request runs inside a database transaction."""

import json
from datetime import timedelta
from urllib.parse import quote

import httpx
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import connection
from django.utils import timezone

from datalayer.models import CalendarConnection

SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.freebusy",
]


class CalendarError(Exception):
    def __init__(self, code, status=0):
        self.code, self.status = code, status
        super().__init__(code)


def encrypt(value):
    try:
        return (
            Fernet(settings.CALENDAR_ENCRYPTION_KEY.encode())
            .encrypt(json.dumps(value).encode())
            .decode()
        )
    except (ValueError, TypeError):
        raise CalendarError("calendar_key_not_configured") from None


def decrypt(value):
    try:
        return json.loads(Fernet(settings.CALENDAR_ENCRYPTION_KEY.encode()).decrypt(value.encode()))
    except (InvalidToken, ValueError, TypeError):
        raise CalendarError("calendar_key_unavailable") from None


def google_request(method, url, *, client=None, **kwargs):
    if connection.in_atomic_block:
        raise RuntimeError("calendar_network_inside_transaction")
    owned = client is None
    client = client or httpx.Client(timeout=12, follow_redirects=False)
    try:
        response = client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise CalendarError("google_http_" + str(response.status_code), response.status_code)
        return response.json() if response.content else {}
    except CalendarError:
        raise
    except Exception:
        # Provider exceptions may include credentials or the authorization code.
        raise CalendarError("google_response_unknown") from None
    finally:
        if owned:
            client.close()


def token_exchange(data, client=None):
    return google_request(
        "POST",
        "https://oauth2.googleapis.com/token",
        client=client,
        data={
            **data,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
        },
    )


def access_token(conn, client=None):
    if not conn.connected:
        raise CalendarError("calendar_disconnected")
    credentials = decrypt(conn.credentials)
    if credentials.get("expires_at", 0) > timezone.now().timestamp() + 60:
        return credentials["access_token"]
    try:
        result = token_exchange(
            {"grant_type": "refresh_token", "refresh_token": credentials["refresh_token"]}, client
        )
    except CalendarError as exc:
        if exc.status in (400, 401, 403):
            CalendarConnection.objects.filter(pk=conn.pk, generation=conn.generation).update(
                connected=False
            )
            raise CalendarError("calendar_disconnected") from None
        raise
    credentials.update(result)
    credentials["expires_at"] = (
        timezone.now() + timedelta(seconds=result.get("expires_in", 3600))
    ).timestamp()
    saved = CalendarConnection.objects.filter(
        pk=conn.pk, generation=conn.generation, connected=True
    ).update(credentials=encrypt(credentials))
    if not saved:
        raise CalendarError("calendar_connection_changed")
    return credentials["access_token"]


class GoogleCalendar:
    def __init__(self, conn, client=None):
        self.conn, self.client = conn, client

    def request(self, method, path, **kwargs):
        if not CalendarConnection.objects.filter(
            pk=self.conn.pk, generation=self.conn.generation, connected=True
        ).exists():
            raise CalendarError("calendar_disconnected")
        token = access_token(self.conn, self.client)
        try:
            return google_request(
                method,
                "https://www.googleapis.com/calendar/v3/" + path,
                client=self.client,
                headers={"Authorization": "Bearer " + token, **kwargs.pop("headers", {})},
                **kwargs,
            )
        except CalendarError as exc:
            if exc.status == 401:
                CalendarConnection.objects.filter(
                    pk=self.conn.pk, generation=self.conn.generation
                ).update(connected=False)
                raise CalendarError("calendar_disconnected") from None
            raise

    def busy(self, start, end):
        result = self.request(
            "POST",
            "freeBusy",
            json={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": "primary"}],
            },
        )
        calendars = result.get("calendars", {})
        calendar = calendars.get("primary") or calendars.get(self.conn.email)
        if calendar is None or calendar.get("errors"):
            raise CalendarError("calendar_availability_unavailable")
        return calendar.get("busy", [])

    def event(self, event_id):
        return self.request("GET", "calendars/primary/events/" + quote(event_id, safe=""))

    def create(self, body):
        return self.request(
            "POST", "calendars/primary/events", json=body, params={"sendUpdates": "none"}
        )

    def change(self, event_id, body, etag):
        return self.request(
            "PATCH",
            "calendars/primary/events/" + quote(event_id, safe=""),
            json=body,
            headers={"If-Match": etag},
            params={"sendUpdates": "none"},
        )

    def delete(self, event_id, etag):
        return self.request(
            "DELETE",
            "calendars/primary/events/" + quote(event_id, safe=""),
            headers={"If-Match": etag},
            params={"sendUpdates": "none"},
        )

import base64
import hashlib
import hmac
import io
import json
import time
from datetime import timedelta

import httpx
import pytest
from django.test import Client
from django.utils import timezone
from pypdf import PdfReader

from datalayer.capture_mail import configuration
from datalayer.captures import output, review
from datalayer.models import CaptureMailEvent
from tests.test_capture import approved
from tests.test_capture import owner as owner
from worker.capture_delivery import deliver

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def resend_settings(settings):
    settings.CAPTURE_EMAIL_PROVIDER = "resend"
    settings.RESEND_API_KEY = "re_test_only_never_real"
    settings.DEFAULT_FROM_EMAIL = "Maia <equipo@maia.test>"
    settings.RESEND_WEBHOOK_SECRET = (
        "whsec_" + base64.b64encode(b"test-signing-secret-only-1234").decode()
    )
    return settings


def callback(
    settings,
    kind="email.delivered",
    receipt="mail-123",
    event_id="evt-1",
    when=None,
    tag=None,
    stamp=None,
):
    data = {
        "type": kind,
        "created_at": (when or timezone.now()).isoformat(),
        "data": {"email_id": receipt},
    }
    if tag:
        data["data"]["tags"] = {"capture_delivery": str(tag)}
    raw = json.dumps(data).encode()
    stamp = str(stamp if stamp is not None else int(time.time()))
    signature = base64.b64encode(
        hmac.new(
            base64.b64decode(settings.RESEND_WEBHOOK_SECRET[6:]),
            f"{event_id}.{stamp}.".encode() + raw,
            hashlib.sha256,
        ).digest()
    ).decode()
    return raw, {
        "HTTP_SVIX_ID": event_id,
        "HTTP_SVIX_TIMESTAMP": stamp,
        "HTTP_SVIX_SIGNATURE": "v1," + signature,
    }


def test_resend_sends_private_pdf_html_and_one_idempotent_request(owner, resend_settings):
    capture, _ = approved(owner, title="Casa <script>alert(1)</script>")
    row = capture.deliveries.get(channel="email")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "mail-123"})

    deliver(row.pk, client=httpx.Client(transport=httpx.MockTransport(handler)))
    deliver(row.pk, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(seen) == 1
    payload = json.loads(seen[0].content)
    assert payload["to"] == [owner.email] and payload["from"] == resend_settings.DEFAULT_FROM_EMAIL
    assert seen[0].headers["Idempotency-Key"] == f"capture-mail/{row.pk}/1"
    assert "<script>" not in payload["html"] and "&lt;script&gt;" in payload["html"]
    pdf = PdfReader(io.BytesIO(base64.b64decode(payload["attachments"][0]["content"])))
    assert "SIN ACEPTAR" in pdf.pages[0].extract_text()
    row.refresh_from_db()
    assert row.provider_id == "mail-123" and row.status == "sent" and row.attempts == 1
    assert "mail_configuration" not in output(capture)
    assert output(capture, staff=True)["mail_configuration"]["ready"]


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "failed"),
        (403, "failed"),
        (422, "failed"),
        (429, "failed"),
        (409, "uncertain"),
        (500, "uncertain"),
    ],
)
def test_resend_distinguishes_rejection_from_uncertainty(owner, resend_settings, status, expected):
    capture, _ = approved(owner)
    row = capture.deliveries.get(channel="email")
    deliver(
        row.pk,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    status, json={"message": "do not log private provider body"}
                )
            )
        ),
    )
    row.refresh_from_db()
    assert row.status == expected and "private" not in row.error_code


def test_resend_missing_credentials_blocks_instead_of_falling_back(owner, resend_settings):
    resend_settings.RESEND_API_KEY = ""
    capture, _ = approved(owner)
    row = capture.deliveries.get(channel="email")

    def never(_):
        pytest.fail("Must not call Resend without configuration")

    deliver(row.pk, client=httpx.Client(transport=httpx.MockTransport(never)))
    row.refresh_from_db()
    assert row.status == "blocked" and row.attempts == 0
    assert not configuration()["ready"]


def test_signed_callback_before_receipt_recovers_delivery_and_deduplicates(owner, resend_settings):
    capture, _ = approved(owner)
    row = capture.deliveries.get(channel="email")
    raw, headers = callback(resend_settings, tag=row.pk)
    browser = Client(enforce_csrf_checks=True)

    def handler(_):
        assert (
            browser.post(
                "/api/capture/mail/webhook", data=raw, content_type="application/json", **headers
            ).status_code
            == 200
        )
        return httpx.Response(200, json={"id": "mail-123"})

    deliver(row.pk, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert (
        browser.post(
            "/api/capture/mail/webhook", data=raw, content_type="application/json", **headers
        ).status_code
        == 200
    )
    assert CaptureMailEvent.objects.count() == 1
    row.refresh_from_db()
    assert row.status == "delivered" and row.provider_id == "mail-123"


@pytest.mark.parametrize("offset", [-600, 600])
def test_webhook_rejects_stale_or_future_signatures(resend_settings, offset):
    raw, headers = callback(resend_settings, stamp=int(time.time()) + offset)
    assert (
        Client()
        .post("/api/capture/mail/webhook", data=raw, content_type="application/json", **headers)
        .status_code
        == 403
    )
    assert not CaptureMailEvent.objects.exists()


def test_webhook_rejects_tampered_body(resend_settings):
    raw, headers = callback(resend_settings)
    assert (
        Client()
        .post(
            "/api/capture/mail/webhook", data=raw + b" ", content_type="application/json", **headers
        )
        .status_code
        == 403
    )
    assert not CaptureMailEvent.objects.exists()


def test_callbacks_do_not_regress_delivery_or_reenable_bounced_mail(owner, resend_settings):
    capture, staff = approved(owner)
    row = capture.deliveries.get(channel="email")
    row.provider, row.provider_id, row.status = "resend", "mail-123", "sent"
    row.save()
    now = timezone.now()
    client = Client()
    for index, (kind, when) in enumerate(
        [
            ("email.delivered", now),
            ("email.sent", now - timedelta(minutes=1)),
            ("email.delivery_delayed", now + timedelta(seconds=1)),
        ]
    ):
        raw, headers = callback(resend_settings, kind=kind, event_id=f"evt-{index}", when=when)
        assert (
            client.post(
                "/api/capture/mail/webhook", data=raw, content_type="application/json", **headers
            ).status_code
            == 200
        )
    row.refresh_from_db()
    assert row.status == "delivered"
    raw, headers = callback(
        resend_settings, kind="email.bounced", event_id="bounce", when=now + timedelta(minutes=1)
    )
    client.post("/api/capture/mail/webhook", data=raw, content_type="application/json", **headers)
    row.refresh_from_db()
    assert row.status == "bounced"
    with pytest.raises(ValueError, match="no admite"):
        review(
            capture.pk,
            staff,
            {"action": "retry_delivery", "revision": capture.revision, "delivery_id": row.pk},
        )


def test_stored_contract_can_be_sent_once_after_real_provider_is_configured(owner, resend_settings):
    capture, staff = approved(owner)
    row = capture.deliveries.get(channel="email")
    row.status = "stored"
    row.save()
    resend_settings.RESEND_API_KEY = ""
    with pytest.raises(ValueError, match="no admite"):
        review(
            capture.pk,
            staff,
            {"action": "retry_delivery", "revision": capture.revision, "delivery_id": row.pk},
        )
    resend_settings.RESEND_API_KEY = "re_test_only_never_real"
    review(
        capture.pk,
        staff,
        {"action": "retry_delivery", "revision": capture.revision, "delivery_id": row.pk},
    )
    deliver(
        row.pk,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"id": "mail-123"}))
        ),
    )
    row.refresh_from_db()
    assert row.status == "sent"
    with pytest.raises(ValueError, match="no admite"):
        review(
            capture.pk,
            staff,
            {"action": "retry_delivery", "revision": capture.revision, "delivery_id": row.pk},
        )

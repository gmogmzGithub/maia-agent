import io
import json
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from PIL import Image

from datalayer.capture_catalog import CONTRACT_VERSION, KINDS
from datalayer.capture_media import normalize_upload
from datalayer.capture_schemas import CaptureData
from datalayer.captures import accept, expire, review, save_draft, submit
from datalayer.inventory import public_inventory, search_inventory, set_publication
from datalayer.models import Advisor, CaptureAgreement, CaptureDelivery, Property, User
from datalayer.schemas import SearchCriteria
from tests.test_increment import browser
from worker.capture_delivery import deliver

pytestmark = pytest.mark.django_db(transaction=True)


def test_approval_queues_one_email_with_frozen_pdf_and_direct_link(owner, settings, monkeypatch):
    from pypdf import PdfReader

    from datalayer import capture_catalog
    from datalayer.captures import request_acceptance

    settings.PUBLIC_BASE_URL = "https://maia.example.com"
    capture, staff = approved(owner)
    row = capture.deliveries.get(channel="email")
    assert row.recipient == owner.email
    assert f"/propietarios?capture={capture.pk}" in row.body
    assert row.attachment["version"] == CONTRACT_VERSION
    assert request_acceptance(capture).pk == row.pk
    assert capture.deliveries.filter(channel="email").count() == 1
    original = row.attachment["text"]
    monkeypatch.setattr(capture_catalog, "CONTRACT_TEXT", "NO DEBE CAMBIAR EL PDF EN COLA")
    deliver(row.pk)
    deliver(row.pk)
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.to == [owner.email]
    filename, content, mime = email.attachments[0]
    assert filename.endswith(".pdf") and mime == "application/pdf"
    pdf = PdfReader(io.BytesIO(content))
    text = " ".join(page.extract_text() for page in pdf.pages)
    assert "SIN ACEPTAR" in text and CONTRACT_VERSION in text
    assert str(capture.pk) in text and "seis meses" in text
    assert original[:30] in text and "NO DEBE CAMBIAR" not in text
    capture.refresh_from_db()
    assert capture.status == "approved" and not capture.agreements.exists()
    assert not capture.property.published


def test_outdated_approval_email_is_not_sent(owner):
    capture, staff = approved(owner)
    row = capture.deliveries.get(channel="email")
    review(
        capture.pk, staff, {"action": "update", "revision": capture.revision, "data": capture.data}
    )
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "superseded"
    assert not mail.outbox


def test_pdf_failure_does_not_send_an_email_without_contract(owner, monkeypatch):
    capture, _ = approved(owner)
    row = capture.deliveries.get(channel="email")

    def fail(_):
        raise RuntimeError("render failed")

    monkeypatch.setattr("datalayer.capture_contract.contract_pdf", fail)
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "failed" and row.error_code == "attachment_generation_failed"
    assert not mail.outbox


def test_contract_email_uncertainty_does_not_duplicate_sends(owner, monkeypatch):
    capture, _ = approved(owner)
    row = capture.deliveries.get(channel="email")
    calls = []

    def fail(self):
        calls.append(True)
        raise TimeoutError("provider may have accepted")

    monkeypatch.setattr("worker.capture_delivery.EmailMultiAlternatives.send", fail)
    deliver(row.pk)
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "uncertain" and len(calls) == 1


def test_contract_file_mail_is_stored_not_reported_as_delivered(owner, settings, tmp_path):
    settings.EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    settings.EMAIL_FILE_PATH = str(tmp_path / "mail")
    capture, _ = approved(owner)
    row = capture.deliveries.get(channel="email")
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "stored"
    from email import policy
    from email.parser import BytesParser

    message = BytesParser(policy=policy.default).parsebytes(
        next((tmp_path / "mail").iterdir()).read_bytes()
    )
    assert len(list(message.iter_attachments())) == 1


def test_contract_download_is_private_and_preserves_accepted_snapshot(owner):
    from pypdf import PdfReader

    capture, _ = approved(owner)
    path = f"/api/capture/requests/{capture.pk}/contract"
    client = Client()
    assert client.get(path).status_code == 404
    other = User.objects.create_user(
        "other-pdf@example.com", "test-password", phone="+523312345679"
    )
    client.force_login(other)
    assert client.get(path).status_code == 404
    client.force_login(owner)
    response = client.get(path)
    assert response.status_code == 200 and response["Cache-Control"] == "private, no-store"
    assert (
        "SIN ACEPTAR"
        in PdfReader(io.BytesIO(b"".join(response.streaming_content))).pages[0].extract_text()
    )
    capture = accept(capture.pk, owner, capture.revision, CONTRACT_VERSION)
    capture.data["title"] = "MODIFICACIÓN QUE NO DEBE CAMBIAR EL ACUERDO"
    capture.save()
    response = client.get(path)
    text = " ".join(
        p.extract_text() for p in PdfReader(io.BytesIO(b"".join(response.streaming_content))).pages
    )
    assert "ACEPTACIÓN REGISTRADA" in text and "MODIFICACIÓN" not in text
    assert capture.agreements.count() == 1


def test_storage_audit_detects_missing_files_without_repairing(owner):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    capture = draft(owner)
    call_command(
        "check_capture_storage", verify_images=True, find_orphans=True, stdout=io.StringIO()
    )
    asset = capture.assets.first()
    asset.file.delete(save=False)
    with pytest.raises(CommandError):
        call_command("check_capture_storage", stdout=io.StringIO(), stderr=io.StringIO())
    assert capture.assets.count() == 5


def test_rotating_a_large_photo_reapplies_website_compression(owner):
    import random

    from django.core.files.base import ContentFile

    from datalayer.capture_assets import rotate

    capture = draft(owner)
    asset = capture.assets.first()
    stream = io.BytesIO()
    Image.frombytes("RGB", (1400, 1200), random.Random(11).randbytes(1400 * 1200 * 3)).save(
        stream, "WEBP", quality=98
    )
    asset.file.save("large.webp", ContentFile(stream.getvalue()))
    asset.content_type, asset.size = "image/webp", len(stream.getvalue())
    asset.save()
    rotate(owner, capture.pk, asset.pk, capture.revision)
    asset.refresh_from_db()
    assert asset.size <= 800_000
    with asset.file.open("rb") as source, Image.open(source) as image:
        assert image.height > image.width and not image.getexif()


@pytest.fixture
def owner(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    return User.objects.create_user(
        "owner@example.com",
        "some-long-safe-password",
        phone="+523312345678",
        email_verified_at=timezone.now(),
    )


def draft(owner, photos=5, **changes):
    data = {
        "name": "PRUEBA Propietario",
        "municipality": "Zapopan",
        "neighborhood": "Centro",
        "private_address": "Dirección PRIVADA 123",
        "title": "PRUEBA Captación",
        "price": "123000",
        "phone_confirmed": True,
        "latitude": 20.674321,
        "longitude": -103.353456,
        **changes,
    }
    capture = save_draft(owner, data, uuid.uuid4(), 0)
    for i in range(photos):
        image = io.BytesIO()
        Image.new("RGB", (80, 60), color=(i * 20, 60, 70)).save(image, format="JPEG")
        capture.assets.create(
            request_id=uuid.uuid4(),
            kind="photo",
            file=SimpleUploadedFile(f"photo-{i}.jpg", image.getvalue()),
            size=len(image.getvalue()),
            content_type="image/jpeg",
            position=i,
        )
    return capture


def approved(owner, **changes):
    Advisor.objects.get_or_create(name="PRUEBA asesor", defaults={"is_default": True})
    capture = draft(owner, **changes)
    capture = submit(capture.pk, owner, capture.revision)
    staff, _ = User.objects.get_or_create(email="reviewer@example.com", defaults={"is_staff": True})
    capture = review(
        capture.pk,
        staff,
        {
            "action": "approve",
            "revision": capture.revision,
            "representation_verified": True,
            "outside_area_approved": True,
        },
    )
    return capture, staff


def post(client, headers, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json", **headers)


def test_owner_sees_assigned_advisor_contact_without_private_fields(owner):
    from datalayer.models import Capture

    advisor = Advisor.objects.create(
        name="Asesor de prueba", whatsapp="+523312345678", telegram_chat_id="123456"
    )
    capture = Capture.objects.create(owner=owner, advisor=advisor)
    client, _ = browser()
    path = f"/api/capture/requests/{capture.pk}"
    assert client.get(path).status_code == 401
    client.force_login(owner)
    assert client.get(path).json()["advisor"] == {
        "name": advisor.name,
        "whatsapp": advisor.whatsapp,
    }
    advisor.whatsapp = "+523387654321"
    advisor.save(update_fields=["whatsapp"])
    assert client.get(path).json()["advisor"]["whatsapp"] == advisor.whatsapp
    capture.advisor = None
    capture.save(update_fields=["advisor"])
    assert client.get(path).json()["advisor"] is None
    other = User.objects.create_user(
        "another-owner@example.com", phone="+523312345679", email_verified_at=timezone.now()
    )
    client.force_login(other)
    assert client.get(path).status_code == 404


def test_intake_requires_review_and_explicit_acceptance(owner):
    capture, staff = approved(owner)
    assert not capture.property.published
    with pytest.raises(ValidationError):
        set_publication(capture.property_id, True)
    old_revision = capture.revision
    capture = accept(capture.pk, owner, old_revision, CONTRACT_VERSION)
    accept(capture.pk, owner, old_revision, CONTRACT_VERSION)
    agreement = capture.agreements.get()
    assert (
        agreement.accepted_by == owner
        and 181 <= (agreement.expires_at - agreement.accepted_at).days <= 184
    )
    capture = review(capture.pk, staff, {"action": "publish", "revision": capture.revision})
    assert (
        capture.status == "published" and public_inventory().filter(pk=capture.property_id).exists()
    )


def test_expiration_hides_property_before_maintenance(owner):
    capture, _ = approved(owner)
    capture = accept(capture.pk, owner, capture.revision, CONTRACT_VERSION)
    set_publication(capture.property_id, True)
    CaptureAgreement.objects.filter(capture=capture).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert not public_inventory().filter(pk=capture.property_id).exists()
    assert Client().get(f"/api/properties/{capture.property_id}").status_code == 404
    with pytest.raises(ValidationError):
        set_publication(capture.property_id, True)
    expire(capture.pk)
    capture.refresh_from_db()
    assert (
        capture.status == "expired" and not Property.objects.get(pk=capture.property_id).published
    )


def test_private_address_coordinates_and_contact_do_not_leak(owner):
    capture, _ = approved(owner)
    capture = accept(capture.pk, owner, capture.revision, CONTRACT_VERSION)
    set_publication(capture.property_id, True)
    result = Client().get(f"/api/properties/{capture.property_id}").json()
    assert "Dirección PRIVADA" not in json.dumps(result) and "owner@example.com" not in json.dumps(
        result
    )
    assert result["public_location"] == {
        "latitude": 20.67,
        "longitude": -103.35,
        "approximate": True,
    }
    assert "private_address" not in result["details"]


def test_minimum_photos_verified_email_and_catalog(owner):
    capture = draft(owner, photos=4)
    with pytest.raises(ValueError, match="cinco"):
        submit(capture.pk, owner, capture.revision)
    owner.email_verified_at = None
    with pytest.raises(ValueError, match="email"):
        submit(capture.pk, owner, capture.revision)
    assert len(KINDS) == 19
    for data in [
        {"operation": "season"},
        {"operation": "rent", "is_presale": True},
        {"kind": "warehouse", "subtype": "Casa de ciudad"},
    ]:
        with pytest.raises(ValueError):
            CaptureData(**data)
    assert CaptureData(is_presale=True).is_presale


def test_foreign_account_and_guest_cannot_access_capture_or_assets(owner):
    capture = draft(owner)
    client, headers = browser()
    assert client.get("/api/capture/requests").status_code == 401
    other = User.objects.create_user(
        "other@example.com",
        "safe-password-other",
        phone="+523312345679",
        email_verified_at=timezone.now(),
    )
    client.force_login(other)
    assert client.get(f"/api/capture/requests/{capture.pk}").status_code == 404
    assert client.get(f"/api/capture/assets/{capture.assets.first().pk}").status_code == 404
    for action in ["submit", "accept", "request"]:
        assert (
            post(
                client, headers, f"/api/capture/requests/{capture.pk}", {"action": action}
            ).status_code
            == 404
        )
    assert client.get("/api/crm/captures").status_code == 403
    assert (
        post(
            client,
            headers,
            "/api/capture/requests",
            {"id": str(capture.pk), "revision": 1, "data": capture.data},
        ).status_code
        == 409
    )
    capture.refresh_from_db()
    assert capture.owner == owner and capture.status == "draft"


def test_write_requires_csrf_and_current_revision(owner):
    capture = draft(owner)
    client, headers = browser()
    client.force_login(owner)
    payload = {"id": str(capture.pk), "revision": 0, "data": capture.data}
    assert post(client, {}, "/api/capture/requests", payload).status_code == 403
    assert post(client, headers, "/api/capture/requests", payload).status_code == 422
    capture.refresh_from_db()
    assert capture.revision == 1


def test_verification_link_for_deleted_account_does_not_verify_recreated_account(owner):
    from django.core import signing

    email = "recreated@example.com"
    old = User.objects.create_user(email, phone="+523312345679")
    token = signing.dumps({"id": old.pk, "email": email}, salt="owner-email")
    old.delete()
    current = User.objects.create_user(email, phone="+523312345679")
    client, headers = browser()
    client.force_login(current)
    response = post(client, headers, "/api/capture/account", {"action": "verify", "token": token})
    assert response.status_code == 422
    assert "Solicita un nuevo correo de verificación" in response.json()["detail"]
    current.refresh_from_db()
    assert current.email_verified_at is None
    assert client.get("/api/capture/requests").status_code == 403


def test_unverified_owner_cannot_access_capture_or_private_files_but_can_resend(owner):
    capture, _ = approved(owner)
    asset = capture.assets.first()
    owner.email_verified_at = None
    owner.save(update_fields=["email_verified_at"])
    client, headers = browser()
    client.force_login(owner)
    path = f"/api/capture/requests/{capture.pk}"
    assert client.get("/api/capture/requests").status_code == 403
    assert client.get(path).status_code == 403
    assert post(client, headers, path, {"action": "accept"}).status_code == 403
    assert post(client, headers, path + "/upload", {}).status_code == 403
    assert client.get(f"/api/capture/assets/{asset.pk}").status_code == 404
    assert client.delete(f"/api/capture/assets/{asset.pk}", **headers).status_code == 403
    assert client.get(path + "/contract").status_code == 404
    assert client.get("/api/capture/account").json()["account"]["verified"] is False
    before = CaptureDelivery.objects.count()
    assert post(client, headers, "/api/capture/account", {"action": "resend"}).status_code == 200
    assert CaptureDelivery.objects.count() == before + 1
    owner.email_verified_at = timezone.now()
    owner.save(update_fields=["email_verified_at"])
    assert client.get("/api/capture/requests").status_code == 200
    assert client.get(path).status_code == 200
    assert client.get(f"/api/capture/assets/{asset.pk}").status_code == 200
    assert client.get(path + "/contract").status_code == 200


def test_signup_verification_and_single_use_password_reset(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    client, headers = browser()
    result = post(
        client,
        headers,
        "/api/capture/account",
        {
            "action": "register",
            "email": "new@example.com",
            "phone": "3312345678",
            "password": "a-long-sensible-password",
        },
    )
    assert result.status_code == 200, result.content
    assert result.json()["account"]["verified"] is False and "token" not in result.json()
    headers = {"HTTP_X_CSRFTOKEN": result.json()["csrf_token"]}
    assert client.get("/api/capture/requests").status_code == 403
    assert (
        post(
            client,
            headers,
            "/api/capture/requests",
            {
                "id": str(uuid.uuid4()),
                "data": {},
                "revision": 0,
            },
        ).status_code
        == 403
    )
    deliver(CaptureDelivery.objects.get(channel="email").pk)
    token = mail.outbox[0].body.split("#verify=", 1)[1].splitlines()[0]
    result = post(client, headers, "/api/capture/account", {"action": "verify", "token": token})
    assert result.status_code == 200 and result.json()["account"]["verified"]
    assert client.get("/api/capture/requests").status_code == 200
    assert (
        post(
            client,
            headers,
            "/api/capture/account",
            {"action": "reset_request", "email": "new@example.com"},
        ).status_code
        == 200
    )
    deliver(CaptureDelivery.objects.get(subject__startswith="Recupera").pk)
    reset = mail.outbox[-1].body.split("#reset=", 1)[1].strip()
    payload = {"action": "reset", "token": reset, "password": "another-long-strong-password"}
    assert post(client, headers, "/api/capture/account", payload).status_code == 200
    assert post(client, headers, "/api/capture/account", payload).status_code == 422
    assert not User.objects.get(email="new@example.com").is_staff


def test_large_image_optimized_orientation_and_metadata():
    source = io.BytesIO()
    image = Image.new("RGB", (4000, 3000), color="lightblue")
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "PRIVATE OWNER"
    image.save(source, format="PNG", exif=exif)
    upload = SimpleUploadedFile("original.png", source.getvalue(), content_type="image/png")
    result, mime, extension = normalize_upload(upload, "photo")
    with Image.open(result) as normalized:
        assert max(normalized.size) <= 2400 and normalized.height > normalized.width
        assert not normalized.getexif() and normalized.format == "WEBP"
    assert mime == "image/webp" and extension == "webp" and result.size < upload.size
    with pytest.raises(ValueError):
        normalize_upload(SimpleUploadedFile("photo.jpg", b"not an image"), "photo")


def test_upload_retries_deduplicate_and_assets_remain_private(owner):
    capture = draft(owner, photos=0)
    client, headers = browser()
    client.force_login(owner)
    source = io.BytesIO()
    Image.new("RGB", (100, 80)).save(source, format="JPEG")
    request_id = uuid.uuid4()

    def upload():
        return client.post(
            f"/api/capture/requests/{capture.pk}/upload",
            {
                "file": SimpleUploadedFile("photo.jpg", source.getvalue()),
                "kind": "photo",
                "request_id": str(request_id),
            },
            **headers,
        )

    result = upload()
    assert result.status_code == 200, result.content
    assert result.json()["assets"][0]["request_id"] == str(request_id)
    assert upload().status_code == 200 and capture.assets.count() == 1
    asset = capture.assets.get()
    assert asset.content_type == "image/webp"
    assert Client().get(f"/api/capture/assets/{asset.pk}").status_code == 404
    assert client.get(f"/api/capture/assets/{asset.pk}").status_code == 200


def test_currency_and_equivalent_types_remain_distinct(owner):
    for currency, kind, subtype in [
        ("MXN", "condominium", ""),
        ("USD", "house", "Casa en condominio"),
    ]:
        Property.objects.create(
            title="Property",
            operation="sale",
            kind=kind,
            subtype=subtype,
            currency=currency,
            municipality="Mérida",
            neighborhood="Centro",
            price="100",
            published=True,
        )
    assert search_inventory(SearchCriteria(kind="condominium"))["total"] == 2
    assert search_inventory(SearchCriteria(max_price=200))["total"] == 1
    assert (
        search_inventory(SearchCriteria(max_price=200, currency="USD"))["results"][0]["currency"]
        == "USD"
    )
    assert search_inventory(SearchCriteria(municipality="Mérida"))["total"] == 2


def test_outside_region_approval_and_corrections_invalidate_acceptance(owner):
    capture = draft(owner, municipality="Mérida", state="Yucatán", is_presale=True)
    capture = submit(capture.pk, owner, capture.revision)
    staff = User.objects.create_user("staff@example.com", "strong-staff-password", is_staff=True)
    with pytest.raises(ValueError, match="zona base"):
        review(
            capture.pk,
            staff,
            {"action": "approve", "revision": capture.revision, "representation_verified": True},
        )
    capture = review(
        capture.pk,
        staff,
        {
            "action": "approve",
            "revision": capture.revision,
            "representation_verified": True,
            "outside_area_approved": True,
        },
    )
    capture = accept(capture.pk, owner, capture.revision, CONTRACT_VERSION)
    set_publication(capture.property_id, True)
    capture = review(
        capture.pk,
        staff,
        {
            "action": "update",
            "revision": capture.revision,
            "data": {**capture.data, "price": "345000"},
        },
    )
    assert capture.status == "submitted" and capture.verified_at is None
    assert not Property.objects.get(pk=capture.property_id).published
    assert not capture.agreements.filter(ended_at__isnull=True).exists()


def test_existing_inventory_unchanged():
    prop = Property.objects.create(
        title="Old inventory",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="Centro",
        price=123,
    )
    set_publication(prop.pk, True)
    assert public_inventory().filter(pk=prop.pk).exists()


def test_renewal_requires_new_acceptance_and_withdrawal_revokes_media(owner):
    capture, staff = approved(owner)
    capture = accept(capture.pk, owner, capture.revision, CONTRACT_VERSION)
    capture = review(capture.pk, staff, {"action": "publish", "revision": capture.revision})
    photo_id = capture.assets.first().pk
    assert Client().get(f"/api/capture/assets/{photo_id}").status_code == 200
    capture = review(capture.pk, staff, {"action": "renew", "revision": capture.revision})
    assert (
        capture.status == "approved"
        and not public_inventory().filter(pk=capture.property_id).exists()
    )
    assert Client().get(f"/api/capture/assets/{photo_id}").status_code == 404
    with pytest.raises(ValidationError):
        set_publication(capture.property_id, True)
    capture = accept(capture.pk, owner, capture.revision, CONTRACT_VERSION)
    assert capture.agreements.count() == 2
    capture = review(capture.pk, staff, {"action": "withdraw", "revision": capture.revision})
    assert (
        capture.status == "withdrawn"
        and not capture.agreements.filter(ended_at__isnull=True).exists()
    )


def test_legacy_editor_cannot_bypass_capture_review(owner):
    from datalayer.inventory import save_property
    from datalayer.schemas import PropertyInput

    capture, _ = approved(owner)
    payload = PropertyInput(
        title="Changed",
        operation="sale",
        kind="house",
        municipality="Zapopan",
        neighborhood="Centro",
        price="1",
        published=True,
    )
    with pytest.raises(ValidationError, match="Captación"):
        save_property(payload, capture.property)
    assert Property.objects.get(pk=capture.property_id).price == 123000


def test_heic_upload_uses_server_decoder():
    from pillow_heif import from_pillow

    output = io.BytesIO()
    from_pillow(Image.new("RGB", (300, 200), "green")).save(output)
    result, mime, _ = normalize_upload(
        SimpleUploadedFile("iphone.heic", output.getvalue()), "photo"
    )
    assert mime == "image/webp"
    with Image.open(result) as normalized:
        assert normalized.size == (300, 200)


def test_uncertain_email_delivery_never_retries(owner, monkeypatch):
    from datalayer.captures import delivery

    calls = []

    def failed_send(*args, **kwargs):
        calls.append(True)
        raise TimeoutError("unknown delivery")

    monkeypatch.setattr("worker.capture_delivery.send_mail", failed_send)
    row = delivery("email", "test-uncertain", owner.email, "PRUEBA", "Test-only body")
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "uncertain"
    deliver(row.pk)
    assert len(calls) == 1


def test_capture_requests_and_valuation_are_private_until_communicated(owner):
    from datalayer.captures import output, owner_request

    capture, staff = approved(owner)
    capture = owner_request(capture.pk, owner, "change", "Corrige una característica")
    with pytest.raises(ValueError, match="pendiente"):
        owner_request(capture.pk, owner, "withdraw", "Retirar")
    capture = review(
        capture.pk,
        staff,
        {
            "action": "valuation",
            "revision": capture.revision,
            "valuation": "100000",
            "valuation_notes": "Private draft",
        },
    )
    assert output(capture)["valuation"] == ""
    capture = review(
        capture.pk,
        staff,
        {
            "action": "valuation",
            "revision": capture.revision,
            "valuation": "100000",
            "valuation_notes": "Comunicada",
            "communicated": True,
        },
    )
    assert output(capture)["valuation"] == "100000"
    assert not owner.is_staff


def test_photo_limit_is_twenty_and_retry_at_limit_is_idempotent(owner):
    from datalayer.capture_assets import upload
    from datalayer.capture_catalog import catalog
    from datalayer.models import CaptureAsset

    capture = draft(owner, photos=0)
    for _ in range(20):
        CaptureAsset.objects.create(
            capture=capture, request_id=uuid.uuid4(), kind="photo",
            file="capture/test-only.webp", content_type="image/webp", size=10,
        )
    limits = catalog()["upload_limits"]
    assert limits == {"min_photos": 5, "max_photos": 20, "max_plans": 5}
    # A replay remains valid at capacity and does not decode/store another file.
    first = capture.assets.first()
    upload(owner, capture.pk, "photo", first.request_id, None)
    image = io.BytesIO()
    Image.new("RGB", (8, 8)).save(image, "PNG")
    with pytest.raises(ValueError, match="máximo"):
        upload(owner, capture.pk, "photo", uuid.uuid4(),
               SimpleUploadedFile("extra.png", image.getvalue(), content_type="image/png"))
    assert capture.assets.filter(kind="photo").count() == 20


def test_rotating_photo_changes_preview_url_without_exposing_storage_path(owner):
    from datalayer.capture_assets import rotate, upload
    from datalayer.captures import output

    capture = draft(owner, photos=0)
    source = io.BytesIO()
    Image.new("RGB", (30, 10), "green").save(source, "PNG")
    capture = upload(owner, capture.pk, "photo", uuid.uuid4(),
                     SimpleUploadedFile("photo.png", source.getvalue()))
    before = output(capture)["assets"][0]["url"]
    capture = rotate(owner, capture.pk, capture.assets.get().pk, capture.revision)
    after = output(capture)["assets"][0]["url"]
    assert before != after
    assert capture.assets.get().file.name not in after

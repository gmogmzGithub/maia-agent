"""Owner-authorized file mutations; normalization precedes short persistence locks."""

import uuid

from django.db import transaction

from datalayer.capture_catalog import UPLOAD_LIMITS
from datalayer.capture_media import normalize_upload
from datalayer.captures import check_revision
from datalayer.models import Capture, CaptureAsset


def upload(owner, capture_id, kind, request_id, uploaded_file):
    capture = Capture.objects.get(pk=capture_id, owner=owner, status="draft")
    if kind not in {"photo", "plan"}:
        raise ValueError("Archivo inválido")
    existing = capture.assets.filter(request_id=request_id).first()
    if existing:
        return capture
    content, content_type, extension = normalize_upload(uploaded_file, kind)
    # CPU/decoding runs without an open transaction. Check status again under lock.
    with transaction.atomic():
        capture = Capture.objects.select_for_update().get(
            pk=capture_id, owner=owner, status="draft"
        )
        if capture.assets.filter(request_id=request_id).exists():
            return capture
        if capture.assets.filter(kind=kind).count() >= (UPLOAD_LIMITS["max_photos"] if kind == "photo" else UPLOAD_LIMITS["max_plans"]):
            raise ValueError("Alcanzaste el máximo de archivos de este tipo.")
        asset = CaptureAsset(
            capture=capture,
            kind=kind,
            request_id=request_id,
            content_type=content_type,
            position=capture.assets.count(),
            size=content.size,
        )
        asset.file.save(f"{uuid.uuid4()}.{extension}", content, save=False)
        try:
            asset.save()
            capture.revision += 1
            capture.save()
        except Exception:
            asset.file.delete(save=False)
            raise
    return capture


def rotate(owner, capture_id, asset_id, revision):
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image

    # Decode and compress before taking the short persistence lock, like uploads.
    capture = Capture.objects.get(pk=capture_id, owner=owner, status="draft")
    check_revision(capture, revision)
    asset = capture.assets.get(pk=asset_id, content_type="image/webp")
    with asset.file.open("rb") as source, Image.open(source) as image:
        output = BytesIO()
        image.rotate(-90, expand=True).save(output, "PNG")
    content, _, _ = normalize_upload(ContentFile(output.getvalue()), "photo")
    with transaction.atomic():
        capture = Capture.objects.select_for_update().get(
            pk=capture_id, owner=owner, status="draft"
        )
        check_revision(capture, revision)
        row = capture.assets.get(pk=asset_id, content_type="image/webp")
        storage, old_name = row.file.storage, row.file.name
        row.file.save(f"{uuid.uuid4()}.webp", content, save=False)
        try:
            row.size = content.size
            row.save()
            transaction.on_commit(lambda: storage.delete(old_name))
            capture.revision += 1
            capture.save()
        except Exception:
            row.file.delete(save=False)
            raise
    return capture


def reorder(owner, capture_id, ids, revision):
    with transaction.atomic():
        capture = Capture.objects.select_for_update().get(
            pk=capture_id, owner=owner, status="draft"
        )
        check_revision(capture, revision)
        rows = {str(a.pk): a for a in capture.assets.all()}
        if not isinstance(ids, list) or len(ids) != len(rows) or set(ids) != set(rows):
            raise ValueError("Orden inválido")
        for position, asset_id in enumerate(ids):
            CaptureAsset.objects.filter(pk=rows[asset_id].pk).update(position=position)
        capture.revision += 1
        capture.save()
    return capture


@transaction.atomic
def delete(owner, asset_id):
    row = CaptureAsset.objects.get(pk=asset_id)
    capture = Capture.objects.select_for_update().get(
        pk=row.capture_id, owner=owner, status="draft"
    )
    row.delete()
    transaction.on_commit(lambda: row.file.delete(save=False))
    capture.revision += 1
    capture.save()
    return capture

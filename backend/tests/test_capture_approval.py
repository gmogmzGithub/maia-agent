from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from datalayer.capture_approval import approval_matches
from datalayer.captures import review
from datalayer.models import GoogleLocation
from tests.test_capture import approved
from tests.test_capture import owner as owner
from worker.capture_delivery import deliver

pytestmark = pytest.mark.django_db(transaction=True)


def google_approval(owner):
    point = GoogleLocation.objects.create(
        owner=owner,
        place_id="test-private-location",
        latitude=20.67,
        longitude=-103.35,
        expires_at=timezone.now() + timedelta(days=29),
    )
    capture, staff = approved(
        owner,
        location_ref=str(point.pk),
        latitude=None,
        longitude=None,
        location_confirmed=True,
    )
    return capture, staff, capture.deliveries.get(channel="email")


def retry(capture, staff, row):
    return review(
        capture.pk,
        staff,
        {"action": "retry_delivery", "revision": capture.revision, "delivery_id": row.pk},
    )


def test_google_approval_retry_and_initial_delivery_use_same_commercial_identity(owner):
    capture, staff, row = google_approval(owner)
    assert capture.data["location_ref"]
    assert "location_ref" not in row.attachment["data"]
    row.status = "failed"
    row.save()

    retry(capture, staff, row)
    deliver(row.pk)
    deliver(row.pk)

    row.refresh_from_db()
    assert row.status == "sent"
    assert len(mail.outbox) == 1
    capture.refresh_from_db()
    assert capture.status == "approved" and not capture.agreements.exists()


def test_refreshing_provider_reference_or_capture_revision_keeps_approval_valid(owner):
    capture, staff, row = google_approval(owner)
    replacement = GoogleLocation.objects.create(
        owner=owner,
        place_id="test-refreshed-location",
        latitude=20.67,
        longitude=-103.35,
        expires_at=timezone.now() + timedelta(days=29),
    )
    capture.data = {**capture.data, "location_ref": str(replacement.pk)}
    capture.revision += 1
    capture.save()
    assert approval_matches(capture, row.attachment)
    row.status = "blocked"
    row.save()

    retry(capture, staff, row)
    deliver(row.pk)

    row.refresh_from_db()
    assert row.status == "sent" and len(mail.outbox) == 1


@pytest.mark.parametrize("change", ["commercial_data", "reviewed_at", "missing_review", "status"])
def test_changed_approval_blocks_both_retry_and_pending_delivery(owner, change):
    capture, staff, row = google_approval(owner)
    if change == "commercial_data":
        capture.data = {**capture.data, "price": "456000"}
    elif change == "reviewed_at":
        capture.verified_at += timedelta(seconds=1)
    elif change == "missing_review":
        capture.verified_at = None
    else:
        capture.status = "submitted"
    capture.save()
    row.status = "failed"
    row.save()
    assert not approval_matches(capture, row.attachment)

    with pytest.raises(ValueError, match="La aprobación cambió"):
        retry(capture, staff, row)
    row.refresh_from_db()
    assert row.status == "failed"

    row.status = "pending"
    row.save()
    deliver(row.pk)
    row.refresh_from_db()
    assert row.status == "superseded"
    assert row.error_code == "approval_no_longer_current"
    assert not mail.outbox

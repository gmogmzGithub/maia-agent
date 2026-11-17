import uuid

import pytest

from datalayer.captures import submit
from datalayer.models import User
from tests.test_capture import draft, post
from tests.test_capture import owner as owner
from tests.test_increment import browser

pytestmark = pytest.mark.django_db(transaction=True)


def test_schema_errors_preserve_first_detail_and_expose_all_fields_without_inputs(owner):
    client, headers = browser()
    client.force_login(owner)
    response = post(
        client,
        headers,
        "/api/capture/requests",
        {
            "id": str(uuid.uuid4()),
            "revision": 0,
            "data": {"price": "-1", "currency": "INVALID", "private_address": "PRIVATE"},
        },
    )
    assert response.status_code == 422
    value = response.json()
    assert value["detail"] == value["errors"][0]["message"]
    assert {issue["field"] for issue in value["errors"]} == {"price", "currency"}
    assert all(set(issue) == {"field", "message", "code"} for issue in value["errors"])
    assert "PRIVATE" not in response.content.decode()


@pytest.mark.parametrize(
    ("representation", "field", "code", "detail"),
    [
        (
            False,
            "representation_verified",
            "representation_verification_required",
            "Confirma que verificaste al propietario o representante.",
        ),
        (
            True,
            "outside_area_approved",
            "outside_area_approval_required",
            "Aprueba expresamente la captación fuera de la zona base.",
        ),
    ],
)
def test_review_validation_exposes_stable_field_and_code(
    owner, representation, field, code, detail
):
    capture = draft(owner, municipality="Tepatitlán")
    capture = submit(capture.pk, owner, capture.revision)
    staff = User.objects.create_user("review-errors@example.com", is_staff=True)
    client, headers = browser()
    client.force_login(staff)
    response = post(
        client,
        headers,
        f"/api/crm/captures/{capture.pk}",
        {
            "action": "approve",
            "revision": capture.revision,
            "representation_verified": representation,
            "outside_area_approved": False,
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": detail,
        "errors": [{"message": detail, "field": field, "code": code}],
    }
    capture.refresh_from_db()
    assert capture.status == "submitted" and not capture.property_id


def test_photo_requirement_has_a_field_without_changing_existing_detail(owner):
    capture = draft(owner, photos=4)
    client, headers = browser()
    client.force_login(owner)
    response = post(
        client,
        headers,
        f"/api/capture/requests/{capture.pk}",
        {"action": "submit", "revision": capture.revision},
    )
    assert response.status_code == 422
    value = response.json()
    assert value["detail"] == "Agrega al menos cinco fotos para enviar la solicitud."
    assert value["errors"][0]["field"] == "photos"
    assert value["errors"][0]["code"] == "minimum_photos_required"

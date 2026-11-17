import json

import pytest

from datalayer.models import Property
from tests.test_increment import browser
from tests.test_prospects import staff_browser

pytestmark = pytest.mark.django_db(transaction=True)


def make_property():
    return Property.objects.create(
        title="PRUEBA · Publicación",
        operation="sale",
        kind="land",
        municipality="Zapopan",
        neighborhood="Centro",
        price=1500000,
        internal_notes="Información privada",
        published=True,
    )


def test_publication_action_requires_staff_csrf_and_accepts_only_publication():
    prop = make_property()
    path = f"/api/crm/properties/{prop.pk}/publication"
    guest, headers = browser()
    assert (
        guest.patch(
            path, data=json.dumps({"published": False}), content_type="application/json", **headers
        ).status_code
        == 401
    )
    staff, headers, _ = staff_browser()
    assert (
        staff.patch(
            path, data=json.dumps({"published": False}), content_type="application/json"
        ).status_code
        == 403
    )
    assert (
        staff.patch(
            path,
            data=json.dumps({"published": False, "price": "1"}),
            content_type="application/json",
            **headers,
        ).status_code
        == 422
    )
    prop.refresh_from_db()
    assert prop.published
    assert (
        staff.patch(
            "/api/crm/properties/999999/publication",
            data=json.dumps({"published": False}),
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )


def test_publication_action_preserves_fields_and_changes_public_visibility():
    prop = make_property()
    staff, headers, _ = staff_browser()
    path = f"/api/crm/properties/{prop.pk}/publication"
    Property.objects.filter(pk=prop.pk).update(
        price=1600000, internal_notes="Actualizada por otro asesor"
    )
    for published in (False, False, True):
        result = staff.patch(
            path,
            data=json.dumps({"published": published}),
            content_type="application/json",
            **headers,
        )
        assert result.status_code == 200 and result.json()["published"] is published
        assert result.json()["price"] == "1600000.00"
        assert result.json()["reference"] == prop.reference
        assert result.json()["internal_notes"] == "Actualizada por otro asesor"
        assert staff.get(f"/api/properties/{prop.pk}").status_code == (200 if published else 404)
        ids = [p["id"] for p in staff.get("/api/properties").json()["results"]]
        assert (prop.pk in ids) is published

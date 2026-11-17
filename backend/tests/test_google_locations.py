import json
import uuid
from datetime import timedelta

import httpx
import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from datalayer import google_locations as geo
from datalayer.capture_schemas import CaptureData
from datalayer.captures import accept, output, save_draft
from datalayer.inventory import public_property, set_publication
from datalayer.models import GoogleLocation, GoogleLocationUsage, GoogleSearchSession, User
from tests.test_capture import approved
from tests.test_capture import owner as owner

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def google(settings, monkeypatch):
    settings.GOOGLE_MAPS_BROWSER_KEY = "browser-test-only"
    settings.GOOGLE_MAPS_SERVER_KEY = "server-test-only"
    settings.GOOGLE_LOCATION_MONTHLY_LIMITS = dict(
        autocomplete=10000, details=3000, maps=3000, zone=1000
    )
    calls = []

    class Provider:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("places:autocomplete"):
                result = {
                    "suggestions": [
                        {
                            "placePrediction": {
                                "placeId": "private-place",
                                "text": {"text": "Dirección de prueba, Zapopan"},
                            }
                        }
                    ]
                }
            else:
                result = {
                    "places": [
                        {"id": "public-zone", "location": {"latitude": 20.7, "longitude": -103.4}}
                    ]
                }
            return httpx.Response(200, json=result)

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            result = {
                "id": "private-place",
                "location": {"latitude": 20.674321, "longitude": -103.353456},
                "addressComponents": [
                    {"types": ["country"], "longText": "México", "shortText": "MX"},
                    {"types": ["route"], "longText": "Calle de prueba"},
                    {"types": ["street_number"], "longText": "123"},
                    {"types": ["administrative_area_level_1"], "longText": "Jalisco"},
                    {"types": ["administrative_area_level_2"], "longText": "Zapopan"},
                    {"types": ["sublocality_level_1"], "longText": "Colonia de prueba"},
                ],
            }
            return httpx.Response(200, json=result)

    monkeypatch.setattr(geo.httpx, "Client", Provider)
    return calls


def api(owner):
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    token = client.get("/api/session").json()["csrf_token"]
    return client, {"HTTP_X_CSRFTOKEN": token}


def post(client, headers, value):
    return client.post(
        "/api/location/search", data=json.dumps(value), content_type="application/json", **headers
    )


def test_search_selection_session_fields_and_private_credentials(owner, google):
    client, headers = api(owner)
    assert post(client, {}, {"action": "suggest", "text": "Calle"}).status_code == 403
    result = post(client, headers, {"action": "suggest", "text": "Calle de prueba"})
    assert result.status_code == 200
    assert "server-test-only" not in result.content.decode()
    session = result.json()["session"]
    result = post(
        client, headers, {"action": "resolve", "place_id": "private-place", "session": session}
    )
    assert result.status_code == 200
    value = result.json()
    assert value["fields"] == {
        "private_address": "Calle de prueba 123",
        "state": "Jalisco",
        "municipality": "Zapopan",
        "neighborhood": "Colonia de prueba",
    }
    assert value["location"]["latitude"] == 20.674321
    row = GoogleLocation.objects.get(pk=value["location"]["id"])
    assert row.expires_at < timezone.now() + timedelta(days=30)
    assert GoogleSearchSession.objects.get(pk=session).completed
    assert (
        post(
            client, headers, {"action": "resolve", "place_id": "private-place", "session": session}
        ).status_code
        == 422
    )
    assert google[0][1]["json"]["includedRegionCodes"] == ["mx"]
    assert (
        "locationBias" in google[0][1]["json"] and "locationRestriction" not in google[0][1]["json"]
    )
    assert google[1][1]["params"]["sessionToken"] == session
    assert google[1][1]["headers"]["X-Goog-FieldMask"] == "id,addressComponents,location"
    assert not google[1][1]["params"].get("key")


def test_second_owner_and_unverified_account_cannot_reuse_private_location(owner, google):
    point = geo.map_point(owner, 20.67, -103.35)
    other = User.objects.create_user(
        "different@example.com", phone="+523312345679", email_verified_at=timezone.now()
    )
    session = geo.search_session(owner)
    client, headers = api(other)
    assert client.get(f"/api/location/points/{point['id']}").status_code == 404
    assert (
        post(
            client, headers, {"action": "suggest", "text": "Calle", "session": str(session.pk)}
        ).status_code
        == 422
    )
    with pytest.raises(ValidationError):
        save_draft(other, {"location_ref": point["id"]}, uuid.uuid4(), 0)
    other.email_verified_at = None
    other.save()
    assert post(client, headers, {"action": "suggest", "text": "Calle"}).status_code == 403
    assert google == []


def test_google_coordinates_and_reference_not_copied_to_contract_or_public_snapshot(owner, google):
    capture, staff = approved(owner)
    row = GoogleLocation.objects.create(
        owner=owner,
        place_id="private-place",
        latitude=20.674321,
        longitude=-103.353456,
        expires_at=timezone.now() + geo.TTL,
    )
    capture.data.update(
        location_ref=str(row.pk), latitude=None, longitude=None, location_confirmed=True
    )
    capture.save()
    from datalayer.capture_contract import contract_snapshot
    from datalayer.captures import sync_property

    capture.exact_location_approved = False
    capture.save()
    sync_property(capture)
    snapshot = contract_snapshot(capture)
    assert "location_ref" not in snapshot["data"]
    assert "20.674321" not in json.dumps(snapshot)
    assert output(capture)["location"]["latitude"] == 20.674321
    capture = accept(capture.pk, owner, capture.revision, snapshot["version"])
    assert "location_ref" not in capture.agreements.get().snapshot
    set_publication(capture.property_id, True)
    capture.property.refresh_from_db()
    assert capture.property.public_location == {"lookup": True, "approximate": True}
    assert "20.674321" not in json.dumps(public_property(capture.property))
    public = Client().get(f"/api/location/properties/{capture.property_id}")
    assert public.status_code == 200
    assert public.json()["location"] == {"latitude": 20.7, "longitude": -103.4, "approximate": True}
    assert "private-place" not in public.content.decode()
    assert str(row.pk) not in public.content.decode()
    assert public["Cache-Control"] == "private, no-store"
    assert google[-1][1]["json"]["textQuery"] == "Centro, Zapopan, Jalisco, México"
    assert "Dirección PRIVADA" not in str(google)


def test_public_endpoint_does_not_disclose_expired_or_unpublished_capture(owner, google):
    capture, _ = approved(owner)
    assert Client().get(f"/api/location/properties/{capture.property_id}").status_code == 404
    assert google == []


def test_quota_stops_before_request_and_missing_config_is_manual_fallback(owner, google, settings):
    settings.GOOGLE_LOCATION_MONTHLY_LIMITS = {
        **settings.GOOGLE_LOCATION_MONTHLY_LIMITS,
        "autocomplete": 1,
    }
    geo.suggestions(owner, "Calle")
    with pytest.raises(geo.LocationUnavailable):
        geo.suggestions(owner, "Otra calle")
    assert len(google) == 1
    assert GoogleLocationUsage.objects.get(sku="autocomplete").count == 1
    settings.GOOGLE_MAPS_SERVER_KEY = ""
    client, headers = api(owner)
    assert client.get("/api/location/config").json() == {"enabled": False}
    assert post(client, headers, {"action": "suggest", "text": "Calle"}).status_code == 503
    assert len(google) == 1


def test_maintenance_refreshes_only_provider_point_without_changing_contract_or_manual_pin(
    owner, google
):
    automatic = GoogleLocation.objects.create(
        owner=owner,
        place_id="private-place",
        latitude=20,
        longitude=-103,
        expires_at=timezone.now() + timedelta(days=1),
    )
    capture = save_draft(owner, {"location_ref": str(automatic.pk)}, uuid.uuid4(), 0)
    original = dict(capture.data)
    revision = capture.revision
    manual = GoogleLocation.objects.create(
        owner=owner,
        source="map",
        latitude=21,
        longitude=-104,
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    geo.maintain()
    automatic.refresh_from_db()
    manual.refresh_from_db()
    capture.refresh_from_db()
    assert automatic.latitude == 20.674321
    assert manual.latitude is None and manual.longitude is None
    assert capture.data == original and capture.revision == revision
    assert geo.point_output(manual)["needs_confirmation"]
    assert len(google) == 1


def test_reference_location_requires_point_and_does_not_invent_neighborhood():
    data = CaptureData(
        name="Propietario",
        kind="ranch",
        municipality="Zapopan",
        location_mode="reference",
        location_reference="Acceso por camino rural",
        latitude=20.67,
        longitude=-103.35,
        price="123000",
        phone_confirmed=True,
    )
    data.check_complete()
    assert not data.neighborhood and not data.private_address
    with pytest.raises(ValueError):
        data.model_copy(update={"latitude": None, "longitude": None}).check_complete()
    with pytest.raises(ValueError):
        data.model_copy(update={"kind": "house"}).check_complete()


def test_missing_components_do_not_turn_locality_into_municipality():
    fields = geo.components(
        {
            "addressComponents": [
                {"types": ["country"], "shortText": "MX", "longText": "México"},
                {"types": ["locality"], "longText": "Localidad"},
            ]
        }
    )
    assert "municipality" not in fields and "neighborhood" not in fields


def test_state_names_are_normalized_without_defaulting_to_jalisco():
    def fields(state):
        return geo.components(
            {
                "addressComponents": [
                    {"types": ["country"], "shortText": "MX", "longText": "México"},
                    {"types": ["administrative_area_level_1"], "longText": state},
                ]
            }
        )

    assert fields("Michoacán de Ocampo")["state"] == "Michoacán"
    assert "state" not in fields("No reconocido")


def test_staff_can_locate_for_capture_owner_but_owner_cannot_impersonate_another(owner, google):
    capture, staff = approved(owner)
    client, headers = api(staff)
    result = post(
        client,
        headers,
        {"action": "point", "capture_id": str(capture.pk), "latitude": 20.67, "longitude": -103.35},
    )
    assert result.status_code == 200
    row = GoogleLocation.objects.get(pk=result.json()["location"]["id"])
    assert row.owner == owner
    assert client.get(f"/api/location/points/{row.pk}").status_code == 200
    client, headers = api(owner)
    assert (
        post(
            client,
            headers,
            {
                "action": "point",
                "capture_id": str(capture.pk),
                "latitude": 20.67,
                "longitude": -103.35,
            },
        ).status_code
        == 403
    )


def test_provider_failure_is_safe_and_map_key_is_separate(owner, google, monkeypatch):
    client, headers = api(owner)
    result = client.post(
        "/api/location/map-session", data="{}", content_type="application/json", **headers
    )
    assert result.status_code == 200 and result.json()["key"] == "browser-test-only"
    assert "server-test-only" not in result.content.decode()

    class FailedProvider:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, *args, **kwargs):
            return httpx.Response(
                403, json={"error": {"message": "server-test-only private input"}}
            )

    monkeypatch.setattr(geo.httpx, "Client", FailedProvider)
    result = post(client, headers, {"action": "suggest", "text": "Calle de prueba"})
    assert result.status_code == 503
    assert (
        "server-test-only" not in result.content.decode()
        and "private input" not in result.content.decode()
    )


@pytest.mark.parametrize("point", [(True, 0), (float("nan"), 1), (90.1, 0), (None, -103)])
def test_invalid_points_are_rejected(point):
    with pytest.raises(ValidationError):
        geo.valid_point(*point)


def test_saved_draft_survives_logout_and_password_login_with_private_point(owner):
    point = geo.map_point(owner, 20.67, -103.35)
    client, headers = api(owner)
    capture_id = str(uuid.uuid4())
    payload = {
        "id": capture_id,
        "revision": 0,
        "data": {
            "title": "Borrador persistido",
            "private_address": "Calle propia 123",
            "municipality": "Zapopan",
            "neighborhood": "Centro",
            "location_ref": point["id"],
        },
    }
    response = client.post(
        "/api/capture/requests",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert (
        client.post(
            "/api/auth/logout", data="{}", content_type="application/json", **headers
        ).status_code
        == 200
    )
    assert client.get(f"/api/capture/requests/{capture_id}").status_code == 401
    headers = {"HTTP_X_CSRFTOKEN": client.get("/api/session").json()["csrf_token"]}
    response = client.post(
        "/api/capture/account",
        data=json.dumps(
            {"action": "login", "email": owner.email, "password": "some-long-safe-password"}
        ),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    resumed = client.get(f"/api/capture/requests/{capture_id}")
    assert resumed.status_code == 200
    assert resumed.json()["data"]["title"] == "Borrador persistido"
    assert resumed.json()["data"]["latitude"] is None
    assert resumed.json()["location"]["id"] == point["id"]
    assert resumed.json()["location"]["latitude"] == 20.67
    second = User.objects.create_user(
        "second-owner@example.com", phone="+523312345679", email_verified_at=timezone.now()
    )
    client, _ = api(second)
    assert client.get(f"/api/capture/requests/{capture_id}").status_code == 404
    assert client.get(f"/api/location/points/{point['id']}").status_code == 404

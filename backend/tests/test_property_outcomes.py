import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from datalayer import closings, property_records
from datalayer.inventory import public_property, save_property
from datalayer.models import Advisor, Capture, Closing, Property, User
from datalayer.schemas import PropertyInput

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def team():
    actor = User.objects.create_user(email="property-actor@example.test", is_staff=True)
    advisor = Advisor.objects.create(name="Asesor de propiedad")
    return actor, advisor


def internal(team):
    return save_property(
        PropertyInput.model_validate(
            {
                "title": "Casa conservada",
                "operation": "sale",
                "kind": "house",
                "currency": "MXN",
                "state": "Jalisco",
                "municipality": "Guadalajara",
                "neighborhood": "Americana",
                "price": "3500000",
                "published": True,
                "advisor_id": team[1].pk,
                "area_m2": "200",
                "land_m2": "150",
                "private_data": {
                    "private_address": "Libertad 123 interior 4",
                    "characteristics": {
                        "age_type": "years",
                        "age_years": 12,
                        "condition": "Bueno",
                        "amenities": ["Cocina integral"],
                    },
                },
            }
        ),
        actor=team[0],
    )


def complete(team, offer):
    view = property_records.result(team[0], offer.pk)
    assert view["missing_profile"] == []
    preview = property_records.prepare(
        team[0],
        offer.pk,
        {
            "request_id": str(uuid.uuid4()),
            "source": view["source"],
            "date": "2022-06-12",
            "price": "3100000.50",
            "currency": "MXN",
        },
    )
    result = closings.command(
        team[0],
        preview["id"],
        action="confirm",
        request_id=uuid.uuid4(),
        revision=preview["revision"],
        preview_token=preview["preview_token"],
        reviewed_duplicates=preview["duplicates"],
    )
    return result


def test_internal_property_closes_with_only_final_price_and_date(team):
    offer = internal(team)
    result = complete(team, offer)
    assert result["data"]["address_text"] == "Libertad 123 interior 4"
    assert result["data"]["exterior_number"] == ""
    assert result["data"]["land_m2"] == "150.00"
    assert result["data"]["construction_m2"] == "200.00"
    assert result["data"]["characteristics"]["age_years"] == 12
    offer.refresh_from_db()
    assert not offer.published and offer.price == Decimal("3500000")
    assert property_records.result(team[0], offer.pk)["property"]["commercial_status"] == "sold"
    public = public_property(offer)
    assert "private_data" not in public and "Libertad" not in str(public)


def test_external_capture_reuses_address_and_characteristics_without_new_form(team):
    offer = Property.objects.create(
        title="Casa captada",
        operation="rent",
        kind="apartment",
        state="Jalisco",
        municipality="Zapopan",
        neighborhood="Centro",
        price="20000",
        advisor=team[1],
    )
    owner = User.objects.create_user(email="property-owner@example.test")
    Capture.objects.create(
        owner=owner,
        property=offer,
        status="accepted",
        data={
            "private_address": "Hidalgo 8, departamento 7",
            "state": "Jalisco",
            "municipality": "Zapopan",
            "neighborhood": "Centro",
            "private_m2": "75",
            "land_m2": None,
            "bedrooms": 2,
            "bathrooms": "1.5",
            "amenities": ["Alberca"],
            "location_ref": str(uuid.uuid4()),
        },
    )
    result = complete(team, offer)
    assert result["data"]["address_text"] == "Hidalgo 8, departamento 7"
    assert result["data"]["characteristics"]["bedrooms"] == 2
    assert result["data"]["private_m2"] == "75.00"
    assert "location_ref" not in str(result["data"])


def test_withdrawal_preserves_unsold_data_and_does_not_create_final_price(team):
    offer = internal(team)
    original = property_records.snapshot(offer)
    property_records.withdraw(
        team[0], offer.pk, "El propietario canceló la comercialización", original
    )
    offer.refresh_from_db()
    assert not Closing.objects.exists()
    assert offer.private_data["private_address"] == "Libertad 123 interior 4"
    assert offer.land_m2 == Decimal("150") and offer.price == Decimal("3500000")
    view = property_records.result(team[0], offer.pk)
    assert view["property"]["commercial_status"] == "withdrawn"
    assert view["operations"] == []
    assert view["history"][-1]["actor_email"] == team[0].email
    saved = offer.record_events.get(action="withdraw").snapshot
    assert saved["facts"]["price"] is None
    assert saved["facts"]["characteristics"]["age_years"] == 12
    property_records.restore(team[0], offer.pk, "Volver a revisión", view["source"])
    offer.refresh_from_db()
    assert offer.withdrawn_at is None and not offer.published


def test_old_incomplete_property_is_fixed_at_source_not_in_a_closing_form(team):
    offer = Property.objects.create(
        title="Anterior",
        operation="sale",
        kind="house",
        state="Jalisco",
        municipality="Guadalajara",
        neighborhood="Centro",
        price="2000000",
        advisor=team[1],
    )
    view = property_records.result(team[0], offer.pk)
    assert "street" in view["missing_profile"]
    with pytest.raises(ValidationError):
        property_records.prepare(
            team[0],
            offer.pk,
            {
                "source": view["source"],
                "date": "2022-06-12",
                "price": "1800000",
                "request_id": str(uuid.uuid4()),
            },
        )
    assert not Closing.objects.exists()
    offer.private_data = {"private_address": "Dirección exacta aportada por el asesor"}
    offer.save(update_fields=["private_data", "updated_at"])
    assert property_records.result(team[0], offer.pk)["missing_profile"] == []


def test_changing_source_after_review_requires_new_review(team):
    offer = internal(team)
    source = property_records.result(team[0], offer.pk)["source"]
    offer.area_m2 = Decimal("225")
    offer.save(update_fields=["area_m2", "updated_at"])
    with pytest.raises(closings.ClosingConflict):
        property_records.prepare(
            team[0],
            offer.pk,
            {
                "source": source,
                "date": "2022-06-12",
                "price": "3000000",
                "request_id": str(uuid.uuid4()),
            },
        )
    assert not Closing.objects.exists()


def test_owner_contract_cancellation_keeps_capture_agreement_and_property_facts(team):
    from datetime import timedelta

    from django.utils import timezone

    from datalayer.models import CaptureAgreement

    offer = internal(team)
    owner = User.objects.create_user(email="cancel-owner@example.test")
    original = {
        "private_address": "Hidalgo 44 departamento 2",
        "price": "3500000",
        "currency": "MXN",
        "land_m2": "150",
        "age_type": "years",
        "age_years": 12,
        "location_ref": str(uuid.uuid4()),
    }
    capture = Capture.objects.create(owner=owner, property=offer, status="published", data=original)
    agreement = CaptureAgreement.objects.create(
        capture=capture,
        accepted_by=owner,
        accepted_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=30),
        version="accepted",
        text="Contrato aceptado que debe conservarse",
        snapshot={"price": "3500000"},
    )
    source = property_records.result(team[0], offer.pk)["source"]
    property_records.withdraw(team[0], offer.pk, "El propietario canceló el contrato", source)
    capture.refresh_from_db()
    agreement.refresh_from_db()
    offer.refresh_from_db()
    assert capture.status == "withdrawn" and capture.data == original
    assert (
        agreement.ended_at
        and agreement.text == "Contrato aceptado que debe conservarse"
        and agreement.snapshot == {"price": "3500000"}
    )
    assert not offer.published and not Closing.objects.exists()
    archived = capture.events.get(action="withdraw").snapshot
    assert archived["private_data"]["private_address"] == original["private_address"]
    assert "location_ref" not in archived
    assert "location_ref" not in archived["private_data"]
    assert original["location_ref"] not in str(archived)
    assert (
        property_records.result(team[0], offer.pk)["profile"]["address_text"]
        == original["private_address"]
    )

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from datalayer import closings
from datalayer.closing_schemas import ClosingData
from datalayer.inventory import set_publication
from datalayer.models import (
    Advisor,
    Capture,
    CaptureAgreement,
    Closing,
    ClosingRevision,
    OfferClosure,
    PhysicalProperty,
    Property,
    User,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def team():
    admin = User.objects.create_user(
        email="closing-admin@example.test", is_staff=True, is_superuser=True
    )
    seller = User.objects.create_user(email="closing-seller@example.test", is_staff=True)
    advisor = Advisor.objects.create(name="Responsable")
    return admin, seller, advisor


def facts(team, **changes):
    result = dict(
        operation="sale",
        price="3100000.00",
        currency="MXN",
        year=2022,
        month=6,
        day=12,
        kind="house",
        state="Jalisco",
        municipality="Guadalajara",
        zone_type="colonia",
        zone="Americana",
        street="Libertad",
        exterior_number="123",
        interior_applicable=False,
        responsible_id=team[2].pk,
        land_m2="150",
        construction_m2="200",
    )
    result.update(changes)
    return result


def draft(team, **kwargs):
    return closings.create_draft(team[1], request_id=uuid.uuid4(), data=facts(team), **kwargs)


def confirm(team, row, **changes):
    summary = closings.preview(team[1], row["id"])
    params = dict(
        action="confirm",
        request_id=uuid.uuid4(),
        revision=summary["revision"],
        preview_token=summary["preview_token"],
        reviewed_duplicates=summary["duplicates"],
    )
    params.update(changes)
    return closings.command(team[1], row["id"], **params)


def offer():
    return Property.objects.create(
        title="Casa",
        operation="sale",
        kind="house",
        state="Jalisco",
        municipality="Guadalajara",
        neighborhood="Americana",
        price="3500000",
        published=True,
    )


def test_partial_historical_date_and_unknown_surfaces(team):
    value = facts(team, month=None, day=None, land_m2=None, construction_m2=None)
    row = closings.create_draft(team[0], request_id=uuid.uuid4(), data=value)
    assert row["data"]["year"] == 2022 and row["data"]["month"] is None
    assert "construction_m2" in row["missing_characteristics"]
    with pytest.raises(ValidationError):
        confirm(team, row)


def test_immutable_history_and_rent_independent_of_sale(team):
    row = confirm(team, draft(team))
    assert row["status"] == "confirmed"
    rental = closings.create_draft(
        team[1],
        request_id=uuid.uuid4(),
        data=facts(team, operation="rent", price="16000"),
        physical_property_id=row["physical_property_id"],
    )
    confirm(team, rental)
    correction = closings.command(
        team[1],
        row["id"],
        action="correct",
        request_id=uuid.uuid4(),
        revision=2,
        reason="Error de captura",
        data=facts(team, price="3000000"),
    )
    assert correction["history"][1]["data"]["price"] == "3100000.00"
    assert Decimal(correction["data"]["price"]) == Decimal("3000000")
    assert PhysicalProperty.objects.count() == 1
    assert Closing.objects.count() == 2
    old = ClosingRevision.objects.filter(closing_id=row["id"], number=2).get()
    old.price = Decimal("1")
    with pytest.raises(ValueError, match="inmutables"):
        old.save()
    with pytest.raises(closings.ClosingConflict):
        closings.delete_draft(team[1], row["id"], revision=3)


def test_session_staff_can_confirm_without_extra_permission_and_email_is_immutable(team):
    from django.test import Client

    from datalayer.models import ClosingAuthorization, PropertyEvent

    actor = team[1]
    client = Client()
    client.force_login(actor)
    assert not ClosingAuthorization.objects.exists()
    assert client.get("/api/crm/closings").json()["can_confirm"] is True
    row = draft(team, origin="current", offer_id=offer().pk)
    summary = closings.preview(actor, row["id"])
    response = client.post(
        f"/api/crm/closings/{row['id']}/actions",
        data={
            "action": "confirm",
            "request_id": str(uuid.uuid4()),
            "revision": summary["revision"],
            "preview_token": summary["preview_token"],
            "reviewed_duplicates": [],
            "actor_email": "forged@example.test",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["history"][-1]["actor_email"] == actor.email
    event = PropertyEvent.objects.get(action="confirm")
    assert event.actor_email == actor.email
    original = actor.email
    actor.email = "new-address@example.test"
    actor.save(update_fields=["email"])
    history = closings.output(Closing.objects.get(pk=row["id"]), history=True)["history"]
    assert all(item["actor_email"] == original for item in history)
    event.refresh_from_db()
    assert event.actor_email == original
    outsider = User.objects.create_user(email="owner-only@example.test")
    client.force_login(outsider)
    assert client.get("/api/crm/closings").status_code == 403
    client.logout()
    assert client.get("/api/crm/closings").status_code == 403


def test_current_confirmation_ends_only_linked_offer_and_preserves_agreement(team):
    a, b = offer(), offer()
    owner = User.objects.create_user(email="closing-owner@example.test")
    capture = Capture.objects.create(owner=owner, property=a, status="published")
    agreement = CaptureAgreement.objects.create(
        capture=capture,
        version="original",
        text="Aceptado",
        snapshot={"price": "3500000"},
        accepted_by=owner,
        accepted_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=30),
    )
    row = confirm(team, draft(team, origin="current", offer_id=a.pk))
    a.refresh_from_db()
    b.refresh_from_db()
    agreement.refresh_from_db()
    capture.refresh_from_db()
    assert not a.published and b.published and capture.status == "closed"
    assert agreement.ended_at and agreement.snapshot == {"price": "3500000"}
    assert a.price == Decimal("3500000") and row["data"]["price"] == "3100000.00"
    with pytest.raises(ValidationError):
        set_publication(a.pk, True)
    with pytest.raises(closings.ClosingConflict):
        confirm(team, row)


def test_annul_reopen_then_new_closing_preserves_old_and_idempotency(team):
    prop = offer()
    row = confirm(team, draft(team, origin="current", offer_id=prop.pk))
    annulled = closings.command(
        team[1],
        row["id"],
        action="annul",
        request_id=uuid.uuid4(),
        revision=2,
        reason="Nunca ocurrió",
    )
    with pytest.raises(ValidationError):
        set_publication(prop.pk, True)
    key = uuid.uuid4()
    args = dict(action="reopen", request_id=key, revision=3, reason="Revisar comercialización")
    first = closings.command(team[1], row["id"], **args)
    assert closings.command(team[1], row["id"], **args) == first
    prop.refresh_from_db()
    assert prop.commercialization_round == 2 and not prop.published
    assert annulled["status"] == "annulled"
    set_publication(prop.pk, True)
    new = confirm(team, draft(team, origin="current", offer_id=prop.pk))
    assert new["id"] != row["id"] and OfferClosure.objects.count() == 2
    with pytest.raises(closings.ClosingConflict):
        closings.command(team[1], row["id"], **{**args, "reason": "Distinto"})


def test_preview_stale_inactive_session_and_confirmation_retry(team):
    prop = offer()
    row = draft(team, origin="current", offer_id=prop.pk)
    summary = closings.preview(team[1], row["id"])
    set_publication(prop.pk, False)
    with pytest.raises(closings.ClosingConflict, match="resumen"):
        confirm(team, row, preview_token=summary["preview_token"])
    User.objects.filter(pk=team[1].pk).update(is_active=False)
    with pytest.raises(PermissionDenied):
        confirm(team, row)
    User.objects.filter(pk=team[1].pk).update(is_active=True)
    summary = closings.preview(team[1], row["id"])
    args = dict(
        action="confirm",
        request_id=uuid.uuid4(),
        revision=1,
        preview_token=summary["preview_token"],
        reviewed_duplicates=[],
    )
    result = closings.command(team[1], row["id"], **args)
    assert closings.command(team[1], row["id"], **args) == result
    assert ClosingRevision.objects.filter(closing_id=row["id"]).count() == 2


def test_historical_link_does_not_end_current_offer_and_invalid_provider_fields_rejected(team):
    prop = offer()
    confirm(team, draft(team, origin="historical", offer_id=prop.pk))
    prop.refresh_from_db()
    assert prop.published and not OfferClosure.objects.exists()
    from pydantic import ValidationError as SchemaError

    with pytest.raises(SchemaError):
        ClosingData.model_validate(facts(team, location_ref=str(uuid.uuid4())))
    with pytest.raises(SchemaError):
        ClosingData.model_validate(facts(team, month=2, day=31))


def test_draft_ownership_and_revision_conflicts(team):
    row = draft(team)
    outsider = User.objects.create_user(email="other@example.test", is_staff=True)
    with pytest.raises(PermissionDenied):
        closings.update_draft(outsider, row["id"], revision=1, data=facts(team))
    with pytest.raises(closings.ClosingConflict):
        closings.update_draft(team[1], row["id"], revision=0, data=facts(team))
    closings.delete_draft(team[1], row["id"], revision=1)
    assert not Closing.objects.exists()


def test_resolving_selected_search_preserves_contact_and_new_intentions(team):
    from datalayer.followups import eligible, ensure_cycle, template_options
    from datalayer.memory import read_memory
    from datalayer.models import Conversation, Message, Prospect

    buyer = Prospect.objects.create(
        phone="+523311110001", criteria={"operation": "sale", "municipality": "Guadalajara"}
    )
    conv = Conversation.objects.create(
        prospect=buyer,
        declared_phone=buyer.phone,
        intent_started_at=timezone.now(),
        criteria=buyer.criteria,
        followup_permission=True,
    )
    cycle = ensure_cycle(conv)
    other = Prospect.objects.create(phone="+523311110002")
    other_conv = Conversation.objects.create(prospect=other, intent_started_at=timezone.now())
    other_cycle = ensure_cycle(other_conv)
    prop = offer()
    row = closings.create_draft(
        team[1],
        request_id=uuid.uuid4(),
        data=facts(team, buyer_id=buyer.pk),
        origin="current",
        offer_id=prop.pk,
    )
    row = confirm(team, row)
    key = uuid.uuid4()
    result = closings.resolve_search(team[1], row["id"], cycle.intent_id, request_id=key)
    assert closings.resolve_search(team[1], row["id"], cycle.intent_id, request_id=key) == result
    buyer.refresh_from_db()
    conv.refresh_from_db()
    other_cycle.refresh_from_db()
    assert not buyer.contact_opted_out and conv.followup_permission and buyer.status == "new"
    assert not other_cycle.closed_at
    assert eligible(cycle, timezone.now()) == "search_resolved"
    assert template_options(cycle) == []
    assert read_memory(conv)["search_attended"] is True
    assert ensure_cycle(conv).pk == cycle.pk
    Message.objects.create(conversation=conv, role="user", text="Ahora busco otra casa")
    new = ensure_cycle(conv, new=True, actor=team[1])
    assert new.intent_id != cycle.intent_id and new.closed_at is None
    assert read_memory(conv)["search_attended"] is False


def test_api_permissions_private_history_and_review_conflict(team):
    from django.test import Client

    client = Client()
    assert client.get("/api/crm/closings").status_code == 403
    client.force_login(team[0])
    client.force_login(team[1])
    assert client.get("/api/crm/closings")["Cache-Control"] == "private, no-store"
    response = client.post(
        "/api/crm/closings",
        data={"request_id": str(uuid.uuid4()), "data": facts(team)},
        content_type="application/json",
    )
    assert response.status_code == 201
    row = response.json()
    summary = client.get(f"/api/crm/closings/{row['id']}/preview").json()
    response = client.post(
        f"/api/crm/closings/{row['id']}/actions",
        data={
            "request_id": str(uuid.uuid4()),
            "revision": row["revision"],
            "action": "confirm",
            "preview_token": summary["preview_token"],
            "reviewed_duplicates": [],
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    assert len(client.get(f"/api/crm/closings/{row['id']}").json()["history"]) == 2
    assert (
        client.put(
            f"/api/crm/closings/{row['id']}",
            data={"revision": 2, "data": facts(team)},
            content_type="application/json",
        ).status_code
        == 409
    )
    owner = User.objects.create_user(
        email="read-owner@example.test", phone="+523311110003", email_verified_at=timezone.now()
    )
    client.force_login(owner)
    assert client.get(f"/api/crm/closings/{row['id']}").status_code == 403


def test_concurrent_confirmation_serializes_one_offer(team):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections

    other = User.objects.create_user(email="concurrent@example.test", is_staff=True)
    prop = offer()
    first = draft(team, origin="current", offer_id=prop.pk)
    second = closings.create_draft(
        other, request_id=uuid.uuid4(), data=facts(team), origin="current", offer_id=prop.pk
    )
    summaries = [closings.preview(team[1], row["id"]) for row in (first, second)]

    def run(args):
        actor, row, summary = args
        close_old_connections()
        try:
            closings.command(
                actor,
                row["id"],
                action="confirm",
                request_id=uuid.uuid4(),
                revision=1,
                preview_token=summary["preview_token"],
                reviewed_duplicates=[],
            )
            return "confirmed"
        except (closings.ClosingConflict, ValidationError):
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(run, [(team[1], first, summaries[0]), (other, second, summaries[1])])
        )
    assert sorted(results) == ["confirmed", "conflict"]
    assert OfferClosure.objects.filter(offer=prop).count() == 1


def test_capture_reopen_does_not_revive_exclusivity_and_reverse_keeps_offer_closed(team):
    from datalayer.captures import review

    prop = offer()
    owner = User.objects.create_user(email="reopen-owner@example.test")
    capture = Capture.objects.create(
        owner=owner, property=prop, status="published", verified_at=timezone.now()
    )
    row = confirm(team, draft(team, origin="current", offer_id=prop.pk))
    capture.refresh_from_db()
    for action in ("update", "approve", "renew", "withdraw", "reject", "publish"):
        with pytest.raises(ValidationError):
            review(capture.pk, team[1], {"revision": capture.revision, "action": action})
    closings.command(
        team[1], row["id"], action="annul", request_id=uuid.uuid4(), revision=2, reason="Error"
    )
    closings.command(
        team[1], row["id"], action="reopen", request_id=uuid.uuid4(), revision=3, reason="Revisar"
    )
    capture.refresh_from_db()
    assert capture.status == "submitted" and capture.verified_at is None
    with pytest.raises(ValidationError):
        set_publication(prop.pk, True)
    another = confirm(team, draft(team, origin="current", offer_id=prop.pk))
    reversed_row = closings.command(
        team[1],
        another["id"],
        action="reverse",
        request_id=uuid.uuid4(),
        revision=2,
        reason="Se deshizo",
        reversal_date="2022-07-01",
    )
    assert reversed_row["status"] == "reversed"
    with pytest.raises(closings.ClosingConflict):
        closings.command(
            team[1],
            another["id"],
            action="reopen",
            request_id=uuid.uuid4(),
            revision=3,
            reason="No procede",
        )


def test_manual_identity_link_preserves_history_and_prevents_duplicate_blind_confirmation(team):
    first = confirm(team, draft(team))
    second = draft(team)
    previous = closings.preview(team[1], second["id"])
    closings.link_identities(
        team[1],
        second["physical_property_id"],
        first["physical_property_id"],
        reason="Misma casa confirmada por asesor",
        request_id=uuid.uuid4(),
    )
    summary = closings.preview(team[1], second["id"])
    assert summary["physical_property_id"] == second["physical_property_id"]
    assert summary["canonical_physical_property_id"] == first["physical_property_id"]
    assert summary["duplicates"] == [first["id"]]
    assert summary["preview_token"] != previous["preview_token"]
    with pytest.raises(closings.ClosingConflict):
        confirm(team, second, reviewed_duplicates=[])
    result = confirm(team, second)
    assert result["identity_links"][0]["reason"] == "Misma casa confirmada por asesor"
    assert Closing.objects.get(pk=second["id"]).physical_property_id == uuid.UUID(
        second["physical_property_id"]
    )


def test_registry_migration_preserves_legacy_offers_and_does_not_invent_closings():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    before = [("core", "0013_followup_cycle_pilot")]
    executor = MigrationExecutor(connection)
    after = executor.loader.graph.leaf_nodes("core")
    executor.migrate(before)
    try:
        apps = executor.loader.project_state(before).apps
        LegacyProperty = apps.get_model("core", "Property")
        a = LegacyProperty.objects.create(
            title="Anterior A",
            operation="sale",
            kind="house",
            municipality="Guadalajara",
            neighborhood="Americana",
            price="1234567.89",
            published=True,
        )
        b = LegacyProperty.objects.create(
            title="Anterior B",
            operation="rent",
            kind="house",
            municipality="Guadalajara",
            neighborhood="Americana",
            price="15000",
            published=False,
        )
        original = list(
            LegacyProperty.objects.order_by("pk").values("pk", "reference", "price", "published")
        )
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        assert (
            list(Property.objects.order_by("pk").values("pk", "reference", "price", "published"))
            == original
        )
        assert (
            Property.objects.get(pk=a.pk).physical_property_id
            != Property.objects.get(pk=b.pk).physical_property_id
        )
        assert not Closing.objects.exists() and PhysicalProperty.objects.count() == 2
    finally:
        MigrationExecutor(connection).migrate(after)


def test_current_close_preserves_visit_and_only_notifies_advisor(team):
    from datalayer.models import (
        Appointment,
        CalendarConnection,
        Conversation,
        Notification,
        Prospect,
        WhatsAppDelivery,
    )

    prop = offer()
    buyer = Prospect.objects.create(phone="+523311110004", advisor=team[2])
    conv = Conversation.objects.create(
        prospect=buyer, channel="whatsapp", whatsapp_sender="523311110004"
    )
    calendar = CalendarConnection.objects.create(
        advisor=team[2], email="calendar@example.test", subject="fixture", credentials="not-used"
    )
    visit = Appointment.objects.create(
        conversation=conv,
        prospect=buyer,
        property=prop,
        advisor=team[2],
        connection=calendar,
        connection_generation=calendar.generation,
        start=timezone.now() + timedelta(days=2),
        end=timezone.now() + timedelta(days=2, hours=1),
        status="confirmed",
    )
    row = confirm(team, draft(team, origin="current", offer_id=prop.pk))
    visit.refresh_from_db()
    assert visit.status == "confirmed"
    assert (
        Notification.objects.filter(event_key__startswith=f"closing:{row['id']}:visit:").count()
        == 1
    )
    assert not WhatsAppDelivery.objects.exists()


def test_resolving_an_older_search_does_not_close_newer_search_of_same_buyer(team):
    from datalayer.followups import ensure_cycle, finish_cycle
    from datalayer.models import Conversation, Message, Prospect

    buyer = Prospect.objects.create(phone="+523311110005", criteria={"municipality": "Guadalajara"})
    conv = Conversation.objects.create(
        prospect=buyer,
        criteria=buyer.criteria,
        intent_started_at=timezone.now() - timedelta(days=30),
        followup_permission=True,
    )
    old = ensure_cycle(conv)
    finish_cycle(old, timezone.now() - timedelta(days=1))
    buyer.criteria = {"municipality": "Zapopan"}
    buyer.save(update_fields=["criteria"])
    Message.objects.create(conversation=conv, role="user", text="Ahora busco en Zapopan")
    new = ensure_cycle(conv, new=True)
    row = closings.create_draft(
        team[1],
        request_id=uuid.uuid4(),
        data=facts(team, buyer_id=buyer.pk),
        origin="current",
        offer_id=offer().pk,
    )
    row = confirm(team, row)
    closings.resolve_search(team[1], row["id"], old.intent_id, request_id=uuid.uuid4())
    old.intent.refresh_from_db()
    new.refresh_from_db()
    buyer.refresh_from_db()
    assert old.intent.criteria == {"municipality": "Guadalajara"}
    assert new.closed_at is None and new.permission is True
    assert buyer.criteria == {"municipality": "Zapopan"} and not buyer.contact_opted_out


def test_rural_history_requires_individualized_reference_and_keeps_unknown_traits(team):
    value = facts(
        team,
        address_mode="rural",
        kind="ranch",
        zone_type="localidad",
        zone="El Refugio",
        street="",
        exterior_number="",
        interior_applicable=None,
        rural_identification="Parcela 24, lote 3",
        rural_reference="",
        land_m2="100000",
        construction_m2=None,
    )
    row = closings.create_draft(team[1], request_id=uuid.uuid4(), data=value)
    with pytest.raises(ValidationError):
        confirm(team, row)
    value["rural_reference"] = "Escritura, identificación de parcela 24"
    row = closings.update_draft(team[1], row["id"], revision=1, data=value)
    result = confirm(team, row)
    assert result["data"]["land_m2"] == "100000.00"
    assert result["data"]["construction_m2"] is None
    assert result["missing_characteristics"] and result["status"] == "confirmed"


def test_apartment_private_area_usd_and_mxn_charges_remain_separate(team):
    value = facts(
        team,
        kind="apartment",
        currency="USD",
        price="250000",
        land_m2=None,
        construction_m2="110",
        private_m2="90",
        charges_status="itemized",
        charges=[{"concept": "Mantenimiento", "amount": "1500.50", "currency": "MXN"}],
    )
    row = closings.create_draft(team[1], request_id=uuid.uuid4(), data=value)
    result = confirm(team, row)
    assert Decimal(result["data"]["price"]) == Decimal("250000")
    assert result["data"]["charges"][0]["currency"] == "MXN"
    assert result["data"]["land_m2"] is None
    assert Decimal(result["data"]["private_m2"]) == Decimal("90")
    assert Decimal(result["data"]["construction_m2"]) == Decimal("110")

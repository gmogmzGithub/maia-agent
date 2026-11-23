import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from datalayer.easybroker import connections, imports, schemas, sync
from datalayer.inventory import public_inventory, public_property, search_inventory, set_publication
from datalayer.models import (
    AccountThrottle,
    Advisor,
    EasyBrokerConnection,
    EasyBrokerListing,
    EasyBrokerListingRevision,
    EasyBrokerOfferLink,
    ImportedOfferPolicy,
    Property,
    User,
)
from datalayer.schemas import SearchCriteria
from worker.easybroker import Client, ProviderError, process

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def team(settings):
    settings.EASYBROKER_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.EASYBROKER_PUBLIC_ENABLED = True
    admin = User.objects.create_user(
        email="eb-admin@example.test", is_staff=True, is_superuser=True
    )
    staff = User.objects.create_user(email="eb-team@example.test", is_staff=True)
    advisor = Advisor.objects.create(name="Responsable")
    return admin, staff, advisor


def connection(team, key="test-key", name="Cuenta A"):
    value = schemas.CreateConnection(
        request_id=uuid.uuid4(), name=name, environment="sandbox", advisor_id=team[2].pk, key=key
    )
    result = connections.create(team[0], value)
    row = EasyBrokerConnection.objects.get(pk=result["id"])
    assert key not in json.dumps(result) and "fingerprint" not in json.dumps(result)
    return row


def detail(external_id="EB-1", **extra):
    return {
        "public_id": external_id,
        "updated_at": "2026-11-20T12:00:00-06:00",
        "title": "Texto privado Calle 123",
        "description": "Importe privado 7654321",
        "private_description": "Nota confidencial",
        "show_prices": True,
        "property_type": "Casa",
        "bedrooms": 3,
        "bathrooms": 2,
        "parking_spaces": 0,
        "lot_size": 150,
        "construction_size": 200,
        "location": {
            "name": "Ubicación original sin separar",
            "street": "Calle 123",
            "show_exact_location": False,
            "latitude": 20.123456789,
            "longitude": -103.987654321,
        },
        "operations": [
            {"type": "sale", "amount": "7654321.10", "currency": "MXN", "unit": "total"}
        ],
        "property_images": [{"url": "https://assets.example.test/photo.jpg?signature=temporary"}],
        "public_url": "https://private.example.test/123",
        "tags": ["secreto"],
        **extra,
    }


def status(raw, state="published"):
    return {"public_id": raw["public_id"], "updated_at": raw["updated_at"], "status": state}


class FixtureClient:
    def __init__(self, raw, state="published"):
        self.raw = raw
        self.state = state

    def statuses(self, page):
        assert page == 1
        return [status(self.raw, self.state)], None

    def detail(self, external_id):
        assert external_id == self.raw["public_id"]
        return self.raw


def drain(row, raw, state="published"):
    run = sync.request_sync(row.pk)
    client = FixtureClient(raw, state)
    for _ in range(8):
        AccountThrottle.objects.filter(key="easybroker-global").update(
            started_at=timezone.now() - timedelta(seconds=1)
        )
        process(run.pk, client)
        run.refresh_from_db()
        if run.finished_at:
            break
    assert run.status == "complete", (run.status, run.error_code)
    return EasyBrokerListing.objects.get(connection=row, public_id=raw["public_id"])


def approve(team, listing, operation="sale", **extra):
    listing.refresh_from_db()
    value = schemas.Approve(
        request_id=uuid.uuid4(),
        revision=listing.revision,
        action="approve",
        reason="Revisión humana",
        operation=operation,
        title="Casa revisada",
        description="Descripción pública revisada",
        state="Jalisco",
        municipality="Zapopan",
        neighborhood="Centro",
        advisor_id=team[2].pk,
        publish=True,
        **extra,
    )
    result = imports.review(team[1], listing.pk, value)
    # A retry returns the same result, even though its revision has advanced.
    assert imports.review(team[1], listing.pk, value) == result
    return Property.objects.get(
        pk=next(v["offer_id"] for v in result["links"] if v["operation"] == operation)
    )


def test_private_import_requires_review_and_deduplicates_per_account(team):
    first = connection(team)
    raw = detail()
    listing = drain(first, raw)
    assert not Property.objects.exists()
    assert listing.facts["location"]["street"] == "Calle 123"
    assert "temporary" not in json.dumps(listing.facts)
    assert "public_url" not in listing.facts and "tags" not in listing.facts
    assert listing.issues
    drain(first, raw)
    assert EasyBrokerListingRevision.objects.count() == 1
    second = connection(team, key="second-test-key", name="Cuenta B")
    drain(second, raw)
    assert EasyBrokerListing.objects.count() == 2
    assert not public_inventory().exists()
    prop = approve(team, listing)
    public = public_property(prop)
    assert public["title"] == "Casa revisada" and public["parking"] == 0
    assert public["public_location"] == {} and public["details"] == {}
    assert "123" not in json.dumps(public) and "Nota confidencial" not in json.dumps(public)
    assert public["price"] == "7654321.10"
    assert public_inventory().count() == 1


def test_hidden_prices_are_not_search_or_sort_side_channels(team):
    row = connection(team)
    listing = drain(row, detail(show_prices=False))
    prop = approve(team, listing)
    assert prop.price == Decimal("7654321.10")
    public = public_property(prop)
    assert public["price"] is None and public["currency"] is None
    assert search_inventory(SearchCriteria(max_price=9000000))["total"] == 0
    assert search_inventory(SearchCriteria(currency="MXN"))["total"] == 0
    assert search_inventory(SearchCriteria())["total"] == 1
    from harness.presentation.properties import property_text

    assert "Precio por consultar" in property_text(public, {}, "https://example.test")
    assert "7654321" not in property_text(public, {}, "https://example.test")


def test_expiry_is_per_offer_at_exactly_24_hours_and_manual_block_survives(team):
    row = connection(team)
    raw = detail()
    listing = drain(row, raw)
    prop = approve(team, listing)
    listing.refresh_from_db()
    deadline = listing.checked_at + timedelta(hours=24)
    with patch("django.utils.timezone.now", return_value=deadline - timedelta(microseconds=1)):
        assert public_inventory().filter(pk=prop.pk).exists()
    with patch("django.utils.timezone.now", return_value=deadline):
        assert not public_inventory().filter(pk=prop.pk).exists()
    set_publication(prop.pk, False)
    drain(row, raw)
    assert not public_inventory().filter(pk=prop.pk).exists()
    assert ImportedOfferPolicy.objects.get(offer=prop).manual_block


@pytest.mark.parametrize(
    "operation",
    [
        {"type": "sale", "amount": "123.45", "currency": "MXN", "unit": "square_meter"},
        {"type": "sale", "amount": "123.45", "currency": "EUR", "unit": "total"},
        {"type": "temporary_rental", "amount": "123.45", "currency": "MXN", "period": "daily"},
        {"type": "sale", "amount": "123.456", "currency": "MXN", "unit": "total"},
    ],
)
def test_unsupported_facts_are_conserved_without_fake_prices(team, operation):
    listing = drain(connection(team), detail(operations=[operation]))
    assert listing.facts["operations"] == [operation]
    assert listing.issues
    with pytest.raises(ValidationError):
        approve(team, listing)
    assert not Property.objects.exists()


def test_multiple_operations_share_identity_and_local_link_never_overwrites(team):
    raw = detail()
    raw["operations"].append(
        {"type": "rental", "amount": "30000", "currency": "MXN", "unit": "total"}
    )
    listing = drain(connection(team), raw)
    sale = approve(team, listing)
    rent = approve(team, listing, operation="rent")
    assert sale.pk != rent.pk and sale.physical_property_id == rent.physical_property_id
    other = drain(connection(team, key="other-key"), detail(external_id="EB-2"))
    local = Property.objects.create(
        title="Local",
        operation="sale",
        kind="house",
        price=1500,
        municipality="Zapopan",
        neighborhood="Centro",
        published=True,
    )
    imports.review(
        team[1],
        other.pk,
        schemas.Link(
            action="link",
            request_id=uuid.uuid4(),
            revision=other.revision,
            reason="Referencia comprobada",
            operation="sale",
            offer_id=local.pk,
        ),
    )
    drain(other.connection, detail(external_id="EB-2", title="Otro título"))
    local.refresh_from_db()
    assert local.title == "Local" and local.price == Decimal("1500") and local.published
    assert EasyBrokerOfferLink.objects.get(offer=local).role == "local"


def test_duplicate_key_and_unauthorized_configuration_are_rejected(team):
    connection(team)
    with pytest.raises(IntegrityError), transaction.atomic():
        connection(team)
    value = schemas.CreateConnection(
        request_id=uuid.uuid4(),
        name="Prohibida",
        environment="sandbox",
        advisor_id=team[2].pk,
        key="third-key",
    )
    with pytest.raises(PermissionDenied):
        connections.create(team[1], value)


def test_readonly_client_validates_pagination_and_never_follows_redirects(team):
    row = connection(team)
    calls = []

    def transport(request):
        calls.append(request)
        assert request.method == "GET" and request.headers["X-Authorization"] == "test-key"
        return httpx.Response(
            200,
            json={
                "content": [],
                "pagination": {
                    "page": 1,
                    "limit": 100,
                    "total": 1,
                    "next_page": "https://attacker.example/v1/listing_statuses?page=2",
                },
            },
        )

    client = Client(row, httpx.MockTransport(transport))
    with pytest.raises(ProviderError, match="invalid_pagination"):
        client.statuses(1)
    assert len(calls) == 1
    client = Client(
        row,
        httpx.MockTransport(
            lambda _: httpx.Response(302, headers={"Location": "https://attacker.example"})
        ),
    )
    with pytest.raises(ProviderError, match="invalid_response"):
        client.detail("EB-1")


def test_private_endpoints_enforce_permissions_and_do_not_echo_secrets(team, client):
    assert client.get("/api/crm/easybroker/connections").status_code == 403
    client.force_login(team[1])
    response = client.post(
        "/api/crm/easybroker/connections",
        data=json.dumps(
            {
                "request_id": str(uuid.uuid4()),
                "name": "Prohibida",
                "environment": "sandbox",
                "advisor_id": team[2].pk,
                "key": "sensitive-test-key",
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 403 and b"sensitive-test-key" not in response.content
    assert response["Cache-Control"] == "private, no-store"
    client.force_login(team[0])
    response = client.post(
        "/api/crm/easybroker/connections",
        data=json.dumps({"key": "sensitive-test-key", "unknown": True}),
        content_type="application/json",
    )
    assert response.status_code == 422 and b"sensitive-test-key" not in response.content


def test_negative_status_requires_human_republication_without_a_fake_closing(team):
    row = connection(team)
    raw = detail()
    listing = drain(row, raw)
    prop = approve(team, listing)
    last_checked = listing.checked_at
    listing = drain(row, raw, state="sold")
    prop.refresh_from_db()
    assert not prop.published and not prop.closing_periods.exists()
    assert listing.checked_at == last_checked
    listing = drain(row, raw)
    assert not public_inventory().exists()
    prop = approve(team, listing)
    assert public_inventory().filter(pk=prop.pk).exists()


def test_expiry_maintenance_recovers_only_expiry_and_not_disconnection(team):
    from datalayer.easybroker.publication import expire_imports as maintain

    row = connection(team)
    raw = detail()
    listing = drain(row, raw)
    prop = approve(team, listing)
    EasyBrokerListing.objects.filter(pk=listing.pk).update(
        checked_at=timezone.now() - timedelta(hours=24)
    )
    maintain()
    prop.refresh_from_db()
    assert not prop.published and ImportedOfferPolicy.objects.get(offer=prop).expired
    listing = drain(row, raw)
    assert public_inventory().filter(pk=prop.pk).exists()
    row.refresh_from_db()
    connections.configure(
        team[0],
        row.pk,
        schemas.Toggle(request_id=uuid.uuid4(), revision=row.revision, action="disconnect"),
    )
    assert not public_inventory().exists()
    row.refresh_from_db()
    connections.configure(
        team[0],
        row.pk,
        schemas.Toggle(request_id=uuid.uuid4(), revision=row.revision, action="reconnect"),
    )
    listing = drain(row, raw)
    assert not public_inventory().exists()
    approve(team, listing)
    assert public_inventory().filter(pk=prop.pk).exists()


def test_changed_content_redacts_history_memory_and_keeps_photos_out_of_storage(team):
    from datalayer.conversations import message_output
    from datalayer.memory import read_memory
    from datalayer.models import Conversation, Message
    from datalayer.public_history import persist_cards

    row = connection(team)
    listing = drain(row, detail())
    prop = approve(team, listing)
    conv = Conversation.objects.create(browser_id=uuid.uuid4())
    card = public_property(prop)
    message = Message.objects.create(
        conversation=conv,
        role="assistant",
        text="Su precio es 7654321.10",
        properties=persist_cards([card]),
    )
    assert message.properties == [{"id": prop.pk, "public_revision": card["public_revision"]}]
    assert "signature" not in json.dumps(message.properties)
    assert message_output(message)["properties"][0]["photos"]
    # A later answer without a card still depends on the imported facts.
    later = Message.objects.create(
        conversation=conv, role="assistant", text="Sí, cuesta 7654321.10"
    )
    drain(row, detail(show_prices=False))
    for previous in (message, later):
        output = message_output(previous)
        assert "7654321" not in json.dumps(output) and output["properties"] == []
    memory = read_memory(conv)
    assert "7654321" not in json.dumps(memory)


def test_omitted_fact_is_preserved_but_null_withdrawal_never_uses_old_offer(team):
    from datalayer.property_records import facts

    row = connection(team)
    raw = detail()
    listing = drain(row, raw)
    prop = approve(team, listing)
    raw.pop("construction_size")
    listing = drain(row, raw)
    prop.refresh_from_db()
    assert prop.area_m2 == Decimal("200")
    raw["construction_size"] = None
    raw["property_type"] = None
    listing = drain(row, raw)
    assert listing.facts["construction_size"] is None and listing.issues
    assert facts(prop).kind == "" and facts(prop).construction_m2 is None
    assert not public_inventory().exists()
    assert listing.revisions.filter(facts__property_type="Casa").exists()


def test_old_worker_cannot_write_after_connection_change(team):
    from datalayer.easybroker.sync import StaleRun

    row = connection(team)
    run = row.runs.get(status="queued")
    acquired = sync.claim(run.pk)
    row.refresh_from_db()
    connections.configure(
        team[0],
        row.pk,
        schemas.Toggle(request_id=uuid.uuid4(), revision=row.revision, action="disconnect"),
    )
    with pytest.raises(StaleRun):
        sync.accept(acquired, ([status(detail())], None))
    assert not row.listings.exists()


def test_failed_account_does_not_prevent_another_or_refresh_offer(team):
    bad = connection(team)
    listing = drain(bad, detail())
    approve(team, listing)
    checked = listing.checked_at
    good = connection(team, key="independent-key", name="Cuenta B")
    run = sync.request_sync(bad.pk)

    class Rejected(FixtureClient):
        def statuses(self, page):
            raise ProviderError("authentication")

    AccountThrottle.objects.all().update(started_at=timezone.now() - timedelta(seconds=1))
    process(run.pk, Rejected(detail()))
    run.refresh_from_db()
    assert run.status == "failed" and run.error_code == "authentication"
    listing.refresh_from_db()
    assert listing.checked_at == checked
    assert drain(good, detail(external_id="EB-2")).checked_at
    assert public_inventory().count() == 1


def test_404_does_not_delete_or_renew_freshness(team):
    row = connection(team)
    listing = drain(row, detail())
    prop = approve(team, listing)
    checked = listing.checked_at
    run = sync.request_sync(row.pk)

    class Missing(FixtureClient):
        def detail(self, external_id):
            raise ProviderError("not_found")

    for _ in range(5):
        AccountThrottle.objects.all().update(started_at=timezone.now() - timedelta(seconds=1))
        process(run.pk, Missing(detail()))
    listing.refresh_from_db()
    run.refresh_from_db()
    assert listing.checked_at == checked and run.status == "partial"
    assert (
        Property.objects.filter(pk=prop.pk).exists()
        and public_inventory().filter(pk=prop.pk).exists()
    )


def test_confirmed_closing_freezes_private_facts_and_external_evidence(team):
    from datalayer import closings, property_records

    row = connection(team)
    listing = drain(row, detail())
    prop = approve(team, listing)
    source = property_records.snapshot(prop)
    prepared = property_records.prepare(
        team[1],
        prop.pk,
        {
            "request_id": str(uuid.uuid4()),
            "source": source,
            "date": "2025-11-20",
            "price": "7000000",
            "currency": "MXN",
        },
    )
    result = closings.command(
        team[1],
        prepared["id"],
        action="confirm",
        request_id=uuid.uuid4(),
        revision=prepared["revision"],
        preview_token=prepared["preview_token"],
        reviewed_duplicates=prepared["duplicates"],
    )
    closing = prop.closings.get(pk=result["id"])
    confirmed = closing.revisions.get(action="confirm")
    evidence = confirmed.source_evidence
    assert evidence["external_source"]["public_id"] == "EB-1"
    raw = detail(
        title="Otro título",
        location={
            "name": "Otra zona",
            "street": "Dirección posterior",
            "show_exact_location": True,
        },
    )
    drain(row, raw)
    prop.refresh_from_db()
    confirmed.refresh_from_db()
    assert confirmed.source_evidence == evidence and not prop.published
    assert property_records.facts(prop).address_text == "Calle 123"
    assert property_records.snapshot(prop)["source"] == evidence["external_source"]


def test_pending_whatsapp_is_checked_again_immediately_before_transport(team, settings):
    from datalayer.models import Conversation, Message, WhatsAppDelivery
    from datalayer.public_history import persist_cards
    from worker.whatsapp import deliver

    settings.WHATSAPP_ACCESS_TOKEN = "configured"
    settings.WHATSAPP_PHONE_NUMBER_ID = "configured"
    settings.WHATSAPP_API_VERSION = "v25.0"
    row = connection(team)
    listing = drain(row, detail())
    prop = approve(team, listing)
    conv = Conversation.objects.create(
        channel="whatsapp", whatsapp_sender="5213312345678", last_whatsapp_at=timezone.now()
    )
    msg = Message.objects.create(
        conversation=conv,
        role="assistant",
        text="Cuesta 7654321.10",
        properties=persist_cards([public_property(prop)]),
    )
    delivery = WhatsAppDelivery.objects.create(
        conversation=conv,
        message=msg,
        recipient=conv.whatsapp_sender,
        event_key="pending-eb",
        payload={"type": "text", "text": {"body": msg.text}},
    )
    drain(row, detail(show_prices=False))
    with patch("worker.whatsapp.request") as transport:
        deliver(delivery.pk)
    delivery.refresh_from_db()
    assert delivery.status == "skipped" and delivery.error_code == "property_facts_changed"
    transport.assert_not_called()


def test_primary_selection_preserves_previous_links_and_never_falls_back(team):
    first = connection(team)
    a = drain(first, detail())
    offer = approve(team, a)
    second = connection(team, key="source-b")
    b = drain(second, detail(external_id="EB-2"))
    linked = imports.review(
        team[1],
        b.pk,
        schemas.Link(
            action="link",
            request_id=uuid.uuid4(),
            revision=b.revision,
            operation="sale",
            offer_id=offer.pk,
            reason="Mismo inmueble comprobado",
        ),
    )
    secondary = next(link for link in linked["links"] if link["role"] == "secondary")
    original = EasyBrokerOfferLink.objects.get(offer=offer, role="primary", active=True)
    imports.review(
        team[1],
        b.pk,
        schemas.Primary(
            action="primary",
            request_id=uuid.uuid4(),
            revision=linked["revision"],
            link_id=secondary["id"],
            reason="Nueva fuente elegida",
        ),
    )
    original.refresh_from_db()
    assert not original.active and original.role == "primary"
    assert EasyBrokerOfferLink.objects.filter(offer=offer, active=True).count() == 2
    assert not public_inventory().exists()
    approve(team, b)
    assert public_inventory().filter(pk=offer.pk).exists()
    second.refresh_from_db()
    connections.configure(
        team[0],
        second.pk,
        schemas.Toggle(action="disconnect", request_id=uuid.uuid4(), revision=second.revision),
    )
    drain(first, detail())
    assert not public_inventory().exists()
    assert ImportedOfferPolicy.objects.get(offer=offer).primary_link.listing_id == b.pk


def test_expired_offer_rejects_interest_and_slots_without_maintenance(team):
    from datalayer.appointments import booking_policy, validate_slot
    from datalayer.models import Conversation
    from datalayer.prospects import record_interest

    listing = drain(connection(team), detail())
    offer = approve(team, listing)
    conv = Conversation.objects.create(browser_id=uuid.uuid4())
    EasyBrokerListing.objects.filter(pk=listing.pk).update(
        checked_at=timezone.now() - timedelta(hours=24)
    )
    assert record_interest(conv, {"property_ids": [offer.pk]})["error"] == "property_not_available"
    start = timezone.now() + timedelta(days=2)
    with pytest.raises(ValidationError, match="nuevas reservas"):
        validate_slot(offer, start, start + timedelta(hours=1), booking_policy())


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("channel", ["website", "whatsapp"])
def test_hidden_detail_without_card_is_tracked_before_committing_turn(team, structured, channel):
    from asgiref.sync import async_to_sync

    from datalayer.models import Conversation, Message
    from datalayer.schemas import ReplyProposal
    from datalayer.turns import finish_turn, load_turn
    from harness.tools import TurnTools

    row = connection(team)
    listing = drain(row, detail())
    offer = approve(team, listing)
    conv = Conversation.objects.create(
        browser_id=uuid.uuid4(),
        revision=1,
        channel=channel,
        whatsapp_sender="523312345678" if channel == "whatsapp" else "",
        last_whatsapp_at=timezone.now(),
    )
    Message.objects.create(conversation=conv, role="user", text="¿Cuánto cuesta?")
    turn = load_turn(conv.pk)
    tools = TurnTools(conv.pk, turn)
    result = async_to_sync(tools.execute)(
        {"name": "get_property", "input": {"property_id": offer.pk, "show_card": False}}
    )
    assert result["details"]["price"] == "7654321.10" and tools.cards == []
    drain(row, detail(show_prices=False))
    reply = (
        ReplyProposal.model_validate(
            {
                "blocks": [{"kind": "text", "text": "Cuesta 7654321.10"}],
                "continuity": {"purpose": "Confirmar precio 7654321.10", "pending": None},
            }
        )
        if structured
        else None
    )
    finish_turn(conv.pk, turn, "Cuesta 7654321.10", [], "completed", [0, 0], 1, [], reply=reply)
    message = conv.messages.filter(role="assistant").get()
    assert "7654321" not in json.dumps(
        {
            "text": message.text,
            "presentation": message.presentation,
            "continuity": message.continuity,
        }
    )
    if channel == "whatsapp":
        assert "7654321" not in json.dumps(message.whatsappdelivery_set.get().payload)


def test_imported_message_insertion_stores_references_and_inherits_sources(team):
    from datalayer.models import Conversation, Message

    listing = drain(connection(team), detail())
    prop = approve(team, listing)
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    card = public_property(prop)
    message = Message.objects.create(
        conversation=conversation, role="assistant", text="Ficha revisada", properties=[card]
    )
    message.refresh_from_db()
    assert message.properties == [{"id": prop.pk, "public_revision": card["public_revision"]}]
    next_message = Message.objects.create(
        conversation=conversation, role="assistant", text="Seguimos revisando esta opción"
    )
    assert next_message.public_sources == message.public_sources


def test_api_revision_conflict_and_csrf_are_enforced(team, client):
    from django.test import Client as BrowserClient

    row = connection(team)
    client.force_login(team[0])
    response = client.post(
        f"/api/crm/easybroker/connections/{row.pk}/actions",
        data=json.dumps(
            {"request_id": str(uuid.uuid4()), "action": "disconnect", "revision": row.revision + 1}
        ),
        content_type="application/json",
    )
    assert response.status_code == 409
    browser = BrowserClient(enforce_csrf_checks=True)
    browser.force_login(team[0])
    response = browser.post(
        f"/api/crm/easybroker/connections/{row.pk}/sync",
        data=json.dumps({"request_id": str(uuid.uuid4()), "revision": row.revision}),
        content_type="application/json",
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "code,expected,delay",
    [
        (401, "authentication", 0),
        (403, "authentication", 0),
        (404, "not_found", 0),
        (429, "rate_limit", 120),
        (500, "provider_unavailable", 30),
        (503, "provider_unavailable", 30),
    ],
)
def test_provider_errors_are_safe_and_preserve_retry_after(team, code, expected, delay):
    row = connection(team)
    client = Client(
        row,
        httpx.MockTransport(
            lambda _: httpx.Response(
                code, headers={"Retry-After": "120"}, text="provider-private-body test-key"
            )
        ),
    )
    with pytest.raises(ProviderError) as raised:
        client.detail("EB-1")
    assert raised.value.code == expected and raised.value.retry_after == delay
    assert "test-key" not in str(raised.value) and "provider-private-body" not in str(raised.value)


def test_retry_after_http_date_and_invalid_json_are_not_successes(team):
    from email.utils import format_datetime

    row = connection(team)
    now = timezone.now().replace(microsecond=0)
    retry = format_datetime(now + timedelta(seconds=90), usegmt=True)
    client = Client(
        row, httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": retry}))
    )
    with (
        patch("django.utils.timezone.now", return_value=now),
        pytest.raises(ProviderError) as raised,
    ):
        client.detail("EB-1")
    assert raised.value.retry_after == 90
    for body in (b"not-json", b'{"amount":NaN}', b'{"amount":Infinity}'):
        client = Client(
            row, httpx.MockTransport(lambda _, body=body: httpx.Response(200, content=body))
        )
        with pytest.raises(ProviderError, match="transport_or_schema"):
            client.detail("EB-1")


def test_retry_releases_executor_and_exhaustion_does_not_claim_success(team):
    row = connection(team)
    listing = drain(row, detail())
    last_checked = listing.checked_at
    row.refresh_from_db()
    last_success = row.last_success_at
    run = sync.request_sync(row.pk)

    class Limited(FixtureClient):
        def statuses(self, page):
            raise ProviderError("rate_limit", 120)

    now = timezone.now()
    for attempt in range(3):
        AccountThrottle.objects.all().update(started_at=now - timedelta(seconds=1))
        with (
            patch("django.utils.timezone.now", return_value=now),
            patch("worker.dispatch.enqueue_easybroker") as enqueue,
        ):
            process(run.pk, Limited(detail()))
        run.refresh_from_db()
        assert run.lease is None and run.lease_until is None
        if attempt < 2:
            assert not run.finished_at and run.checkpoint["attempts"] == attempt + 1
            assert enqueue.call_args.kwargs["at"] == now + timedelta(seconds=120)
        else:
            assert run.status == "partial" and run.counters["failed"] == 1
            enqueue.assert_not_called()
    listing.refresh_from_db()
    row.refresh_from_db()
    assert listing.checked_at == last_checked and row.last_success_at == last_success


def test_expired_lease_recovery_rejects_late_worker_and_replays_no_revision(team):
    from datalayer.easybroker.sync import StaleRun

    row = connection(team)
    run = row.runs.get(status="queued")
    first = sync.claim(run.pk)
    later = timezone.now() + timedelta(seconds=16)
    with patch("django.utils.timezone.now", return_value=later):
        recovered = sync.claim(run.pk)
        assert recovered != first
        with pytest.raises(StaleRun):
            sync.accept(first, ([status(detail())], None))
        sync.accept(recovered, ([status(detail())], None))
        AccountThrottle.objects.all().update(started_at=later - timedelta(seconds=1))
        batch = sync.claim(run.pk)
        sync.accept(batch, detail())
        with pytest.raises(StaleRun):
            sync.accept(batch, detail())
        listing = row.listings.get(public_id="EB-1")
        assert listing.revisions.count() == 1
    run.refresh_from_db()
    assert run.status == "complete"


def test_primary_change_is_idempotent_after_replacing_the_selected_link(team):
    listing = drain(connection(team), detail())
    offer = approve(team, listing)
    other = drain(connection(team, key="idempotent-source"), detail(external_id="EB-2"))
    linked = imports.review(
        team[1],
        other.pk,
        schemas.Link(
            action="link",
            request_id=uuid.uuid4(),
            revision=other.revision,
            operation="sale",
            offer_id=offer.pk,
            reason="Mismo inmueble comprobado",
        ),
    )
    value = schemas.Primary(
        action="primary",
        request_id=uuid.uuid4(),
        revision=linked["revision"],
        link_id=linked["links"][0]["id"],
        reason="Fuente elegida",
    )
    result = imports.review(team[1], other.pk, value)
    count = offer.source_links.count()
    assert imports.review(team[1], other.pk, value) == result
    assert offer.source_links.count() == count


def test_concurrent_primary_changes_revalidate_all_locked_sources(team):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    from datalayer.closings import ClosingConflict

    first = drain(connection(team), detail())
    offer = approve(team, first)
    commands = []
    for index in (2, 3):
        listing = drain(
            connection(team, key=f"concurrent-{index}"), detail(external_id=f"EB-{index}")
        )
        linked = imports.review(
            team[1],
            listing.pk,
            schemas.Link(
                action="link",
                request_id=uuid.uuid4(),
                revision=listing.revision,
                operation="sale",
                offer_id=offer.pk,
                reason="Mismo inmueble comprobado",
            ),
        )
        command = schemas.Primary(
            action="primary",
            request_id=uuid.uuid4(),
            revision=linked["revision"],
            link_id=linked["links"][0]["id"],
            reason="Elección concurrente",
        )
        commands.append((team[index - 2], listing.pk, command))
    barrier = Barrier(2)
    original = EasyBrokerConnection.objects.select_for_update

    def synchronize_before_locks(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    def choose(arguments):
        close_old_connections()
        try:
            imports.review(*arguments)
            return "applied"
        except ClosingConflict:
            return "conflict"
        finally:
            close_old_connections()

    with patch.object(
        EasyBrokerConnection.objects, "select_for_update", side_effect=synchronize_before_locks
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(choose, commands))
    assert sorted(outcomes) == ["applied", "conflict"]
    assert offer.source_links.filter(active=True, role="primary").count() == 1


def test_sync_transport_runs_one_request_outside_transactions_per_batch(team):
    from django.db import connection as database

    row = connection(team)
    run = row.runs.get(status="queued")
    calls = []

    class ReadOnly(FixtureClient):
        def statuses(self, page):
            assert not database.in_atomic_block
            calls.append("statuses")
            return super().statuses(page)

        def detail(self, external_id):
            assert not database.in_atomic_block
            calls.append("detail")
            return super().detail(external_id)

    client = ReadOnly(detail())
    process(run.pk, client)
    assert calls == ["statuses"]
    AccountThrottle.objects.all().update(started_at=timezone.now() - timedelta(seconds=1))
    process(run.pk, client)
    assert calls == ["statuses", "detail"]
    run.refresh_from_db()
    assert run.status == "complete"


def test_sync_accepts_observation_and_continuation_in_one_transaction(team):
    row = connection(team)
    run = row.runs.get(status="queued")
    raw = detail()
    sync.accept(sync.claim(run.pk), ([status(raw), status(detail(external_id="EB-2"))], None))
    AccountThrottle.objects.all().update(started_at=timezone.now() - timedelta(seconds=1))
    batch = sync.claim(run.pk)
    with patch("worker.dispatch.enqueue_easybroker", side_effect=RuntimeError("queue unavailable")):
        with pytest.raises(RuntimeError, match="queue unavailable"):
            sync.accept(batch, raw)
    run.refresh_from_db()
    assert not row.listings.exists() and len(run.checkpoint["pending"]) == 2
    sync.accept(batch, raw)
    run.refresh_from_db()
    assert row.listings.get().revisions.count() == 1
    assert len(run.checkpoint["pending"]) == 1

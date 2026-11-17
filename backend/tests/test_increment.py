import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async
from django.db import connection, connections
from django.test import Client

from datalayer.conversations import receive_message
from datalayer.inventory import search_inventory
from datalayer.models import Conversation, Execution, Message, Property, User
from datalayer.schemas import SearchCriteria
from harness.memory.context import build_messages
from harness.runtime import attend

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def close_async_connections():
    yield
    asyncio.run(sync_to_async(connections.close_all)())


@pytest.fixture
def home():
    return Property.objects.create(
        title="PRUEBA · Casa",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price="32000",
        bedrooms=3,
        bathrooms=2,
        parking=2,
        furnished=True,
        accepts_pets=True,
        near_schools=True,
        published=True,
        internal_notes="PRIVADO: datos del propietario",
    )


def queue_count():
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM procrastinate_jobs")
        return cursor.fetchone()[0]


def browser():
    client = Client(enforce_csrf_checks=True)
    token = client.get("/api/session").json()["csrf_token"]
    return client, {"HTTP_X_CSRFTOKEN": token}


def post(client, path, payload, headers):
    return client.post(path, data=json.dumps(payload), content_type="application/json", **headers)


def test_filters_unknowns_pagination_and_private_data(home):
    unknown = Property.objects.create(
        title="PRUEBA · Mascotas sin confirmar",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=30000,
        bedrooms=3,
        accepts_pets=None,
        published=True,
    )
    Property.objects.create(
        title="PRUEBA · No mascotas",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=30000,
        bedrooms=3,
        accepts_pets=False,
        published=True,
    )
    Property.objects.create(
        title="PRUEBA · Fuera de presupuesto",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=45000,
        bedrooms=3,
        accepts_pets=True,
        published=True,
    )
    Property.objects.create(
        title="PRUEBA · No publicada",
        operation="rent",
        kind="house",
        municipality="Zapopan",
        neighborhood="La Estancia",
        price=30000,
        bedrooms=3,
        accepts_pets=True,
        published=False,
    )
    criteria = SearchCriteria(operation="rent", max_price=40000, min_bedrooms=3, accepts_pets=True)
    result = search_inventory(criteria)
    assert [p["id"] for p in result["results"]] == [home.id, unknown.id]
    assert result["results"][1]["unconfirmed"] == ["accepts_pets"]
    assert all("internal_notes" not in p for p in result["results"])
    assert search_inventory(criteria.model_copy(update={"verified_only": True}))["total"] == 1
    for i in range(4):
        Property.objects.create(
            title=f"PRUEBA · Página {i}",
            operation="sale",
            kind="land",
            municipality="Tonalá",
            neighborhood="Centro",
            price=1000000 + i,
            published=True,
        )
    page = search_inventory(SearchCriteria(operation="sale"))
    assert len(page["results"]) == 3 and page["next_offset"] == 3 and page["total"] == 4
    assert len(search_inventory(SearchCriteria(operation="sale"), 3)["results"]) == 1


def test_crm_public_projection_auth_and_publish(home):
    client, headers = browser()
    assert client.get("/api/crm/properties").status_code == 401
    assert "PRIVADO" not in client.get("/api/properties").content.decode()
    user = User.objects.create_user("prueba@example.test", "test-password-123", is_staff=True)
    assert (
        post(
            client, "/api/auth/login", {"email": user.email, "password": "test-password-123"}, {}
        ).status_code
        == 403
    )
    login = post(
        client, "/api/auth/login", {"email": user.email, "password": "test-password-123"}, headers
    )
    assert login.status_code == 200
    headers = {"HTTP_X_CSRFTOKEN": login.json()["csrf_token"]}
    assert client.get("/api/crm/properties").json()[0]["internal_notes"].startswith("PRIVADO")
    created = post(
        client,
        "/api/crm/properties",
        {
            "title": "PRUEBA · Nueva desde CRM",
            "operation": "rent",
            "kind": "house",
            "municipality": "Zapopan",
            "neighborhood": "La Estancia",
            "price": "35000",
            "published": True,
        },
        headers,
    )
    assert created.status_code == 200
    assert client.get(f"/api/properties/{created.json()['id']}").status_code == 200
    assert client.get(f"/api/properties/{created.json()['id']}").json()["accepts_pets"] is None


def test_message_isolation_deduplication_and_atomic_queue():
    client, headers = browser()
    assert post(client, "/api/conversations", {}, {}).status_code == 403
    conversation_id = post(client, "/api/conversations", {}, headers).json()["id"]
    payload = {"text": "Busco casa", "client_message_id": str(uuid.uuid4())}
    assert (
        post(client, f"/api/conversations/{conversation_id}/messages", payload, headers).status_code
        == 200
    )
    assert (
        post(client, f"/api/conversations/{conversation_id}/messages", payload, headers).status_code
        == 200
    )
    assert Message.objects.count() == 1 and queue_count() == 1
    # A distinct message with the same text is retained, but the queued turn is coalesced.
    payload["client_message_id"] = str(uuid.uuid4())
    assert (
        post(client, f"/api/conversations/{conversation_id}/messages", payload, headers).status_code
        == 200
    )
    assert Message.objects.count() == 2 and queue_count() == 1
    other, _ = browser()
    assert other.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_enqueue_failure_rolls_back_message_and_revision(monkeypatch):
    from procrastinate.jobs import JobDeferrer

    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    jobs_before = queue_count()

    def fail(*args, **kwargs):
        raise RuntimeError("PRUEBA · no se pudo programar")

    monkeypatch.setattr(JobDeferrer, "defer", fail)
    with pytest.raises(RuntimeError):
        receive_message(conversation.id, conversation.browser_id, "Busco casa", uuid.uuid4())
    conversation.refresh_from_db()
    assert conversation.revision == 0 and Message.objects.count() == 0
    assert queue_count() == jobs_before


class Block:
    def __init__(self, **data):
        self.data = data

    def model_dump(self, **kwargs):
        return self.data


def response(*blocks, stop_reason=None, raw=False):
    return SimpleNamespace(
        content=[Block(**block) for block in blocks],
        usage=SimpleNamespace(input_tokens=100, output_tokens=30),
        stop_reason=stop_reason or ("tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"),
        raw=raw,
    )


def tool(criteria, offset=0):
    return {
        "type": "tool_use",
        "id": "test-tool-id",
        "name": "search_properties",
        "input": {"criteria_patch": criteria, "offset": offset},
    }


class ScriptedClient:
    """Controlled API boundary for tests only; production always uses Anthropic."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = self
        self.calls = []

    async def create(self, **kwargs):
        assert "Comunicación con el cliente" in kwargs["system"]
        assert "Comunicación humana" in kwargs["system"]
        self.calls.append(kwargs)
        value = next(self.responses)
        if callable(value):
            value = await value()
        # Legacy scenarios specify copy only. Adapt that fixture to the explicit final contract.
        if not value.raw and all(b.data["type"] == "text" for b in value.content):
            ids, control = [], None
            for message in kwargs["messages"]:
                if not isinstance(message["content"], list):
                    continue
                for block in message["content"]:
                    if block.get("type") != "tool_result" or not isinstance(block.get("content"), str):
                        continue
                    try:
                        data = json.loads(block["content"])
                    except json.JSONDecodeError:
                        continue
                    ids = data.get("presentation_property_ids", ids)
                    if data.get("pending_confirmation"):
                        control = {"kind": "contact"}
            parts = [{"kind": "text", "text": b.data["text"]} for b in value.content]
            if ids:
                parts.append({"kind": "properties", "property_ids": ids})
            if control:
                parts.append(control)
            value = response({"type": "tool_use", "id": "final", "name": "propose_reply", "input": {
                "blocks": parts, "continuity": {"purpose": "atender la solicitud", "pending": {
                    "kind": "contact_confirmation", "subject": "confirmar celular",
                } if control else None},
            }})
        return value


def new_turn(text):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), revision=1)
    Message.objects.create(conversation=conversation, role="user", text=text)
    return conversation


def test_harness_queries_real_inventory_and_retains_full_history(home):
    conversation = new_turn("Casa en renta en Zapopan, hasta 40000, tres recámaras y mascotas")
    client = ScriptedClient(
        [
            response(
                tool(
                    {
                        "operation": "rent",
                        "municipality": "Zapopan",
                        "max_price": 40000,
                        "min_bedrooms": 3,
                        "accepts_pets": True,
                    }
                )
            ),
            response({"type": "text", "text": "Encontré una opción para ti."}),
        ]
    )
    asyncio.run(attend(str(conversation.id), client, group_messages=False))
    reply = conversation.messages.last()
    assert reply.properties[0]["id"] == home.id
    assert "PRIVADO" not in json.dumps(client.calls, ensure_ascii=False)
    assert Execution.objects.get().status == "completed"
    assert Execution.objects.get().input_tokens == 200
    conversation.refresh_from_db()
    conversation.revision += 1
    conversation.save()
    Message.objects.create(conversation=conversation, role="user", text="¿Está amueblada?")
    second = ScriptedClient(
        [response({"type": "text", "text": "Voy a revisar el detalle vigente."})]
    )
    asyncio.run(attend(str(conversation.id), second, group_messages=False))
    assert second.calls[0]["messages"][0]["content"].startswith("Casa en renta")
    assert len(second.calls[0]["messages"]) >= 3


def test_zero_results_does_not_allow_automatic_relaxation(home):
    conversation = new_turn("Hasta 10000")
    client = ScriptedClient(
        [
            response(tool({"max_price": 10000})),
            response(tool({"max_price": 50000})),
            response(
                {
                    "type": "text",
                    "text": "No encontré coincidencias. ¿Quieres ampliar el presupuesto?",
                }
            ),
        ]
    )
    asyncio.run(attend(str(conversation.id), client, group_messages=False))
    conversation.refresh_from_db()
    assert conversation.criteria["max_price"] == "10000"
    assert conversation.messages.last().properties == []
    assert Execution.objects.get().tool_events[1]["outcome"] == "ask_permission"


def test_new_message_supersedes_an_answer_in_flight(home):
    conversation = new_turn("Busco rentar")

    async def meanwhile():
        await sync_to_async(receive_message)(
            conversation.id, conversation.browser_id, "Perdón, quiero comprar", uuid.uuid4()
        )
        return response({"type": "text", "text": "Respuesta desactualizada de renta"})

    asyncio.run(attend(str(conversation.id), ScriptedClient([meanwhile]), group_messages=False))
    assert not conversation.messages.filter(role="assistant").exists()
    assert Execution.objects.get().status == "superseded"


def test_inventory_change_prevents_stale_cards(home):
    conversation = new_turn("Busco una casa")

    async def meanwhile():
        await Property.objects.filter(pk=home.pk).aupdate(price=999999)
        return response({"type": "text", "text": "Está dentro de tu presupuesto."})

    client = ScriptedClient([response(tool({"max_price": 40000})), meanwhile])
    asyncio.run(attend(str(conversation.id), client, group_messages=False))
    reply = conversation.messages.last()
    assert reply.properties == [] and "cambió" in reply.text


@pytest.mark.parametrize("corrected", [True, False])
def test_property_details_stay_in_cards_after_bounded_copy_repair(home, corrected):
    conversation = new_turn("Busco una casa en renta")
    repeated = "**PRUEBA · Casa** cuesta $32,000 MXN al mes. Tiene 3 recámaras."
    client = ScriptedClient(
        [
            response(tool({"max_price": 40000})),
            response({"type": "text", "text": repeated}),
            response(
                {
                    "type": "text",
                    "text": "Te comparto esta opción. ¿Quieres conocer más detalles?"
                    if corrected
                    else repeated,
                }
            ),
        ]
    )
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    reply = conversation.messages.last()
    assert len(reply.properties) == 1 and not reply.is_error
    assert "32,000" not in reply.text and "**" not in reply.text
    assert "PRUEBA · Casa" not in reply.text
    assert len(client.calls) == 3 and [t["name"] for t in client.calls[-1]["tools"]] == ["propose_reply"]
    assert Execution.objects.get().status == "completed"


def test_missing_credentials_records_failure_without_inventing_results(settings):
    settings.ANTHROPIC_API_KEY = ""
    conversation = new_turn("Quiero una casa")
    asyncio.run(attend(str(conversation.id), group_messages=False))
    assert Execution.objects.get().error_code == "MissingCredentials"
    assert conversation.messages.last().is_error
    assert conversation.messages.last().properties == []


@pytest.mark.parametrize("answer", [
    "Sí, acepta mascotas.",
    "La renta es de $32,000 MXN al mes.",
    "La cercanía a escuelas está pendiente de confirmar.",
])
def test_specific_question_can_answer_facts_without_repeating_card(home, answer):
    conversation = new_turn("¿Me confirmas ese dato de la casa?")
    client = ScriptedClient([
        response({"type": "tool_use", "id": "detail", "name": "get_property",
                  "input": {"property_id": home.pk, "show_card": False}}),
        response({"type": "text", "text": answer}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    reply = conversation.messages.last()
    assert reply.text == answer and reply.properties == [] and not reply.is_error
    assert len(client.calls) == 2


def test_property_refresh_after_search_preserves_three_result_cards(home):
    homes = [home]
    for n in range(2):
        homes.append(Property.objects.create(
            title=f"PRUEBA · Otra casa {n}", operation="rent", kind="house",
            municipality="Zapopan", price=33000 + n, published=True,
        ))
    conversation = new_turn("Muéstrame casas en renta en Zapopan")
    client = ScriptedClient([
        response(tool({"operation": "rent", "municipality": "Zapopan", "accepts_pets": True})),
        response(*[{
            "type": "tool_use", "id": f"detail-{p.pk}", "name": "get_property",
            "input": {"property_id": p.pk},
        } for p in homes]),
        response({"type": "text", "text": "Estas son las opciones disponibles."}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    reply = conversation.messages.last()
    assert not reply.is_error
    assert [p["id"] for p in reply.properties] == [p.pk for p in homes]
    assert all("accepts_pets" in p["unconfirmed"] for p in reply.properties[1:])


@pytest.mark.parametrize("corrected", [True, False])
def test_card_copy_repair_keeps_contact_confirmation_without_repeating_actions(home, corrected):
    conversation = new_turn("Me interesa la casa. Mi celular es 3312345678.")
    repeated = "PRUEBA · Casa cuesta $32,000 MXN y tiene 3 recámaras. Confirma tu número."
    client = ScriptedClient([
        response({"type": "tool_use", "id": "property", "name": "get_property",
                  "input": {"property_id": home.pk}},
                 {"type": "tool_use", "id": "interest", "name": "record_interest",
                  "input": {"property_ids": [home.pk]}},
                 {"type": "tool_use", "id": "contact", "name": "prepare_contact",
                  "input": {"phone": "3312345678"}}),
        response({"type": "text", "text": repeated}),
        response({"type": "text", "text": "Revisa tu número y confírmalo aquí."
                  if corrected else repeated}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    conversation.refresh_from_db()
    reply = conversation.messages.last()
    assert not reply.is_error and len(reply.properties) == 1
    assert "32,000" not in reply.text and "conf" in reply.text
    assert conversation.contact_candidate["phone"] == "+523312345678"
    assert not conversation.prospect_id
    assert conversation.interests.count() == 1
    events = Execution.objects.get().tool_events
    assert [event["tool"] for event in events if event["tool"] != "reply_validation"] == ["get_property", "record_interest", "prepare_contact"]
    assert [t["name"] for t in client.calls[-1]["tools"]] == ["propose_reply"]


def test_interest_click_records_exact_property_once_before_model_runs(home):
    from datalayer.models import FollowupCycle
    from datalayer.turns import load_turn

    client, headers = browser()
    cid = post(client, "/api/conversations", {}, headers).json()["id"]
    payload = {"text": "Me interesa esta propiedad", "property_id": home.pk,
               "client_message_id": str(uuid.uuid4())}
    result = post(client, f"/api/conversations/{cid}/messages", payload, headers)
    assert result.status_code == 200
    assert result.json()["has_interest"] and not result.json()["human_requested"]
    assert not result.json()["contact_registered"] and result.json()["followup_permission"] is None
    message = result.json()["messages"][0]
    assert message["text"] == "" and message["role"] == "assistant"
    assert [p["id"] for p in message["properties"]] == [home.pk]
    conversation = Conversation.objects.get(pk=cid)
    assert list(conversation.interests.values_list("pk", flat=True)) == [home.pk]
    assert not FollowupCycle.objects.exists()
    turn = load_turn(cid)
    assert turn["interest_expressed"]
    assert turn["interest_action"]["id"] == home.pk
    assert f'"id": {home.pk}' in build_messages(turn)[0]["content"]
    assert "PRIVADO" not in build_messages(turn)[0]["content"]
    home.published = False
    home.save(update_fields=["published"])
    assert post(client, f"/api/conversations/{cid}/messages", payload, headers).status_code == 200
    assert Message.objects.count() == 1 and queue_count() == 1


def test_interest_action_is_hidden_after_card_and_stays_hidden_on_reload(home):
    from datalayer.inventory import public_property

    client, headers = browser()
    cid = post(client, "/api/conversations", {}, headers).json()["id"]
    Message.objects.create(conversation_id=cid, role="assistant", text="Una opción.",
                           properties=[public_property(home)])
    result = post(client, f"/api/conversations/{cid}/messages", {
        "text": "texto fabricado que no debe aparecer", "property_id": home.pk,
        "client_message_id": str(uuid.uuid4()),
    }, headers)
    assert len(result.json()["messages"]) == 1
    assert result.json() == client.get(f"/api/conversations/{cid}").json()
    action = Message.objects.last()
    assert action.kind == "property_interest" and action.display_kind == "hidden"
    assert "texto fabricado" not in action.text


@pytest.mark.parametrize("show_again", [False, True])
def test_retrieval_only_repeats_existing_card_when_requested(home, show_again):
    from datalayer.inventory import public_property

    conversation = new_turn("Vuelve a mostrar la ficha" if show_again else "¿Acepta mascotas?")
    Message.objects.create(conversation=conversation, role="assistant", text="Una opción.",
                           properties=[public_property(home)])
    client = ScriptedClient([
        response({"type": "tool_use", "id": "detail", "name": "get_property",
                  "input": {"property_id": home.pk, "show_again": show_again}}),
        response({"type": "text", "text": "Puedes revisarla aquí." if show_again else "Sí, acepta mascotas."}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    reply = conversation.messages.last()
    assert len(reply.properties) == int(show_again) and not reply.is_error
    tool_result = json.loads(client.calls[1]["messages"][-2]["content"][0]["content"])
    assert ("property" in tool_result) is show_again


@pytest.mark.parametrize("known_name, name_requested", [("", False), ("Guillermo", False), ("", True)])
def test_interest_action_does_not_force_slots_or_append_name(home, monkeypatch, known_name, name_requested):
    from datalayer.models import AppointmentOperation, AppointmentProposal

    conversation = Conversation.objects.create(browser_id=uuid.uuid4(), contact_name=known_name,
                                               name_requested=name_requested)
    receive_message(conversation.pk, conversation.browser_id, "ignored", uuid.uuid4(), property_id=home.pk)
    slot_calls = []

    def available(cid, revision, name, arguments):
        slot_calls.append((name, arguments))
        return {"options": [{"start": "2026-11-09T10:00:00-06:00", "end": "2026-11-09T11:00:00-06:00"}]}

    monkeypatch.setattr("harness.tools.visit_tool", available)
    client = ScriptedClient([
        response({"type": "tool_use", "id": "detail", "name": "get_property",
                  "input": {"property_id": home.pk}}),
        response({"type": "text", "text": "Claro, te ayudo a coordinar una visita."}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    assert slot_calls == []
    assert conversation.messages.last().properties == []
    assert conversation.messages.last().text == "Claro, te ayudo a coordinar una visita."
    assert not AppointmentProposal.objects.exists() and not AppointmentOperation.objects.exists()


def test_new_written_request_after_interest_directs_the_turn(home, monkeypatch):
    conversation = Conversation.objects.create(browser_id=uuid.uuid4())
    receive_message(conversation.pk, conversation.browser_id, "ignored", uuid.uuid4(), property_id=home.pk)
    receive_message(conversation.pk, conversation.browser_id, "Antes dime si acepta mascotas", uuid.uuid4())

    def unexpected_slots(*args, **kwargs):
        raise AssertionError("La nueva petición no requiere horarios")

    monkeypatch.setattr("harness.tools.visit_tool", unexpected_slots)
    client = ScriptedClient([
        response({"type": "tool_use", "id": "detail", "name": "get_property",
                  "input": {"property_id": home.pk, "show_card": False}}),
        response({"type": "text", "text": "Sí, acepta mascotas."}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    reply = conversation.messages.last()
    assert reply.text == "Sí, acepta mascotas." and not reply.properties and not reply.is_error


def test_name_question_belongs_to_the_proposal_not_a_backend_append(home):
    conversation = new_turn("Quiero información")
    client = ScriptedClient([
        response({"type": "tool_use", "id": "final", "name": "propose_reply", "input": {
            "blocks": [{"kind": "text", "text": "¿Con quién tengo el gusto?"}],
            "continuity": {"purpose": "coordinar visita", "pending": {"kind": "name", "subject": "nombre opcional"}},
        }}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    conversation.refresh_from_db()
    assert not conversation.name_requested
    assert conversation.messages.last().text == "¿Con quién tengo el gusto?"
    assert conversation.messages.last().continuity["pending"]["kind"] == "name"
    receive_message(conversation.pk, conversation.browser_id, "El lunes", uuid.uuid4())
    client = ScriptedClient([
        response({"type": "text", "text": "Revisemos ese día."}),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    assert conversation.messages.last().text == "Revisemos ese día."


def test_failed_reply_does_not_mark_name_as_asked():
    conversation = new_turn("Quiero información")
    client = ScriptedClient([
        response({"type": "text", "text": "respuesta incompleta"}, stop_reason="max_tokens", raw=True),
    ])
    asyncio.run(attend(str(conversation.pk), client, group_messages=False))
    conversation.refresh_from_db()
    assert not conversation.name_requested and conversation.messages.last().is_error


def test_interest_click_rejects_unpublished_property_without_partial_changes(home):
    home.published = False
    home.save(update_fields=["published"])
    client, headers = browser()
    cid = post(client, "/api/conversations", {}, headers).json()["id"]
    result = post(client, f"/api/conversations/{cid}/messages", {
        "text": "Me interesa", "property_id": home.pk,
        "client_message_id": str(uuid.uuid4()),
    }, headers)
    assert result.status_code == 422
    conversation = Conversation.objects.get(pk=cid)
    assert not conversation.interest_expressed and not conversation.interests.exists()
    assert not Message.objects.exists() and queue_count() == 0


def test_interest_click_requires_own_session_and_csrf(home):
    client, headers = browser()
    cid = post(client, "/api/conversations", {}, headers).json()["id"]
    payload = {"text": "Me interesa", "property_id": home.pk,
               "client_message_id": str(uuid.uuid4())}
    assert post(client, f"/api/conversations/{cid}/messages", payload, {}).status_code == 403
    other, other_headers = browser()
    assert post(other, f"/api/conversations/{cid}/messages", payload, other_headers).status_code == 404
    assert not Message.objects.exists() and not Conversation.objects.get(pk=cid).interest_expressed

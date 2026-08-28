"""The operator surfaces: Mexican Spanish, usable, accessible, and honest.

Four things this suite holds still.

**Language.** Every visible string is Mexican Spanish, and the internal
vocabulary — lead, listing, pipeline, property expert — never leaks into it.

**Accessibility and mobile.** One shell, so the language attribute, the skip
link, the visible focus ring, the labelled controls, the table header scopes and
the single-column collapse cannot go missing from one screen at a time. No
JavaScript is required for any action.

**Honesty.** Denied outbound decisions and an active Do Not Contact are shown to
the operator with the reason. Showing them is the point; none of these surfaces
can send anything.

**Refusals an operator can act on.** A credential with no member row, an
Opportunity that is not theirs, an illegal stage change and an empty list all
produce Spanish text that says what to do next.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, BasicAuth
from sqlalchemy import func, select

from realestate.api.crm import DENIAL_REASON_LABELS
from realestate.app import create_app
from realestate.config import get_settings
from realestate.db.engine import Database
from realestate.db.models import (
    ConsentCategory,
    ConsentRecord,
    ConsentState,
    NextActionKind,
    Opportunity,
    OpportunityStage,
    OutboundInitiation,
    OutboxMessage,
    SuppressionRecord,
)
from realestate.domain.commercial.assignment import Assignment
from realestate.domain.commercial.next_actions import NextActions, ScheduleNextAction
from realestate.domain.commercial.opportunities import (
    AdvanceStage,
    OpportunityManagement,
)
from realestate.domain.outbound import (
    Denied,
    OutboundIntent,
    OutboundMessaging,
    Purpose,
)
from tests.conftest import DATABASE_URL, REPO_ROOT, requires_postgres
from tests.fixtures import commercial

pytestmark = requires_postgres

ADMIN = BasicAuth(commercial.ADMIN_LOGIN, commercial.ADMIN_PASSWORD)
ADVISOR = BasicAuth(commercial.ADVISOR_LOGIN, commercial.ADVISOR_PASSWORD)
OTHER_ADVISOR = BasicAuth(
    commercial.SECOND_ADVISOR_LOGIN, commercial.SECOND_ADVISOR_PASSWORD
)
#: Authenticates, but is deliberately not a member of the Organization.
STRANGER_LOGIN = "desconocido@larevia.test"
STRANGER_PASSWORD = "test-stranger-password"
STRANGER = BasicAuth(STRANGER_LOGIN, STRANGER_PASSWORD)

CRM_PATHS = (
    "/crm",
    "/crm/bandeja",
    "/crm/oportunidades",
    "/crm/contactos",
    "/crm/asignacion",
)

# Internal vocabulary that must never reach an operator's screen
# (PROJECT_MEMORY). Word boundaries matter: "contacto" legitimately contains
# "contact".
FORBIDDEN_WORDS = (
    r"\blead\b",
    r"\bleads\b",
    r"\blisting\b",
    r"\blistings\b",
    r"\bpipeline\b",
    r"\bopportunity\b",
    r"\bopportunities\b",
    r"\bnext action\b",
    r"\bproperty expert\b",
    r"\bassignment queue\b",
    r"\bdormant\b",
    r"\bqualified\b",
    r"\bbroker\b",
)

_TAGS = re.compile(r"<[^>]+>")
_DROPPED = re.compile(r"<(style|script)\b.*?</\1>", re.DOTALL | re.IGNORECASE)


def visible_text(html: str) -> str:
    """What a person actually reads, without markup or the stylesheet."""
    return _TAGS.sub(" ", _DROPPED.sub(" ", html))


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv(
        "DEVELOPER_BASIC_CREDENTIALS_JSON",
        commercial.credentials_json(**{STRANGER_LOGIN: STRANGER_PASSWORD}),
    )
    get_settings.cache_clear()

    database = Database(DATABASE_URL)
    async with database.session_scope() as session:
        await commercial.reset(session)
        await commercial.provision(session)

    app = create_app(get_settings())
    app.state.database = database
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://product.test"
    ) as client:
        yield client, database
    await database.dispose()
    get_settings.cache_clear()


async def _opportunity(database, *, assign: bool = True, wa_id="5213312345678"):  # noqa: ANN001, ANN202
    """A Contact with a conversation and an Opportunity, ready to render."""
    async with database.session_scope() as session:
        # Contact first: the builder owns creating the channel identity, so the
        # conversation is hung off the Lead it made rather than a second one.
        state = await commercial.opportunity_for(
            session, wa_id, profile_name="Ana Demo", assign=assign
        )
        conversation = await commercial.make_conversation(session, state.lead)
        await commercial.make_inbound(
            session, conversation, text_body="Quiero ver la casa del coto Demo."
        )
        await session.commit()
        return state.contact_id, conversation.id, state.opportunity_id


# -- Authentication and authorization -------------------------------------


async def test_every_crm_surface_requires_basic_auth(wired) -> None:
    client, _database = wired
    for path in CRM_PATHS:
        response = await client.get(path)
        assert response.status_code == 401, path
        assert response.headers["WWW-Authenticate"] == "Basic"


async def test_a_credential_with_no_member_row_is_refused_in_spanish(wired) -> None:
    """Authentication succeeded; authorization is the new, explicit step."""
    client, _database = wired
    response = await client.get("/crm", auth=STRANGER)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "no pertenece a ninguna organización" in detail
    assert "administrador" in detail


async def test_the_shell_names_the_session_and_the_role(wired) -> None:
    client, _database = wired

    admin = await client.get("/crm", auth=ADMIN)
    advisor = await client.get("/crm", auth=ADVISOR)

    assert "Administrador de la organización" in admin.text
    assert commercial.ADMIN_LOGIN in admin.text
    assert "Asesor inmobiliario" in advisor.text


async def test_the_assignment_queue_is_administrator_only(wired) -> None:
    client, database = wired
    await _opportunity(database, assign=False)

    admin = await client.get("/crm/asignacion", auth=ADMIN)
    advisor = await client.get("/crm/asignacion", auth=ADVISOR)

    assert admin.status_code == 200
    assert advisor.status_code == 404
    assert (
        "Sólo un administrador de la organización puede realizar esta acción."
        in advisor.text
    )


async def test_another_advisors_opportunity_reads_as_absent(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.get(
        f"/crm/oportunidades/{opportunity_id}", auth=OTHER_ADVISOR
    )

    assert response.status_code == 404
    assert "No encontramos esa oportunidad." in response.text
    # No hint that it exists and belongs to somebody else.
    assert "Ana Demo" not in response.text


# -- Accessibility and mobile ---------------------------------------------


@pytest.mark.parametrize("path", CRM_PATHS)
async def test_every_surface_ships_the_accessible_spanish_shell(
    wired, path: str
) -> None:
    client, database = wired
    await _opportunity(database)

    response = await client.get(path, auth=ADMIN)

    assert response.status_code == 200
    html = response.text
    assert '<html lang="es-MX">' in html
    assert '<meta name="viewport" content="width=device-width,initial-scale=1">' in html
    assert 'href="#contenido"' in html
    assert "Ir al contenido principal" in html
    assert '<main id="contenido">' in html
    assert 'aria-label="Navegación principal"' in html
    assert 'aria-current="page"' in html
    # Keyboard focus stays visible and controls stay reachable on a phone.
    assert "focus-visible" in html
    assert "min-height:44px" in html
    assert "@media (max-width:760px)" in html
    # No JavaScript is required for any surface to work.
    assert "<script" not in html
    assert "onclick" not in html


@pytest.mark.parametrize("path", CRM_PATHS)
async def test_every_form_control_has_a_label(wired, path: str) -> None:
    client, database = wired
    await _opportunity(database)

    html = (await client.get(path, auth=ADMIN)).text

    ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html))
    labelled = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    assert ids <= labelled, ids - labelled

    # Controls without an id are wrapped by their own label instead.
    for control in re.findall(r"<(?:input|select|textarea)\b[^>]*>", html):
        if 'type="hidden"' in control or 'id="' in control:
            continue
        assert "<label" in html


@pytest.mark.parametrize("path", CRM_PATHS)
async def test_every_table_names_its_headers_and_says_what_it_holds(
    wired, path: str
) -> None:
    client, database = wired
    await _opportunity(database)

    html = (await client.get(path, auth=ADMIN)).text

    for table in re.findall(r"<table>.*?</table>", html, re.DOTALL):
        assert "<caption>" in table
        for header in re.findall(r"<th\b[^>]*>", table):
            assert 'scope="col"' in header


@pytest.mark.parametrize("path", CRM_PATHS)
async def test_no_internal_vocabulary_reaches_the_screen(wired, path: str) -> None:
    client, database = wired
    await _opportunity(database)

    text = visible_text((await client.get(path, auth=ADMIN)).text).lower()

    for pattern in FORBIDDEN_WORDS:
        assert re.search(pattern, text) is None, (path, pattern)


async def test_the_opportunity_detail_is_also_spanish_and_labelled(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)

    assert response.status_code == 200
    html = response.text
    text = visible_text(html).lower()
    for pattern in FORBIDDEN_WORDS:
        assert re.search(pattern, text) is None, pattern
    ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html))
    labelled = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    assert ids <= labelled, ids - labelled
    for label in (
        "Necesidad del contacto",
        "Siguiente acción",
        "Etapa comercial",
        "Asignación",
        "Historial de etapas",
    ):
        assert label in html


# -- Empty states ---------------------------------------------------------


async def test_empty_surfaces_say_what_to_do_next(wired) -> None:
    client, _database = wired

    panel = await client.get("/crm", auth=ADMIN)
    assert "Todavía no hay oportunidades calificadas activas." in panel.text
    assert "No hay acciones vencidas." in panel.text
    assert "La cola de asignación está vacía." in panel.text

    inbox = await client.get("/crm/bandeja", auth=ADMIN)
    assert "No hay conversaciones que coincidan." in inbox.text
    assert "espera el primer mensaje de WhatsApp" in inbox.text

    opportunities = await client.get("/crm/oportunidades", auth=ADMIN)
    assert "No hay oportunidades que coincidan." in opportunities.text

    contacts = await client.get("/crm/contactos", auth=ADMIN)
    assert "No hay contactos que coincidan." in contacts.text

    queue = await client.get("/crm/asignacion", auth=ADMIN)
    assert "La cola está vacía." in queue.text


async def test_a_filter_that_matches_nothing_still_renders_a_page(wired) -> None:
    client, database = wired
    await _opportunity(database)

    response = await client.get("/crm/bandeja?q=nadie&scope=mine", auth=ADMIN)

    assert response.status_code == 200
    assert "No hay conversaciones que coincidan." in response.text
    assert "Limpiar" in response.text


async def test_unparseable_filters_fall_back_instead_of_erroring(wired) -> None:
    """A stale bookmark should show a list, not a 422."""
    client, database = wired
    await _opportunity(database)

    response = await client.get(
        "/crm/bandeja?scope=cualquiera&stage=Inventada&limit=abc", auth=ADMIN
    )

    assert response.status_code == 200
    assert "Ana Demo" in response.text


# -- The Inbox and its restrictions ---------------------------------------


async def test_the_inbox_shows_the_conversation_and_what_is_owed(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=commercial.now() - timedelta(hours=2),
                command_key="surface:overdue",
            ),
        )
        await session.commit()

    response = await client.get("/crm/bandeja", auth=ADMIN)

    assert "Ana Demo" in response.text
    assert "coto Demo" in response.text
    assert "Espera respuesta" in response.text
    assert "Llamar por teléfono" in response.text
    assert "Vencida" in response.text


async def test_denied_outbound_decisions_are_visible_with_their_reason(
    wired,
) -> None:
    client, database = wired
    _contact_id, conversation_id, _opportunity_id = await _opportunity(database)

    async with database.session_scope() as session:
        from realestate.db.models import Conversation

        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        decision = await OutboundMessaging(session).request(
            OutboundIntent(
                conversation=conversation,
                body="¿Sigues buscando?",
                purpose=Purpose.LEAD_FOLLOW_UP,
                initiation=OutboundInitiation.BUSINESS_INITIATED,
                idempotency_key="surface:denied",
            )
        )
        await session.commit()
        assert isinstance(decision, Denied)
        denied_reason = decision.reason.value

    response = await client.get(f"/crm/bandeja/{conversation_id}", auth=ADMIN)

    assert response.status_code == 200
    assert "Mensajes que no se enviaron" in response.text
    assert "Seguimiento" in response.text
    # The reason shown is the reason Stage 1 actually recorded, translated —
    # here, that the Contact wrote and is owed an answer rather than outreach.
    assert DENIAL_REASON_LABELS[denied_reason] in response.text
    assert "nadie puede enviarlas desde esta pantalla" in response.text
    # The list is visible on the Inbox too.
    listing = await client.get("/crm/bandeja?restringidos=1", auth=ADMIN)
    assert "envío(s) no permitido(s)" in listing.text


async def test_an_opt_out_is_shown_and_no_surface_can_send(wired) -> None:
    client, database = wired
    _contact_id, conversation_id, _opportunity_id = await _opportunity(database)

    async with database.session_scope() as session:
        from realestate.db.models import Conversation

        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        session.add(
            SuppressionRecord(
                lead_id=conversation.lead_id,
                scope="BusinessInitiated",
                reason="ExplicitOptOut",
                evidence="baja",
            )
        )
        session.add(
            ConsentRecord(
                lead_id=conversation.lead_id,
                category=ConsentCategory.MARKETING.value,
                state=ConsentState.REVOKED.value,
                source="InboundOptOut",
                evidence="baja",
            )
        )
        await session.commit()

    response = await client.get(f"/crm/bandeja/{conversation_id}", auth=ADMIN)

    assert response.status_code == 200
    assert "No se puede enviar nada a este contacto" in response.text
    assert "pidió explícitamente no recibir mensajes" in response.text
    assert "Sí es posible responder cuando el contacto escribe." in response.text
    # Stage 3 gave this screen a reply path (ADR-0029), so "no form at all"
    # stopped being the guarantee. What still holds is stronger and is asserted
    # where it lives: an operator who does not hold the conversation gets no
    # message box at all, and the Outbound Eligibility Gate refuses a suppressed
    # Contact whoever is typing — see tests/test_conversation_handling.py.
    assert "Responder por WhatsApp" not in response.text
    assert 'name="mensaje"' not in response.text
    assert "<textarea" not in response.text

    # And the contact list marks the restriction.
    contacts = await client.get("/crm/contactos", auth=ADMIN)
    assert "No contactar" in contacts.text

    async with database.session_scope() as session:
        # Nothing was staged by looking at it.
        assert (await session.scalar(select(OutboxMessage).limit(1))) is None


def test_the_crm_router_has_no_path_to_outbound_messaging() -> None:
    """Structural, not behavioural: the gate has no entry point here."""
    source = (REPO_ROOT / "src/realestate/api/crm.py").read_text(encoding="utf-8")
    for forbidden in ("OutboundMessaging", "OutboxService", "WhatsAppClient"):
        assert forbidden not in source


# -- Contacts -------------------------------------------------------------


async def test_the_contact_detail_shows_identities_and_look_alikes(wired) -> None:
    client, database = wired
    contact_id, _conversation_id, _opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        await commercial.make_contact(session, "523312345678")
        await session.commit()

    response = await client.get(f"/crm/contactos/{contact_id}", auth=ADMIN)

    assert response.status_code == 200
    assert "Identidades de canal" in response.text
    assert "Verificada" in response.text
    assert "Hay números parecidos en otros contactos." in response.text
    assert "parecerse no demuestra que sean la misma" in response.text


async def test_an_unknown_contact_reads_as_absent(wired) -> None:
    client, _database = wired
    response = await client.get(f"/crm/contactos/{uuid.uuid4()}", auth=ADMIN)
    assert response.status_code == 404
    assert "No encontramos ese registro." in response.text


async def test_searching_contacts_narrows_the_list(wired) -> None:
    client, database = wired
    await _opportunity(database)

    found = await client.get("/crm/contactos?q=Ana", auth=ADMIN)
    missing = await client.get("/crm/contactos?q=Zoraida", auth=ADMIN)

    assert "Ana Demo" in found.text
    assert "Ana Demo" not in missing.text


# -- Mutations through the surfaces ---------------------------------------


async def test_an_advisor_can_schedule_and_complete_an_action(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    due = (commercial.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")

    scheduled = await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones",
        data={
            "tipo": NextActionKind.CALL.value,
            "vence": due,
            "nota": "Confirmar",
            "clave": "advisor-schedule",
        },
        auth=ADVISOR,
        follow_redirects=True,
    )
    assert scheduled.status_code == 200
    assert "Se agendó la siguiente acción." in scheduled.text

    async with database.session_scope() as session:
        pending = await NextActions(session).pending(opportunity_id)
        assert pending is not None
        action_id = pending.id

    completed = await client.post(
        f"/crm/acciones/{action_id}/completar",
        data={
            "resultado": "Done",
            "detalle": "Ya le llamé.",
            "clave": "advisor-complete",
        },
        auth=ADVISOR,
        follow_redirects=True,
    )
    assert "Se registró el resultado de la acción." in completed.text
    assert "Realizada" in completed.text


async def test_an_invalid_due_date_is_reported_in_spanish(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones",
        data={"tipo": NextActionKind.CALL.value, "vence": "mañana"},
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "fecha y hora de vencimiento válida" in response.text
    assert 'role="alert"' in response.text


async def test_an_unknown_action_type_is_refused(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones",
        data={"tipo": "Inventada", "vence": "2026-09-01T10:00"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Tipo de acción desconocido." in response.text


async def test_an_illegal_stage_change_explains_itself(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "avanzar",
            "etapa": OpportunityStage.SEARCHING.value,
            "clave": "illegal-stage",
        },
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "No se puede pasar de «Nueva» a «En búsqueda»." in response.text


async def test_qualifying_without_criteria_names_what_is_missing(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "avanzar",
            "etapa": OpportunityStage.QUALIFIED.value,
            "clave": "qualify-missing",
        },
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "Faltan criterios confirmados" in response.text
    assert "Zona aceptable" in response.text


async def test_criteria_can_be_recorded_and_confirmed_from_the_surface(
    wired,
) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    recorded = await client.post(
        f"/crm/oportunidades/{opportunity_id}/criterios",
        data={
            "intent": "registrar",
            "nombre": "service_area",
            "valor": "Zapopan norte",
            "evidencia": "Lo dijo por teléfono.",
            "clave": "record-criterion",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se actualizaron los criterios." in recorded.text
    assert "Zapopan norte" in recorded.text
    assert "Confirmado" in recorded.text

    # A pending interpretation gets a confirm button, and confirming works.
    async with database.session_scope() as session:
        from realestate.domain.commercial.needs import (
            HORIZON,
            CriterionStatement,
            PropertyNeeds,
        )

        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await PropertyNeeds(session).record(
            actor=admin,
            need_id=opportunity.property_need_id,
            statements=[CriterionStatement.inferred(HORIZON, "tres meses")],
        )
        await session.commit()

    page = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert "Por confirmar" in page.text
    assert "Confirmar con el contacto" in page.text

    confirmed = await client.post(
        f"/crm/oportunidades/{opportunity_id}/criterios",
        data={
            "intent": "confirmar",
            "nombre": "horizon",
            "clave": "confirm-criterion",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se actualizaron los criterios." in confirmed.text
    # No criterion is awaiting confirmation any more. The superseded
    # interpretation stays visible in the history, which is the point of it.
    assert "Confirmar con el contacto" not in confirmed.text
    assert "Interpretado por Maia" in confirmed.text


async def test_an_empty_criterion_is_refused(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/criterios",
        data={
            "intent": "registrar",
            "nombre": "service_area",
            "valor": "  ",
            "clave": "empty-criterion",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Indica el criterio y su valor." in response.text

async def test_only_the_administrator_sees_the_won_form(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="surface:qualify",
            ),
        )
        await session.commit()

    as_admin = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    as_advisor = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADVISOR)

    assert "Registrar operación concluida" in as_admin.text
    assert "Una cita, una visita o" in as_admin.text
    assert "Registrar operación concluida" not in as_advisor.text
    assert (
        "Sólo un administrador de la organización puede registrar una"
        in as_advisor.text
    )

    refused = await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "ganada",
            "evidencia": "CompletedSale",
            "detalle": "Ya se firmó.",
            "clave": "advisor-won-refused",
        },
        auth=ADVISOR,
        follow_redirects=True,
    )
    assert "Sólo un administrador" in refused.text

    accepted = await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "ganada",
            "evidencia": "CompletedSale",
            "detalle": "Escritura firmada ante notario 12.",
            "clave": "admin-won",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se registró el cambio de etapa." in accepted.text
    assert "Ganada: Venta concluida legalmente" in accepted.text


async def test_lost_and_dormant_are_recorded_with_their_reasons(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, first = await _opportunity(database)
    _contact_id2, _conversation_id2, second = await _opportunity(
        database, wa_id="5213399990000"
    )

    lost = await client.post(
        f"/crm/oportunidades/{first}/etapa",
        data={
            "intent": "perdida",
            "motivo": "BoughtElsewhere",
            "detalle": "Compró en otro coto.",
            "clave": "lost",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Perdida: Compró o rentó en otro lugar" in lost.text

    dormant = await client.post(
        f"/crm/oportunidades/{second}/etapa",
        data={
            "intent": "pausa",
            "motivo": "AwaitingNewInventory",
            "condicion": "Cuando entre inventario en Zapopan norte.",
            "clave": "dormant",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "En pausa: Espera inventario nuevo" in dormant.text
    assert "Cuando entre inventario en Zapopan norte." in dormant.text


async def test_an_unknown_reason_or_intent_is_refused(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    for data, expected in (
        ({"intent": "avanzar", "etapa": "Inventada"}, "Etapa desconocida."),
        ({"intent": "perdida", "motivo": "Inventado"}, "Motivo desconocido."),
        (
            {"intent": "pausa", "motivo": "Inventado", "condicion": "x"},
            "Motivo desconocido.",
        ),
        (
            {"intent": "ganada", "evidencia": "Inventada", "detalle": "x"},
            "Evidencia desconocida.",
        ),
        ({"intent": "otra-cosa"}, "Acción desconocida."),
    ):
        response = await client.post(
            f"/crm/oportunidades/{opportunity_id}/etapa",
            data={**data, "clave": f"unknown-{expected}"},
            auth=ADMIN,
            follow_redirects=True,
        )
        assert expected in response.text, data


# -- The Assignment Queue -------------------------------------------------


async def test_the_queue_lists_unassigned_work_with_a_reason(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from realestate.domain.commercial.organization import (
            DirectoryPlan,
            OrganizationDirectory,
        )

        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(),
                default_advisor=None,
            )
        )
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await Assignment(session).assign(admin, opportunity_id)
        await session.commit()

    response = await client.get("/crm/asignacion", auth=ADMIN)

    assert "Ana Demo" in response.text
    assert "No hay un asesor elegible configurado" in response.text
    assert "No hay asesores activos." in response.text
    assert "directorio de la organización" in response.text


async def test_assigning_from_the_queue_works_and_reports_itself(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )
    async with database.session_scope() as session:
        members = await commercial.provision(session)
        advisor_id = members[commercial.ADVISOR_LOGIN]

    response = await client.post(
        f"/crm/asignacion/{opportunity_id}",
        data={"asesor": str(advisor_id), "clave": "queue-assign"},
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "Se asignó la oportunidad." in response.text
    assert "La cola está vacía." in response.text


async def test_a_malformed_advisor_choice_is_refused(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )

    from_queue = await client.post(
        f"/crm/asignacion/{opportunity_id}",
        data={"asesor": "no-es-un-uuid"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Asesor desconocido." in from_queue.text

    from_detail = await client.post(
        f"/crm/oportunidades/{opportunity_id}/asignar",
        data={
            "intent": "manual",
            "asesor": "no-es-un-uuid",
            "clave": "malformed-detail",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Asesor desconocido." in from_detail.text


async def test_the_detail_can_assign_release_and_reassign(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )

    automatic = await client.post(
        f"/crm/oportunidades/{opportunity_id}/asignar",
        data={"intent": "automatica", "clave": "automatic-assign"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se actualizó el asesor responsable." in automatic.text
    assert "Asignación manual del administrador" not in automatic.text

    released = await client.post(
        f"/crm/oportunidades/{opportunity_id}/asignar",
        data={"intent": "liberar", "clave": "release-assignment"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Sin asignar" in released.text

    unknown = await client.post(
        f"/crm/oportunidades/{opportunity_id}/asignar",
        data={"intent": "otra", "clave": "unknown-assignment"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Acción desconocida." in unknown.text


# -- Exceptions -----------------------------------------------------------


async def test_an_exception_can_be_recorded_and_cleared(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    recorded = await client.post(
        f"/crm/oportunidades/{opportunity_id}/excepcion",
        data={
            "intent": "registrar",
            "motivo": "AwaitingContact",
            "detalle": "Quedó de confirmar el sábado.",
            "clave": "record-exception",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se registró la excepción." in recorded.text
    assert "Esperando respuesta del contacto" in recorded.text
    assert "Quedó de confirmar el sábado." in recorded.text

    cleared = await client.post(
        f"/crm/oportunidades/{opportunity_id}/excepcion",
        data={"intent": "cerrar", "clave": "clear-exception"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se cerró la excepción." in cleared.text
    assert "Excepción de seguimiento" in cleared.text

    unknown = await client.post(
        f"/crm/oportunidades/{opportunity_id}/excepcion",
        data={
            "intent": "registrar",
            "motivo": "Inventado",
            "clave": "unknown-exception",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Motivo desconocido." in unknown.text


# -- The panel ------------------------------------------------------------


async def test_the_panel_reports_coverage_and_the_specific_gaps(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from realestate.domain.commercial.organization import (
            DirectoryPlan,
            OrganizationDirectory,
        )

        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(),
                default_advisor=None,
            )
        )
        await session.commit()
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="surface:coverage:qualify",
            ),
        )
        await session.commit()

    before = await client.get("/crm", auth=ADMIN)
    assert "Cobertura de seguimiento" in before.text
    assert "0%" in before.text
    assert "no cumplen la promesa de seguimiento" in before.text
    assert "Requieren asignación" in before.text
    assert "esperan asignación manual" in before.text

    async with database.session_scope() as session:
        await OrganizationDirectory(session).reconcile(commercial.DEFAULT_PLAN)
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await Assignment(session).assign(admin, opportunity_id)
        await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=commercial.now() + timedelta(days=1),
                command_key="surface:panel",
            ),
        )
        await session.commit()

    after = await client.get("/crm", auth=ADMIN)
    assert "100%" in after.text
    assert (
        "Todas las oportunidades calificadas activas tienen asesor responsable"
        in after.text
    )
    assert "No hay huecos de seguimiento." in after.text


async def test_the_panel_lists_overdue_actions_for_their_owner(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.SCHEDULE_VISIT,
                due_at=commercial.now() - timedelta(days=2),
                command_key="surface:overdue",
            ),
        )
        await session.commit()

    as_advisor = await client.get("/crm", auth=ADVISOR)
    as_other = await client.get("/crm", auth=OTHER_ADVISOR)

    assert "Agendar una visita" in as_advisor.text
    assert "Ana Demo" in as_advisor.text
    assert "hace 2 días" in as_advisor.text
    assert "No hay acciones vencidas." in as_other.text
    # An Advisor does not get the Administrator's queue block.
    assert "Cola de asignación" not in as_advisor.text


async def test_the_opportunity_list_filters_and_flags_the_promise(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        from realestate.domain.commercial.organization import (
            DirectoryPlan,
            OrganizationDirectory,
        )

        await OrganizationDirectory(session).reconcile(
            DirectoryPlan(
                administrators=(commercial.ADMIN_LOGIN,),
                advisors=(),
                default_advisor=None,
            )
        )
        await session.commit()
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity = await session.get(Opportunity, opportunity_id)
        assert opportunity is not None and opportunity.property_need_id is not None
        await commercial.confirm_minimum_criteria(
            session, admin, opportunity.property_need_id
        )
        await OpportunityManagement(session).record(
            admin,
            AdvanceStage(
                opportunity_id=opportunity_id,
                to_stage=OpportunityStage.QUALIFIED,
                command_key="surface:list:qualify",
            ),
        )
        await session.commit()

    everything = await client.get("/crm/oportunidades", auth=ADMIN)
    gaps = await client.get("/crm/oportunidades?huecos=1", auth=ADMIN)
    unassigned = await client.get("/crm/oportunidades?scope=unassigned", auth=ADMIN)
    qualified = await client.get(
        f"/crm/oportunidades?stage={OpportunityStage.QUALIFIED.value}", auth=ADMIN
    )

    assert "Hueco" in everything.text
    assert "Sin asesor" in everything.text
    assert "Ana Demo" in gaps.text
    assert "Ana Demo" in unassigned.text
    assert "Ana Demo" in qualified.text


async def test_a_closed_opportunity_appears_only_when_asked_for(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "perdida",
            "motivo": "Unknown",
            "clave": "close-for-list",
        },
        auth=ADMIN,
    )

    active = await client.get("/crm/oportunidades", auth=ADMIN)
    closed = await client.get("/crm/oportunidades?cerradas=1", auth=ADMIN)

    assert "No hay oportunidades que coincidan." in active.text
    assert "Ana Demo" in closed.text
    assert "Perdida" in closed.text


async def test_a_closed_opportunity_refuses_new_work_with_an_explanation(
    wired,
) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "perdida",
            "motivo": "Unknown",
            "clave": "close-for-detail",
        },
        auth=ADMIN,
    )

    page = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert "ya está cerrada y no cambia de etapa" in page.text
    assert "no admite nuevas acciones" in page.text
    # The exception form is gone too: there is nothing to explain any more.
    assert "Excepción de seguimiento" not in page.text


async def test_an_unknown_opportunity_or_action_reads_as_absent(wired) -> None:
    client, _database = wired

    detail = await client.get(f"/crm/oportunidades/{uuid.uuid4()}", auth=ADMIN)
    assert detail.status_code == 404
    assert "No encontramos esa oportunidad." in detail.text

    completion = await client.post(
        f"/crm/acciones/{uuid.uuid4()}/completar",
        data={"resultado": "Done"},
        auth=ADMIN,
    )
    assert completion.status_code == 404


async def test_an_unknown_action_result_is_refused(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        scheduled = await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=commercial.now(),
                command_key="surface:result",
            ),
        )
        await session.commit()

    response = await client.post(
        f"/crm/acciones/{scheduled.next_action_id}/completar",
        data={"resultado": "Inventado"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Resultado desconocido." in response.text


def test_the_navigation_lists_every_surface() -> None:
    from realestate.api.ui import NAV

    assert {link.href for link in NAV} >= set(CRM_PATHS)
    assert all(link.label and link.label[0].isupper() for link in NAV)


def test_the_stylesheet_is_shipped_inline_and_owns_the_focus_ring() -> None:
    """A separate request would leave a surface briefly unstyled."""
    from realestate.api.ui import STYLES

    assert "focus-visible" in STYLES
    assert "prefers-contrast" in STYLES
    assert Path(REPO_ROOT / "src/realestate/api/ui.py").exists()


# -- Edge cases the operator can still land on ----------------------------


async def test_a_conversation_with_no_opportunity_still_appears(wired) -> None:
    """A Contact resolved with no pursuit yet is visible, labelled as such."""
    client, database = wired
    async with database.session_scope() as session:
        _contact_id, lead = await commercial.make_contact(
            session, "5213355550000", profile_name="Sin oportunidad"
        )
        conversation = await commercial.make_conversation(session, lead)
        await commercial.make_inbound(session, conversation, text_body="Buenas")
        await session.commit()

    response = await client.get("/crm/bandeja", auth=ADMIN)

    assert "Sin oportunidad" in response.text
    assert "Sin asesor" in response.text


async def test_the_inbox_marks_restrictions_and_exceptions_in_the_list(
    wired,
) -> None:
    client, database = wired
    _contact_id, conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        from realestate.db.models import Conversation, OpportunityExceptionReason

        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        session.add(
            SuppressionRecord(
                lead_id=conversation.lead_id,
                scope="BusinessInitiated",
                reason="LegacyFollowUpOptOut",
            )
        )
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await OpportunityManagement(session).record_exception(
            admin,
            opportunity_id,
            reason=OpportunityExceptionReason.CONTACT_UNREACHABLE,
            detail="Número apagado.",
            command_key="surface:list-exception",
        )
        await session.commit()

    response = await client.get("/crm/bandeja?restringidos=1", auth=ADMIN)

    assert "No contactar" in response.text
    assert "Baja registrada antes de la bandeja actual" in response.text
    assert "Excepción registrada" in response.text
    assert "Contacto ilocalizable" in response.text


async def test_another_advisors_conversation_reads_as_absent(wired) -> None:
    client, database = wired
    _contact_id, conversation_id, _opportunity_id = await _opportunity(database)

    response = await client.get(f"/crm/bandeja/{conversation_id}", auth=OTHER_ADVISOR)

    assert response.status_code == 404
    assert "No encontramos esa conversación." in response.text


async def test_an_opportunity_without_a_need_renders_and_says_so(wired) -> None:
    client, database = wired
    async with database.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(session, "5213366660000")
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(
            session, admin, contact_id, with_need=False
        )
        await session.commit()

    response = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)

    assert response.status_code == 200
    assert "Esta oportunidad no tiene una necesidad registrada." in response.text

    refused = await client.post(
        f"/crm/oportunidades/{opportunity_id}/criterios",
        data={
            "intent": "registrar",
            "nombre": "service_area",
            "valor": "Zapopan",
            "clave": "criterion-without-need",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Esta oportunidad no tiene una necesidad." in refused.text


async def test_an_opportunity_whose_origin_row_is_gone_still_renders(wired) -> None:
    """Defensive: attribution is written once and never deleted by Product."""
    from sqlalchemy import delete

    from realestate.db.models import OpportunityOrigin

    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        await session.execute(
            delete(OpportunityOrigin).where(
                OpportunityOrigin.opportunity_id == opportunity_id
            )
        )
        await session.commit()

    response = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)

    assert response.status_code == 200
    assert "Sin origen registrado" in response.text


async def test_a_closed_opportunity_refuses_a_new_action_from_the_surface(
    wired,
) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "perdida",
            "motivo": "Unknown",
            "clave": "close-before-action",
        },
        auth=ADMIN,
    )

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones",
        data={
            "tipo": NextActionKind.CALL.value,
            "vence": (commercial.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "clave": "action-on-closed",
        },
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "no está activa" in response.text


async def test_completing_an_action_twice_differently_is_refused_in_spanish(
    wired,
) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)
    async with database.session_scope() as session:
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        scheduled = await NextActions(session).schedule(
            admin,
            ScheduleNextAction(
                opportunity_id=opportunity_id,
                kind=NextActionKind.CALL,
                due_at=commercial.now(),
                command_key="surface:twice",
            ),
        )
        await session.commit()

    await client.post(
        f"/crm/acciones/{scheduled.next_action_id}/completar",
        data={"resultado": "Done", "clave": "complete-twice"},
        auth=ADMIN,
    )
    second = await client.post(
        f"/crm/acciones/{scheduled.next_action_id}/completar",
        data={"resultado": "NoAnswer", "clave": "complete-twice"},
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "clave de operación ya se usó con datos diferentes" in second.text


async def test_assigning_somebody_who_does_not_advise_is_refused(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )
    async with database.session_scope() as session:
        members = await commercial.provision(session)
        admin_member_id = members[commercial.ADMIN_LOGIN]

    from_detail = await client.post(
        f"/crm/oportunidades/{opportunity_id}/asignar",
        data={
            "intent": "manual",
            "asesor": str(admin_member_id),
            "clave": "assign-non-advisor-detail",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "no puede ser asesor responsable" in from_detail.text

    from_queue = await client.post(
        f"/crm/asignacion/{opportunity_id}",
        data={
            "asesor": str(admin_member_id),
            "clave": "assign-non-advisor-queue",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "no puede ser asesor responsable" in from_queue.text


async def test_an_advisor_sees_no_assignment_controls(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADVISOR)

    assert response.status_code == 200
    assert "<h2>Asignación</h2>" not in response.text
    assert "Aplicar la regla automática" not in response.text
    # Their own next action is still theirs to schedule.
    assert "Agendar la siguiente acción" in response.text


async def test_a_migrated_opportunity_can_be_given_a_need_and_then_qualify(
    wired,
) -> None:
    """The legacy backfill invents no need; the operator starts one here.

    Without this control a migrated Opportunity could never be qualified, and
    the backfill would be a dead end rather than a starting point.
    """
    client, database = wired
    async with database.session_scope() as session:
        contact_id, _lead = await commercial.make_contact(
            session, "5213377770000", profile_name="Legado"
        )
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        opportunity_id = await commercial.open_opportunity(
            session, admin, contact_id, with_need=False
        )
        await Assignment(session).assign(admin, opportunity_id)
        await session.commit()

    page = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    assert "Esta oportunidad no tiene una necesidad registrada." in page.text
    assert "Registrar la necesidad" in page.text

    attached = await client.post(
        f"/crm/oportunidades/{opportunity_id}/necesidad",
        data={"clave": "attach-need"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se registró la necesidad del contacto." in attached.text
    assert "Todavía no hay criterios registrados." in attached.text

    # Doing it twice keeps the same need rather than orphaning its criteria.
    again = await client.post(
        f"/crm/oportunidades/{opportunity_id}/necesidad",
        data={"clave": "attach-need"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert again.status_code == 200
    async with database.session_scope() as session:
        from realestate.db.models import PropertyNeed

        needs = list(
            await session.scalars(
                select(PropertyNeed).where(PropertyNeed.contact_id == contact_id)
            )
        )
        assert len(needs) == 1
        admin = await commercial.actor_for(session, commercial.ADMIN_LOGIN)
        await commercial.confirm_minimum_criteria(session, admin, needs[0].id)
        await session.commit()

    qualified = await client.post(
        f"/crm/oportunidades/{opportunity_id}/etapa",
        data={
            "intent": "avanzar",
            "etapa": OpportunityStage.QUALIFIED.value,
            "accion_tipo": NextActionKind.CALL.value,
            "accion_vence": (commercial.now() + timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M"
            ),
            "clave": "qualify-migrated",
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Se registró el cambio de etapa." in qualified.text
    assert "Calificada" in qualified.text


async def test_attaching_a_need_to_an_unreachable_opportunity_is_refused(
    wired,
) -> None:
    client, _database = wired
    response = await client.post(
        f"/crm/oportunidades/{uuid.uuid4()}/necesidad",
        data={"clave": "attach-unknown"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "No encontramos esa oportunidad." in response.text


async def test_an_administrator_can_open_a_listing_acquisition(wired) -> None:
    """A property owner asking for help selling has no inbound path.

    The webhook only ever opens a Demand Opportunity, because that is what an
    inquiry is. Without this control the Listing Acquisition kind would be
    modelled and unreachable.
    """
    client, database = wired
    contact_id, _conversation_id, _opportunity_id = await _opportunity(database)

    page = await client.get(f"/crm/contactos/{contact_id}", auth=ADMIN)
    assert "Abrir una oportunidad nueva" in page.text
    assert "le ayudemos a" in page.text

    opened = await client.post(
        f"/crm/contactos/{contact_id}/oportunidades",
        data={"tipo": "ListingAcquisition", "clave": "open-listing"},
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "Se abrió la oportunidad." in opened.text
    assert "Captación" in opened.text
    async with database.session_scope() as session:
        kinds = sorted(
            row
            for row in await session.scalars(
                select(Opportunity.kind).where(Opportunity.contact_id == contact_id)
            )
        )
        assert kinds == ["Demand", "ListingAcquisition"]


async def test_an_advisor_cannot_open_an_opportunity(wired) -> None:
    client, database = wired
    contact_id, _conversation_id, _opportunity_id = await _opportunity(database)

    page = await client.get(f"/crm/contactos/{contact_id}", auth=ADVISOR)
    assert "Sólo un administrador puede abrir una oportunidad nueva." in page.text

    refused = await client.post(
        f"/crm/contactos/{contact_id}/oportunidades",
        data={"tipo": "ListingAcquisition", "clave": "advisor-open-listing"},
        auth=ADVISOR,
        follow_redirects=True,
    )
    assert "Sólo un administrador de la organización" in refused.text


async def test_opening_an_unknown_kind_or_contact_is_refused(wired) -> None:
    client, database = wired
    contact_id, _conversation_id, _opportunity_id = await _opportunity(database)

    bad_kind = await client.post(
        f"/crm/contactos/{contact_id}/oportunidades",
        data={"tipo": "Inventada", "clave": "unknown-kind"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "Tipo de oportunidad desconocido." in bad_kind.text

    bad_contact = await client.post(
        f"/crm/contactos/{uuid.uuid4()}/oportunidades",
        data={"tipo": "Demand", "clave": "unknown-contact"},
        auth=ADMIN,
        follow_redirects=True,
    )
    assert "No encontramos ese registro." in bad_contact.text


# -- Idempotency the operator can actually reach ---------------------------


async def test_every_mutating_form_carries_an_idempotency_key(wired) -> None:
    """Without it the domain's idempotency is real but unreachable."""
    client, database = wired
    # Unassigned, so the Assignment Queue has a row and therefore a form.
    contact_id, _conversation_id, opportunity_id = await _opportunity(
        database, assign=False
    )

    for path in (
        f"/crm/oportunidades/{opportunity_id}",
        f"/crm/contactos/{contact_id}",
        "/crm/asignacion",
    ):
        html = (await client.get(path, auth=ADMIN)).text
        # Either quote style: some forms are built inside f-strings that
        # already use double quotes, and HTML permits both.
        forms = re.findall(
            r"<form\b[^>]*method=['\"]post['\"][^>]*>.*?</form>", html, re.DOTALL
        )
        assert forms, path
        for form in forms:
            assert 'name="clave"' in form, (path, form[:160])


async def test_double_submitting_a_form_does_not_open_two_opportunities(
    wired,
) -> None:
    client, database = wired
    contact_id, _conversation_id, _opportunity_id = await _opportunity(database)

    page = await client.get(f"/crm/contactos/{contact_id}", auth=ADMIN)
    key = re.search(r'name="clave" value="([0-9a-f]+)"', page.text)
    assert key is not None
    payload = {"tipo": "ListingAcquisition", "clave": key.group(1)}

    first = await client.post(
        f"/crm/contactos/{contact_id}/oportunidades",
        data=payload,
        auth=ADMIN,
        follow_redirects=True,
    )
    second = await client.post(
        f"/crm/contactos/{contact_id}/oportunidades",
        data=payload,
        auth=ADMIN,
        follow_redirects=True,
    )

    assert "Se abrió la oportunidad." in first.text
    assert second.status_code == 200
    async with database.session_scope() as session:
        kinds = sorted(
            row
            for row in await session.scalars(
                select(Opportunity.kind).where(Opportunity.contact_id == contact_id)
            )
        )
        # One Demand from the fixture plus one Captación, not two.
        assert kinds == ["Demand", "ListingAcquisition"]


async def test_double_submitting_an_action_owes_one_obligation(wired) -> None:
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    page = await client.get(f"/crm/oportunidades/{opportunity_id}", auth=ADMIN)
    keys = re.findall(r'name="clave" value="([0-9a-f]+)"', page.text)
    assert keys
    due = (commercial.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    payload = {
        "tipo": NextActionKind.CALL.value,
        "vence": due,
        "clave": keys[0],
    }

    await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones", data=payload, auth=ADMIN
    )
    await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones", data=payload, auth=ADMIN
    )

    async with database.session_scope() as session:
        from realestate.db.models import NextAction

        total = await session.scalar(
            select(func.count(NextAction.id)).where(
                NextAction.opportunity_id == opportunity_id
            )
        )
        # One action, not one immediately superseded by its twin.
        assert total == 1


async def test_a_submission_without_a_key_is_refused(wired) -> None:
    """A mutation cannot pretend to be idempotent without a retry identity."""
    client, database = wired
    _contact_id, _conversation_id, opportunity_id = await _opportunity(database)

    response = await client.post(
        f"/crm/oportunidades/{opportunity_id}/acciones",
        data={
            "tipo": NextActionKind.CALL.value,
            "vence": (commercial.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        },
        auth=ADMIN,
        follow_redirects=True,
    )
    assert response.status_code == 400
    assert "Falta la clave de operación" in response.text


# -- The property surfaces are administrator-only now ---------------------


async def test_the_property_surfaces_require_an_administrator(wired) -> None:
    """CONTEXT.md reserves Property management to the Administrator.

    Before Stage 2 these routes accepted any credential in the operational
    credential map with no role lookup at all.
    """
    client, _database = wired

    for path in ("/admin/properties", "/admin/properties/new", "/upload"):
        as_admin = await client.get(path, auth=ADMIN)
        as_advisor = await client.get(path, auth=ADVISOR)
        as_stranger = await client.get(path, auth=STRANGER)

        assert as_admin.status_code == 200, path
        assert as_advisor.status_code == 403, path
        assert "administrar el inventario" in as_advisor.json()["detail"]
        assert as_stranger.status_code == 403, path
        assert "no pertenece a ninguna organización" in as_stranger.json()["detail"]

    unauthenticated = await client.get("/admin/properties")
    assert unauthenticated.status_code == 401


async def test_the_property_surface_links_back_to_the_crm(wired) -> None:
    """An operator could walk into Properties and not walk back."""
    client, _database = wired
    html = (await client.get("/admin/properties", auth=ADMIN)).text

    assert 'href="/crm"' in html
    # And it now carries the same accessibility guarantees as the CRM shell.
    assert '<html lang="es-MX">' in html
    assert "Ir al contenido principal" in html
    assert '<main id="contenido">' in html
    assert "focus-visible" in html

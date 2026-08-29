"""The operational CRM: Inbox, Opportunities, Contacts and the Assignment Queue.

Server-rendered, Mexican Spanish, no JavaScript required. Every screen reads
through :class:`~realestate.domain.commercial.views.CommercialInbox` and every
mutation goes through one of the commercial modules, so this file holds
presentation and nothing else — no transaction, no invariant, no idempotency
rule and no authorization decision beyond resolving who is asking.

Authentication is the existing HTTP Basic credential. Authorization is the
Organization member row it resolves to: a credential with no member is refused
with an explanation instead of being treated as an administrator.

What these surfaces deliberately *show* rather than hide: an Opportunity nobody
owns, a Next Action already overdue, and every outbound message Product refused
to send along with the reason. None of them can send anything — the Stage 1
eligibility gate has no entry point here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from realestate.api.operator import (
    redirect_back,
    command_field,
    command_key,
    command_payload,
    refusal,
    require_actor,
    shell,
    tag,
)
from realestate.api.ui import (
    checkbox,
    datetime_input_value,
    empty,
    errors_box,
    escape,
    flash,
    local,
    options,
    parse_datetime_input,
    relative,
    table,
)
from sqlalchemy import or_, select

from realestate.db.models import (
    ACTIVE_STAGES,
    Appointment,
    AppointmentStatus,
    ChannelIdentityTrust,
    InboxGroup,
    InboxGroupStatus,
    NextAction,
    NextActionKind,
    NextActionOutcome,
    Opportunity,
    OpportunityAssignment,
    OpportunityException,
    OpportunityExceptionReason,
    OpportunityKind,
    OpportunityOrigin,
    OpportunityOriginSource,
    OpportunityStage,
    OpportunityStageTransition,
    OrganizationMember,
    PropertyNeedCriterion,
    QUALIFIED_OR_BEYOND,
)
from realestate.api.operations import handling_panel, reply_form
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.commercial.handling import ConversationHandling
from realestate.domain.commercial.handoff import HumanHandoff
from realestate.domain.commercial.assignment import (
    BASIS_LABELS,
    QUEUE_REASON_LABELS,
    Assignment,
)
from realestate.domain.commercial.identity import CommercialIdentity
from realestate.domain.commercial.idempotency import CommercialCommands
from realestate.domain.commercial.needs import (
    CRITERION_LABELS,
    INTENT,
    INTENT_LABELS,
    NEED_STATUS_LABELS,
    REQUIRED_CRITERIA,
    SOURCE_LABELS,
    CriterionStatement,
    NeedSnapshot,
    PropertyNeeds,
    criterion_label,
)
from realestate.domain.commercial.next_actions import (
    KIND_LABELS as ACTION_KIND_LABELS,
    OUTCOME_LABELS,
    STATUS_LABELS as ACTION_STATUS_LABELS,
    CompleteNextAction,
    NextActions,
    ScheduleNextAction,
)
from realestate.domain.commercial.opportunities import (
    ADVANCEABLE_STAGES,
    ALLOWED_TRANSITIONS,
    DORMANT_REASON_LABELS,
    OpenOpportunity,
    OriginFacts,
    EXCEPTION_REASON_LABELS,
    KIND_LABELS,
    LOST_REASON_LABELS,
    STAGE_LABELS,
    WON_EVIDENCE_LABELS,
    AdvanceStage,
    DormantReason,
    LostReason,
    OpportunityManagement,
    QualificationAction,
    RecordDormant,
    RecordLost,
    RecordWon,
    WonEvidence,
)
from realestate.domain.commercial.organization import (
    OrganizationDirectory,
)
from realestate.domain.outbound import DenialReason, Purpose
from realestate.domain.commercial.views import (
    CommercialInbox,
    InboxFilters,
    RestrictionView,
)

router = APIRouter(prefix="/crm", tags=["crm"])

# Spanish for the Stage 1 outbound vocabulary. It lives here rather than beside
# those enums because the eligibility gate has no operator surface of its own —
# this is the only place its decisions are read by a person. Keyed off the enum
# members, so renaming one is a failure here rather than an English identifier
# appearing on somebody's screen.
DENIAL_REASON_LABELS = {
    DenialReason.UNKNOWN_RECIPIENT.value: "No se pudo identificar al destinatario",
    DenialReason.MISSING_REACTIVE_TRIGGER.value: (
        "Faltó el mensaje que se estaba respondiendo"
    ),
    DenialReason.UNTRUSTED_TRIGGER.value: (
        "El mensaje citado no pertenece a esta conversación"
    ),
    DenialReason.SUPPRESSED.value: "El contacto pidió no ser contactado",
    DenialReason.CONTACT_REPLIED.value: ("El contacto ya respondió y espera respuesta"),
    DenialReason.MARKETING_CONSENT_MISSING.value: (
        "No hay consentimiento de difusión registrado"
    ),
    DenialReason.SERVICE_WINDOW_CLOSED.value: (
        "Pasaron más de 24 horas y no hay plantilla aprobada"
    ),
    DenialReason.TEMPLATE_NOT_APPROVED.value: (
        "La plantilla no está aprobada por Meta"
    ),
    DenialReason.TEMPLATE_METADATA_INCOMPLETE.value: (
        "Los datos de la plantilla están incompletos"
    ),
    DenialReason.TEMPLATE_CATEGORY_MISMATCH.value: (
        "La categoría de la plantilla no corresponde"
    ),
    DenialReason.FOLLOW_UP_POLICY_INACTIVE.value: (
        "El seguimiento automático está desactivado"
    ),
    DenialReason.ELIGIBILITY_EVIDENCE_MISSING.value: (
        "Falta la evidencia de elegibilidad"
    ),
    DenialReason.ENGAGEMENT_NOT_ACTIVE.value: (
        "La reactivación o campaña se detuvo antes de entregar"
    ),
}

PURPOSE_LABELS = {
    Purpose.AGENT_REPLY.value: "Respuesta de Maia",
    Purpose.HUMAN_REPLY.value: "Respuesta de una persona",
    Purpose.APPOINTMENT_RESCHEDULED.value: "Cita reagendada",
    Purpose.APPOINTMENT_REMINDER.value: "Recordatorio de cita",
    Purpose.PROCESSING_FAILURE.value: "Aviso de falla",
    Purpose.APPOINTMENT_CONFIRMATION.value: "Confirmación de cita",
    Purpose.APPOINTMENT_RESOLUTION.value: "Resolución de cita",
    Purpose.APPOINTMENT_CANCELLATION.value: "Cancelación de cita",
    Purpose.APPOINTMENT_NEEDS_REVIEW.value: "Cita en revisión",
    Purpose.LEAD_FOLLOW_UP.value: "Seguimiento",
    Purpose.REACTIVATION.value: "Reactivación revisada",
    Purpose.DEVELOPMENT_CAMPAIGN.value: "Campaña de desarrollo",
}

# Suppression reasons are free-form strings written by the paths that create
# them (an inbound opt-out, revision 0011's legacy conversion), not an enum, so
# these are matched with a fallback rather than keyed off members.
SUPPRESSION_REASON_LABELS = {
    "ExplicitOptOut": "El contacto pidió explícitamente no recibir mensajes",
    "LegacyFollowUpOptOut": "Baja registrada antes de la bandeja actual",
}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _stage_tag(stage: str | None) -> str:
    if stage is None:
        return tag("Sin oportunidad", "warn")
    kind = ""
    if stage == OpportunityStage.WON.value:
        kind = "ok"
    elif stage in (OpportunityStage.LOST.value, OpportunityStage.DORMANT.value):
        kind = "warn"
    return tag(STAGE_LABELS[stage], kind)


def _action_cell(
    action: NextAction | None, overdue: bool, exception_reason: str | None
) -> str:
    if action is None:
        if exception_reason is not None:
            return (
                tag("Excepción registrada", "warn")
                + '<br><span class="muted">'
                + escape(
                    EXCEPTION_REASON_LABELS.get(exception_reason, exception_reason)
                )
                + "</span>"
            )
        return tag("Sin siguiente acción", "bad")
    label = ACTION_KIND_LABELS.get(action.kind, action.kind)
    due = local(action.due_at)
    marker = tag("Vencida", "bad") if overdue else tag("A tiempo", "ok")
    return f"{escape(label)}<br><span class='muted'>{escape(due)}</span><br>{marker}"


def _restriction_note(restriction: RestrictionView) -> str:
    parts: list[str] = []
    if restriction.suppressed:
        reason = SUPPRESSION_REASON_LABELS.get(
            restriction.suppression_reason or "",
            "Restricción de comunicación activa",
        )
        parts.append(
            tag("No contactar", "bad")
            + f" <span class='muted'>{escape(reason)}</span>"
        )
    if restriction.denied_count:
        parts.append(
            tag(f"{restriction.denied_count} envío(s) no permitido(s)", "warn")
        )
    return "<br>".join(parts)


# ---------------------------------------------------------------- Panel ------


@dataclass(frozen=True)
class _PriorityItem:
    label: str
    kind: str
    reason: str
    detail: str
    owner: str
    href: str
    action: str


def _priority_rows(items: list[_PriorityItem]) -> str:
    if not items:
        return empty(
            "No hay asuntos que requieran intervención.",
            "Product no encontró conversaciones en espera, compromisos vencidos "
            "ni revisiones dentro de tu alcance.",
        )
    return (
        '<ol class="priority-list">'
        + "".join(
            '<li class="priority-row">'
            f'<span class="priority-label priority-{escape(item.kind)}">'
            f"{escape(item.label)}</span>"
            f'<div><div class="priority-reason">{escape(item.reason)}</div>'
            f'<div class="priority-meta">{escape(item.detail)}</div></div>'
            f'<div class="priority-owner">{escape(item.owner)}</div>'
            f'<a class="button priority-action" href="{escape(item.href)}">'
            f"{escape(item.action)}</a></li>"
            for item in items
        )
        + "</ol>"
    )


@router.get("", response_class=HTMLResponse)
async def panel(
    request: Request, actor: Actor = Depends(require_actor)
) -> HTMLResponse:
    """Follow-up Coverage first, then the specific work that is missing."""
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        views = CommercialInbox(session)
        coverage = await views.coverage(actor, now=moment)
        inbox_rows = await views.query(
            actor, InboxFilters(needs_reply=True, limit=20), now=moment
        )
        due_rows = await NextActions(session).due_with_contacts(
            actor, now=moment, limit=40
        )
        queue = await Assignment(session).queue(actor) if actor.is_administrator else []
        members = {
            member.id: member.display_name
            for member in await OrganizationDirectory(session).members(
                actor.organization_id
            )
        }
        appointment_query = (
            select(Appointment, OrganizationMember.display_name)
            .outerjoin(
                OrganizationMember,
                OrganizationMember.id == Appointment.advisor_id,
            )
            .where(Appointment.organization_id == actor.organization_id)
            .where(Appointment.status == AppointmentStatus.NEEDS_REVIEW.value)
            .order_by(Appointment.starts_at, Appointment.id)
            .limit(20)
        )
        if not actor.sees_whole_operation:
            appointment_query = appointment_query.where(
                or_(
                    Appointment.advisor_id == actor.member_id,
                    Appointment.conducting_advisor_id == actor.member_id,
                )
            )
        appointment_rows = list(await session.execute(appointment_query))

    overdue_rows = [item for item in due_rows if item.action.due_at <= moment]
    upcoming_rows = [
        item
        for item in due_rows
        if moment < item.action.due_at <= moment + timedelta(days=7)
    ]

    priority: list[_PriorityItem] = []
    priority.extend(
        _PriorityItem(
            label="Ahora",
            kind="now",
            reason=(
                f"{entry.contact_name or 'Un contacto'} espera respuesta"
            ),
            detail=(
                f"Bandeja · {relative(entry.last_inbound_at, now=moment)} · "
                f"{STAGE_LABELS.get(entry.stage or '', 'Sin etapa')}"
            ),
            owner=entry.advisor_name or "Sin asesor",
            href=f"/crm/bandeja/{entry.conversation_id}",
            action="Responder",
        )
        for entry in inbox_rows[:8]
    )
    priority.extend(
        _PriorityItem(
            label="Hoy",
            kind="today",
            reason=(
                f"{ACTION_KIND_LABELS.get(item.action.kind, item.action.kind)} · "
                f"{item.contact_name or 'Contacto sin nombre'}"
            ),
            detail=(
                f"Venció {local(item.action.due_at)} · "
                f"{relative(item.action.due_at, now=moment)}"
            ),
            owner=members.get(item.action.responsible_member_id, "Sin responsable"),
            href=f"/crm/oportunidades/{item.action.opportunity_id}",
            action="Abrir acción",
        )
        for item in overdue_rows[:8]
    )
    if actor.is_administrator:
        priority.extend(
            _PriorityItem(
                label="Revisión",
                kind="review",
                reason=(
                    f"{item.contact_name or 'Una oportunidad'} no tiene asesor responsable"
                ),
                detail=f"Cola de asignación · {relative(item.since, now=moment)}",
                owner="Sin asesor",
                href="/crm/asignacion",
                action="Asignar",
            )
            for item in queue[:8]
        )
    priority.extend(
        _PriorityItem(
            label="Revisión",
            kind="review",
            reason=f"La visita {visit.reference} requiere revisión",
            detail=f"Agenda · {local(visit.starts_at)}",
            owner=advisor_name or "Sin asesor",
            href="/crm/agenda",
            action="Revisar visita",
        )
        for visit, advisor_name in appointment_rows[:8]
    )
    priority.extend(
        _PriorityItem(
            label="Próximamente",
            kind="soon",
            reason=(
                f"{ACTION_KIND_LABELS.get(item.action.kind, item.action.kind)} · "
                f"{item.contact_name or 'Contacto sin nombre'}"
            ),
            detail=f"Vence {local(item.action.due_at)}",
            owner=members.get(item.action.responsible_member_id, "Sin responsable"),
            href=f"/crm/oportunidades/{item.action.opportunity_id}",
            action="Preparar",
        )
        for item in upcoming_rows[:8]
    )

    metric_scope = (
        f"Toda {actor.organization_name}" if actor.is_administrator else "Mi trabajo"
    )
    metric_freshness = local(moment)
    stats = "".join(
        f'<div class="stat"><div class="muted">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div>'
        f'<div class="muted">{escape(note)} · {escape(metric_scope)} · '
        f'Estado actual · Consultado {escape(metric_freshness)}</div>'
        f'<a href="{escape(href)}">Ver trabajo</a></div>'
        for label, value, note, href in (
            (
                "Cobertura de seguimiento",
                f"{coverage.percentage}%",
                f"{coverage.covered} de {coverage.active} oportunidades calificadas activas",
                "/crm/oportunidades?huecos=1",
            ),
            (
                "Oportunidades calificadas",
                str(coverage.qualified_active),
                f"{coverage.qualified_covered} con asesor y acción vigente",
                "/crm/oportunidades?stage=Qualified",
            ),
            (
                "Sin asesor responsable",
                str(coverage.without_advisor),
                "Requieren asignación",
                "/crm/asignacion" if actor.is_administrator else "/crm/oportunidades",
            ),
            (
                "Con acción vencida",
                str(coverage.overdue),
                "Requieren atención hoy",
                "/crm/oportunidades?huecos=1",
            ),
        )
    )

    if coverage.complete and coverage.active:
        banner = flash(
            "Todas las oportunidades calificadas activas tienen asesor responsable y una "
            "siguiente acción vigente o una excepción registrada.",
            "ok",
        )
    elif coverage.active == 0:
        banner = flash("Todavía no hay oportunidades calificadas activas.", "warn")
    else:
        banner = flash(
            f"{coverage.active - coverage.covered} oportunidad(es) calificada(s) activa(s) "
            "no cumplen la promesa de seguimiento.",
            "warn",
        )

    gap_rows = "".join(
        f"<tr><td><a href='/crm/oportunidades/{row.opportunity.id}'>"
        f"{escape(row.contact_name or row.channel_identity or 'Contacto sin nombre')}</a>"
        f"<br><span class='muted'>{escape(KIND_LABELS[row.opportunity.kind])}</span></td>"
        f"<td>{_stage_tag(row.opportunity.stage)}</td>"
        f"<td>{escape(row.advisor_name or '—')}</td>"
        f"<td>{_action_cell(row.next_action, row.overdue, row.exception_reason)}</td></tr>"
        for row in coverage.gaps[:15]
    )
    gaps_table = table(
        "Oportunidades calificadas activas que no cumplen la promesa",
        ("Contacto", "Etapa", "Asesor", "Siguiente acción"),
        gap_rows,
        empty_message="No hay huecos de seguimiento.",
        empty_hint=(
            "Cada oportunidad calificada activa tiene asesor y una acción vigente o una excepción."
        ),
    )

    overdue_list = "".join(
        f"<li class='card'><strong>"
        f"{escape(ACTION_KIND_LABELS.get(item.action.kind, item.action.kind))}</strong>"
        f" · {escape(item.contact_name or 'Contacto sin nombre')}<br>"
        f"<span class='muted'>Vencía {escape(local(item.action.due_at))} "
        f"({escape(relative(item.action.due_at, now=moment))})</span><br>"
        f"<a href='/crm/oportunidades/{item.action.opportunity_id}'>Abrir oportunidad</a></li>"
        for item in overdue_rows
    )
    overdue_block = (
        f"<h2>Acciones vencidas</h2><ul class='plain'>{overdue_list}</ul>"
        if overdue_list
        else "<h2>Acciones vencidas</h2>" + empty("No hay acciones vencidas.")
    )

    queue_block = ""
    if actor.is_administrator:
        queue_block = "<h2>Cola de asignación</h2>" + (
            f"<p>{len(queue)} oportunidad(es) esperan asignación manual. "
            f"<a href='/crm/asignacion'>Ir a la cola</a></p>"
            if queue
            else empty("La cola de asignación está vacía.")
        )

    issue_count = (
        len(inbox_rows) + len(overdue_rows) + len(queue) + len(appointment_rows)
    )
    if issue_count:
        summary = (
            '<div class="operational-summary"><strong>'
            f"{issue_count} asunto{'s' if issue_count != 1 else ''} requieren atención"
            "</strong>"
            f"{len(inbox_rows)} persona(s) esperan · "
            f"{len(overdue_rows)} acción(es) vencida(s) · "
            f"{len(queue)} oportunidad(es) sin asesor · "
            f"{len(appointment_rows)} visita(s) requieren revisión</div>"
        )
    else:
        summary = (
            '<div class="ok" role="status"><strong>La operación está al día.</strong> '
            "No hay asuntos que requieran intervención dentro de tu alcance.</div>"
        )
    priority_block = (
        '<section class="work-section" aria-labelledby="prioridad">'
        '<div class="work-section-header"><div><h2 id="prioridad">'
        + ("Prioridad de operación" if actor.is_administrator else "Lo siguiente")
        + '</h2><p>Ordenada por urgencia, vencimiento y tiempo de espera.</p></div></div>'
        + _priority_rows(priority)
        + "</section>"
    )
    content = (
        f"{summary}{priority_block}"
        '<section class="work-section" aria-labelledby="salud-operativa">'
        '<div class="work-section-header"><div><h2 id="salud-operativa">'
        "Salud operativa</h2><p>Alcance actual · definición de cobertura de seguimiento.</p>"
        f"</div></div>{banner}<div class='stats'>{stats}</div></section>"
        f"<h2>Huecos de seguimiento</h2>{gaps_table}"
        f"{overdue_block}{queue_block}"
    )
    title = (
        f"Operación de {actor.organization_name}"
        if actor.is_administrator
        else "Mi trabajo"
    )
    return shell(actor, title, content, active="/crm")


# --------------------------------------------------------------- Bandeja -----


@router.get("/bandeja", response_class=HTMLResponse)
async def inbox(
    request: Request, actor: Actor = Depends(require_actor)
) -> HTMLResponse:
    """Conversations the operator may work, most recent first."""
    filters = InboxFilters.parse(dict(request.query_params))
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        entries = await CommercialInbox(session).query(actor, filters, now=moment)

    rows = "".join(
        f"<tr><td><a href='/crm/bandeja/{entry.conversation_id}'>"
        f"{escape(entry.contact_name or 'Contacto sin nombre')}</a><br>"
        f"<span class='muted'>{escape(entry.channel_identity)}</span></td>"
        f"<td>{escape(entry.preview)}"
        + ("<br>" + tag("Contenido expirado", "warn") if entry.preview_expired else "")
        + "</td>"
        f"<td>{escape(local(entry.last_inbound_at))}<br>"
        f"<span class='muted'>{escape(relative(entry.last_inbound_at, now=moment))}</span>"
        + ("<br>" + tag("Espera respuesta", "warn") if entry.awaiting_reply else "")
        + "</td>"
        f"<td>{_stage_tag(entry.stage)}<br>"
        f"<span class='muted'>{escape(entry.advisor_name or 'Sin asesor')}</span></td>"
        f"<td>{_action_cell(entry.next_action, entry.next_action_overdue, entry.exception_reason)}</td>"
        f"<td>{_restriction_note(entry.restriction) or '—'}</td></tr>"
        for entry in entries
    )
    listing = table(
        f"{len(entries)} conversación(es)",
        (
            "Contacto",
            "Último mensaje",
            "Recibido",
            "Oportunidad",
            "Siguiente acción",
            "Restricciones",
        ),
        rows,
        empty_message="No hay conversaciones que coincidan.",
        empty_hint="Quita los filtros o espera el primer mensaje de WhatsApp.",
    )
    content = _inbox_filter_form(filters, actor) + listing
    return shell(actor, "Bandeja de conversaciones", content, active="/crm/bandeja")


#: What each scope means to an operator. One vocabulary, keyed off the tuple
#: that defines the scopes, so a new one cannot appear on one surface only.
SCOPE_LABELS = {
    "all": "Todas las que puedo ver",
    "mine": "Mías",
    "unassigned": "Sin asesor",
}


def _inbox_filter_form(filters: InboxFilters, actor: Actor) -> str:
    checks = "".join(
        checkbox(name, label, value)
        for name, label, value in (
            ("sin_respuesta", "Sólo las que esperan respuesta", filters.needs_reply),
            ("vencidas", "Sólo con acción vencida", filters.overdue),
            ("restringidos", "Sólo con restricciones", filters.restricted),
        )
    )
    return f"""<form class="card" method="get" action="/crm/bandeja">
<div class="filters">
<div class="field"><label for="f-q">Buscar por nombre o número
<input id="f-q" name="q" value="{escape(filters.query or "")}"
 placeholder="Ana, 5213312..."></label></div>
<div class="field"><label for="f-scope">Alcance
<select id="f-scope" name="scope">{options(InboxFilters.SCOPES if actor.is_administrator else ("all", "mine"), filters.scope, SCOPE_LABELS)}</select></label></div>
<div class="field"><label for="f-stage">Etapa
<select id="f-stage" name="stage"><option value="">Todas</option>
{options(tuple(STAGE_LABELS), filters.stage or "", STAGE_LABELS)}</select></label></div>
<div class="field"><fieldset><legend>Filtros</legend>{checks}</fieldset></div>
</div>
<div class="actions"><button type="submit">Aplicar filtros</button>
<a class="button quiet" href="/crm/bandeja">Limpiar</a></div>
</form>"""


#: What the handling controls confirm, in the operator's words.
_CONVERSATION_FLASH = {
    "atendiendo": "Ahora tú atiendes esta conversación. Maia dejó de responder.",
    "liberada": "Liberaste la conversación.",
    "enviado": "Se envió el mensaje por el canal oficial.",
    "solicitud": (
        "Confirmaste que ya atiendes la solicitud. Maia sigue pausada."
    ),
}


@router.get("/bandeja/{conversation_id}", response_class=HTMLResponse)
async def conversation(
    request: Request,
    conversation_id: uuid.UUID,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """One conversation, its restrictions, and what Product refused to send."""
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        views = CommercialInbox(session)
        try:
            view = await views.conversation(actor, conversation_id)
        except CommercialError as exc:
            return refusal(actor, exc, active="/crm/bandeja")
        queue = await views.query(actor, InboxFilters(limit=8), now=moment)
        handling = await ConversationHandling(session).snapshot(conversation_id)
        pending_handoff = await HumanHandoff(session).open_for_conversation(
            conversation_id
        )
        mid_turn = await session.scalar(
            select(InboxGroup.id)
            .where(InboxGroup.conversation_id == conversation_id)
            .where(InboxGroup.status == InboxGroupStatus.PROCESSING.value)
            .limit(1)
        )

    messages = "".join(
        f"<li class='msg{' out' if message.direction == 'Maia' else ''}'>"
        f"<div class='who'>{escape(message.direction)} · "
        f"{escape(local(message.at))}</div>"
        f"<div{' class="expired"' if message.expired else ''}>"
        f"{escape(message.body)}</div>"
        + (
            f"<div class='muted'>{escape(PURPOSE_LABELS.get(message.kind or '', message.kind or ''))}</div>"
            if message.kind
            else ""
        )
        + "</li>"
        for message in view.messages
    )
    thread = (
        f"<ul class='thread'>{messages}</ul>"
        if messages
        else empty("Esta conversación no tiene mensajes disponibles.")
    )

    restriction = view.restriction
    restriction_block = ""
    if restriction.suppressed:
        restriction_block += (
            '<div class="error" role="alert"><strong>No se puede enviar nada a '
            "este contacto por iniciativa nuestra.</strong><p>"
            + escape(
                SUPPRESSION_REASON_LABELS.get(
                    restriction.suppression_reason or "",
                    "Hay una restricción de comunicación activa.",
                )
            )
            + f" Registrada el {escape(local(restriction.suppressed_at))}.</p>"
            "<p>Sí es posible responder cuando el contacto escribe.</p></div>"
        )
    if restriction.denials:
        denial_rows = "".join(
            f"<tr><td>{escape(local(denial.at))}</td>"
            f"<td>{escape(PURPOSE_LABELS.get(denial.purpose, denial.purpose))}</td>"
            f"<td>{escape(DENIAL_REASON_LABELS.get(denial.reason, denial.reason))}</td></tr>"
            for denial in restriction.denials
        )
        restriction_block += (
            "<h2>Mensajes que no se enviaron</h2>"
            '<p class="hint">Product registra cada decisión de envío. Estas no se '
            "autorizaron; nadie puede enviarlas desde esta pantalla.</p>"
            + table(
                f"Últimas {len(restriction.denials)} decisiones denegadas",
                ("Fecha", "Tipo", "Motivo"),
                denial_rows,
            )
        )

    opportunity_block = empty(
        "Esta conversación no tiene una oportunidad abierta.",
        "Se crea automáticamente con el primer mensaje del contacto.",
    )
    if view.opportunity is not None:
        opportunity_block = f"""<dl class="pairs">
<dt>Etapa</dt><dd>{_stage_tag(view.opportunity.stage)}</dd>
<dt>Asesor responsable</dt><dd>{escape(view.advisor_name or "Sin asignar")}</dd>
<dt>Tipo</dt><dd>{escape(KIND_LABELS[view.opportunity.kind])}</dd>
<dt>Última actividad</dt><dd>{escape(local(view.opportunity.last_activity_at))}
 <span class="muted">({escape(relative(view.opportunity.last_activity_at, now=moment))})</span></dd>
</dl><div class="actions">
<a class="button" href="/crm/oportunidades/{view.opportunity.id}">Abrir oportunidad</a>
<a class="button quiet" href="/crm/contactos/{view.contact.id}">Ver contacto</a></div>"""

    queue_items = "".join(
        '<li class="queue-item'
        + (" selected" if entry.conversation_id == conversation_id else "")
        + '"><a href="/crm/bandeja/'
        + str(entry.conversation_id)
        + '"><span class="priority-label priority-'
        + (
            "now"
            if entry.awaiting_reply
            else "today"
            if entry.next_action_overdue
            else "review"
            if entry.restriction.suppressed or entry.restriction.denied_count
            else "soon"
        )
        + '">'
        + (
            "Ahora"
            if entry.awaiting_reply
            else "Hoy"
            if entry.next_action_overdue
            else "Revisión"
            if entry.restriction.suppressed or entry.restriction.denied_count
            else "Al día"
        )
        + "</span><strong>"
        + escape(entry.contact_name or "Contacto sin nombre")
        + '</strong><div class="queue-preview">'
        + escape(entry.preview)
        + '</div><span class="muted">'
        + escape(relative(entry.last_inbound_at, now=moment))
        + " · "
        + escape(entry.advisor_name or "Sin asesor")
        + "</span></a></li>"
        for entry in queue
    )
    queue_panel = (
        '<aside class="workspace-panel queue-panel" aria-label="Prioridad de conversaciones">'
        '<h2>Prioridad</h2><p class="hint">Conversaciones dentro de tu alcance.</p>'
        f'<ul class="queue-list">{queue_items}</ul>'
        '<p><a href="/crm/bandeja">Ver toda la Bandeja</a></p></aside>'
    )
    conversation_panel = (
        '<section class="workspace-panel conversation-panel" aria-label="Conversación seleccionada">'
        f"<h2>{escape(view.contact.display_name or 'Contacto sin nombre')}</h2>"
        f'<p class="hint">WhatsApp · {escape(view.channel_identity)}</p>'
        + handling_panel(
            handling,
            pending_handoff,
            actor,
            conversation_id=conversation_id,
            maia_mid_turn=mid_turn is not None,
        )
        + "<h2>Conversación</h2>"
        + thread
        + reply_form(handling, actor, conversation_id=conversation_id)
        + "</section>"
    )
    context_panel = (
        '<aside class="workspace-panel context-panel sticky-rail" '
        'aria-label="Contexto y autoridad">'
        + f"{restriction_block}"
        + f"<div><h2>Contacto</h2><dl class='pairs'>"
        f"<dt>Nombre</dt><dd>{escape(view.contact.display_name or 'Sin nombre registrado')}</dd>"
        f"<dt>WhatsApp</dt><dd>{escape(view.channel_identity)}</dd></dl></div>"
        f"<div><h2>Oportunidad</h2>{opportunity_block}</div></aside>"
    )
    content = (
        flash(_CONVERSATION_FLASH.get(guardado))
        + (f'<div class="error" role="alert">{escape(error)}</div>' if error else "")
        + '<div class="workspace conversation-workspace">'
        + queue_panel
        + conversation_panel
        + context_panel
        + "</div>"
    )
    return shell(
        actor,
        "Bandeja",
        content,
        active="/crm/bandeja",
    )


# --------------------------------------------------------- Oportunidades -----


@router.get("/oportunidades", response_class=HTMLResponse)
async def opportunities(
    request: Request,
    stage: str = "",
    scope: str = "all",
    huecos: str = "",
    cerradas: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """The pipeline, with the coverage gaps callable out."""
    moment = _now()
    chosen = stage if stage in STAGE_LABELS else None
    async with request.app.state.database.session_scope() as session:
        rows = await CommercialInbox(session).opportunities(
            actor,
            stage=chosen,
            scope=scope if scope in InboxFilters.SCOPES else "all",
            only_gaps=huecos == "1",
            include_closed=cerradas == "1",
            now=moment,
        )

    body = "".join(
        f"<tr><td><a href='/crm/oportunidades/{row.opportunity.id}'>"
        f"{escape(row.contact_name or row.channel_identity or 'Contacto sin nombre')}</a>"
        f"<br><span class='muted'>{escape(row.channel_identity or '')}</span></td>"
        f"<td>{escape(KIND_LABELS[row.opportunity.kind])}</td>"
        f"<td>{_stage_tag(row.opportunity.stage)}</td>"
        f"<td>{escape(row.advisor_name or '—')}"
        + (
            ""
            if row.opportunity.responsible_advisor_id
            else "<br>" + tag("Sin asesor", "bad")
        )
        + "</td>"
        f"<td>{_action_cell(row.next_action, row.overdue, row.exception_reason)}</td>"
        f"<td>{escape(local(row.opportunity.last_activity_at))}</td>"
        f"<td>{tag('Cumple', 'ok') if row.covered else tag('Hueco', 'bad')}</td></tr>"
        for row in rows
    )
    listing = table(
        f"{len(rows)} oportunidad(es)",
        (
            "Contacto",
            "Tipo",
            "Etapa",
            "Asesor",
            "Siguiente acción",
            "Última actividad",
            "Promesa",
        ),
        body,
        empty_message="No hay oportunidades que coincidan.",
        empty_hint="Cambia los filtros o revisa la bandeja de conversaciones.",
    )
    filter_form = f"""<form class="card" method="get" action="/crm/oportunidades">
<div class="filters">
<div class="field"><label for="o-stage">Etapa
<select id="o-stage" name="stage"><option value="">Todas las activas</option>
{options(tuple(STAGE_LABELS), chosen or "", STAGE_LABELS)}</select></label></div>
<div class="field"><label for="o-scope">Alcance
<select id="o-scope" name="scope">{options(InboxFilters.SCOPES if actor.is_administrator else ("all", "mine"), scope, SCOPE_LABELS)}</select></label></div>
<div class="field"><fieldset><legend>Filtros</legend>
{checkbox("huecos", "Sólo huecos de seguimiento", huecos == "1")}
{checkbox("cerradas", "Incluir cerradas y en pausa", cerradas == "1")}
</fieldset></div>
</div>
<div class="actions"><button type="submit">Aplicar filtros</button>
<a class="button quiet" href="/crm/oportunidades">Limpiar</a></div></form>"""
    return shell(
        actor, "Oportunidades", filter_form + listing, active="/crm/oportunidades"
    )


@router.get("/oportunidades/{opportunity_id}", response_class=HTMLResponse)
async def opportunity_detail(
    request: Request,
    opportunity_id: uuid.UUID,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        management = OpportunityManagement(session)
        try:
            opportunity = await management.opportunity(actor, opportunity_id)
        except CommercialError as exc:
            return refusal(actor, exc, active="/crm/oportunidades")
        identity = CommercialIdentity(session)
        contact = await identity.contact(actor, opportunity.contact_id)
        identities = await identity.identities(contact.id)
        needs = PropertyNeeds(session)
        snapshot = (
            await needs.snapshot(opportunity.property_need_id)
            if opportunity.property_need_id
            else None
        )
        criteria_history = (
            await needs.history(opportunity.property_need_id)
            if opportunity.property_need_id
            else []
        )
        actions = NextActions(session)
        pending = await actions.pending(opportunity.id)
        action_history = await actions.history(opportunity.id)
        transitions = await management.transitions(opportunity.id)
        origin = await management.origin(opportunity.id)
        exception = await management.open_exception(opportunity.id)
        assignments = await Assignment(session).history(opportunity.id)
        advisors = await OrganizationDirectory(session).members(
            actor.organization_id, advisors_only=True
        )
        advisor_names = {member.id: member.display_name for member in advisors}
        current_advisor = (
            advisor_names.get(opportunity.responsible_advisor_id)
            if opportunity.responsible_advisor_id
            else None
        )

    overdue = pending is not None and pending.due_at <= moment
    header = f"""<div><h2>Resumen</h2><dl class="pairs">
<dt>Contacto</dt><dd><a href="/crm/contactos/{contact.id}">
{escape(contact.display_name or "Sin nombre registrado")}</a><br>
<span class="muted">{escape(", ".join(row.identity for row in identities))}</span></dd>
<dt>Tipo</dt><dd>{escape(KIND_LABELS[opportunity.kind])}</dd>
<dt>Etapa</dt><dd>{_stage_tag(opportunity.stage)}</dd>
<dt>Asesor responsable</dt><dd>{escape(current_advisor or "Sin asignar")}</dd>
<dt>Calificada el</dt><dd>{escape(local(opportunity.qualified_at))}</dd>
<dt>Última actividad</dt><dd>{escape(local(opportunity.last_activity_at))}</dd>
<dt>Origen</dt><dd>{escape(_origin_text(origin))}</dd>
</dl></div>"""

    outcome_block = ""
    if opportunity.stage == OpportunityStage.LOST.value:
        outcome_block = flash(
            "Perdida: "
            + LOST_REASON_LABELS.get(
                opportunity.lost_reason or "", opportunity.lost_reason or ""
            ),
            "warn",
        )
    elif opportunity.stage == OpportunityStage.DORMANT.value:
        outcome_block = flash(
            "En pausa: "
            + DORMANT_REASON_LABELS.get(
                opportunity.dormant_reason or "", opportunity.dormant_reason or ""
            )
            + f". Se retoma si: {opportunity.dormant_revisit_condition or '—'}",
            "warn",
        )
    elif opportunity.stage == OpportunityStage.WON.value:
        outcome_block = flash(
            "Ganada: "
            + WON_EVIDENCE_LABELS.get(
                opportunity.won_evidence or "", opportunity.won_evidence or ""
            )
            + f". Evidencia: {opportunity.won_evidence_detail or '—'}",
            "ok",
        )

    covered = (
        opportunity.stage not in QUALIFIED_OR_BEYOND
        or (
            opportunity.responsible_advisor_id is not None
            and (
                (pending is not None and not overdue)
                or (pending is None and exception is not None)
            )
        )
    )
    requires_review = bool(
        overdue
        or exception is not None
        or (snapshot is not None and (snapshot.pending or snapshot.missing_required))
    )
    next_action_label = (
        ACTION_KIND_LABELS.get(pending.kind, pending.kind)
        if pending is not None
        else "Sin siguiente acción"
    )
    next_action_due = local(pending.due_at) if pending is not None else "—"
    summary = f"""<div class="opportunity-summary" aria-label="Resumen de la oportunidad">
<div><span class="summary-label">Etapa</span><span class="summary-value">{_stage_tag(opportunity.stage)}</span></div>
<div><span class="summary-label">Asesor responsable</span><span class="summary-value">{escape(current_advisor or "Sin asignar")}</span></div>
<div><span class="summary-label">Siguiente acción</span><span class="summary-value">{escape(next_action_label)}</span><span class="muted">{escape(next_action_due)}</span></div>
<div><span class="summary-label">Cobertura</span><span class="summary-value">{tag("Vigente", "ok") if covered else tag("Incompleta", "bad")}</span></div>
<div><span class="summary-label">Atención</span><span class="summary-value">{tag("Revisión", "warn") if requires_review else tag("Al día", "ok")}</span></div>
</div>"""
    review_banner = ""
    if snapshot is not None and snapshot.pending:
        pending_labels = ", ".join(
            criterion_label(name) for name in snapshot.pending
        )
        review_banner = (
            '<div class="warn" role="status"><strong>Hay criterios pendientes de '
            "confirmar.</strong> "
            + escape(pending_labels)
            + ". Confírmalos con el contacto y registra la fuente.</div>"
        )
    elif overdue:
        review_banner = (
            '<div class="error" role="alert"><strong>La siguiente acción está '
            "vencida.</strong> Registra el resultado o sustituye el compromiso con "
            "una fecha vigente.</div>"
        )

    main_work = (
        '<div class="opportunity-main">'
        + review_banner
        + _criteria_card(opportunity, snapshot, criteria_history)
        + _next_action_card(
            opportunity, pending, overdue, action_history, advisors, actor, moment
        )
        + _exception_card(opportunity, exception)
        + _history_card(transitions)
        + "</div>"
    )
    action_rail = (
        '<aside class="workspace-panel sticky-rail" aria-label="Acciones permitidas">'
        "<h2>Acciones</h2>"
        + _stage_card(opportunity, actor)
        + _assignment_card(
            opportunity, actor, advisors, advisor_names, assignments
        )
        + header
        + "</aside>"
    )
    content = (
        flash(SAVED_MESSAGES.get(guardado))
        + errors_box([error] if error else [])
        + outcome_block
        + summary
        + '<div class="workspace opportunity-workspace">'
        + main_work
        + action_rail
        + "</div>"
    )
    return shell(
        actor,
        contact.display_name or "Oportunidad sin nombre de contacto",
        content,
        active="/crm/oportunidades",
    )


#: What just succeeded, by token, for every surface. One registry: a second
#: one drifted immediately, and the assignment queue had grown a third
#: encoding — a bare ``"1"`` sentinel that could not carry two outcomes.
SAVED_MESSAGES = {
    "etapa": "Se registró el cambio de etapa.",
    "accion": "Se agendó la siguiente acción.",
    "completada": "Se registró el resultado de la acción.",
    "asignacion": "Se actualizó el asesor responsable.",
    "excepcion": "Se registró la excepción.",
    "excepcion-cerrada": "Se cerró la excepción.",
    "criterios": "Se actualizaron los criterios.",
    "necesidad": "Se registró la necesidad del contacto.",
    "oportunidad": "Se abrió la oportunidad.",
    "asignada": "Se asignó la oportunidad.",
}


ORIGIN_LABELS = {
    OpportunityOriginSource.WHATSAPP_INBOUND.value: "Mensaje entrante de WhatsApp",
    OpportunityOriginSource.WEBSITE_CONVERSATION.value: "Conversación en el sitio",
    OpportunityOriginSource.REFERRAL.value: "Recomendación",
    OpportunityOriginSource.CAMPAIGN.value: "Campaña",
    OpportunityOriginSource.ADVISOR_ENTRY.value: "Registrada por un asesor",
    OpportunityOriginSource.LEGACY_BACKFILL.value: "Historial anterior a la bandeja",
}


def _origin_text(origin: OpportunityOrigin | None) -> str:
    if origin is None:
        return "Sin origen registrado"
    text = ORIGIN_LABELS.get(origin.source, origin.source)
    if origin.channel:
        text += f" · {origin.channel}"
    return f"{text} · {local(origin.recorded_at)}"


def _criteria_card(
    opportunity: Opportunity,
    snapshot: NeedSnapshot | None,
    history: list[PropertyNeedCriterion],
) -> str:
    if snapshot is None:
        # Reachable on an Opportunity migrated from history: the backfill
        # invents no need, so the operator has to start one before the Contact's
        # criteria can be recorded at all.
        return (
            '<div class="card"><h2>Necesidad del contacto</h2>'
            + empty(
                "Esta oportunidad no tiene una necesidad registrada.",
                "Regístrala para poder capturar y confirmar los criterios.",
            )
            + f"""<form method="post" action="/crm/oportunidades/{opportunity.id}/necesidad">{command_field()}
<div class="actions"><button type="submit">Registrar la necesidad</button></div>
</form></div>"""
        )
    confirmed_items = "".join(
        '<div class="criterion"><strong>'
        f"{escape(criterion_label(name))}</strong><br>"
        f"{escape(INTENT_LABELS.get(value, value) if name == INTENT else value)}"
        '<br><span class="muted">Confirmado en Product</span></div>'
        for name, value in snapshot.confirmed.items()
    )
    pending_items = "".join(
        '<div class="criterion pending"><strong>'
        f"{escape(criterion_label(name))}</strong><br>"
        f"{escape(INTENT_LABELS.get(value, value) if name == INTENT else value)}"
        f"<form method='post' "
        f"action='/crm/oportunidades/{opportunity.id}/criterios'>"
        f"<input type='hidden' name='intent' value='confirmar'>{command_field()}"
        f"<input type='hidden' name='nombre' value='{escape(name)}'>"
        f"<button class='quiet'>Confirmar con el contacto</button></form></div>"
        for name, value in snapshot.pending.items()
    )
    missing = snapshot.missing_required
    missing_note = (
        flash(
            "Faltan criterios confirmados para poder calificar: "
            + ", ".join(criterion_label(name) for name in missing),
            "warn",
        )
        if missing
        else flash("Los criterios mínimos están confirmados.", "ok")
    )
    stale_note = (
        flash(
            "La necesidad tiene más de 90 días sin confirmarse. Reconfírmala "
            "antes de usarla como verdad actual.",
            "warn",
        )
        if snapshot.is_stale
        else ""
    )
    record_form = f"""<h3>Registrar un criterio confirmado</h3>
<form method="post" action="/crm/oportunidades/{opportunity.id}/criterios">
<input type="hidden" name="intent" value="registrar">{command_field()}
<div class="grid">
<label for="c-nombre">Criterio
<select id="c-nombre" name="nombre">
{options(REQUIRED_CRITERIA, "", CRITERION_LABELS)}</select></label>
<label for="c-valor">Valor confirmado
<input id="c-valor" name="valor" maxlength="300"
 placeholder="Zapopan norte, 3.5 a 4.5 millones MXN, 3 meses..."></label>
<label class="full" for="c-evidencia">¿Cómo lo confirmó el contacto?
<input id="c-evidencia" name="evidencia" maxlength="300"></label>
</div>
<div class="actions"><button type="submit">Guardar criterio</button></div>
</form>"""
    history_rows = "".join(
        f"<tr><td>{escape(criterion_label(row.name))}</td><td>{escape(row.value)}</td>"
        f"<td>{escape('Confirmado' if row.state == 'Confirmed' else 'Por confirmar')}</td>"
        f"<td>{escape(SOURCE_LABELS.get(row.source, row.source))}</td>"
        f"<td>{escape(local(row.recorded_at))}</td>"
        f"<td>{escape('vigente' if row.superseded_at is None else 'sustituido')}</td></tr>"
        for row in history[:20]
    )
    history_block = (
        f"<details><summary>Historial de criterios ({len(history)})</summary>"
        + table(
            "Cada valor con su procedencia",
            ("Criterio", "Valor", "Estado", "Origen", "Fecha", "Vigencia"),
            history_rows,
        )
        + "</details>"
        if history_rows
        else ""
    )
    current = (
        '<p class="hint">Estado de la necesidad: '
        + escape(NEED_STATUS_LABELS[snapshot.status.value])
        + "</p>"
        + (
            '<h3>Criterios confirmados</h3><div class="criteria-grid">'
            + confirmed_items
            + "</div>"
            if confirmed_items
            else ""
        )
        + (
            '<h3>Pendiente</h3><div class="criteria-grid">'
            + pending_items
            + "</div>"
            if pending_items
            else ""
        )
        + (
            empty("Todavía no hay criterios registrados.")
            if not confirmed_items and not pending_items
            else ""
        )
    )
    return (
        f'<div class="card"><h2>Necesidad del contacto</h2>{stale_note}'
        f"{missing_note}{current}{record_form}{history_block}</div>"
    )


def _next_action_card(
    opportunity: Opportunity,
    pending: NextAction | None,
    overdue: bool,
    history: list[NextAction],
    advisors: list[OrganizationMember],
    actor: Actor,
    moment: datetime,
) -> str:
    if pending is None:
        current = empty(
            "No hay una siguiente acción vigente.",
            "Agenda una o registra una excepción para explicar por qué no hay.",
        )
    else:
        current = f"""<dl class="pairs">
<dt>Acción</dt><dd>{escape(ACTION_KIND_LABELS.get(pending.kind, pending.kind))}</dd>
<dt>Vence</dt><dd>{escape(local(pending.due_at))}
 <span class="muted">({escape(relative(pending.due_at, now=moment))})</span>
 {tag("Vencida", "bad") if overdue else tag("A tiempo", "ok")}</dd>
<dt>Nota</dt><dd>{escape(pending.note or "—")}</dd>
</dl>
<form method="post" action="/crm/acciones/{pending.id}/completar">{command_field()}
<div class="grid">
<label for="a-resultado">Resultado
<select id="a-resultado" name="resultado" required>
{options(tuple(OUTCOME_LABELS), "", OUTCOME_LABELS)}</select></label>
<label for="a-detalle">Detalle
<input id="a-detalle" name="detalle" maxlength="300"></label>
</div>
<div class="actions"><button type="submit">Registrar resultado</button></div>
</form>"""

    if opportunity.stage not in ACTIVE_STAGES:
        form = flash(
            "Esta oportunidad no está activa, así que no admite nuevas acciones.",
            "warn",
        )
    else:
        default_due = datetime_input_value(moment + timedelta(days=1))
        advisor_options = "".join(
            f'<option value="{member.id}"'
            f"{' selected' if member.id == opportunity.responsible_advisor_id else ''}>"
            f"{escape(member.display_name)}</option>"
            for member in advisors
        )
        responsible_field = (
            f"""<label for="a-responsable">Responsable
<select id="a-responsable" name="responsable">
<option value="">Asesor responsable actual</option>{advisor_options}</select></label>"""
            if actor.is_administrator
            else ""
        )
        form = f"""<h3>{"Sustituir la siguiente acción" if pending else "Agendar la siguiente acción"}</h3>
{('<p class="hint">La acción vigente quedará marcada como sustituida.</p>' if pending else "")}
<form method="post" action="/crm/oportunidades/{opportunity.id}/acciones">{command_field()}
<div class="grid">
<label for="a-tipo">Tipo de acción
<select id="a-tipo" name="tipo" required>
{options(tuple(ACTION_KIND_LABELS), NextActionKind.CALL.value, ACTION_KIND_LABELS)}
</select></label>
<label for="a-vence">Vence
<input id="a-vence" name="vence" type="datetime-local" value="{escape(default_due)}"
 required></label>
{responsible_field}
<label class="full" for="a-nota">Nota para quien la ejecute
<input id="a-nota" name="nota" maxlength="300"></label>
</div>
<div class="actions"><button type="submit">Guardar acción</button></div>
</form>"""

    history_rows = "".join(
        f"<tr><td>{escape(ACTION_KIND_LABELS.get(row.kind, row.kind))}</td>"
        f"<td>{escape(local(row.due_at))}</td>"
        f"<td>{escape(ACTION_STATUS_LABELS.get(row.status, row.status))}</td>"
        f"<td>{escape(OUTCOME_LABELS.get(row.outcome or '', '—'))}</td>"
        f"<td>{escape(row.outcome_detail or row.note or '—')}</td></tr>"
        for row in history[:20]
    )
    history_block = (
        f"<details><summary>Historial de acciones ({len(history)})</summary>"
        + table(
            "Acciones agendadas, completadas, sustituidas y canceladas",
            ("Acción", "Vencía", "Estado", "Resultado", "Detalle"),
            history_rows,
        )
        + "</details>"
        if history_rows
        else ""
    )
    return f'<div class="card"><h2>Siguiente acción</h2>{current}{form}{history_block}</div>'


@dataclass(frozen=True)
class _OutcomeForm:
    """One evidence-bearing outcome control.

    Table-driven because the four stage forms differed only in their tokens and
    wording: four near-identical blocks of markup had to be kept in visual and
    accessibility sync by eye, and adding a fifth outcome meant copying one.
    """

    intent: str
    stage: str
    heading: str
    choices: dict[str, str]
    choice_name: str
    choice_label: str
    text_label: str
    text_required: bool
    button: str
    button_class: str
    hint: str = ""
    text_name: str = "detalle"
    admin_only: bool = False


OUTCOME_FORMS: tuple[_OutcomeForm, ...] = (
    _OutcomeForm(
        intent="perdida",
        stage=OpportunityStage.LOST.value,
        heading="Registrar como perdida",
        choices=LOST_REASON_LABELS,
        choice_name="motivo",
        choice_label="Motivo",
        text_label="Detalle",
        text_required=False,
        button="Registrar pérdida",
        button_class="danger",
    ),
    _OutcomeForm(
        intent="pausa",
        stage=OpportunityStage.DORMANT.value,
        heading="Poner en pausa",
        hint=(
            "En pausa no es lo mismo que perdida: hay que decir bajo qué "
            "condición se puede retomar."
        ),
        choices=DORMANT_REASON_LABELS,
        choice_name="motivo",
        choice_label="Motivo",
        text_label="Se retoma si… *",
        text_name="condicion",
        text_required=True,
        button="Poner en pausa",
        button_class="secondary",
    ),
    _OutcomeForm(
        intent="ganada",
        stage=OpportunityStage.WON.value,
        heading="Registrar como ganada",
        hint=(
            "Sólo con evidencia operativa aceptada. Una cita, una visita o una "
            "oferta no cuentan como operación concluida."
        ),
        choices=WON_EVIDENCE_LABELS,
        choice_name="evidencia",
        choice_label="Evidencia",
        text_label="Descripción de la evidencia *",
        text_required=True,
        button="Registrar operación concluida",
        button_class="",
        admin_only=True,
    ),
)


def _outcome_form(opportunity: Opportunity, form: _OutcomeForm) -> str:
    field_id = f"{form.intent}-choice"
    text_id = f"{form.intent}-text"
    hint = f'<p class="hint">{escape(form.hint)}</p>' if form.hint else ""
    required = " required" if form.text_required else ""
    button_class = f' class="{form.button_class}"' if form.button_class else ""
    return f"""<h3>{escape(form.heading)}</h3>{hint}
<form method="post" action="/crm/oportunidades/{opportunity.id}/etapa">
<input type="hidden" name="intent" value="{escape(form.intent)}">{command_field()}
<div class="grid">
<label for="{field_id}">{escape(form.choice_label)}
<select id="{field_id}" name="{escape(form.choice_name)}" required>
{options(tuple(form.choices), "", form.choices)}</select></label>
<label for="{text_id}">{escape(form.text_label)}
<input id="{text_id}" name="{escape(form.text_name)}" maxlength="300"{required}>
</label>
</div>
<div class="actions"><button{button_class} type="submit">
{escape(form.button)}</button></div></form>"""


def _stage_card(opportunity: Opportunity, actor: Actor) -> str:
    allowed = ALLOWED_TRANSITIONS[opportunity.stage]
    if not allowed:
        return (
            '<div class="card"><h2>Etapa comercial</h2>'
            + flash("Esta oportunidad ya está cerrada y no cambia de etapa.", "warn")
            + "</div>"
        )

    advanceable = tuple(value for value in ADVANCEABLE_STAGES if value in allowed)
    needs_new_coverage = opportunity.stage not in QUALIFIED_OR_BEYOND
    coverage_targets = (
        tuple(value for value in advanceable if value in QUALIFIED_OR_BEYOND)
        if needs_new_coverage
        else ()
    )
    plain_targets = tuple(
        value for value in advanceable if value not in coverage_targets
    )
    blocks = []
    if plain_targets:
        blocks.append(
            f"""<h3>Mover de etapa</h3>
<form method="post" action="/crm/oportunidades/{opportunity.id}/etapa">
<input type="hidden" name="intent" value="avanzar">{command_field()}
<div class="grid">
<label for="s-etapa">Nueva etapa
<select id="s-etapa" name="etapa" required>
    {options(plain_targets, "", STAGE_LABELS)}</select></label>
<label for="s-detalle">Nota
<input id="s-detalle" name="detalle" maxlength="300"></label>
</div>
<div class="actions"><button type="submit">Cambiar etapa</button></div></form>"""
        )
    if coverage_targets:
        default_due = datetime_input_value(_now() + timedelta(days=1))
        blocks.append(
            f"""<h3>Calificar y dejar seguimiento</h3>
<p class="hint">La calificación, la asignación y la siguiente acción se guardan juntas.</p>
<form method="post" action="/crm/oportunidades/{opportunity.id}/etapa">
<input type="hidden" name="intent" value="avanzar">{command_field()}
<div class="grid">
<label for="q-etapa">Nueva etapa
<select id="q-etapa" name="etapa" required>
{options(coverage_targets, "", STAGE_LABELS)}</select></label>
<label for="q-accion">Siguiente acción
<select id="q-accion" name="accion_tipo" required>
{options(tuple(ACTION_KIND_LABELS), NextActionKind.CALL.value, ACTION_KIND_LABELS)}
</select></label>
<label for="q-vence">Vence
<input id="q-vence" name="accion_vence" type="datetime-local"
 value="{escape(default_due)}" required></label>
<label for="q-detalle">Nota de etapa
<input id="q-detalle" name="detalle" maxlength="300"></label>
<label class="full" for="q-nota">Nota para quien dará seguimiento
<input id="q-nota" name="accion_nota" maxlength="300"></label>
</div>
<div class="actions"><button type="submit">Calificar y agendar</button></div></form>"""
        )

    for form in OUTCOME_FORMS:
        if form.stage not in allowed:
            continue
        if form.admin_only and not actor.is_administrator:
            blocks.append(
                f"<h3>{escape(form.heading)}</h3>"
                + flash(
                    "Sólo un administrador de la organización puede registrar una "
                    "oportunidad como ganada.",
                    "warn",
                )
            )
            continue
        blocks.append(_outcome_form(opportunity, form))

    return '<div class="card"><h2>Etapa comercial</h2>' + "".join(blocks) + "</div>"


def _assignment_card(
    opportunity: Opportunity,
    actor: Actor,
    advisors: list[OrganizationMember],
    advisor_names: dict[uuid.UUID, str],
    history: list[OpportunityAssignment],
) -> str:
    if not actor.is_administrator:
        return ""
    advisor_options = "".join(
        f'<option value="{member.id}"'
        f"{' selected' if member.id == opportunity.responsible_advisor_id else ''}>"
        f"{escape(member.display_name)}</option>"
        for member in advisors
    )
    manual = (
        f"""<form method="post" action="/crm/oportunidades/{opportunity.id}/asignar">
<input type="hidden" name="intent" value="manual">{command_field()}
<label for="as-advisor">Asesor responsable
<select id="as-advisor" name="asesor" required>{advisor_options}</select></label>
<div class="actions"><button type="submit">Asignar</button></div></form>"""
        if advisors
        else flash(
            "No hay asesores activos configurados. Agrega logins en "
            "ORGANIZATION_ADVISOR_LOGINS y reinicia el producto.",
            "warn",
        )
    )
    automatic = f"""<form method="post" action="/crm/oportunidades/{opportunity.id}/asignar">
<input type="hidden" name="intent" value="automatica">{command_field()}
<div class="actions"><button class="quiet" type="submit">
Aplicar la regla automática</button></div></form>"""
    release = (
        f"""<form method="post" action="/crm/oportunidades/{opportunity.id}/asignar">
<input type="hidden" name="intent" value="liberar">{command_field()}
<div class="actions"><button class="secondary" type="submit">
Liberar y enviar a la cola</button></div></form>"""
        if opportunity.responsible_advisor_id
        else ""
    )
    history_rows = "".join(
        f"<tr><td>{escape(advisor_names.get(row.advisor_id, str(row.advisor_id)))}</td>"
        f"<td>{escape(BASIS_LABELS.get(row.basis, row.basis))}</td>"
        f"<td>{escape(local(row.assigned_at))}</td>"
        f"<td>{escape(local(row.unassigned_at) if row.unassigned_at else 'vigente')}</td></tr>"
        for row in history[:10]
    )
    history_block = (
        f"<details><summary>Historial de asignaciones ({len(history)})</summary>"
        + table(
            "Quién fue responsable y desde cuándo",
            ("Asesor", "Motivo", "Desde", "Hasta"),
            history_rows,
        )
        + "</details>"
        if history_rows
        else ""
    )
    return (
        '<div class="card"><h2>Asignación</h2>'
        f"{manual}{automatic}{release}{history_block}</div>"
    )


def _exception_card(
    opportunity: Opportunity, exception: OpportunityException | None
) -> str:
    if opportunity.stage not in ACTIVE_STAGES:
        return ""
    if exception is not None:
        return f"""<div class="card"><h2>Excepción registrada</h2>
<dl class="pairs">
<dt>Motivo</dt><dd>{escape(EXCEPTION_REASON_LABELS.get(exception.reason, exception.reason))}</dd>
<dt>Detalle</dt><dd>{escape(exception.detail or "—")}</dd>
<dt>Registrada por</dt><dd>{escape(exception.recorded_by)} ·
{escape(local(exception.recorded_at))}</dd></dl>
<form method="post" action="/crm/oportunidades/{opportunity.id}/excepcion">
<input type="hidden" name="intent" value="cerrar">{command_field()}
<div class="actions"><button class="quiet" type="submit">Cerrar excepción</button>
</div></form></div>"""
    return f"""<div class="card"><h2>Excepción de seguimiento</h2>
<p class="hint">Usa esto sólo cuando de verdad no corresponde una siguiente
acción. Queda registrado con tu nombre.</p>
<form method="post" action="/crm/oportunidades/{opportunity.id}/excepcion">
<input type="hidden" name="intent" value="registrar">{command_field()}
<div class="grid">
<label for="e-motivo">Motivo <select id="e-motivo" name="motivo" required>
{options(tuple(EXCEPTION_REASON_LABELS), "", EXCEPTION_REASON_LABELS)}</select></label>
<label for="e-detalle">Detalle
<input id="e-detalle" name="detalle" maxlength="300"></label>
</div>
<div class="actions"><button class="secondary" type="submit">
Registrar excepción</button></div></form></div>"""


def _history_card(transitions: list[OpportunityStageTransition]) -> str:
    if not transitions:
        return ""
    rows = "".join(
        f"<tr><td>{escape(local(row.occurred_at))}</td>"
        f"<td>{escape(STAGE_LABELS.get(row.from_stage or '', '—'))}</td>"
        f"<td>{escape(STAGE_LABELS.get(row.to_stage, row.to_stage))}</td>"
        f"<td>{escape(row.reason or '—')}</td>"
        f"<td>{escape(row.actor_id)}</td></tr>"
        for row in transitions[:25]
    )
    return (
        '<div class="card"><h2>Historial de etapas</h2>'
        + table(
            "Cada cambio con su motivo y quién lo hizo",
            ("Fecha", "De", "A", "Motivo", "Quién"),
            rows,
        )
        + "</div>"
    )


# ----------------------------------------------------------- Mutations -------


def _redirect(opportunity_id: uuid.UUID, saved: str) -> RedirectResponse:
    return redirect_back(f"/crm/oportunidades/{opportunity_id}", saved=saved)


def _redirect_error(opportunity_id: uuid.UUID, message: str) -> RedirectResponse:
    return redirect_back(f"/crm/oportunidades/{opportunity_id}", error=message)


@router.post("/oportunidades/{opportunity_id}/etapa")
async def change_stage(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    intent = str(form.get("intent", ""))
    detail = str(form.get("detalle", "")).strip() or None
    key = command_key(form, "crm-stage")
    async with request.app.state.database.session_scope() as session:
        management = OpportunityManagement(session)
        try:
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="ChangeOpportunityStage",
                subject_type="Opportunity",
                subject_id=str(opportunity_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                return _redirect(opportunity_id, "etapa")
            if intent == "avanzar":
                stage = str(form.get("etapa", ""))
                if stage not in STAGE_LABELS:
                    return _redirect_error(opportunity_id, "Etapa desconocida.")
                qualification_action = None
                action_kind = str(form.get("accion_tipo", ""))
                action_due = parse_datetime_input(str(form.get("accion_vence", "")))
                if action_kind or action_due is not None:
                    if action_kind not in ACTION_KIND_LABELS or action_due is None:
                        return _redirect_error(
                            opportunity_id,
                            "Indica una siguiente acción y un vencimiento válidos.",
                        )
                    qualification_action = QualificationAction(
                        kind=NextActionKind(action_kind),
                        due_at=action_due,
                        note=str(form.get("accion_nota", "")).strip() or None,
                    )
                await management.record(
                    actor,
                    AdvanceStage(
                        opportunity_id=opportunity_id,
                        to_stage=OpportunityStage(stage),
                        reason="OperatorDecision",
                        detail=detail,
                        command_key=key,
                        qualification_action=qualification_action,
                    ),
                )
            elif intent == "perdida":
                reason = str(form.get("motivo", ""))
                if reason not in LOST_REASON_LABELS:
                    return _redirect_error(opportunity_id, "Motivo desconocido.")
                await management.record(
                    actor,
                    RecordLost(
                        opportunity_id=opportunity_id,
                        reason=LostReason(reason),
                        detail=detail,
                        command_key=key,
                    ),
                )
            elif intent == "pausa":
                reason = str(form.get("motivo", ""))
                if reason not in DORMANT_REASON_LABELS:
                    return _redirect_error(opportunity_id, "Motivo desconocido.")
                await management.record(
                    actor,
                    RecordDormant(
                        opportunity_id=opportunity_id,
                        reason=DormantReason(reason),
                        revisit_condition=str(form.get("condicion", "")),
                        command_key=key,
                    ),
                )
            elif intent == "ganada":
                evidence = str(form.get("evidencia", ""))
                if evidence not in WON_EVIDENCE_LABELS:
                    return _redirect_error(opportunity_id, "Evidencia desconocida.")
                await management.record(
                    actor,
                    RecordWon(
                        opportunity_id=opportunity_id,
                        evidence=WonEvidence(evidence),
                        evidence_detail=str(form.get("detalle", "")),
                        command_key=key,
                    ),
                )
            else:
                return _redirect_error(opportunity_id, "Acción desconocida.")
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "etapa")


@router.post("/oportunidades/{opportunity_id}/acciones")
async def schedule_action(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    kind = str(form.get("tipo", ""))
    if kind not in ACTION_KIND_LABELS:
        return _redirect_error(opportunity_id, "Tipo de acción desconocido.")
    due_at = parse_datetime_input(str(form.get("vence", "")))
    if due_at is None:
        return _redirect_error(
            opportunity_id, "Indica una fecha y hora de vencimiento válida."
        )
    if due_at <= _now():
        return _redirect_error(
            opportunity_id, "La siguiente acción debe vencer en el futuro."
        )
    responsible_raw = str(form.get("responsable", "")).strip()
    responsible: uuid.UUID | None = None
    if responsible_raw:
        try:
            responsible = uuid.UUID(responsible_raw)
        except ValueError:
            return _redirect_error(opportunity_id, "Responsable desconocido.")
    key = command_key(form, "crm-action")
    async with request.app.state.database.session_scope() as session:
        try:
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="ScheduleNextAction",
                subject_type="Opportunity",
                subject_id=str(opportunity_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                return _redirect(opportunity_id, "accion")
            await NextActions(session).schedule(
                actor,
                ScheduleNextAction(
                    opportunity_id=opportunity_id,
                    kind=NextActionKind(kind),
                    due_at=due_at,
                    responsible_member_id=responsible,
                    note=str(form.get("nota", "")).strip() or None,
                    command_key=key,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "accion")


@router.post("/acciones/{next_action_id}/completar")
async def complete_action(
    request: Request,
    next_action_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    outcome = str(form.get("resultado", ""))
    async with request.app.state.database.session_scope() as session:
        actions = NextActions(session)
        try:
            action = await actions.action(actor, next_action_id)
        except CommercialError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=exc.message
            ) from exc
        opportunity_id = action.opportunity_id
        if outcome not in OUTCOME_LABELS:
            return _redirect_error(opportunity_id, "Resultado desconocido.")
        try:
            key = command_key(form, "crm-complete")
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="CompleteNextAction",
                subject_type="NextAction",
                subject_id=str(next_action_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                return _redirect(opportunity_id, "completada")
            await actions.complete(
                actor,
                CompleteNextAction(
                    next_action_id=next_action_id,
                    outcome=NextActionOutcome(outcome),
                    outcome_detail=str(form.get("detalle", "")).strip() or None,
                    command_key=key,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "completada")


@router.post("/oportunidades/{opportunity_id}/asignar")
async def assign(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    intent = str(form.get("intent", ""))
    key = command_key(form, "crm-assignment")
    async with request.app.state.database.session_scope() as session:
        assignment = Assignment(session)
        try:
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="ManageAssignment",
                subject_type="Opportunity",
                subject_id=str(opportunity_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                return _redirect(opportunity_id, "asignacion")
            if intent == "manual":
                try:
                    advisor_id = uuid.UUID(str(form.get("asesor", "")))
                except ValueError:
                    return _redirect_error(opportunity_id, "Asesor desconocido.")
                await assignment.assign_manually(actor, opportunity_id, advisor_id)
            elif intent == "automatica":
                await assignment.assign(actor, opportunity_id)
            elif intent == "liberar":
                await assignment.release(actor, opportunity_id)
            else:
                return _redirect_error(opportunity_id, "Acción desconocida.")
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "asignacion")


@router.post("/oportunidades/{opportunity_id}/excepcion")
async def exception(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    intent = str(form.get("intent", ""))
    key = command_key(form, "crm-exception")
    async with request.app.state.database.session_scope() as session:
        management = OpportunityManagement(session)
        try:
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="ManageOpportunityException",
                subject_type="Opportunity",
                subject_id=str(opportunity_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                saved = "excepcion-cerrada" if intent == "cerrar" else "excepcion"
                return _redirect(opportunity_id, saved)
            if intent == "registrar":
                reason = str(form.get("motivo", ""))
                if reason not in EXCEPTION_REASON_LABELS:
                    return _redirect_error(opportunity_id, "Motivo desconocido.")
                await management.record_exception(
                    actor,
                    opportunity_id,
                    reason=OpportunityExceptionReason(reason),
                    detail=str(form.get("detalle", "")).strip() or None,
                    command_key=key,
                )
                saved = "excepcion"
            elif intent == "cerrar":
                await management.clear_exception(actor, opportunity_id)
                saved = "excepcion-cerrada"
            else:
                return _redirect_error(opportunity_id, "Acción desconocida.")
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, saved)


@router.post("/oportunidades/{opportunity_id}/necesidad")
async def attach_need(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    """Start a Property Need for an Opportunity that has none."""
    form = await request.form()
    key = command_key(form, "crm-attach-need")
    async with request.app.state.database.session_scope() as session:
        try:
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="AttachPropertyNeed",
                subject_type="Opportunity",
                subject_id=str(opportunity_id),
                payload=command_payload(form),
            )
            if not replayed:
                await OpportunityManagement(session).attach_need(actor, opportunity_id)
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "necesidad")


@router.post("/oportunidades/{opportunity_id}/criterios")
async def criteria(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    intent = str(form.get("intent", ""))
    name = str(form.get("nombre", "")).strip()
    key = command_key(form, "crm-criteria")
    async with request.app.state.database.session_scope() as session:
        management = OpportunityManagement(session)
        try:
            opportunity = await management.opportunity(actor, opportunity_id)
            if opportunity.property_need_id is None:
                return _redirect_error(
                    opportunity_id, "Esta oportunidad no tiene una necesidad."
                )
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="UpdatePropertyNeedCriteria",
                subject_type="PropertyNeed",
                subject_id=str(opportunity.property_need_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                return _redirect(opportunity_id, "criterios")
            needs = PropertyNeeds(session)
            if intent == "confirmar":
                await needs.confirm(actor, opportunity.property_need_id, [name])
            elif intent == "registrar":
                value = str(form.get("valor", "")).strip()
                if not name or not value:
                    return _redirect_error(
                        opportunity_id, "Indica el criterio y su valor."
                    )
                await needs.record(
                    actor,
                    opportunity.property_need_id,
                    [
                        CriterionStatement.recorded(
                            name,
                            value,
                            evidence=str(form.get("evidencia", "")).strip() or None,
                        )
                    ],
                )
            else:
                return _redirect_error(opportunity_id, "Acción desconocida.")
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "criterios")


# ------------------------------------------------------------ Contactos ------


@router.get("/contactos", response_class=HTMLResponse)
async def contacts(
    request: Request, q: str = "", actor: Actor = Depends(require_actor)
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        rows = await CommercialInbox(session).contacts(actor, query=q.strip() or None)
    body = "".join(
        f"<tr><td><a href='/crm/contactos/{row.contact.id}'>"
        f"{escape(row.contact.display_name or 'Sin nombre registrado')}</a></td>"
        f"<td>{escape(', '.join(row.identities))}</td>"
        f"<td>{row.open_opportunities}</td>"
        f"<td>{escape(local(row.last_activity_at))}</td>"
        f"<td>{tag('No contactar', 'bad') if row.suppressed else '—'}</td></tr>"
        for row in rows
    )
    listing = table(
        f"{len(rows)} contacto(s)",
        (
            "Nombre",
            "WhatsApp",
            "Oportunidades abiertas",
            "Última actividad",
            "Restricciones",
        ),
        body,
        empty_message="No hay contactos que coincidan.",
        empty_hint="Un contacto se crea con el primer mensaje verificado de WhatsApp.",
    )
    search = f"""<form class="card" method="get" action="/crm/contactos">
<label for="c-q">Buscar por nombre o número
<input id="c-q" name="q" value="{escape(q)}"></label>
<div class="actions"><button type="submit">Buscar</button>
<a class="button quiet" href="/crm/contactos">Limpiar</a></div></form>"""
    return shell(actor, "Contactos", search + listing, active="/crm/contactos")


@router.get("/contactos/{contact_id}", response_class=HTMLResponse)
async def contact_detail(
    request: Request,
    contact_id: uuid.UUID,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        identity = CommercialIdentity(session)
        try:
            contact = await identity.contact(actor, contact_id)
        except CommercialError as exc:
            return refusal(actor, exc, active="/crm/contactos")
        identities = await identity.identities(contact_id)
        duplicates = await identity.possible_duplicates(actor, contact_id)
        needs = PropertyNeeds(session)
        contact_needs = await needs.needs_for_contact(contact_id)
        snapshots = [await needs.snapshot(need.id) for need in contact_needs]
        opportunities_list = await OpportunityManagement(session).active_for_contact(
            actor, contact_id
        )

    identity_rows = "".join(
        f"<tr><td>{escape(row.identity)}</td><td>{escape(row.channel)}</td>"
        f"<td>{escape('Verificada' if row.trust == ChannelIdentityTrust.VERIFIED.value else 'Declarada')}</td>"
        f"<td>{escape(local(row.first_seen_at))}</td></tr>"
        for row in identities
    )
    duplicate_block = ""
    if duplicates:
        items = "".join(
            f"<li>{escape(row.identity)} · "
            f"<a href='/crm/contactos/{row.contact_id}'>ver contacto</a></li>"
            for row in duplicates
        )
        duplicate_block = f"""<div class="warn" role="status" aria-live="polite">
<strong>Hay números parecidos en otros contactos.</strong>
<p>No los unimos automáticamente: parecerse no demuestra que sean la misma
persona. Revísalos y decide tú.</p><ul>{items}</ul></div>"""

    need_blocks = "".join(
        f"""<div class="card"><h3>Necesidad del {escape(local(need.created_at))}</h3>
<dl class="pairs">
<dt>Estado</dt><dd>{escape(NEED_STATUS_LABELS[snapshot.status.value])}</dd>
<dt>Operación</dt><dd>{escape(INTENT_LABELS.get(need.transaction_intent or "", "Por confirmar"))}</dd>
<dt>Confirmado</dt><dd>{escape(", ".join(f"{criterion_label(k)}: {v}" for k, v in snapshot.confirmed.items()) or "—")}</dd>
<dt>Por confirmar</dt><dd>{escape(", ".join(f"{criterion_label(k)}: {v}" for k, v in snapshot.pending.items()) or "—")}</dd>
<dt>Última confirmación</dt><dd>{escape(local(snapshot.last_confirmed_at))}</dd>
</dl></div>"""
        for need, snapshot in zip(contact_needs, snapshots, strict=True)
    ) or empty("Este contacto no tiene necesidades registradas.")

    opportunity_rows = "".join(
        f"<tr><td><a href='/crm/oportunidades/{row.id}'>"
        f"{escape(KIND_LABELS[row.kind])}</a></td>"
        f"<td>{_stage_tag(row.stage)}</td>"
        f"<td>{escape(local(row.created_at))}</td>"
        f"<td>{escape(local(row.last_activity_at))}</td></tr>"
        for row in opportunities_list
    )
    opportunity_block = table(
        "Historial comercial completo",
        ("Tipo", "Etapa", "Creada", "Última actividad"),
        opportunity_rows,
        empty_message="Este contacto no tiene oportunidades.",
    )

    open_form = ""
    if actor.is_administrator:
        # A Listing Acquisition has no inbound path: an owner who wants help
        # selling is recorded by a person, not resolved from a webhook. Without
        # this control the kind would be modelled and unreachable.
        open_form = f"""<h3>Abrir una oportunidad nueva</h3>
<p class="hint">Una captación es cuando la persona quiere que le ayudemos a
vender o rentar su propiedad. En esta versión la continúa el administrador.</p>
<form method="post" action="/crm/contactos/{contact_id}/oportunidades">{command_field()}
<label for="o-tipo">Tipo
<select id="o-tipo" name="tipo" required>
{options(tuple(KIND_LABELS), OpportunityKind.LISTING_ACQUISITION.value, KIND_LABELS)}
</select></label>
<div class="actions"><button type="submit">Abrir oportunidad</button></div>
</form>"""

    content = f"""{flash(SAVED_MESSAGES.get(guardado))}{
        errors_box([error] if error else [])
    }
{duplicate_block}
<div class="card"><h2>Identidades de canal</h2>
<p class="hint">Una identidad verificada es la que la plataforma autenticó.
Sólo una identidad idéntica resuelve al mismo contacto.</p>
{
        table(
            f"{len(identities)} identidad(es)",
            ("Identificador", "Canal", "Confianza", "Primera vez"),
            identity_rows,
        )
    }</div>
<h2>Necesidades</h2>{need_blocks}
<h2>Oportunidades</h2>{opportunity_block}
<div class="card">{
        open_form
        or '<p class="hint">Sólo un administrador puede abrir una oportunidad nueva.</p>'
    }</div>"""
    return shell(
        actor,
        contact.display_name or "Contacto sin nombre",
        content,
        active="/crm/contactos",
    )


@router.post("/contactos/{contact_id}/oportunidades")
async def open_opportunity(
    request: Request,
    contact_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    """Open a pursuit for a Contact who is already known.

    The inbound path only ever opens a Demand Opportunity, because that is what
    an inquiry is. Everything else — a Listing Acquisition, a second Demand for
    a different need — is a person's decision and is recorded as one.
    """
    form = await request.form()
    kind = str(form.get("tipo", ""))
    contact_path = f"/crm/contactos/{contact_id}"

    def failed(message: str) -> RedirectResponse:
        return redirect_back(contact_path, error=message)

    if kind not in KIND_LABELS:
        return failed("Tipo de oportunidad desconocido.")
    key = command_key(form, "crm-open")
    async with request.app.state.database.session_scope() as session:
        try:
            actor.require_administrator()
            identity = CommercialIdentity(session)
            await identity.contact(actor, contact_id)
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="OpenOpportunity",
                subject_type="Contact",
                subject_id=str(contact_id),
                payload=command_payload(form),
            )
            if replayed:
                await session.commit()
                return redirect_back(contact_path, saved="oportunidad")
            need = await PropertyNeeds(session).open(actor, contact_id=contact_id)
            await OpportunityManagement(session).record(
                actor,
                OpenOpportunity(
                    contact_id=contact_id,
                    kind=OpportunityKind(kind),
                    property_need_id=need.id,
                    origin=OriginFacts(
                        source=OpportunityOriginSource.ADVISOR_ENTRY,
                        channel="WhatsApp",
                    ),
                    command_key=key,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return failed(exc.message)
    return redirect_back(contact_path, saved="oportunidad")


# ------------------------------------------------------------ Asignación -----


@router.get("/asignacion", response_class=HTMLResponse)
async def assignment_queue(
    request: Request,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """The Administrator's queue of Opportunities nobody is responsible for."""
    async with request.app.state.database.session_scope() as session:
        try:
            queue = await Assignment(session).queue(actor)
        except CommercialError as exc:
            return refusal(actor, exc, active="/crm/asignacion")
        advisors = await OrganizationDirectory(session).members(
            actor.organization_id, advisors_only=True
        )

    advisor_options = "".join(
        f'<option value="{member.id}">{escape(member.display_name)}</option>'
        for member in advisors
    )
    rows = "".join(
        f"<tr><td><a href='/crm/oportunidades/{item.opportunity.id}'>"
        f"{escape(item.contact_name or 'Contacto sin nombre')}</a><br>"
        f"<span class='muted'>{escape(KIND_LABELS[item.opportunity.kind])}</span></td>"
        f"<td>{_stage_tag(item.opportunity.stage)}</td>"
        f"<td>{escape(QUEUE_REASON_LABELS.get(item.reason.value if item.reason else '', 'Sin asesor asignado'))}"
        + (
            f"<br><span class='muted'>{escape(item.detail)}</span>"
            if item.detail
            else ""
        )
        + "</td>"
        f"<td>{escape(local(item.since))}</td>"
        f"<td><form method='post' action='/crm/asignacion/{item.opportunity.id}'>{command_field()}"
        f"<label class='muted' for='q-{item.opportunity.id}'>Asesor</label>"
        f"<select id='q-{item.opportunity.id}' name='asesor' required>{advisor_options}</select>"
        f"<div class='actions'><button type='submit'>Asignar</button></div>"
        f"</form></td></tr>"
        for item in queue
    )
    listing = table(
        f"{len(queue)} oportunidad(es) sin asesor responsable",
        ("Contacto", "Etapa", "Motivo", "En la cola desde", "Asignar"),
        rows,
        empty_message="La cola está vacía.",
        empty_hint="Toda oportunidad activa tiene un asesor responsable.",
    )
    warning = (
        ""
        if advisors
        else flash(
            "No hay asesores activos. Configura al menos un asesor en el "
            "directorio de la organización y reinicia el producto para asignar.",
            "warn",
        )
    )
    content = (
        flash(SAVED_MESSAGES.get(guardado))
        + errors_box([error] if error else [])
        + warning
        + listing
    )
    return shell(actor, "Cola de asignación", content, active="/crm/asignacion")


@router.post("/asignacion/{opportunity_id}")
async def assign_from_queue(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    try:
        advisor_id = uuid.UUID(str(form.get("asesor", "")))
    except ValueError:
        return redirect_back("/crm/asignacion", error="Asesor desconocido.")
    key = command_key(form, "crm-queue-assignment")
    async with request.app.state.database.session_scope() as session:
        try:
            replayed = await CommercialCommands(session).claim(
                actor,
                command_key=key,
                operation="AssignFromQueue",
                subject_type="Opportunity",
                subject_id=str(opportunity_id),
                payload=command_payload(form),
            )
            if not replayed:
                await Assignment(session).assign_manually(
                    actor, opportunity_id, advisor_id
                )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return redirect_back("/crm/asignacion", error=exc.message)
    return redirect_back("/crm/asignacion", saved="asignada")

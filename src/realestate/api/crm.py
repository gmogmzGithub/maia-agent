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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import FormData

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
    counted,
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
    Property,
    TransactionJourneyTemplateVersion,
    QUALIFIED_OR_BEYOND,
)
from realestate.api.operations import handling_panel, reply_form
from realestate.domain.commercial.actors import (
    Actor,
    CommercialError,
    InvalidTransition,
    MissingEvidence,
)
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
from realestate.domain.journeys import (
    JourneyState,
    JourneyTemplates,
    JourneyWorkspace,
    MILESTONE_STATE_LABELS,
    MilestoneState,
    TransactionJourneys,
)
from realestate.domain.market_intelligence import (
    PROFILE_FIELDS,
    SALE_FIELDS,
    MarketRecords,
)

router = APIRouter(prefix="/crm", tags=["crm"])

CUSTOMER_CHANNEL_LABELS = {
    "WhatsApp": "WhatsApp",
    "FacebookMessenger": "Facebook Messenger",
    "Instagram": "Instagram",
}

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
    DenialReason.CHANNEL_POLICY_UNSUPPORTED.value: (
        "Ese tipo de mensaje no está permitido en este canal"
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
            tag("No contactar", "bad") + f" <span class='muted'>{escape(reason)}</span>"
        )
    if restriction.denied_count:
        parts.append(
            tag(
                counted(
                    restriction.denied_count,
                    "envío no permitido",
                    "envíos no permitidos",
                ),
                "warn",
            )
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
        funnel = await views.funnel(actor)
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
            reason=(f"{entry.contact_name or 'Un contacto'} espera respuesta"),
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
        f"Estado actual · Consultado {escape(metric_freshness)}</div>"
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
        uncovered = coverage.active - coverage.covered
        banner = flash(
            counted(
                uncovered,
                "oportunidad calificada activa",
                "oportunidades calificadas activas",
            )
            + (" no cumple" if uncovered == 1 else " no cumplen")
            + " la promesa de seguimiento.",
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
            f"<p>{counted(len(queue), 'oportunidad', 'oportunidades')} "
            f"{'espera' if len(queue) == 1 else 'esperan'} asignación manual. "
            f"<a href='/crm/asignacion'>Ir a la cola</a></p>"
            if queue
            else empty("La cola de asignación está vacía.")
        )

    issue_count = (
        len(inbox_rows) + len(overdue_rows) + len(queue) + len(appointment_rows)
    )
    if issue_count:
        waiting_count = len(inbox_rows)
        overdue_count = len(overdue_rows)
        queue_count = len(queue)
        review_count = len(appointment_rows)
        summary = (
            '<div class="operational-summary"><strong>'
            f"{counted(issue_count, 'asunto', 'asuntos')} "
            f"{'requiere' if issue_count == 1 else 'requieren'} atención"
            "</strong><span>"
            f"{counted(waiting_count, 'persona', 'personas')} "
            f"{'espera' if waiting_count == 1 else 'esperan'} · "
            f"{counted(overdue_count, 'acción vencida', 'acciones vencidas')} · "
            f"{counted(queue_count, 'oportunidad sin asesor', 'oportunidades sin asesor')} · "
            f"{counted(review_count, 'visita para revisar', 'visitas para revisar')}"
            "</span></div>"
        )
    else:
        summary = (
            '<div class="ok" role="status"><strong>La operación está al día.</strong> '
            "No hay asuntos que requieran intervención dentro de tu alcance.</div>"
        )
    visible_priority = priority[:10]
    priority_more = (
        '<p class="priority-more">Mostramos los 10 asuntos más urgentes. '
        '<a href="/crm/bandeja">Ver Bandeja</a> · '
        '<a href="/crm/oportunidades">Ver Oportunidades</a></p>'
        if len(priority) > len(visible_priority)
        else ""
    )
    priority_block = (
        '<section class="work-section" aria-labelledby="prioridad">'
        '<div class="work-section-header"><div><h2 id="prioridad">'
        + ("Lo más importante" if actor.is_administrator else "Lo siguiente")
        + "</h2><p>Primero lo urgente; después, lo que puedes preparar.</p></div></div>"
        + _priority_rows(visible_priority)
        + priority_more
        + "</section>"
    )
    active_funnel_stages = (
        OpportunityStage.NEW,
        OpportunityStage.IN_CONVERSATION,
        OpportunityStage.QUALIFIED,
        OpportunityStage.SEARCHING,
        OpportunityStage.VISITING,
        OpportunityStage.NEGOTIATING,
    )
    funnel_steps = "".join(
        '<li class="funnel-step">'
        f'<a href="/crm/oportunidades?stage={stage.value}">'
        f'<span class="funnel-count">{funnel[stage.value]}</span>'
        f'<span class="funnel-label">{escape(STAGE_LABELS[stage.value])}</span>'
        "</a></li>"
        for stage in active_funnel_stages
    )
    funnel_states = "".join(
        '<a class="funnel-state" '
        f'href="/crm/oportunidades?stage={stage.value}">'
        f"<span>{escape(STAGE_LABELS[stage.value])}</span>"
        f"<strong>{funnel[stage.value]}</strong></a>"
        for stage in (
            OpportunityStage.DORMANT,
            OpportunityStage.WON,
            OpportunityStage.LOST,
        )
    )
    funnel_block = (
        '<section class="work-section" aria-labelledby="embudo-comercial">'
        '<div class="work-section-header"><div><h2 id="embudo-comercial">'
        "Embudo comercial</h2><p>Estado actual de cada oportunidad dentro de tu alcance. "
        "Selecciona una etapa para ver sus contactos.</p></div>"
        '<a href="/crm/oportunidades">Ver todas</a></div>'
        f'<ol class="funnel" aria-label="Etapas activas">{funnel_steps}</ol>'
        f'<div class="funnel-states" aria-label="Oportunidades pausadas y cerradas">'
        f"{funnel_states}</div></section>"
    )
    details = (
        '<details class="secondary-work"><summary>Ver detalle operativo</summary>'
        '<div class="secondary-work-content">'
        f"<h2>Huecos de seguimiento</h2>{gaps_table}"
        f"{overdue_block}{queue_block}</div></details>"
    )
    content = (
        f"{summary}{priority_block}{funnel_block}"
        '<section class="work-section" aria-labelledby="salud-operativa">'
        '<div class="work-section-header"><div><h2 id="salud-operativa">'
        "Resumen</h2><p>Una vista simple del seguimiento dentro de tu alcance.</p>"
        f"</div></div>{banner}<div class='stats'>{stats}</div></section>"
        f"{details}"
    )
    title = (
        f"Hoy en {actor.organization_name}" if actor.is_administrator else "Mi trabajo"
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
        f"<span class='muted'>{escape(CUSTOMER_CHANNEL_LABELS.get(entry.channel, entry.channel))} · "
        f"{escape(entry.channel_identity)}</span></td>"
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
        counted(len(entries), "conversación", "conversaciones"),
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
        empty_hint="Quita los filtros o espera el primer mensaje de un canal conectado.",
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
    "solicitud": ("Confirmaste que ya atiendes la solicitud. Maia sigue pausada."),
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
        f'<p class="hint">{escape(CUSTOMER_CHANNEL_LABELS.get(view.channel, view.channel))} · '
        f'{escape(view.channel_identity)}</p>'
        + handling_panel(
            handling,
            pending_handoff,
            actor,
            conversation_id=conversation_id,
            maia_mid_turn=mid_turn is not None,
        )
        + "<h2>Conversación</h2>"
        + thread
        + reply_form(
            handling,
            actor,
            conversation_id=conversation_id,
            channel_label=CUSTOMER_CHANNEL_LABELS.get(view.channel, view.channel),
        )
        + "</section>"
    )
    context_panel = (
        '<aside class="workspace-panel context-panel sticky-rail" '
        'aria-label="Contexto y autoridad">'
        + f"{restriction_block}"
        + f"<div><h2>Contacto</h2><dl class='pairs'>"
        f"<dt>Nombre</dt><dd>{escape(view.contact.display_name or 'Sin nombre registrado')}</dd>"
        f"<dt>Canal</dt><dd>{escape(CUSTOMER_CHANNEL_LABELS.get(view.channel, view.channel))}</dd>"
        f"<dt>Identificador</dt><dd>{escape(view.channel_identity)}</dd></dl></div>"
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
        counted(len(rows), "oportunidad", "oportunidades"),
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
        journey_workspace = await TransactionJourneys(session).for_opportunity(
            actor, opportunity.id
        )
        journey_template = await JourneyTemplates(session).latest(actor)
        journey_properties = list(
            await session.scalars(
                select(Property)
                .where(Property.organization_id == actor.organization_id)
                .order_by(Property.name)
            )
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

    covered = opportunity.stage not in QUALIFIED_OR_BEYOND or (
        opportunity.responsible_advisor_id is not None
        and (
            (pending is not None and not overdue)
            or (pending is None and exception is not None)
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
        pending_labels = ", ".join(criterion_label(name) for name in snapshot.pending)
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
        + _journey_card(
            opportunity,
            actor,
            journey_workspace,
            journey_template,
            journey_properties,
        )
        + _history_card(transitions)
        + "</div>"
    )
    action_rail = (
        '<aside class="workspace-panel sticky-rail" aria-label="Acciones permitidas">'
        "<h2>Acciones</h2>"
        + _stage_card(opportunity, actor)
        + _assignment_card(opportunity, actor, advisors, advisor_names, assignments)
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
    "template-borrador": "Se preparó el template de compra para revisión.",
    "template-aprobado": "Se aprobó el template de compra.",
    "tramite-iniciado": "Se inició el trámite de compra sin cambiar la etapa comercial.",
    "hito": "Se guardó el estado confirmado del hito.",
    "perfil-compra": "Se guardó el perfil de compra confirmado.",
    "datos-venta": "Se guardaron los datos de venta confirmados.",
    "tramite-concluido": "Se registró el resultado de la Jornada.",
}


ORIGIN_LABELS = {
    OpportunityOriginSource.WHATSAPP_INBOUND.value: "Mensaje entrante de WhatsApp",
    OpportunityOriginSource.MESSAGING_INBOUND.value: "Mensaje entrante de red social",
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
            '<h3>Pendiente</h3><div class="criteria-grid">' + pending_items + "</div>"
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
    return f"""<details class="outcome-disclosure">
<summary>{escape(form.heading)}</summary><div class="outcome-body">{hint}
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
{escape(form.button)}</button></div></form></div></details>"""


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


def _form_value(value: object | None) -> str:
    return "" if value is None else str(value)


def _not_provided(name: str, states: dict[str, str]) -> str:
    checked = " checked" if states.get(name) == "NotProvided" else ""
    return (
        f'<label class="checkbox"><input type="checkbox" name="np_{escape(name)}" '
        f'value="1"{checked}> No proporcionado</label>'
    )


def _journey_card(
    opportunity: Opportunity,
    actor: Actor,
    workspace: JourneyWorkspace | None,
    template: TransactionJourneyTemplateVersion | None,
    properties: list[Property],
) -> str:
    heading = '<div class="card"><h2>Trámite y datos de venta</h2>'
    if opportunity.kind != OpportunityKind.DEMAND.value:
        return (
            heading
            + empty("La primera Jornada está disponible sólo para procesos de compra.")
            + "</div>"
        )
    if workspace is None:
        if template is None:
            controls = (
                f'<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/template">'
                f"{command_field()}<div class='actions'><button type='submit'>"
                "Preparar template de compra para revisión</button></div></form>"
                if actor.is_administrator
                else flash(
                    "Un administrador debe preparar y aprobar el template de compra.",
                    "warn",
                )
            )
            return (
                heading
                + empty(
                    "Todavía no hay un template de compra.",
                    "Prepararlo no inicia ningún trámite ni envía mensajes.",
                )
                + controls
                + "</div>"
            )
        plan = "".join(
            f"<li>{escape(item['name'])} · {escape(item['responsibility'])}</li>"
            for item in template.plan
        )
        review = (
            f"<p><strong>Template v{template.version}: {escape(template.name)}</strong> "
            f"{tag('Aprobado' if template.state == 'Approved' else 'Borrador', 'ok' if template.state == 'Approved' else 'warn')}</p>"
            f"<ol>{plan}</ol>"
        )
        if template.state == "Draft":
            controls = (
                f'<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/template/{template.id}/aprobar">'
                f"{command_field()}<div class='actions'><button type='submit'>"
                "Aprobar este template después de revisarlo</button></div></form>"
                if actor.is_administrator
                else flash("El template todavía no está aprobado.", "warn")
            )
        else:
            controls = (
                f'<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/iniciar">'
                f"{command_field()}<div class='actions'><button type='submit'>"
                "Iniciar trámite de compra</button></div></form>"
            )
        return (
            heading
            + review
            + controls
            + '<p class="hint">Iniciar el trámite no marca la oportunidad como Ganada.</p>'
            + "</div>"
        )

    journey = workspace.journey
    milestone_rows = "".join(
        f"""<li class="card"><strong>{milestone.sequence}. {escape(milestone.name)}</strong>
<p class="hint">Responsable: {escape(milestone.responsibility)} · Estado actual:
{escape(MILESTONE_STATE_LABELS[milestone.state])}</p>
<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/hitos/{milestone.id}">
{command_field()}<div class="grid">
<label>Estado<select name="estado" required>{options(tuple(MILESTONE_STATE_LABELS), milestone.state, MILESTONE_STATE_LABELS)}</select></label>
<label>Evidencia<input name="evidencia" maxlength="500" value="{escape(milestone.evidence or "")}"></label>
<label>Motivo<input name="motivo" maxlength="500" value="{escape(milestone.reason or "")}"></label>
<label>Vence<input type="datetime-local" name="vence" value="{escape(datetime_input_value(milestone.due_at) if milestone.due_at else "")}"></label>
</div><div class="actions"><button type="submit">Guardar hito</button></div></form></li>"""
        for milestone in workspace.milestones
    )
    profile = workspace.profile
    profile_form = f"""<details><summary>Perfil de compra</summary>
<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/perfil">
{command_field()}<div class="grid">
<label>Año de nacimiento<input type="number" name="birth_year" min="1900" max="2100" value="{escape(_form_value(profile.birth_year))}">{_not_provided("birth_year", profile.field_states)}</label>
<label>Ingreso mensual individual<input type="number" step="0.01" min="0" name="monthly_income" value="{escape(_form_value(profile.monthly_income))}">{_not_provided("monthly_income", profile.field_states)}</label>
<label>Moneda del ingreso<input name="income_currency" maxlength="3" value="{escape(_form_value(profile.income_currency))}"></label>
<label>Adultos en el hogar<input type="number" min="1" name="adults" value="{escape(_form_value(profile.adults))}">{_not_provided("adults", profile.field_states)}</label>
<label>Número de hijos<input type="number" min="0" name="children" value="{escape(_form_value(profile.children))}">{_not_provided("children", profile.field_states)}</label>
<label>Dependientes financieros<input type="number" min="0" name="financial_dependants" value="{escape(_form_value(profile.financial_dependants))}">{_not_provided("financial_dependants", profile.field_states)}</label>
<label>Co-compradores<input type="number" min="0" name="co_buyers" value="{escape(_form_value(profile.co_buyers))}">{_not_provided("co_buyers", profile.field_states)}</label>
<label>Número de compra de vivienda<input type="number" min="1" name="home_purchase_number" value="{escape(_form_value(profile.home_purchase_number))}">{_not_provided("home_purchase_number", profile.field_states)}</label>
<label>Forma de pago<select name="payment_path"><option value="">Sin capturar</option>{options(("Cash", "Credit", "Combined"), profile.payment_path or "", {"Cash": "Contado", "Credit": "Crédito", "Combined": "Combinado"})}</select>{_not_provided("payment_path", profile.field_states)}</label>
<label>Institución o modalidad<input name="financing_modality" maxlength="200" value="{escape(_form_value(profile.financing_modality))}">{_not_provided("financing_modality", profile.field_states)}</label>
<label>Enganche disponible<input type="number" step="0.01" min="0" name="down_payment" value="{escape(_form_value(profile.down_payment))}"></label>
<label>Moneda del enganche<input name="down_payment_currency" maxlength="3" value="{escape(_form_value(profile.down_payment_currency))}"></label>
<label>Pago mensual objetivo<input type="number" step="0.01" min="0" name="target_monthly_payment" value="{escape(_form_value(profile.target_monthly_payment))}"></label>
<label>Moneda del pago objetivo<input name="target_payment_currency" maxlength="3" value="{escape(_form_value(profile.target_payment_currency))}"></label>
<label>Preaprobación<select name="preapproval_state"><option value="">Sin capturar</option>{options(("NotStarted", "InProgress", "Preapproved", "Denied", "NotApplicable"), profile.preapproval_state or "", {"NotStarted": "No iniciada", "InProgress": "En trámite", "Preapproved": "Preaprobada", "Denied": "Negada", "NotApplicable": "No aplica"})}</select>{_not_provided("preapproval_state", profile.field_states)}</label>
</div><div class="actions"><button type="submit">Guardar perfil confirmado</button></div></form></details>"""
    sale = workspace.sale
    property_options = '<option value="">Selecciona una propiedad</option>' + "".join(
        f'<option value="{row.id}"{" selected" if row.id == sale.property_uuid else ""}>{escape(row.name)} · {escape(row.property_key)}</option>'
        for row in properties
    )
    sale_form = f"""<details open><summary>Datos de venta</summary>
<p class="hint">Al seleccionar la propiedad, Product reutiliza sus datos aprobados del catálogo.</p>
<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/venta">
{command_field()}<div class="grid">
<label>Propiedad<select name="property_uuid">{property_options}</select></label>
<label>Tipo de propiedad<input name="property_type" maxlength="80" value="{escape(_form_value(sale.property_type))}"></label>
<label>Municipio<input name="municipality" maxlength="120" value="{escape(_form_value(sale.municipality))}"></label>
<label>Colonia<input name="colonia" maxlength="160" value="{escape(_form_value(sale.colonia))}">{_not_provided("colonia", sale.field_states)}</label>
<label>Fecha de publicación<input type="date" name="publication_date" value="{escape(_form_value(sale.publication_date))}">{_not_provided("publication_date", sale.field_states)}</label>
<label>Fecha de cierre<input type="date" name="completion_date" value="{escape(_form_value(sale.completion_date))}"></label>
<label>Precio publicado<input type="number" step="0.01" min="0" name="published_price" value="{escape(_form_value(sale.published_price))}">{_not_provided("published_price", sale.field_states)}</label>
<label>Moneda publicada<input name="published_currency" maxlength="3" value="{escape(_form_value(sale.published_currency))}"></label>
<label>Valor de avalúo<input type="number" step="0.01" min="0" name="appraisal_value" value="{escape(_form_value(sale.appraisal_value))}">{_not_provided("appraisal_value", sale.field_states)}</label>
<label>Moneda del avalúo<input name="appraisal_currency" maxlength="3" value="{escape(_form_value(sale.appraisal_currency))}"></label>
<label>Precio pagado<input type="number" step="0.01" min="0" name="paid_price" value="{escape(_form_value(sale.paid_price))}"></label>
<label>Moneda pagada<input name="paid_currency" maxlength="3" value="{escape(_form_value(sale.paid_currency))}"></label>
<label>Terreno m²<input type="number" step="0.01" min="0" name="land_area_sqm" value="{escape(_form_value(sale.land_area_sqm))}">{_not_provided("land_area_sqm", sale.field_states)}</label>
<label>Construcción m²<input type="number" step="0.01" min="0" name="construction_area_sqm" value="{escape(_form_value(sale.construction_area_sqm))}">{_not_provided("construction_area_sqm", sale.field_states)}</label>
<label>Recámaras<input type="number" min="0" name="bedrooms" value="{escape(_form_value(sale.bedrooms))}">{_not_provided("bedrooms", sale.field_states)}</label>
<label>Baños<input type="number" step="0.5" min="0" name="bathrooms" value="{escape(_form_value(sale.bathrooms))}">{_not_provided("bathrooms", sale.field_states)}</label>
<label>Estacionamientos<input type="number" min="0" name="parking_spaces" value="{escape(_form_value(sale.parking_spaces))}">{_not_provided("parking_spaces", sale.field_states)}</label>
<label>Año de construcción<input type="number" min="1800" max="2100" name="construction_year" value="{escape(_form_value(sale.construction_year))}">{_not_provided("construction_year", sale.field_states)}</label>
<label>Condición<select name="property_condition"><option value="">Sin capturar</option>{options(("New", "Excellent", "Good", "NeedsImprovement"), sale.property_condition or "", {"New": "Nueva", "Excellent": "Excelente", "Good": "Buena", "NeedsImprovement": "Requiere mejoras"})}</select>{_not_provided("property_condition", sale.field_states)}</label>
</div><div class="actions"><button type="submit">Guardar datos confirmados</button></div></form></details>"""
    conclude = ""
    if actor.is_administrator and journey.state == JourneyState.ACTIVE.value:
        conclude = f"""<details><summary>Concluir Jornada</summary>
<form method="post" action="/crm/oportunidades/{opportunity.id}/tramite/concluir">{command_field()}
<div class="grid"><label>Resultado<select name="estado"><option value="Completed">Completada</option><option value="Cancelled">Cancelada</option></select></label>
<label>Motivo de cancelación<input name="motivo" maxlength="500"></label></div>
<div class="actions"><button type="submit">Confirmar resultado</button></div></form></details>"""
    return (
        heading
        + f"<p>{tag('Activa' if journey.state == 'Active' else journey.state, 'ok')}</p>"
        + profile_form
        + sale_form
        + "<h3>Hitos confirmados por personas</h3><ol class='plain'>"
        + milestone_rows
        + "</ol>"
        + conclude
        + "</div>"
    )


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


def _form_text(form: FormData, name: str) -> str | None:
    value = form.get(name, "")
    clean = str(value).strip()
    return clean or None


def _form_int(form: FormData, name: str) -> int | None:
    value = _form_text(form, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise InvalidTransition(f"«{name}» debe ser un número entero.") from exc


def _form_decimal(form: FormData, name: str) -> Decimal | None:
    value = _form_text(form, name)
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise InvalidTransition(f"«{name}» debe ser un importe válido.") from exc


def _form_date(form: FormData, name: str) -> date | None:
    value = _form_text(form, name)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidTransition(f"«{name}» debe ser una fecha válida.") from exc


def _currency(form: FormData, name: str) -> str | None:
    value = _form_text(form, name)
    if value is None:
        return None
    clean = value.upper()
    if len(clean) != 3 or not clean.isalpha():
        raise InvalidTransition("La moneda debe usar tres letras, por ejemplo MXN.")
    return clean


def _field_states(
    form: FormData, fields: frozenset[str], values: dict[str, object]
) -> dict[str, str]:
    states: dict[str, str] = {}
    for name in fields:
        if form.get(f"np_{name}") == "1":
            states[name] = "NotProvided"
            if name in values:
                values[name] = None
        elif values.get(name) is not None:
            states[name] = "Provided"
        else:
            states[name] = "NotCaptured"
    return states


@router.post("/oportunidades/{opportunity_id}/tramite/template")
async def create_journey_template(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            await JourneyTemplates(session).create_draft(actor)
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "template-borrador")


@router.post("/oportunidades/{opportunity_id}/tramite/template/{template_id}/aprobar")
async def approve_journey_template(
    request: Request,
    opportunity_id: uuid.UUID,
    template_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            await JourneyTemplates(session).approve(actor, template_id)
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "template-aprobado")


@router.post("/oportunidades/{opportunity_id}/tramite/iniciar")
async def start_journey(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    async with request.app.state.database.session_scope() as session:
        try:
            await TransactionJourneys(session).start(actor, opportunity_id)
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "tramite-iniciado")


@router.post("/oportunidades/{opportunity_id}/tramite/hitos/{milestone_id}")
async def update_journey_milestone(
    request: Request,
    opportunity_id: uuid.UUID,
    milestone_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    state = str(form.get("estado", ""))
    if state not in MILESTONE_STATE_LABELS:
        return _redirect_error(opportunity_id, "Estado de hito desconocido.")
    due_at = parse_datetime_input(str(form.get("vence", "")))
    async with request.app.state.database.session_scope() as session:
        try:
            await TransactionJourneys(session).update_milestone(
                actor,
                milestone_id,
                state=MilestoneState(state),
                evidence=_form_text(form, "evidencia"),
                reason=_form_text(form, "motivo"),
                due_at=due_at,
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "hito")


@router.post("/oportunidades/{opportunity_id}/tramite/perfil")
async def update_purchase_profile(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    try:
        values: dict[str, object] = {
            "birth_year": _form_int(form, "birth_year"),
            "monthly_income": _form_decimal(form, "monthly_income"),
            "income_currency": _currency(form, "income_currency"),
            "adults": _form_int(form, "adults"),
            "children": _form_int(form, "children"),
            "financial_dependants": _form_int(form, "financial_dependants"),
            "co_buyers": _form_int(form, "co_buyers"),
            "home_purchase_number": _form_int(form, "home_purchase_number"),
            "payment_path": _form_text(form, "payment_path"),
            "financing_modality": _form_text(form, "financing_modality"),
            "down_payment": _form_decimal(form, "down_payment"),
            "down_payment_currency": _currency(form, "down_payment_currency"),
            "target_monthly_payment": _form_decimal(form, "target_monthly_payment"),
            "target_payment_currency": _currency(form, "target_payment_currency"),
            "preapproval_state": _form_text(form, "preapproval_state"),
        }
        states = _field_states(form, PROFILE_FIELDS, values)
    except CommercialError as exc:
        return _redirect_error(opportunity_id, exc.message)
    async with request.app.state.database.session_scope() as session:
        try:
            await MarketRecords(session).update_profile(
                actor,
                opportunity_id,
                values=values,
                field_states=states,
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "perfil-compra")


@router.post("/oportunidades/{opportunity_id}/tramite/venta")
async def update_market_sale(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    try:
        property_raw = _form_text(form, "property_uuid")
        values: dict[str, object] = {
            "property_uuid": uuid.UUID(property_raw) if property_raw else None,
            "property_type": _form_text(form, "property_type"),
            "municipality": _form_text(form, "municipality"),
            "colonia": _form_text(form, "colonia"),
            "land_area_sqm": _form_decimal(form, "land_area_sqm"),
            "construction_area_sqm": _form_decimal(form, "construction_area_sqm"),
            "bedrooms": _form_int(form, "bedrooms"),
            "bathrooms": _form_decimal(form, "bathrooms"),
            "parking_spaces": _form_int(form, "parking_spaces"),
            "construction_year": _form_int(form, "construction_year"),
            "property_condition": _form_text(form, "property_condition"),
            "publication_date": _form_date(form, "publication_date"),
            "completion_date": _form_date(form, "completion_date"),
            "published_price": _form_decimal(form, "published_price"),
            "published_currency": _currency(form, "published_currency"),
            "appraisal_value": _form_decimal(form, "appraisal_value"),
            "appraisal_currency": _currency(form, "appraisal_currency"),
            "paid_price": _form_decimal(form, "paid_price"),
            "paid_currency": _currency(form, "paid_currency"),
        }
        for amount, currency in (
            ("published_price", "published_currency"),
            ("appraisal_value", "appraisal_currency"),
            ("paid_price", "paid_currency"),
        ):
            if (values[amount] is None) != (values[currency] is None):
                raise InvalidTransition(
                    "Cada importe debe incluir su moneda y cada moneda su importe."
                )
        states = _field_states(form, SALE_FIELDS, values)
        # Blank catalog facts do not overwrite Product truth; selecting the
        # Property lets the domain reuse them automatically.
        if values["property_uuid"] is not None:
            for name in (
                "property_type",
                "municipality",
                "colonia",
                "land_area_sqm",
                "construction_area_sqm",
                "bedrooms",
                "bathrooms",
                "parking_spaces",
                "construction_year",
            ):
                if values[name] is None and states[name] == "NotCaptured":
                    values.pop(name)
    except (CommercialError, ValueError) as exc:
        message = (
            exc.message
            if isinstance(exc, CommercialError)
            else "Propiedad desconocida."
        )
        return _redirect_error(opportunity_id, message)
    async with request.app.state.database.session_scope() as session:
        try:
            await MarketRecords(session).update_sale(
                actor,
                opportunity_id,
                values=values,
                field_states=states,
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "datos-venta")


@router.post("/oportunidades/{opportunity_id}/tramite/concluir")
async def conclude_journey(
    request: Request,
    opportunity_id: uuid.UUID,
    actor: Actor = Depends(require_actor),
) -> RedirectResponse:
    form = await request.form()
    requested = str(form.get("estado", ""))
    if requested not in {JourneyState.COMPLETED.value, JourneyState.CANCELLED.value}:
        return _redirect_error(opportunity_id, "Resultado de Jornada desconocido.")
    async with request.app.state.database.session_scope() as session:
        try:
            workspace = await TransactionJourneys(session).for_opportunity(
                actor, opportunity_id
            )
            if workspace is None:
                raise MissingEvidence("No hay un trámite iniciado.")
            await TransactionJourneys(session).conclude(
                actor,
                workspace.journey.id,
                state=JourneyState(requested),
                reason=_form_text(form, "motivo"),
            )
            await session.commit()
        except CommercialError as exc:
            await session.rollback()
            return _redirect_error(opportunity_id, exc.message)
    return _redirect(opportunity_id, "tramite-concluido")


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
        counted(len(rows), "contacto", "contactos"),
        (
            "Nombre",
            "Canales",
            "Oportunidades abiertas",
            "Última actividad",
            "Restricciones",
        ),
        body,
        empty_message="No hay contactos que coincidan.",
        empty_hint="Un contacto se crea con el primer mensaje verificado de un canal conectado.",
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
        f"<tr><td>{escape(row.identity)}</td>"
        f"<td>{escape(CUSTOMER_CHANNEL_LABELS.get(row.channel, row.channel))}</td>"
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
            counted(len(identities), "identidad", "identidades"),
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
        counted(
            len(queue),
            "oportunidad sin asesor responsable",
            "oportunidades sin asesor responsable",
        ),
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

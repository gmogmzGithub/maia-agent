"""The human-operation surfaces: Team, Absences, Specialists, Calendar, Alerts.

Server-rendered, Mexican Spanish, no JavaScript required. Every screen reads
through a domain module and every mutation goes through one, so this file holds
presentation and nothing else — no transaction, no invariant, no idempotency
rule, and no authorization decision beyond resolving who is asking.

What these surfaces are *for* is making four things impossible to miss at a
glance, because each one is a way the operation loses a customer:

* who is answering a conversation right now, and whether it is Maia;
* who is responsible, which is not the same as who specialises in the property;
* which visit is actually Confirmed, as opposed to awaiting review;
* what is waiting for a human, and for how long.

Two presentation rules are deliberate rather than incidental. A control never
looks successful before an authoritative confirmation: the reschedule form only
offers starts that the Advisor's own calendar returned a moment ago, and a
refusal is rendered as the named reason rather than a generic failure. And an
Advisor sees the same pages as an Administrator with the *forms* removed, not
the information — knowing that a colleague is away is how a human decides
whether to wait or escalate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from realestate.api.operator import (
    command_field,
    command_key,
    refusal,
    require_actor,
    shell,
    tag,
)
from realestate.api.ui import (
    datetime_input_value,
    empty,
    escape,
    flash,
    local,
    options,
    parse_datetime_input,
    relative,
    table,
)
from realestate.db.models import (
    AdvisorAbsence,
    Appointment,
    AppointmentAttendance,
    AppointmentReminder,
    AppointmentStatus,
    HandlingMode,
    HandoffStatus,
    HumanHandoffRequest,
    MemberRole,
    NextActionKind,
    OrganizationMember,
    PropertyExpertRole,
)
from realestate.domain.commercial.actors import Actor, CommercialError
from realestate.domain.commercial.handling import (
    MODE_LABELS,
    ConversationHandling,
    HandlingSnapshot,
    HumanReply,
    ReleaseHandling,
    TakeHandling,
)
from realestate.domain.commercial.handoff import (
    SOURCE_LABELS,
    AcknowledgeHandoff,
    HumanHandoff,
)
from realestate.domain.commercial.organization import ROLE_LABELS
from realestate.domain.commercial.team import (
    EXPERT_ROLE_LABELS,
    AddMember,
    ExpertDesignationView,
    TeamMemberView,
    DesignateExpert,
    EndAbsence,
    RevokeExpert,
    SetDefaultAdvisor,
    SetMemberActive,
    StartAbsence,
    TeamAdministration,
    UpdateMember,
)
from realestate.domain.internal_alerts import (
    ALERT_KIND_LABELS,
    ALERT_STATUS_LABELS,
    InternalAlerts,
)
from realestate.domain.scheduling.advisors import (
    AdvisorScheduling,
    SlotQuery,
    SlotsUnavailable,
)
from realestate.domain.scheduling.appointments import (
    ATTENDANCE_LABELS,
    STATUS_LABELS as VISIT_STATUS_LABELS,
    Appointments,
    CancelVisit,
    RecordVisitOutcome,
    RescheduleVisit,
    VisitRefused,
)
from realestate.domain.scheduling.reminders import (
    OUTCOME_LABELS as REMINDER_OUTCOME_LABELS,
    REMINDER_KIND_LABELS,
    AppointmentReminders,
)

router = APIRouter(prefix="/crm", tags=["crm"])

TEAM = "/crm/equipo"
AGENDA = "/crm/agenda"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _scheduling(request: Request, session: AsyncSession) -> AdvisorScheduling:
    policy = request.app.state.appointment_policy
    return AdvisorScheduling(session, request.app.state.calendars, policy.scheduling)


def _visits(request: Request, session: AsyncSession) -> Appointments:
    policy = request.app.state.appointment_policy
    return Appointments(
        session,
        _scheduling(request, session),
        schedule=policy.schedule,
        visit_minutes=policy.visit_minutes,
        day_of_reminder_hour=policy.day_of_reminder_hour,
        event_title=policy.event_title,
    )


def _redirect(path: str, *, saved: str = "", error: str = "") -> RedirectResponse:
    query = ""
    if saved:
        query = f"?guardado={saved}"
    elif error:
        query = f"?error={error}"
    return RedirectResponse(url=f"{path}{query}", status_code=303)


# ------------------------------------------------------------------ Equipo ---


@router.get("/equipo", response_class=HTMLResponse)
async def team(
    request: Request,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """The team, with why each person can or cannot take new work."""
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        views = await TeamAdministration(session).team(actor, now=moment)

    rows = "".join(_member_row(view, actor, moment) for view in views)
    listing = table(
        f"{len(views)} integrante(s)",
        (
            "Persona",
            "Rol",
            "Puede recibir trabajo",
            "Carga actual",
            "Ausencias",
            *(("Acciones",) if actor.is_administrator else ()),
        ),
        rows,
        empty_message="Todavía no hay integrantes en la organización.",
        empty_hint=(
            "Da de alta al primer asesor con el formulario de abajo."
            if actor.is_administrator
            else "Pide a un administrador que dé de alta al equipo."
        ),
    )
    content = (
        flash(_TEAM_FLASH.get(guardado))
        + (
            f'<div class="error" role="alert">{escape(error)}</div>'
            if error
            else ""
        )
        + '<p class="hint">Un asesor sólo puede recibir citas si tiene '
        "calendario configurado y no está ausente. Ser especialista de una "
        "propiedad no lo vuelve responsable de una oportunidad.</p>"
        + listing
        + (_add_member_form() if actor.is_administrator else "")
        + f'<p><a href="{TEAM}/ausencias">Ver ausencias</a> · '
        f'<a href="{TEAM}/especialistas">Ver especialistas por propiedad</a></p>'
    )
    return shell(actor, "Equipo", content, active=TEAM)


_TEAM_FLASH = {
    "alta": "Se dio de alta a la persona.",
    "cambio": "Se guardaron los cambios.",
    "estado": "Se actualizó el acceso de la persona.",
    "predeterminado": "Se actualizó el asesor predeterminado.",
    "ausencia": "Se registró la ausencia.",
    "fin-ausencia": "Se terminó la ausencia.",
    "especialista": "Se actualizó el especialista de la propiedad.",
}


def _member_row(view: TeamMemberView, actor: Actor, moment: datetime) -> str:
    member = view.member
    marks: list[str] = []
    if not member.active:
        marks.append(tag("Dado de baja", "bad"))
    elif view.absent:
        assert view.current_absence is not None
        marks.append(
            tag("Ausente", "warn")
            + '<br><span class="muted">Regresa el '
            + escape(local(view.current_absence.ends_at))
            + "</span>"
        )
    elif view.can_receive_appointments:
        marks.append(tag("Sí", "ok"))
    elif not member.advises:
        marks.append(tag("No recibe oportunidades", "warn"))
    else:
        marks.append(
            tag("Falta calendario", "bad")
            + '<br><span class="muted">Sin calendario autoritativo no se '
            "pueden confirmar visitas.</span>"
        )
    if member.is_default_advisor:
        marks.append(tag("Predeterminado", "ok"))
    if not member.telegram_chat_id:
        marks.append(
            '<span class="muted">Sin canal de alertas</span>'
        )

    upcoming = "".join(
        f"<li>{escape(local(absence.starts_at))} → "
        f"{escape(local(absence.ends_at))}</li>"
        for absence in view.upcoming_absences
    )
    absences = f"<ul>{upcoming}</ul>" if upcoming else "—"

    cells = (
        f"<tr><td><strong>{escape(member.display_name)}</strong><br>"
        f"<span class='muted'>{escape(member.login)}</span></td>"
        f"<td>{escape(ROLE_LABELS[member.role])}</td>"
        f"<td>{'<br>'.join(marks)}</td>"
        f"<td>{view.open_opportunities} oportunidad(es)<br>"
        f"<span class='muted'>{view.future_appointments} cita(s) próxima(s)</span></td>"
        f"<td>{absences}</td>"
    )
    if actor.is_administrator:
        cells += f"<td>{_member_actions(view)}</td>"
    return cells + "</tr>"


def _member_actions(view: TeamMemberView) -> str:
    member = view.member
    return f"""<form method="post" action="{TEAM}/miembros/{member.id}">
{command_field()}
<div class="field"><label>Nombre visible
<input name="nombre" value="{escape(member.display_name)}" maxlength="200"></label></div>
<div class="field"><label>Calendario autoritativo
<input name="calendario" value="{escape(member.calendar_id or '')}" maxlength="200"
 placeholder="correo del calendario"></label></div>
<div class="field"><label>Chat de alertas (Telegram)
<input name="alertas" value="{escape(member.telegram_chat_id or '')}" maxlength="40"></label></div>
<div class="actions"><button type="submit">Guardar</button></div>
</form>
<form method="post" action="{TEAM}/miembros/{member.id}/estado">
{command_field()}
<input type="hidden" name="activo" value="{'0' if member.active else '1'}">
<div class="actions"><button type="submit" class="quiet">
{'Dar de baja' if member.active else 'Reactivar'}</button></div>
</form>""" + (
        ""
        if member.is_default_advisor or not (member.active and member.advises)
        else f"""<form method="post" action="{TEAM}/miembros/{member.id}/predeterminado">
{command_field()}
<div class="actions"><button type="submit" class="quiet">
Hacer asesor predeterminado</button></div>
</form>"""
    )


def _add_member_form() -> str:
    return f"""<form class="card" method="post" action="{TEAM}/miembros">
<h2>Dar de alta a una persona</h2>
<p class="hint">El usuario debe existir en las credenciales de la operación.
Dar de alta aquí le otorga el permiso; no crea una contraseña.</p>
{command_field()}
<div class="grid">
<div class="field"><label for="m-login">Usuario
<input id="m-login" name="usuario" required maxlength="120"></label></div>
<div class="field"><label for="m-nombre">Nombre visible
<input id="m-nombre" name="nombre" required maxlength="200"></label></div>
<div class="field"><label for="m-rol">Rol
<select id="m-rol" name="rol">
{options(
    (MemberRole.ADVISOR.value, MemberRole.ADMINISTRATOR.value),
    MemberRole.ADVISOR.value,
    ROLE_LABELS,
)}
</select></label></div>
<div class="field"><label for="m-cal">Calendario autoritativo
<input id="m-cal" name="calendario" maxlength="200"></label></div>
<div class="field"><label for="m-alertas">Chat de alertas (Telegram)
<input id="m-alertas" name="alertas" maxlength="40"></label></div>
</div>
<div class="field"><label class="check"><input type="checkbox" name="asesora" value="1" checked>
Puede recibir oportunidades y citas</label></div>
<div class="actions"><button type="submit">Dar de alta</button></div>
</form>"""


@router.post("/equipo/miembros")
async def add_member(
    request: Request, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    role = (
        MemberRole.ADMINISTRATOR
        if str(form.get("rol")) == MemberRole.ADMINISTRATOR.value
        else MemberRole.ADVISOR
    )
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                AddMember(
                    command_key=command_key(form, "team-add"),
                    login=str(form.get("usuario", "")),
                    display_name=str(form.get("nombre", "")),
                    role=role,
                    advises=bool(form.get("asesora")),
                    calendar_id=str(form.get("calendario", "")),
                    telegram_chat_id=str(form.get("alertas", "")),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(TEAM, error=exc.message)
    return _redirect(TEAM, saved="alta")


@router.post("/equipo/miembros/{member_id}")
async def update_member(
    request: Request, member_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                UpdateMember(
                    command_key=command_key(form, "team-update"),
                    member_id=member_id,
                    display_name=str(form.get("nombre", "")),
                    calendar_id=str(form.get("calendario", "")),
                    telegram_chat_id=str(form.get("alertas", "")),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(TEAM, error=exc.message)
    return _redirect(TEAM, saved="cambio")


@router.post("/equipo/miembros/{member_id}/estado")
async def set_member_active(
    request: Request, member_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                SetMemberActive(
                    command_key=command_key(form, "team-active"),
                    member_id=member_id,
                    active=str(form.get("activo")) == "1",
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(TEAM, error=exc.message)
    return _redirect(TEAM, saved="estado")


@router.post("/equipo/miembros/{member_id}/predeterminado")
async def set_default_advisor(
    request: Request, member_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                SetDefaultAdvisor(
                    command_key=command_key(form, "team-default"),
                    member_id=member_id,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(TEAM, error=exc.message)
    return _redirect(TEAM, saved="predeterminado")


# ---------------------------------------------------------------- Ausencias ---


@router.get("/equipo/ausencias", response_class=HTMLResponse)
async def absences(
    request: Request,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        administration = TeamAdministration(session)
        rows = await administration.absences(actor, include_past=True, now=moment)
        members = {
            view.member.id: view.member
            for view in await administration.team(actor, now=moment)
        }

    def state(absence: AdvisorAbsence) -> str:
        if absence.cancelled_at is not None:
            return tag("Cancelada", "")
        if absence.covers(moment):
            return tag("En curso", "warn")
        if absence.ends_at <= moment:
            return tag("Terminada", "")
        return tag("Programada", "ok")

    listing = table(
        f"{len(rows)} ausencia(s)",
        (
            "Asesor",
            "Periodo",
            "Estado",
            "Motivo",
            *(("Acciones",) if actor.is_administrator else ()),
        ),
        "".join(
            f"<tr><td>{escape(members[row.advisor_id].display_name if row.advisor_id in members else '—')}</td>"
            f"<td>{escape(local(row.starts_at))}<br>→ {escape(local(row.ends_at))}</td>"
            f"<td>{state(row)}</td>"
            f"<td>{escape(row.reason or '—')}</td>"
            + (
                "<td>"
                + (
                    f"""<form method="post" action="{TEAM}/ausencias/{row.id}/terminar">
{command_field()}<div class="actions">
<button type="submit" class="quiet">Terminar ahora</button></div></form>"""
                    if actor.is_administrator
                    and row.cancelled_at is None
                    and row.ends_at > moment
                    else "—"
                )
                + "</td>"
                if actor.is_administrator
                else ""
            )
            + "</tr>"
            for row in rows
        ),
        empty_message="No hay ausencias registradas.",
        empty_hint=(
            "Registra una para excluir a un asesor de asignaciones nuevas."
            if actor.is_administrator
            else ""
        ),
    )
    advisors = [
        view.member
        for view in await _team_members(request, actor, moment)
        if view.member.active and view.member.advises
    ]
    content = (
        flash(_TEAM_FLASH.get(guardado))
        + (f'<div class="error" role="alert">{escape(error)}</div>' if error else "")
        + '<p class="hint">Una ausencia excluye al asesor de <strong>asignaciones '
        "y citas nuevas</strong>. No reasigna sus oportunidades ni cancela sus "
        "citas: eso se revisa a mano.</p>"
        + listing
        + (_absence_form(advisors) if actor.is_administrator else "")
        + f'<p><a href="{TEAM}">Volver al equipo</a></p>'
    )
    return shell(actor, "Ausencias", content, active=TEAM)


async def _team_members(
    request: Request, actor: Actor, moment: datetime
) -> list[TeamMemberView]:
    async with request.app.state.database.session_scope() as session:
        return await TeamAdministration(session).team(actor, now=moment)


def _absence_form(advisors: list[OrganizationMember]) -> str:
    if not advisors:
        return empty(
            "No hay asesores activos a los que registrar una ausencia.",
            "Da de alta a un asesor primero.",
        )
    starts = datetime_input_value(_now() + timedelta(days=1))
    ends = datetime_input_value(_now() + timedelta(days=2))
    labels = {member.id.hex: member.display_name for member in advisors}
    return f"""<form class="card" method="post" action="{TEAM}/ausencias">
<h2>Registrar una ausencia</h2>
{command_field()}
<div class="grid">
<div class="field"><label for="a-asesor">Asesor
<select id="a-asesor" name="asesor">
{options(tuple(labels), advisors[0].id.hex, labels)}
</select></label></div>
<div class="field"><label for="a-inicio">Inicia
<input id="a-inicio" type="datetime-local" name="inicio" value="{escape(starts)}" required>
</label></div>
<div class="field"><label for="a-fin">Termina
<input id="a-fin" type="datetime-local" name="fin" value="{escape(ends)}" required>
</label></div>
</div>
<div class="field"><label for="a-motivo">Motivo (interno)
<input id="a-motivo" name="motivo" maxlength="200"></label></div>
<div class="actions"><button type="submit">Registrar ausencia</button></div>
</form>"""


@router.post("/equipo/ausencias")
async def start_absence(
    request: Request, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    starts = parse_datetime_input(str(form.get("inicio", "")))
    ends = parse_datetime_input(str(form.get("fin", "")))
    path = f"{TEAM}/ausencias"
    if starts is None or ends is None:
        return _redirect(path, error="Revisa las fechas de la ausencia.")
    try:
        advisor_id = uuid.UUID(str(form.get("asesor", "")))
    except ValueError:
        return _redirect(path, error="Elige un asesor.")

    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                StartAbsence(
                    command_key=command_key(form, "absence-start"),
                    advisor_id=advisor_id,
                    starts_at=starts,
                    ends_at=ends,
                    reason=str(form.get("motivo", "")),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="ausencia")


@router.post("/equipo/ausencias/{absence_id}/terminar")
async def end_absence(
    request: Request, absence_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"{TEAM}/ausencias"
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                EndAbsence(
                    command_key=command_key(form, "absence-end"),
                    absence_id=absence_id,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="fin-ausencia")


# ------------------------------------------------------------ Especialistas ---


@router.get("/equipo/especialistas", response_class=HTMLResponse)
async def experts(
    request: Request,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        administration = TeamAdministration(session)
        directory = await administration.expert_directory(actor)
        advisors = [
            view.member
            for view in await administration.team(actor, now=moment)
            if view.member.active and view.member.advises
        ]

    rows = "".join(
        f"<tr><td><strong>{escape(view.property_name)}</strong><br>"
        f"<span class='muted'>{escape(view.property_key)}</span></td>"
        f"<td>{escape(view.primary.display_name) if view.primary else tag('Sin especialista', 'warn')}</td>"
        f"<td>{'<br>'.join(escape(member.display_name) for member in view.backups) or '—'}</td>"
        + (
            f"<td>{_expert_form(view, advisors)}</td>"
            if actor.is_administrator
            else ""
        )
        + "</tr>"
        for view in directory
    )
    listing = table(
        f"{len(directory)} propiedad(es)",
        (
            "Propiedad",
            "Especialista principal",
            "Suplentes",
            *(("Acciones",) if actor.is_administrator else ()),
        ),
        rows,
        empty_message="Todavía no hay propiedades activas.",
    )
    content = (
        flash(_TEAM_FLASH.get(guardado))
        + (f'<div class="error" role="alert">{escape(error)}</div>' if error else "")
        + '<p class="hint">El especialista de una propiedad recibe primero las '
        "oportunidades de esa propiedad. <strong>No es lo mismo que el asesor "
        "responsable</strong>: nombrar un especialista no cambia quién lleva una "
        "oportunidad que ya tiene responsable.</p>"
        + listing
        + f'<p><a href="{TEAM}">Volver al equipo</a></p>'
    )
    return shell(actor, "Especialistas por propiedad", content, active=TEAM)


def _expert_form(
    view: ExpertDesignationView, advisors: list[OrganizationMember]
) -> str:
    if not advisors:
        return "—"
    labels = {member.id.hex: member.display_name for member in advisors}
    roles = {
        PropertyExpertRole.PRIMARY.value: EXPERT_ROLE_LABELS[
            PropertyExpertRole.PRIMARY.value
        ],
        PropertyExpertRole.BACKUP.value: EXPERT_ROLE_LABELS[
            PropertyExpertRole.BACKUP.value
        ],
    }
    revoke = ""
    if view.primary is not None:
        revoke = f"""<form method="post"
 action="{TEAM}/especialistas/{view.property_uuid}/quitar">
{command_field()}
<input type="hidden" name="asesor" value="{view.primary.id.hex}">
<div class="actions"><button type="submit" class="quiet">
Quitar a {escape(view.primary.display_name)}</button></div></form>"""
    return f"""<form method="post" action="{TEAM}/especialistas/{view.property_uuid}">
{command_field()}
<div class="field"><label>Asesor
<select name="asesor">{options(tuple(labels), advisors[0].id.hex, labels)}</select>
</label></div>
<div class="field"><label>Papel
<select name="papel">{options(tuple(roles), PropertyExpertRole.PRIMARY.value, roles)}</select>
</label></div>
<div class="actions"><button type="submit">Designar</button></div>
</form>{revoke}"""


@router.post("/equipo/especialistas/{property_uuid}")
async def designate_expert(
    request: Request, property_uuid: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"{TEAM}/especialistas"
    try:
        advisor_id = uuid.UUID(str(form.get("asesor", "")))
    except ValueError:
        return _redirect(path, error="Elige un asesor.")
    role = (
        PropertyExpertRole.BACKUP
        if str(form.get("papel")) == PropertyExpertRole.BACKUP.value
        else PropertyExpertRole.PRIMARY
    )
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                DesignateExpert(
                    command_key=command_key(form, "expert-designate"),
                    property_uuid=property_uuid,
                    advisor_id=advisor_id,
                    role=role,
                    rank=0 if role is PropertyExpertRole.PRIMARY else 1,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="especialista")


@router.post("/equipo/especialistas/{property_uuid}/quitar")
async def revoke_expert(
    request: Request, property_uuid: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"{TEAM}/especialistas"
    try:
        advisor_id = uuid.UUID(str(form.get("asesor", "")))
    except ValueError:
        return _redirect(path, error="Elige un asesor.")
    async with request.app.state.database.session_scope() as session:
        try:
            await TeamAdministration(session).record(
                actor,
                RevokeExpert(
                    command_key=command_key(form, "expert-revoke"),
                    property_uuid=property_uuid,
                    advisor_id=advisor_id,
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="especialista")


# ------------------------------------------------------------------- Agenda ---


@router.get("/agenda", response_class=HTMLResponse)
async def agenda(
    request: Request,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """Visits this operator owns or conducts, and what each one still needs."""
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        visits = _visits(request, session)
        upcoming = await visits.agenda(actor, since=moment - timedelta(days=14))
        reminders = AppointmentReminders(
            session,
            request.app.state.appointment_policy.schedule,
            day_of_hour=request.app.state.appointment_policy.day_of_reminder_hour,
        )
        members = {
            view.member.id: view.member
            for view in await TeamAdministration(session).team(actor, now=moment)
        }
        rows = []
        for visit in upcoming:
            rows.append(
                (
                    visit,
                    await reminders.for_appointment(visit.id),
                )
            )
        unowned = (
            await visits.unowned(actor) if actor.is_administrator else []
        )

    listing = table(
        f"{len(rows)} cita(s)",
        ("Cuándo", "Propiedad", "Responsable", "Estado", "Recordatorios", "Resultado"),
        "".join(_visit_row(visit, notices, members, moment) for visit, notices in rows),
        empty_message="No hay citas en este periodo.",
        empty_hint="Maia agenda las visitas desde la conversación de WhatsApp.",
    )
    unowned_block = ""
    if unowned:
        unowned_block = (
            "<h2>Citas sin asesor responsable</h2>"
            '<p class="hint">Se agendaron antes de que las citas tuvieran '
            "responsable. No se les asignó nadie automáticamente: decide quién "
            "las atiende.</p>"
            + table(
                f"{len(unowned)} cita(s) por revisar",
                ("Cuándo", "Referencia", "Estado"),
                "".join(
                    f"<tr><td>{escape(local(row.starts_at))}</td>"
                    f"<td>{escape(row.reference)}</td>"
                    f"<td>{escape(VISIT_STATUS_LABELS[row.status])}</td></tr>"
                    for row in unowned
                ),
            )
        )
    content = (
        flash(_AGENDA_FLASH.get(guardado))
        + (f'<div class="error" role="alert">{escape(error)}</div>' if error else "")
        + '<p class="hint">Sólo una cita <strong>confirmada</strong> es una cita. '
        "Una cita en revisión no se le confirmó al cliente.</p>"
        + listing
        + unowned_block
    )
    return shell(actor, "Agenda de visitas", content, active=AGENDA)


_AGENDA_FLASH = {
    "resultado": "Se registró el resultado de la visita.",
    "reagendada": "La cita quedó reagendada.",
    "cancelada": "La cita quedó cancelada.",
}


def _visit_row(
    visit: Appointment,
    notices: list[AppointmentReminder],
    members: dict[uuid.UUID, OrganizationMember],
    moment: datetime,
) -> str:
    # Both are nullable: a pre-Stage-3 row has no owner, and a conducting
    # expert is set only when the visit is explicitly somebody else's to run.
    owner = members.get(visit.advisor_id) if visit.advisor_id else None
    conducting = (
        members.get(visit.conducting_advisor_id)
        if visit.conducting_advisor_id
        else None
    )
    who = escape(owner.display_name) if owner else tag("Sin asesor", "bad")
    if conducting is not None and conducting.id != visit.advisor_id:
        who += (
            '<br><span class="muted">Conduce la visita: '
            + escape(conducting.display_name)
            + "</span>"
        )
    state = tag(
        VISIT_STATUS_LABELS[visit.status],
        "ok"
        if visit.status == AppointmentStatus.CONFIRMED.value
        else "warn"
        if visit.status
        in (
            AppointmentStatus.NEEDS_REVIEW.value,
            AppointmentStatus.RESCHEDULED.value,
        )
        else "bad",
    )
    reminder_cell = (
        "<br>".join(
            f"{escape(REMINDER_KIND_LABELS[notice.kind])}: "
            + escape(
                REMINDER_OUTCOME_LABELS.get(
                    notice.outcome or "", notice.outcome or "Pendiente"
                )
            )
            for notice in notices
        )
        or "—"
    )
    if visit.attendance is not None:
        result = (
            tag(
                ATTENDANCE_LABELS[visit.attendance],
                "ok"
                if visit.attendance == AppointmentAttendance.ATTENDED.value
                else "warn",
            )
            + (
                f'<br><span class="muted">{escape(visit.visit_outcome)}</span>'
                if visit.visit_outcome
                else ""
            )
            + (
                "<br>" + tag("Reagendado autorizado", "warn")
                if visit.reschedule_invitation_authorized
                else ""
            )
        )
    elif (
        visit.status == AppointmentStatus.CONFIRMED.value
        and visit.starts_at <= moment
    ):
        result = _outcome_form(visit)
    elif visit.status == AppointmentStatus.CONFIRMED.value:
        result = _logistics_form(visit)
    else:
        result = "—"

    return (
        f"<tr><td>{escape(local(visit.starts_at))}<br>"
        f"<span class='muted'>{escape(relative(visit.starts_at, now=moment))}</span></td>"
        f"<td>{escape(visit.reference)}</td>"
        f"<td>{who}</td><td>{state}</td><td>{reminder_cell}</td>"
        f"<td>{result}</td></tr>"
    )


_ACTION_LABELS = {
    NextActionKind.CALL.value: "Llamar",
    NextActionKind.WHATSAPP_MESSAGE.value: "Escribir por WhatsApp",
    NextActionKind.SEND_LISTINGS.value: "Enviar propiedades",
    NextActionKind.SCHEDULE_VISIT.value: "Agendar otra visita",
    NextActionKind.DOCUMENT_REVIEW.value: "Revisar documentos",
    NextActionKind.OTHER.value: "Otra",
}


def _outcome_form(visit: Appointment) -> str:
    attendance = {
        AppointmentAttendance.ATTENDED.value: ATTENDANCE_LABELS[
            AppointmentAttendance.ATTENDED.value
        ],
        AppointmentAttendance.MISSED.value: ATTENDANCE_LABELS[
            AppointmentAttendance.MISSED.value
        ],
    }
    due = datetime_input_value(_now() + timedelta(days=2))
    return f"""<form method="post" action="{AGENDA}/{visit.id}/resultado">
{command_field()}
<div class="field"><label>¿Se realizó la visita?
<select name="asistencia">{options(tuple(attendance), AppointmentAttendance.ATTENDED.value, attendance)}</select>
</label></div>
<div class="field"><label>Qué ocurrió
<textarea name="notas" rows="3" maxlength="2000"></textarea></label></div>
<div class="field"><label class="check"><input type="checkbox" name="invitar" value="1">
Autorizar invitación a reagendar (sólo si no se realizó)</label></div>
<div class="field"><label>Siguiente acción
<select name="accion"><option value="">Sin siguiente acción</option>
{options(tuple(_ACTION_LABELS), "", _ACTION_LABELS)}</select></label></div>
<div class="field"><label>Vence
<input type="datetime-local" name="vence" value="{escape(due)}"></label></div>
<div class="actions"><button type="submit">Registrar resultado</button></div>
</form>"""


def _logistics_form(visit: Appointment) -> str:
    return f"""<p><a class="button quiet"
 href="{AGENDA}/{visit.id}/reagendar">Reagendar</a></p>
<form method="post" action="{AGENDA}/{visit.id}/cancelar">
{command_field()}
<div class="actions"><button type="submit" class="quiet">Cancelar cita</button></div>
</form>"""


@router.post("/agenda/{appointment_id}/resultado")
async def record_outcome(
    request: Request, appointment_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    attendance = (
        AppointmentAttendance.MISSED
        if str(form.get("asistencia")) == AppointmentAttendance.MISSED.value
        else AppointmentAttendance.ATTENDED
    )
    kind_value = str(form.get("accion", "")).strip()
    due = parse_datetime_input(str(form.get("vence", "")))
    async with request.app.state.database.session_scope() as session:
        try:
            outcome = await _visits(request, session).record_outcome(
                actor,
                RecordVisitOutcome(
                    appointment_id=appointment_id,
                    attendance=attendance,
                    command_key=command_key(form, "visit-outcome"),
                    notes=str(form.get("notas", "")),
                    authorize_reschedule_invitation=bool(form.get("invitar")),
                    next_action_kind=(
                        NextActionKind(kind_value) if kind_value else None
                    ),
                    next_action_due_at=due if kind_value else None,
                ),
            )
            if isinstance(outcome, VisitRefused):
                return _redirect(AGENDA, error=outcome.message)
            await session.commit()
        except CommercialError as exc:
            return _redirect(AGENDA, error=exc.message)
    return _redirect(AGENDA, saved="resultado")


@router.get("/agenda/{appointment_id}/reagendar", response_class=HTMLResponse)
async def reschedule_form(
    request: Request,
    appointment_id: uuid.UUID,
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """Only times the Advisor's own calendar returned a moment ago.

    A free-text field would let an operator type a time the calendar has since
    taken and see the form succeed before anything authoritative said yes.
    """
    async with request.app.state.database.session_scope() as session:
        visits = _visits(request, session)
        try:
            visit = await visits.visit(actor, appointment_id)
        except CommercialError as exc:
            return refusal(actor, exc, active=AGENDA)
        advisor_id = visit.conducting_advisor_id or visit.advisor_id
        found = None
        if advisor_id is not None:
            found = await _scheduling(request, session).find_slots(
                SlotQuery(
                    organization_id=actor.organization_id, advisor_id=advisor_id
                )
            )

    if found is None or isinstance(found, SlotsUnavailable):
        message = (
            found.message
            if isinstance(found, SlotsUnavailable)
            else "Esta cita no tiene asesor con calendario autoritativo."
        )
        return shell(
            actor,
            "Reagendar visita",
            f'<div class="error" role="alert">{escape(message)}</div>'
            f'<p><a href="{AGENDA}">Volver a la agenda</a></p>',
            active=AGENDA,
        )

    choices = {slot.start.isoformat(): local(slot.start) for slot in found.slots[:24]}
    body = (
        (f'<div class="error" role="alert">{escape(error)}</div>' if error else "")
        + f'<div class="card"><h2>Cita {escape(visit.reference)}</h2>'
        f"<p>Actualmente: <strong>{escape(local(visit.starts_at))}</strong></p>"
        f'<p class="muted">Disponibilidad de {escape(found.advisor_name)}, '
        "consultada en este momento.</p>"
        + (
            f"""<form method="post" action="{AGENDA}/{visit.id}/reagendar">
{command_field()}
<div class="field"><label for="r-inicio">Nuevo horario
<select id="r-inicio" name="inicio">{options(tuple(choices), next(iter(choices)), choices)}</select>
</label></div>
<p class="hint">Primero se aparta el horario nuevo y sólo después se libera el
anterior. Si algo falla, la cita original se queda como está.</p>
<div class="actions"><button type="submit">Reagendar</button>
<a class="button quiet" href="{AGENDA}">Cancelar</a></div>
</form>"""
            if choices
            else empty(
                "No hay horarios disponibles en la ventana de agenda.",
                "Intenta más tarde o libera tiempo en el calendario del asesor.",
            )
        )
        + "</div>"
    )
    return shell(actor, "Reagendar visita", body, active=AGENDA)


@router.post("/agenda/{appointment_id}/reagendar")
async def reschedule_visit(
    request: Request, appointment_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"{AGENDA}/{appointment_id}/reagendar"
    try:
        start = datetime.fromisoformat(str(form.get("inicio", "")))
    except ValueError:
        return _redirect(path, error="Elige un horario de la lista.")
    async with request.app.state.database.session_scope() as session:
        try:
            outcome = await _visits(request, session).reschedule(
                actor,
                RescheduleVisit(
                    appointment_id=appointment_id,
                    new_start=start,
                    command_key=command_key(form, "visit-reschedule"),
                ),
            )
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    if isinstance(outcome, VisitRefused):
        return _redirect(path, error=outcome.message)
    return _redirect(AGENDA, saved="reagendada")


@router.post("/agenda/{appointment_id}/cancelar")
async def cancel_visit(
    request: Request, appointment_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    async with request.app.state.database.session_scope() as session:
        try:
            outcome = await _visits(request, session).cancel(
                actor,
                CancelVisit(
                    appointment_id=appointment_id,
                    command_key=command_key(form, "visit-cancel"),
                ),
            )
        except CommercialError as exc:
            return _redirect(AGENDA, error=exc.message)
    if isinstance(outcome, VisitRefused):
        return _redirect(AGENDA, error=outcome.message)
    if not outcome.contact_notified:
        # The visit is cancelled either way. Saying so plainly stops an operator
        # from assuming the customer was told.
        return _redirect(
            AGENDA,
            error=(
                "La cita quedó cancelada, pero no se pudo avisar al cliente por "
                "WhatsApp. Avísale por otro medio."
            ),
        )
    return _redirect(AGENDA, saved="cancelada")


# ------------------------------------------------------- Handling y alertas ---


@router.post("/bandeja/{conversation_id}/atender")
async def take_handling(
    request: Request, conversation_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"/crm/bandeja/{conversation_id}"
    async with request.app.state.database.session_scope() as session:
        try:
            await ConversationHandling(session).take(
                actor,
                TakeHandling(
                    conversation_id=conversation_id,
                    command_key=command_key(form, "handling-take"),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="atendiendo")


@router.post("/bandeja/{conversation_id}/liberar")
async def release_handling(
    request: Request, conversation_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"/crm/bandeja/{conversation_id}"
    wanted = (
        HandlingMode.AWAITING_CONTACT
        if str(form.get("modo")) == HandlingMode.AWAITING_CONTACT.value
        else HandlingMode.MAIA
    )
    async with request.app.state.database.session_scope() as session:
        try:
            await ConversationHandling(session).release(
                actor,
                ReleaseHandling(
                    conversation_id=conversation_id,
                    command_key=command_key(form, "handling-release"),
                    to_mode=wanted,
                    reason=(
                        "AwaitingContactReply"
                        if wanted is HandlingMode.AWAITING_CONTACT
                        else "ReturnedToMaia"
                    ),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="liberada")


@router.post("/bandeja/{conversation_id}/responder")
async def reply_from_crm(
    request: Request, conversation_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    path = f"/crm/bandeja/{conversation_id}"
    async with request.app.state.database.session_scope() as session:
        try:
            recorded = await ConversationHandling(session).reply(
                actor,
                HumanReply(
                    conversation_id=conversation_id,
                    body=str(form.get("mensaje", "")),
                    command_key=command_key(form, "handling-reply"),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    if not recorded.queued:
        return _redirect(
            path,
            error=(
                "No se pudo enviar el mensaje: "
                + _DENIAL_HINTS.get(
                    recorded.denied_reason or "",
                    "Product no autorizó el envío.",
                )
            ),
        )
    return _redirect(path, saved="enviado")


#: Why a human reply was refused, in terms of what the operator can do next.
_DENIAL_HINTS = {
    "ServiceWindowClosed": (
        "pasaron más de 24 horas desde el último mensaje del cliente y WhatsApp "
        "no permite texto libre. Espera a que escriba."
    ),
    "Suppressed": "el contacto pidió no recibir mensajes.",
    "MissingReactiveTrigger": (
        "no hay un mensaje del cliente al que esta respuesta corresponda."
    ),
    "UnknownRecipient": "no se pudo identificar al destinatario.",
}


@router.post("/bandeja/{conversation_id}/solicitud")
async def acknowledge_handoff(
    request: Request, conversation_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    """Take an unmet request without claiming the WhatsApp conversation."""
    form = await request.form()
    path = f"/crm/bandeja/{conversation_id}"
    try:
        request_id = uuid.UUID(str(form.get("solicitud", "")))
    except ValueError:
        return _redirect(path, error="No encontramos esa solicitud.")
    async with request.app.state.database.session_scope() as session:
        try:
            await HumanHandoff(session).acknowledge(
                actor,
                AcknowledgeHandoff(
                    request_id=request_id,
                    command_key=command_key(form, "handoff-ack"),
                ),
            )
            await session.commit()
        except CommercialError as exc:
            return _redirect(path, error=exc.message)
    return _redirect(path, saved="solicitud")


@router.get("/alertas", response_class=HTMLResponse)
async def alerts(
    request: Request,
    guardado: str = "",
    error: str = "",
    actor: Actor = Depends(require_actor),
) -> HTMLResponse:
    """Everything waiting for a human, oldest first."""
    moment = _now()
    async with request.app.state.database.session_scope() as session:
        pending = await HumanHandoff(session).pending(actor, now=moment)
        open_alerts = await InternalAlerts(session).open_for(actor)

    handoffs = table(
        f"{len(pending)} solicitud(es) sin tomar",
        ("Contacto", "Motivo", "Esperando", "Asesor avisado", "Acción"),
        "".join(
            f"<tr><td>{escape(view.contact_name or 'Contacto sin nombre')}<br>"
            f"<span class='muted'>{escape(view.channel_identity or '')}</span></td>"
            f"<td>{escape(SOURCE_LABELS[view.request.source])}</td>"
            f"<td>{view.waited_seconds // 60} min"
            + (
                "<br>" + tag("Escalada al administrador", "bad")
                if view.escalated
                else ""
            )
            + "</td>"
            f"<td>{escape(view.advisor_name or 'Sin asesor')}</td>"
            f"<td><a class='button' href='/crm/bandeja/{view.request.conversation_id}'>"
            "Abrir conversación</a></td></tr>"
            for view in pending
        ),
        empty_message="No hay solicitudes de atención humana pendientes.",
    )
    notices = table(
        f"{len(open_alerts)} aviso(s)",
        ("Cuándo", "Tipo", "Aviso", "Entrega", "Acción"),
        "".join(
            f"<tr><td>{escape(local(alert.created_at))}</td>"
            f"<td>{escape(ALERT_KIND_LABELS.get(alert.kind, alert.kind))}</td>"
            f"<td><strong>{escape(alert.title)}</strong><br>"
            f"<span class='muted'>{escape(alert.body)}</span></td>"
            f"<td>{escape(ALERT_STATUS_LABELS.get(alert.status, alert.status))}</td>"
            f"""<td><form method="post" action="/crm/alertas/{alert.id}">
{command_field()}<div class="actions">
<button type="submit" class="quiet">Marcar visto</button></div></form></td></tr>"""
            for alert in open_alerts
        ),
        empty_message="No hay avisos abiertos.",
    )
    content = (
        flash("Se marcó el aviso como visto." if guardado else None)
        + (f'<div class="error" role="alert">{escape(error)}</div>' if error else "")
        + "<h2>Solicitudes de atención humana</h2>"
        + '<p class="hint">Cuando un cliente pide hablar con una persona, Maia '
        "deja de responder y se avisa al asesor. A los 15 minutos sin tomarla, "
        "se avisa al administrador. La oportunidad <strong>no</strong> se "
        "reasigna sola.</p>"
        + handoffs
        + "<h2>Avisos de la operación</h2>"
        + notices
    )
    return shell(actor, "Pendientes de atención", content, active="/crm/alertas")


@router.post("/alertas/{alert_id}")
async def acknowledge_alert(
    request: Request, alert_id: uuid.UUID, actor: Actor = Depends(require_actor)
) -> RedirectResponse:
    form = await request.form()
    command_key(form, "alert-ack")
    async with request.app.state.database.session_scope() as session:
        changed = await InternalAlerts(session).acknowledge(actor, alert_id)
        if not changed:
            return _redirect(
                "/crm/alertas", error="No encontramos ese aviso."
            )
        await session.commit()
    return _redirect("/crm/alertas", saved="visto")


# ------------------------------------------------------- Handling fragments ---
#
# Rendered into the conversation page by :mod:`realestate.api.crm`. They live
# here beside the routes that act on them, so the button and the handler that
# receives it cannot drift apart.


def handling_panel(
    snapshot: HandlingSnapshot,
    request_row: HumanHandoffRequest | None,
    actor: Actor,
    *,
    conversation_id: uuid.UUID,
    maia_mid_turn: bool,
) -> str:
    """Who is answering this conversation, and the controls to change it."""
    kind = {
        HandlingMode.MAIA.value: "ok",
        HandlingMode.HUMAN.value: "warn",
        HandlingMode.AWAITING_CONTACT.value: "",
        HandlingMode.ADMIN_REVIEW.value: "bad",
    }[snapshot.mode.value]
    header = tag(MODE_LABELS[snapshot.mode.value], kind)
    detail = ""
    if snapshot.holder_name:
        detail = f" · <strong>{escape(snapshot.holder_name)}</strong>"
    if snapshot.since is not None:
        detail += f' <span class="muted">desde {escape(local(snapshot.since))}</span>'
    if snapshot.reason_label:
        detail += f'<br><span class="muted">{escape(snapshot.reason_label)}</span>'

    pending = ""
    if request_row is not None and request_row.status == HandoffStatus.PENDING.value:
        pending = (
            '<div class="error" role="alert"><strong>Un cliente está esperando a '
            "una persona.</strong><p>"
            + escape(SOURCE_LABELS[request_row.source])
            + f". Solicitada el {escape(local(request_row.requested_at))}."
            + (
                " Ya se avisó al administrador."
                if request_row.admin_alert_at
                else f" Se avisa al administrador el {escape(local(request_row.escalate_at))}."
            )
            + "</p>"
            + f"""<form method="post" action="/crm/bandeja/{conversation_id}/solicitud">
{command_field()}<input type="hidden" name="solicitud" value="{request_row.id}">
<div class="actions"><button type="submit">Confirmar que ya la atiendo</button></div>
</form></div>"""
        )

    controls = ""
    if snapshot.held_by(actor) or (
        actor.is_administrator and snapshot.mode is HandlingMode.HUMAN
    ):
        controls = f"""<form method="post" action="/crm/bandeja/{conversation_id}/liberar">
{command_field()}
<div class="field"><label for="h-modo">Al liberar
<select id="h-modo" name="modo">
<option value="{HandlingMode.MAIA.value}">Devolver a Maia</option>
<option value="{HandlingMode.AWAITING_CONTACT.value}">Dejar en espera del cliente</option>
</select></label></div>
<div class="actions"><button type="submit">Liberar la conversación</button></div>
</form>"""
    elif actor.member_id is not None:
        warning = (
            '<p class="hint">Maia está redactando una respuesta en este momento. '
            "Si tomas la conversación, ese borrador se descarta.</p>"
            if maia_mid_turn
            else ""
        )
        controls = (
            warning
            + f"""<form method="post" action="/crm/bandeja/{conversation_id}/atender">
{command_field()}
<div class="actions"><button type="submit">Atender yo esta conversación</button></div>
</form>"""
        )

    return (
        f'<div class="card"><h2>Quién atiende</h2><p>{header}{detail}</p>'
        f"{pending}{controls}</div>"
    )


def reply_form(
    snapshot: HandlingSnapshot, actor: Actor, *, conversation_id: uuid.UUID
) -> str:
    """The human reply box, only for whoever holds the conversation."""
    if not (
        snapshot.held_by(actor)
        or (actor.is_administrator and snapshot.mode is HandlingMode.HUMAN)
    ):
        return ""
    return f"""<form class="card" method="post"
 action="/crm/bandeja/{conversation_id}/responder">
<h2>Responder por WhatsApp</h2>
<p class="hint">Se envía desde el número oficial de Larevia, no desde tu
teléfono. Product revisa la elegibilidad antes de enviar: fuera de la ventana de
24 horas no se puede enviar texto libre.</p>
{command_field()}
<div class="field"><label for="h-mensaje">Mensaje
<textarea id="h-mensaje" name="mensaje" rows="4" maxlength="3000" required></textarea>
</label></div>
<div class="actions"><button type="submit">Enviar</button></div>
</form>"""

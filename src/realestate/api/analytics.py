"""The internal BI dashboard: aggregates, data quality, and nothing personal.

One surface, Administrator only, and every figure on it comes from
:class:`~realestate.domain.analytics.metrics.OperationMetrics` or the projection
run table. Nothing here queries a Contact, and nothing here can: the analytics
schema has no identity to query.

The dashboard is arranged the way SAN-073 asks Santiago to prioritise — the work
that is owed first, then the funnel, then the quality of the data behind both.
Data quality is on the same page as the results on purpose. A coverage number
next to "42 percent of outcomes are unrecorded" is a number somebody will
question; on a separate tab it is a number somebody will quote.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select

from realestate.api.operator import (
    redirect_back,
    require_administrator,
    shell,
)
from realestate.api.ui import (
    errors_box,
    escape,
    flash,
    local,
    parse_datetime_input,
    table,
)
from realestate.db.models import (
    AnalyticsOutboxEntry,
    AnalyticsOutboxStatus,
    AnalyticsProjectionRun,
    HarmSignalKind,
)
from realestate.domain.analytics.definitions import (
    CURRENT_DEFINITION_VERSION,
    MeasurementDefinitions,
)
from realestate.domain.analytics.emission import AnalyticsEmission
from realestate.domain.analytics.metrics import (
    HarmSignalCommand,
    HarmSignals,
    Measure,
    OperationMetrics,
    Scorecard,
    default_period,
)
from realestate.domain.analytics.projection import AnalyticsProjection
from realestate.domain.analytics.traffic import EXCLUSION_LABELS
from realestate.domain.clock import utc_now
from realestate.domain.commercial.actors import Actor, CommercialError

router = APIRouter(prefix="/crm/bi", tags=["bi"])
ACTIVE = "/crm/bi"

HARM_LABELS = {
    HarmSignalKind.WRONG_INFORMATION.value: "Información incorrecta",
    HarmSignalKind.COMPLAINT.value: "Queja",
    HarmSignalKind.UNTIMELY_MESSAGE.value: "Mensaje inoportuno",
    HarmSignalKind.ASSIGNMENT_FAILURE.value: "Falla de asignación",
    HarmSignalKind.INCORRECT_APPOINTMENT.value: "Cita incorrecta",
    HarmSignalKind.OPERATIONAL_OVERLOAD.value: "Carga operativa excesiva",
}


def _stat(label: str, measure: Measure, hint: str = "") -> str:
    """One tile. ``Sin registrar`` and ``No calculable`` render as themselves.

    The hint carries the sample and the unrecorded count, because a percentage
    over four subjects and one over four hundred are not the same claim.
    """
    detail = hint
    if not detail and measure.sample:
        detail = f"{measure.sample} casos"
        if measure.unrecorded:
            detail += f" · {measure.unrecorded} sin registrar"
    return (
        f'<div class="stat"><div class="muted">{escape(label)}</div>'
        f'<div class="value">{escape(measure.text)}</div>'
        f'<div class="hint">{escape(detail)}</div></div>'
    )


def _page(
    actor: Actor,
    scorecard: Scorecard,
    runs: tuple[AnalyticsProjectionRun, ...],
    pending: int,
    duplicates: int,
    versions: tuple[str, ...],
    message: str | None,
    error: str | None,
) -> HTMLResponse:
    stats = "".join(
        (
            _stat(
                "Cobertura de seguimiento",
                scorecard.follow_up_coverage,
                f"{scorecard.coverage_gaps} oportunidades sin cubrir",
            ),
            _stat("Tiempo a primera respuesta (mediana)", scorecard.time_to_first_response),
            _stat("Tasa de calificación", scorecard.qualification_rate),
            _stat("Asistencia a citas", scorecard.appointment_attendance),
            _stat("Completitud de resultados", scorecard.outcome_completeness),
            _stat(
                "Completitud de datos de seguimiento",
                scorecard.follow_up_data_completeness,
            ),
        )
    )
    harm_rows = "".join(
        f"<tr><td>{escape(HARM_LABELS.get(kind, kind))}</td>"
        f"<td>{count}</td></tr>"
        for kind, count in sorted(scorecard.harm_signals.items())
    )
    excluded_rows = "".join(
        f"<tr><td>{escape(EXCLUSION_LABELS.get(kind, kind))}</td><td>{count}</td></tr>"
        for kind, count in sorted(scorecard.excluded_events.items())
    ) or (
        "<tr><td>Sin eventos excluidos en el periodo</td><td>0</td></tr>"
    )
    run_rows = "".join(
        "<tr>"
        f"<td>{escape(row.definition_version)}</td>"
        f"<td>{escape(local(row.ran_at))}</td>"
        f"<td>{row.projected_events} proyectados<br>{row.excluded_events} excluidos</td>"
        f"<td>{row.late_events} tardíos<br>{row.rebuilt_periods} periodos reconstruidos</td>"
        f"<td>{row.from_sequence} → {row.last_sequence}</td>"
        "</tr>"
        for row in runs
    )
    version_options = "".join(
        f"<option value=\"{escape(version)}\">{escape(version)}</option>"
        for version in versions
    )
    harm_options = "".join(
        f'<option value="{escape(kind)}">{escape(label)}</option>'
        for kind, label in sorted(HARM_LABELS.items(), key=lambda item: item[1])
    )
    content = f"""
{flash(message)}
{errors_box([error] if error else [])}
<h1>Inteligencia de negocio</h1>
<p class="muted">Periodo {escape(local(scorecard.period_start))} a
{escape(local(scorecard.period_end))} · definiciones
{escape(scorecard.definition_version)}. Sólo cifras agregadas: esta pantalla no
consulta identidad, teléfonos ni contenido de conversaciones.</p>

<h2>Tablero operativo</h2>
<div class="stats">{stats}</div>
<p class="hint">{escape(Measure.unrecorded_only(sample=0).text)} nunca significa
cero ni pérdida: es un dato que una persona todavía no registró.</p>

<h2>Señales de daño del piloto</h2>
{table(
    "Señales registradas en el periodo (SAN-079)",
    ("Señal", "Registros"),
    harm_rows,
    empty_message="Sin señales registradas.",
)}
<div class="card"><h3>Registrar una señal de daño</h3>
<form method="post" action="{ACTIVE}/danos">
<div class="grid">
<label>Tipo<select name="kind" required>{harm_options}</select></label>
<label>Ocurrió el<input type="datetime-local" name="occurred_at" required></label>
</div>
<label>Evidencia<textarea name="evidence" required minlength="4"></textarea></label>
<div class="actions"><button>Registrar</button></div>
</form></div>

<h2>Calidad de la medición</h2>
<div class="stats">
<div class="stat"><div class="muted">Eventos en cola</div>
<div class="value">{pending}</div>
<div class="hint">Outbox de analítica pendiente de proyectar</div></div>
<div class="stat"><div class="muted">Duplicados suprimidos</div>
<div class="value">{duplicates}</div>
<div class="hint">Reintentos que no crearon un segundo evento</div></div>
</div>
{table(
    "Tráfico excluido del cálculo",
    ("Motivo", "Eventos"),
    excluded_rows,
)}
{table(
    "Pasadas de proyección",
    ("Definiciones", "Ejecutada", "Volumen", "Tardíos", "Secuencia"),
    run_rows,
    empty_message="Todavía no se ha ejecutado una proyección.",
)}
<div class="card"><h3>Reproyectar</h3>
<p class="hint">Una reproyección desde la secuencia cero reconstruye los mismos
agregados: la inserción de eventos es idempotente y los periodos se recalculan,
no se incrementan.</p>
<form method="post" action="{ACTIVE}/proyectar">
<div class="grid">
<label>Versión de definiciones<select name="version">{version_options}</select></label>
<label class="check"><input type="checkbox" name="replay" value="1"> Reproyectar
desde el inicio</label>
</div>
<div class="actions"><button>Ejecutar pasada</button></div>
</form></div>
"""
    return shell(actor, "Inteligencia de negocio", content, active=ACTIVE)


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    actor: Actor = Depends(require_administrator),
    guardado: str = "",
    error: str = "",
    version: str = "",
) -> HTMLResponse:
    moment = utc_now()
    start, end = default_period(moment)
    async with request.app.state.database.session_scope() as session:
        definitions = MeasurementDefinitions(session)
        versions = await definitions.versions()
        wanted = version if version in versions else CURRENT_DEFINITION_VERSION
        scorecard = await OperationMetrics(session, actor).scorecard(
            period_start=start, period_end=end, definition_version=wanted
        )
        runs = tuple(
            await session.scalars(
                select(AnalyticsProjectionRun)
                .order_by(desc(AnalyticsProjectionRun.ran_at))
                .limit(10)
            )
        )
        pending = await session.scalar(
            select(func.count(AnalyticsOutboxEntry.id)).where(
                AnalyticsOutboxEntry.organization_id == actor.organization_id,
                AnalyticsOutboxEntry.status == AnalyticsOutboxStatus.PENDING.value,
            )
        )
        duplicates = await session.scalar(
            select(
                func.coalesce(func.sum(AnalyticsOutboxEntry.duplicate_attempts), 0)
            ).where(AnalyticsOutboxEntry.organization_id == actor.organization_id)
        )
    return _page(
        actor,
        scorecard,
        runs,
        int(pending or 0),
        int(duplicates or 0),
        versions,
        guardado or None,
        error or None,
    )


@router.post("/proyectar")
async def project(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    version = str(form.get("version", "")) or None
    replay = bool(form.get("replay"))
    try:
        async with request.app.state.database.session_scope() as session:
            projection = AnalyticsProjection(session)
            if replay:
                report = await projection.refresh(version, from_sequence=0)
            else:
                report = await projection.drain(version)
            await session.commit()
    except CommercialError as exc:
        return redirect_back(ACTIVE, error=exc.message)
    return redirect_back(
        ACTIVE,
        saved=(
            f"{report.projected} eventos proyectados, {report.late} tardíos, "
            f"{report.rebuilt_periods} periodos reconstruidos"
        ),
    )


@router.post("/emitir")
async def emit(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    """Emit the operational events on demand, for an Administrator's own check."""
    async with request.app.state.database.session_scope() as session:
        report = await AnalyticsEmission(session, actor).emit_operational()
        await session.commit()
    return redirect_back(ACTIVE, saved=f"{report.total} eventos emitidos")


@router.post("/danos")
async def record_harm(
    request: Request, actor: Actor = Depends(require_administrator)
) -> RedirectResponse:
    form = await request.form()
    raw = str(form.get("occurred_at", "")).strip()
    try:
        kind = HarmSignalKind(str(form.get("kind", "")))
        occurred_at = _parse_moment(raw)
        async with request.app.state.database.session_scope() as session:
            await HarmSignals(session, actor).record(
                HarmSignalCommand(
                    kind=kind,
                    evidence=str(form.get("evidence", "")),
                    occurred_at=occurred_at,
                    command_key=f"harm:{kind.value}:{raw}",
                ),
                at=utc_now(),
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        detail = exc.message if isinstance(exc, CommercialError) else str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc
    return redirect_back(ACTIVE, saved="Señal de daño registrada")


def _parse_moment(raw: str) -> datetime:
    parsed = parse_datetime_input(raw)
    if parsed is None:
        raise ValueError("La fecha y hora no son válidas.")
    return parsed

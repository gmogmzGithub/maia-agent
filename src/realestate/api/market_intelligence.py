"""Analyst-only Shared Market Dataset dashboard and duplicate decisions."""

from __future__ import annotations

import hmac
import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from realestate.api.ui import STYLES, escape
from realestate.config import get_settings
from realestate.domain.commercial.actors import CommercialError
from realestate.domain.market_intelligence import (
    ComparableFilters,
    MarketIntelligenceAnalyst,
    SharedMarketDataset,
)

router = APIRouter(prefix="/market-intelligence", tags=["market-intelligence"])
_basic = HTTPBasic(auto_error=False)


def require_market_analyst(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> MarketIntelligenceAnalyst:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Se requieren credenciales de Inteligencia de Mercado.",
        headers={"WWW-Authenticate": "Basic"},
    )
    if credentials is None:
        raise unauthorized
    configured = get_settings().market_intelligence_basic_credentials_json.strip()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configura MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON.",
        )
    try:
        accounts = json.loads(configured)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON no contiene JSON válido.",
        ) from exc
    if not isinstance(accounts, dict) or not all(
        isinstance(user, str) and user and isinstance(password, str) and password
        for user, password in accounts.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MARKET_INTELLIGENCE_BASIC_CREDENTIALS_JSON contiene una cuenta inválida.",
        )
    authenticated = any(
        hmac.compare_digest(credentials.username, user)
        and hmac.compare_digest(credentials.password, password)
        for user, password in accounts.items()
    )
    if not authenticated:
        raise unauthorized
    return MarketIntelligenceAnalyst(label=credentials.username)


def _money(value: Decimal | None, currency: str | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f} {currency or ''}".strip()


def _page(title: str, body: str, analyst: MarketIntelligenceAnalyst) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="es-MX"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Maia</title><style>{STYLES}</style></head><body>
<main class="main-wrap" id="contenido"><h1>{escape(title)}</h1>
<p class="page-context">Dataset analítico compartido · {escape(analyst.label)} · Sin acceso al CRM</p>
{body}</main></body></html>"""
    )


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    property_type: str = "",
    municipality: str = "",
    currency: str = "",
    subject_record_id: str = "",
    analyst: MarketIntelligenceAnalyst = Depends(require_market_analyst),
) -> HTMLResponse:
    try:
        subject_id = uuid.UUID(subject_record_id) if subject_record_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Venta sujeto inválida.") from exc
    async with request.app.state.database.session_scope() as session:
        dataset = SharedMarketDataset(session, analyst)
        subject = await dataset.completed_record(subject_id) if subject_id else None
        if subject_id and subject is None:
            raise HTTPException(status_code=404, detail="Venta sujeto no encontrada.")
        filters = ComparableFilters(
            property_type=property_type.strip()
            or (subject.property_type if subject else None),
            municipality=municipality.strip()
            or (subject.municipality if subject else None),
            currency=currency.strip().upper()
            or (subject.paid_currency if subject else None),
            exclude_record_id=subject_id,
        )
        report = await dataset.comparables(filters)
        summary = await dataset.aggregate_summary(report)
        completeness = await dataset.completeness()
        candidates = await dataset.duplicate_candidates()
    distribution_labels = {
        "property_type": "Tipo de propiedad",
        "municipality": "Municipio",
        "payment_path": "Forma de pago",
        "home_purchase_number": "Número de compra",
        "buyer_age": "Edad al cierre",
        "monthly_income": "Ingreso mensual",
        "children": "Hijos",
        "financial_dependants": "Dependientes financieros",
    }
    distributions = "".join(
        f"<h3>{escape(distribution_labels[name])}</h3><p>"
        + " · ".join(f"{escape(label)}: {count}" for label, count in values.items())
        + "</p>"
        for name, values in summary.distributions.items()
    )
    aggregate = (
        f"""<dl class="pairs"><dt>Muestra</dt><dd>{report.sample_size}</dd>
<dt>Total pagado</dt><dd>{escape(_money(summary.total_paid_price, report.aggregate_currency))}</dd>
<dt>Mediana pagada</dt><dd>{escape(_money(report.median_paid_price, report.aggregate_currency))}</dd>
<dt>Rango pagado</dt><dd>{escape(_money(report.minimum_paid_price, report.aggregate_currency))} — {escape(_money(report.maximum_paid_price, report.aggregate_currency))}</dd>
<dt>Mediana pagada por m² de construcción</dt><dd>{escape(_money(summary.median_paid_price_per_sqm, report.aggregate_currency))}</dd>
<dt>Mediana publicado menos pagado</dt><dd>{escape(_money(summary.median_published_to_paid_difference, report.aggregate_currency))}</dd>
<dt>Mediana de publicación a cierre</dt><dd>{escape(str(summary.median_days_to_completion) if summary.median_days_to_completion is not None else "—")} días</dd></dl>{distributions}"""
        if report.aggregate_available
        else f"<div class='warn' role='status'>Muestra: {report.sample_size}. Los agregados se reservan hasta contar con al menos 5 ventas aplicables.</div>"
    )
    rows = (
        "".join(
            f"<tr><td><a href='/market-intelligence?subject_record_id={row.id}'>Usar como sujeto</a></td>"
            f"<td>{escape(row.completion_date or '—')}</td><td>{escape(row.property_type or '—')}</td>"
            f"<td>{escape(row.municipality or '—')}</td><td>{escape(_money(row.paid_price, row.paid_currency))}</td>"
            f"<td>{escape(_money(row.paid_price / row.construction_area_sqm, row.paid_currency) if row.paid_price is not None and row.construction_area_sqm else '—')}</td>"
            f"<td>{escape(_money(row.published_price, row.published_currency))}</td>"
            f"<td>{escape(_money(row.appraisal_value, row.appraisal_currency))}</td></tr>"
            for row in report.records
        )
        or '<tr><td colspan="8">No hay ventas comparables con estos filtros.</td></tr>'
    )
    duplicate_forms = (
        "".join(
            f"""<form method="post" action="/market-intelligence/resolutions">
<input type="hidden" name="record_id" value="{left.id}">
<input type="hidden" name="record_id" value="{right.id}">
<p>{escape(left.municipality or "Sin municipio")} · {escape(_money(left.paid_price, left.paid_currency))} · {escape(left.completion_date)}</p>
<label>Razón de la resolución<input name="reason" required maxlength="500"></label>
<div class="actions"><button type="submit">Confirmar que es una sola venta</button></div></form>"""
            for left, right in candidates
        )
        or "<p>No hay candidatos pendientes.</p>"
    )
    subject_card = (
        f"""<section class="card"><h2>Venta sujeto</h2><dl class="pairs">
<dt>Fecha</dt><dd>{escape(subject.completion_date)}</dd><dt>Tipo</dt><dd>{escape(subject.property_type or "—")}</dd>
<dt>Ubicación</dt><dd>{escape(", ".join(item for item in (subject.colonia, subject.municipality) if item) or "—")}</dd>
<dt>Construcción</dt><dd>{escape(subject.construction_area_sqm or "—")} m²</dd>
<dt>Pagado</dt><dd>{escape(_money(subject.paid_price, subject.paid_currency))}</dd></dl></section>"""
        if subject is not None
        else "<p class='hint'>Elige «Usar como sujeto» en una venta para comparar las demás contra su tipo, municipio y moneda.</p>"
    )
    body = f"""{subject_card}<form method="get"><div class="grid">
<label>Tipo de propiedad<input name="property_type" value="{escape(property_type)}"></label>
<label>Municipio<input name="municipality" value="{escape(municipality)}"></label>
<label>Moneda<input name="currency" maxlength="3" value="{escape(currency)}"></label>
<label>Id de venta sujeto<input name="subject_record_id" value="{escape(subject_record_id)}"></label>
</div><div class="actions"><button type="submit">Aplicar criterios SQL</button></div></form>
<section class="card"><h2>Resumen interno</h2>{aggregate}
<p>Ventas completadas proyectadas: {completeness["completed"]} · Registros con los principales campos comparables: {completeness["comparison_complete"]}</p></section>
<section class="card"><h2>Reporte de ventas comparables</h2>
<p class="hint">Cada venta individual puede aparecer desde el primer registro. La muestra siempre se muestra.</p>
<div class="table-scroll"><table><thead><tr><th>Sujeto</th><th>Fecha</th><th>Tipo</th><th>Municipio</th><th>Pagado</th><th>Pagado/m²</th><th>Publicado</th><th>Avalúo</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section class="card"><h2>Posibles ventas co-brokeradas</h2>{duplicate_forms}</section>"""
    return _page("Inteligencia de Mercado", body, analyst)


@router.post("/resolutions")
async def resolve_duplicate(
    request: Request,
    analyst: MarketIntelligenceAnalyst = Depends(require_market_analyst),
) -> RedirectResponse:
    form = await request.form()
    try:
        record_ids = tuple(uuid.UUID(str(value)) for value in form.getlist("record_id"))
        async with request.app.state.database.session_scope() as session:
            await SharedMarketDataset(session, analyst).resolve_duplicate(
                record_ids, reason=str(form.get("reason", ""))
            )
            await session.commit()
    except (ValueError, CommercialError) as exc:
        detail = (
            exc.message if isinstance(exc, CommercialError) else "Selección inválida."
        )
        raise HTTPException(status_code=400, detail=detail) from exc
    return RedirectResponse("/market-intelligence", status_code=303)

"""Authenticated, server-rendered manual Property administration."""

from __future__ import annotations

import asyncio
import html
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from realestate.api.developer import property_writer, require_developer
from realestate.db.models import PropertyDocumentVersion, PropertyStatus
from realestate.domain.administration import (
    AdministrationService,
    Administrator,
    VALID_INACTIVE_REASONS,
)
from realestate.domain.properties import accepted_version, resolve_property
from realestate.domain.property_document import (
    COMMUNITY_AMENITIES,
    CURRENCIES,
    MAINTENANCE_STATUSES,
    OPERATIONS,
    OPTIONAL_KEYS,
    PRIVATE_CHARACTERISTICS,
    PROPERTY_TYPES,
    REQUIRED_KEYS,
    SCHEMA_VERSION,
    ValidationError,
    format_amount,
    narrative_sections,
    render_property_document,
    slugify_property_name,
    split_front_matter,
)

router = APIRouter(prefix="/admin", tags=["admin"])

TYPE_LABELS = {"House": "Casa", "Apartment": "Departamento", "Land": "Terreno"}
OPERATION_LABELS = {"Sale": "En venta", "Rental": "En renta"}
REASON_LABELS = {
    "Sold": "Vendida",
    "Rented": "Rentada",
    "Reserved": "Reservada",
    "TemporarilyUnavailable": "No disponible temporalmente",
    "Withdrawn": "Retirada",
    "Unspecified": "Sin especificar",
}
MAINTENANCE_LABELS = {
    "Fee": "Tiene cuota",
    "None": "No tiene cuota",
    "Unknown": "Por confirmar",
}

# The two multi-select groups. Everything else on the form is single-valued.
CHECKBOX_KEYS = ("private_characteristics", "community_amenities")

# What an empty form starts from. Every other field starts blank.
NEW_PROPERTY_DEFAULTS = {
    "property_type": "House",
    "operation": "Sale",
    "price_currency": "MXN",
    "state": "Jalisco",
    "half_bathrooms": "0",
    "parking_spaces": "0",
    "maintenance_status": "Unknown",
    "maintenance_currency": "MXN",
    "in_development": "true",
}

# Which document facts the form hands over as plain text. Derived from the
# schema itself so a new fact cannot be declared in the domain and silently
# dropped here; the keys listed as exceptions are the ones ``_metadata`` builds
# by hand below because they are conditional or multi-valued.
TEXT_KEYS = tuple(
    key
    for key in REQUIRED_KEYS
    if key not in {"schema_version", "property_id", "in_development"}
)
OPTIONAL_TEXT_KEYS = tuple(
    key
    for key in OPTIONAL_KEYS
    if key
    not in {"maintenance_amount", "maintenance_currency", "maintenance_description", *CHECKBOX_KEYS}
)


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _layout(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)} · Maia</title>
<style>
:root {{ color-scheme: light; --ink:#1f2933; --muted:#667085; --line:#d0d5dd; --brand:#155eef; --bad:#b42318; --ok:#027a48; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:#f8fafc; color:var(--ink); font:15px/1.45 system-ui,sans-serif }}
header {{ background:#fff; border-bottom:1px solid var(--line) }} nav,main {{ max-width:1180px; margin:auto; padding:18px 24px }}
nav {{ display:flex; justify-content:space-between; align-items:center }} nav a {{ margin-left:18px }} a {{ color:var(--brand); text-decoration:none }}
h1 {{ margin:.2rem 0 1.2rem }} h2 {{ margin-top:1.8rem }} .card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:20px; margin:14px 0 }}
.grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 20px }} .full {{ grid-column:1/-1 }}
[hidden] {{ display:none !important }}
label {{ display:block; font-weight:650 }} input,select,textarea {{ width:100%; margin-top:5px; padding:9px 10px; border:1px solid #98a2b3; border-radius:6px; font:inherit; background:#fff }}
textarea {{ min-height:110px; resize:vertical }} textarea.preview {{ min-height:430px; font:13px/1.4 ui-monospace,monospace }}
fieldset {{ border:1px solid var(--line); border-radius:8px; padding:12px 14px }} legend {{ font-weight:700 }}
.checks {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px }} .checks label {{ font-weight:400 }} .checks input {{ width:auto; margin:0 7px 0 0 }}
.actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:18px }} button,.button {{ border:0; border-radius:6px; padding:9px 14px; background:var(--brand); color:#fff; font-weight:700; cursor:pointer }}
button.secondary,.button.secondary {{ background:#475467 }} button.danger {{ background:var(--bad) }} .hint,.muted {{ color:var(--muted) }}
.error {{ background:#fef3f2; color:var(--bad); border-left:4px solid var(--bad); padding:12px 16px }} .ok {{ background:#ecfdf3; color:var(--ok); border-left:4px solid var(--ok); padding:12px 16px }}
table {{ width:100%; border-collapse:collapse; background:#fff }} th,td {{ text-align:left; border-bottom:1px solid var(--line); padding:11px 9px; vertical-align:top }} th {{ color:#475467; font-size:13px }}
.tabs a {{ display:inline-block; padding:8px 12px; border-radius:6px }} .tabs a.current {{ background:#eaf1ff; font-weight:700 }} .inline {{ display:inline }} .inline select {{ width:auto; margin:0 5px }}
.status {{ font-weight:700 }} .Active {{ color:var(--ok) }} .Inactive {{ color:var(--bad) }} pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#101828; color:#f2f4f7; padding:16px; border-radius:8px }}
@media(max-width:760px) {{ .grid,.checks {{ grid-template-columns:1fr }} table {{ display:block; overflow:auto }} nav,main {{ padding:14px }} }}
</style></head><body>
<header><nav><strong>Maia · Administración</strong><span><a href="/admin/properties">Propiedades</a><a href="/admin/properties/new">Agregar propiedad</a><a href="/upload">MD avanzado</a></span></nav></header>
<main>{content}</main></body></html>"""
    )


def _selected(current: object, value: str) -> str:
    return " selected" if current == value else ""


def _checked(values: list[str], value: str) -> str:
    return " checked" if value in values else ""


def _options(
    values: tuple[str, ...], current: object, labels: dict[str, str] | None = None
) -> str:
    shown = labels or {}
    return "".join(
        f'<option value="{_e(value)}"{_selected(current, value)}>{_e(shown.get(value, value))}</option>'
        for value in values
    )


# Identical for every Active row in the inventory table, so built once.
REASON_OPTIONS = _options(VALID_INACTIVE_REASONS, "Unspecified", REASON_LABELS)


def _submitted_values(form: Any) -> dict[str, Any]:
    """One flat mapping of a submitted form, with the checkbox groups as lists."""
    values: dict[str, Any] = {
        key: str(value)
        for key, value in form.multi_items()
        if key not in CHECKBOX_KEYS
    }
    for key in CHECKBOX_KEYS:
        values[key] = list(form.getlist(key))
    return values


def _metadata(values: dict[str, Any], property_key: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "property_id": property_key,
        **{key: str(values.get(key, "")) for key in TEXT_KEYS},
        "in_development": values.get("in_development") == "true",
    }
    for key in OPTIONAL_TEXT_KEYS:
        if str(values.get(key, "")).strip():
            metadata[key] = str(values[key]).strip()
    if metadata["maintenance_status"] == "Fee":
        metadata["maintenance_amount"] = str(values.get("maintenance_amount", ""))
        metadata["maintenance_currency"] = str(values.get("maintenance_currency", ""))
        metadata["maintenance_description"] = str(
            values.get("maintenance_description", "")
        )
    if private := list(values.get("private_characteristics", [])):
        metadata["private_characteristics"] = private
    if metadata["in_development"]:
        if community := list(values.get("community_amenities", [])):
            metadata["community_amenities"] = community
    else:
        metadata.pop("other_community_amenity", None)
    return metadata


def _form_page(
    *,
    values: dict[str, Any],
    editing_key: str | None,
    errors: list[str] | None = None,
    preview: str = "",
) -> HTMLResponse:
    key = editing_key or slugify_property_name(str(values.get("name", "")))
    title = "Editar propiedad" if editing_key else "Agregar propiedad"
    action = f"/admin/properties/{editing_key}" if editing_key else "/admin/properties"
    private = list(values.get("private_characteristics", []))
    community = list(values.get("community_amenities", []))
    in_development = values.get("in_development", "true")
    error_box = ""
    if errors:
        error_box = '<div class="error"><strong>No se guardó ningún cambio.</strong><ul>' + "".join(f"<li>{_e(error)}</li>" for error in errors) + "</ul></div>"
    private_boxes = "".join(
        f'<label><input type="checkbox" name="private_characteristics" value="{_e(value)}"{_checked(private, value)}>{_e("Jardín" if value == "Jardín privado" else value)}</label>'
        for value in PRIVATE_CHARACTERISTICS
    )
    community_boxes = "".join(
        f'<label><input type="checkbox" name="community_amenities" value="{_e(value)}"{_checked(community, value)}>{_e(value)}</label>'
        for value in COMMUNITY_AMENITIES
    )
    preview_box = f'<section class="card"><h2>Vista previa del archivo Markdown</h2><textarea class="preview" readonly>{_e(preview)}</textarea></section>' if preview else ""
    key_control = f'<input id="property-id" value="{_e(key)}" readonly><span class="hint">Se genera del nombre y queda bloqueado después de crear.</span>'
    key_script = ""
    if editing_key is None:
        key_script = """
const propertyName=document.getElementById('property-name'), propertyId=document.getElementById('property-id');
function propertySlug(value) {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()
    .replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,120).replace(/-+$/,'');
}
function updatePropertyId() { propertyId.value=propertySlug(propertyName.value); }
propertyName.addEventListener('input',updatePropertyId); updatePropertyId();
"""
    content = f"""
<h1>{title}</h1>{error_box}
<form method="post" action="{_e(action)}">
<section class="card"><h2>Identidad y operación</h2><div class="grid">
<label>Nombre *<input id="property-name" name="name" value="{_e(values.get('name'))}" required></label>
<label>Property ID *{key_control}</label>
<label>Tipo *<select name="property_type" id="property-type">{_options(PROPERTY_TYPES, values.get('property_type','House'), TYPE_LABELS)}</select></label>
<label>Operación *<select name="operation">{_options(OPERATIONS, values.get('operation','Sale'), OPERATION_LABELS)}</select></label>
<label>Precio *<input name="price_amount" type="number" min="0.01" step="0.01" value="{_e(values.get('price_amount'))}" required></label>
<label>Moneda *<select name="price_currency">{_options(CURRENCIES, values.get('price_currency','MXN'))}</select></label>
</div></section>
<section class="card"><h2>Ubicación pública</h2><div class="grid">
<label>Estado *<input name="state" value="{_e(values.get('state','Jalisco'))}" required></label>
<label>Ciudad o municipio *<input name="city" value="{_e(values.get('city'))}" required></label>
<label>Colonia, coto o desarrollo *<input name="neighborhood" value="{_e(values.get('neighborhood'))}" required></label>
<label>Notas públicas o referencias<input name="public_location_notes" value="{_e(values.get('public_location_notes'))}"></label>
<label class="full">Dirección exacta para la visita <input name="visit_address" value="{_e(values.get('visit_address'))}"><span class="hint">Privada: no se escribe en el MD ni se comparte antes de confirmar una cita.</span></label>
</div></section>
<section class="card"><h2 id="measures-title">Espacios y medidas</h2><div class="grid">
<div id="residential-measures" class="grid full">
<label>Recámaras *<input name="bedrooms" type="number" min="0" step="1" value="{_e(values.get('bedrooms'))}"></label>
<label>Baños completos *<input name="full_bathrooms" type="number" min="0" step="1" value="{_e(values.get('full_bathrooms'))}"></label>
<label>Medios baños *<input name="half_bathrooms" type="number" min="0" step="1" value="{_e(values.get('half_bathrooms','0'))}"></label>
<label>Estacionamientos *<input name="parking_spaces" type="number" min="0" step="1" value="{_e(values.get('parking_spaces','0'))}"></label>
<label>Construcción m²<input name="construction_m2" type="number" min="0.01" step="0.01" value="{_e(values.get('construction_m2'))}"></label>
<label>Terreno m²<input name="land_m2" type="number" min="0.01" step="0.01" value="{_e(values.get('land_m2'))}"></label>
<label>Pisos<input name="floors" type="number" min="1" step="1" value="{_e(values.get('floors'))}"></label>
<label>Año de construcción<input name="year_built" type="number" min="1000" max="2100" step="1" value="{_e(values.get('year_built'))}"></label>
</div>
<div id="land-measures" class="grid full">
<label>Superficie de terreno m² *<input name="land_m2" type="number" min="0.01" step="0.01" value="{_e(values.get('land_m2'))}"></label>
<label>Frente en metros *<input name="land_front_m" type="number" min="0.01" step="0.01" value="{_e(values.get('land_front_m'))}"></label>
<label>Fondo en metros *<input name="land_depth_m" type="number" min="0.01" step="0.01" value="{_e(values.get('land_depth_m'))}"></label>
</div>
</div></section>
<section class="card"><h2 id="description-title">Descripción</h2><div class="grid">
<label class="full"><span id="general-label">Descripción general</span> *<textarea name="general_description" required>{_e(values.get('general_description'))}</textarea></label>
<label class="full"><span id="distribution-label">Distribución y espacios</span> *<textarea name="distribution" required>{_e(values.get('distribution'))}</textarea></label>
</div></section>
<section class="card" id="private-characteristics-section"><h2>Características privadas</h2><fieldset><legend>Selecciona las que pertenecen a la propiedad</legend><div class="checks">{private_boxes}</div>
<label>Otra característica<input name="other_private_characteristic" maxlength="120" value="{_e(values.get('other_private_characteristic'))}"></label></fieldset></section>
<section class="card"><h2>Coto o fraccionamiento</h2><div class="grid"><label>¿Está dentro de un coto, fraccionamiento o desarrollo? *<select name="in_development" id="in-development"><option value="true"{_selected(in_development,'true')}>Sí</option><option value="false"{_selected(in_development,'false')}>No</option></select></label></div>
<fieldset id="community"><legend>Amenidades del coto</legend><div class="checks">{community_boxes}</div><label>Otra amenidad<input name="other_community_amenity" maxlength="120" value="{_e(values.get('other_community_amenity'))}"></label></fieldset></section>
<section class="card"><h2>Mantenimiento</h2><div class="grid">
<label>Situación *<select name="maintenance_status" id="maintenance-status">{_options(MAINTENANCE_STATUSES, values.get('maintenance_status','Unknown'), MAINTENANCE_LABELS)}</select></label>
<div id="maintenance-fee" class="grid full"><label>Monto *<input id="maintenance-amount" name="maintenance_amount" type="number" min="0.01" step="0.01" value="{_e(values.get('maintenance_amount'))}"></label><label>Moneda *<select id="maintenance-currency" name="maintenance_currency">{_options(CURRENCIES, values.get('maintenance_currency','MXN'))}</select></label><label class="full">Descripción del mantenimiento *<textarea id="maintenance-description" name="maintenance_description">{_e(values.get('maintenance_description'))}</textarea></label></div>
</div></section>
<div class="actions"><button name="intent" value="preview" class="secondary">Generar vista previa</button><button name="intent" value="save">{'Guardar nueva versión' if editing_key else 'Crear y activar propiedad'}</button><a class="button secondary" href="/admin/properties">Cancelar</a></div>
</form>{preview_box}
<script>
const propertyType=document.getElementById('property-type');
const residentialMeasures=document.getElementById('residential-measures');
const landMeasures=document.getElementById('land-measures');
const privateCharacteristics=document.getElementById('private-characteristics-section');
const measuresTitle=document.getElementById('measures-title');
const descriptionTitle=document.getElementById('description-title');
const generalLabel=document.getElementById('general-label');
const distributionLabel=document.getElementById('distribution-label');
const dev=document.getElementById('in-development'), community=document.getElementById('community');
const maintenance=document.getElementById('maintenance-status'), fee=document.getElementById('maintenance-fee');
const maintenanceAmount=document.getElementById('maintenance-amount');
const maintenanceCurrency=document.getElementById('maintenance-currency');
const maintenanceDescription=document.getElementById('maintenance-description');
const residentialRequired=new Set(['bedrooms','full_bathrooms','half_bathrooms','parking_spaces']);
function controls(root) {{ return root.querySelectorAll('input,select,textarea'); }}
function setBlock(root, enabled, display) {{
  root.hidden=!enabled;
  root.style.display=enabled?display:'none';
  controls(root).forEach((control) => {{
    control.disabled=!enabled;
    if (!enabled) control.required=false;
  }});
}}
function toggle() {{
  const isLand=propertyType.value==='Land';
  const hasDevelopment=dev.value==='true';
  const hasFee=maintenance.value==='Fee';
  setBlock(residentialMeasures,!isLand,'grid');
  setBlock(landMeasures,isLand,'grid');
  setBlock(privateCharacteristics,!isLand,'block');
  controls(residentialMeasures).forEach((control) => {{
    control.required=!isLand && residentialRequired.has(control.name);
  }});
  controls(landMeasures).forEach((control) => {{ control.required=isLand; }});
  measuresTitle.textContent=isLand?'Medidas del terreno':'Espacios y medidas';
  descriptionTitle.textContent=isLand?'Descripción del terreno':'Descripción';
  generalLabel.textContent=isLand?'Descripción del terreno':'Descripción general';
  distributionLabel.textContent=isLand?'Detalles del terreno y entorno':'Distribución y espacios';
  community.hidden=!hasDevelopment;
  fee.hidden=!hasFee;
  fee.style.display=hasFee?'grid':'none';
  maintenanceAmount.required=hasFee;
  maintenanceAmount.disabled=!hasFee;
  maintenanceCurrency.disabled=!hasFee;
  maintenanceDescription.required=hasFee;
  maintenanceDescription.disabled=!hasFee;
}}
propertyType.addEventListener('change',toggle); dev.addEventListener('change',toggle); maintenance.addEventListener('change',toggle); toggle();
{key_script}
</script>"""
    return _layout(title, content)


def _form_defaults(metadata: dict[str, Any], *, visit_address: str | None, general: str, distribution: str) -> dict[str, Any]:
    values = {key: value for key, value in metadata.items() if key not in {"schema_version", "property_id"}}
    values["in_development"] = "true" if metadata.get("in_development") else "false"
    values["visit_address"] = visit_address or ""
    values["general_description"] = general
    values["distribution"] = distribution
    return values


async def _read_document(
    request: Request, version: PropertyDocumentVersion
) -> bytes | None:
    """Read an accepted artifact off the event loop, as the domain does.

    These handlers share the loop with the Meta webhook and the background
    worker, and an artifact is up to MAX_UPLOAD_BYTES of disk.
    """
    return await asyncio.to_thread(
        request.app.state.artifacts.read, version.artifact_path
    )


async def _render_submission(request: Request, editing_key: str | None, developer: str) -> HTMLResponse:
    form = await request.form()
    values = _submitted_values(form)
    property_key = editing_key or slugify_property_name(str(values.get("name", "")))
    errors: list[str] = []
    content = b""
    if not property_key:
        errors.append("name: debe permitir generar un Property ID válido.")
    else:
        try:
            content = render_property_document(
                _metadata(values, property_key),
                general_description=str(values.get("general_description", "")),
                distribution=str(values.get("distribution", "")),
            )
        except ValidationError as exc:
            errors.extend(exc.errors)
    preview = content.decode("utf-8")
    if errors or form.get("intent") == "preview":
        return _form_page(values=values, editing_key=editing_key, errors=errors or None, preview=preview)

    async with request.app.state.database.session_scope() as session:
        try:
            await property_writer(request, session).accept_upload(
                f"{property_key}.md",
                content,
                developer,
                actor_type="Administrator",
                create_only=editing_key is None,
                expected_property_key=editing_key,
                visit_address=str(values.get("visit_address", "")),
            )
        except ValidationError as exc:
            return _form_page(values=values, editing_key=editing_key, errors=exc.errors, preview=preview)
    return RedirectResponse(f"/admin/properties/{property_key}?saved=1", status_code=303)


@router.get("/properties", response_class=HTMLResponse)
async def inventory(request: Request, view: str = "active", _: str = Depends(require_developer)) -> HTMLResponse:
    if view not in {"active", "inactive", "all"}:
        view = "active"
    async with request.app.state.database.session_scope() as session:
        records = (await AdministrationService(session).list_properties())["properties"]
    filtered = [row for row in records if view == "all" or row["status"].casefold() == view]
    cells = []
    for row in filtered:
        reason = REASON_LABELS.get(row["inactive_reason"], "—")
        price = f"${format_amount(row['price_amount'])} {row['price_currency']}" if isinstance(row["price_amount"], (int, float)) else "—"
        if row["status"] == PropertyStatus.ACTIVE.value:
            status_action = f'<form class="inline" method="post" action="/admin/properties/{_e(row["property_id"])}/status"><input type="hidden" name="status" value="Inactive"><select name="inactive_reason" required>{REASON_OPTIONS}</select><button class="danger" onclick="return confirm(\'¿Marcar esta propiedad como inactiva?\')">Desactivar</button></form>'
        else:
            status_action = f'<form class="inline" method="post" action="/admin/properties/{_e(row["property_id"])}/status"><input type="hidden" name="status" value="Active"><button onclick="return confirm(\'¿Reactivar esta propiedad?\')">Reactivar</button></form>'
        cells.append(f"<tr><td><strong>{_e(row['name'])}</strong><br><span class='muted'>{_e(row['property_id'])}</span></td><td>{_e(TYPE_LABELS.get(row['property_type'],row['property_type']))}<br>{_e(OPERATION_LABELS.get(row['operation'],row['operation']))}</td><td>{_e(price)}</td><td><span class='status {_e(row['status'])}'>{_e(row['status'])}</span><br>{_e(reason)}</td><td>v{row['document_version']}<br><span class='muted'>{_e(row['updated_at'][:10])}</span></td><td>{row['confirmed_appointments']}</td><td><a href='/admin/properties/{_e(row['property_id'])}'>Ver</a> · <a href='/admin/properties/{_e(row['property_id'])}/edit'>Editar</a><br>{status_action}</td></tr>")
    rows = "".join(cells) or '<tr><td colspan="7" class="muted">No hay propiedades en esta vista.</td></tr>'
    tabs = "".join(f'<a class="{"current" if view == value else ""}" href="/admin/properties?view={value}">{label}</a>' for value, label in (("active","Activas"),("inactive","Inactivas"),("all","Todas")))
    return _layout("Propiedades", f'<div class="actions" style="float:right"><a class="button" href="/admin/properties/new">Agregar propiedad</a></div><h1>Propiedades</h1><div class="tabs">{tabs}</div><div class="card" style="overflow:auto"><table><thead><tr><th>Propiedad</th><th>Tipo</th><th>Precio</th><th>Disponibilidad</th><th>Documento</th><th>Visitas futuras</th><th>Acciones</th></tr></thead><tbody>{rows}</tbody></table></div>')


@router.get("/properties/new", response_class=HTMLResponse)
async def new_property(_: str = Depends(require_developer)) -> HTMLResponse:
    return _form_page(values=dict(NEW_PROPERTY_DEFAULTS), editing_key=None)


@router.post("/properties", response_class=HTMLResponse)
async def create_property(request: Request, developer: str = Depends(require_developer)) -> HTMLResponse:
    return await _render_submission(request, None, developer)


@router.get("/properties/{property_key}", response_class=HTMLResponse)
async def property_detail(request: Request, property_key: str, saved: int = 0, _: str = Depends(require_developer)) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        prop = await resolve_property(session, property_key)
        if prop is None:
            return _layout("No encontrada", '<div class="error">No se encontró esa propiedad.</div>')
        version = await accepted_version(session, prop)
        raw = await _read_document(request, version) if version else None
        markdown = raw.decode("utf-8") if raw else ""
        visits = await AdministrationService(session).confirmed_appointments(prop)
        name, status, reason, address = prop.name, prop.status, prop.inactive_reason, prop.visit_address
        number = version.version if version else 0
    banner = '<div class="ok">La propiedad y su nueva versión se guardaron correctamente.</div>' if saved else ""
    return _layout(name, f'<h1>{_e(name)}</h1>{banner}<div class="actions"><a class="button" href="/admin/properties/{_e(property_key)}/edit">Editar</a><a class="button secondary" href="/admin/properties">Volver</a></div><section class="card"><p><strong>Property ID:</strong> {_e(property_key)}</p><p><strong>Disponibilidad:</strong> {_e(status)} · {_e(REASON_LABELS.get(reason,"Sin razón"))}</p><p><strong>Versión:</strong> {number}</p><p><strong>Visitas futuras confirmadas:</strong> {visits}</p><p><strong>Dirección exacta para visitas:</strong> {_e(address or "No capturada")}</p></section><section class="card"><h2>Documento aprobado</h2><pre>{_e(markdown)}</pre></section>')


@router.get("/properties/{property_key}/edit", response_class=HTMLResponse)
async def edit_property(request: Request, property_key: str, _: str = Depends(require_developer)) -> HTMLResponse:
    async with request.app.state.database.session_scope() as session:
        prop = await resolve_property(session, property_key)
        if prop is None:
            return _layout("No encontrada", '<div class="error">No se encontró esa propiedad.</div>')
        version = await accepted_version(session, prop)
        if version is None:
            return _layout("Sin documento", '<div class="error">La propiedad no tiene una versión aceptada.</div>')
        raw = await _read_document(request, version)
        if raw is None:
            return _layout("Documento no disponible", '<div class="error">No se pudo leer el documento aceptado.</div>')
        # The facts were validated and stored when the version was accepted, so
        # the artifact is only reread for the narrative the form lets an
        # administrator edit. Revalidating here would make a document that a
        # later, stricter validator rejects impossible to open and correct.
        metadata = version.document_metadata
        _, body = split_front_matter(raw.decode("utf-8"))
        general, distribution = narrative_sections(body, str(metadata.get("name", "")))
        values = _form_defaults(metadata, visit_address=prop.visit_address, general=general, distribution=distribution)
    return _form_page(values=values, editing_key=property_key)


@router.post("/properties/{property_key}", response_class=HTMLResponse)
async def update_property(request: Request, property_key: str, developer: str = Depends(require_developer)) -> HTMLResponse:
    return await _render_submission(request, property_key, developer)


@router.post("/properties/{property_key}/status")
async def change_status(request: Request, property_key: str, developer: str = Depends(require_developer)) -> RedirectResponse:
    form = await request.form()
    status = str(form.get("status", ""))
    reason = str(form.get("inactive_reason", "")) or None
    async with request.app.state.database.session_scope() as session:
        result = await AdministrationService(session).set_property_status(
            property_key,
            status,
            Administrator(actor_id=developer),
            reason,
        )
        if result["result"] in {"updated", "unchanged"}:
            await session.commit()
    return RedirectResponse("/admin/properties", status_code=303)

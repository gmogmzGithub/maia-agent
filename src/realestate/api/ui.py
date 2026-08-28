"""One server-rendered shell for every operator surface.

Shared rather than duplicated because the parts that are easy to get wrong are
the parts that must not vary: the Spanish language attribute, the skip link, the
visible focus ring, the touch-target floor, the single-column collapse, and the
one place a status message is announced.

Everything here is Mexican Spanish. Internal vocabulary — lead, listing,
pipeline, property expert — does not appear in any string this module or its
callers render.

No JavaScript is required for any surface to work. Every action is an ordinary
form submission. A small progressive layer only exposes the pending state and
blocks a double click while the server confirms the result; without it, the
same authoritative redirect and idempotency key still govern the action.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.responses import HTMLResponse

#: The operation's timezone. Times are rendered in it because an operator in
#: Guadalajara reading UTC will mis-schedule a visit.
OPERATION_TIMEZONE = ZoneInfo("America/Mexico_City")

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def escape(value: object) -> str:
    """HTML-escape anything, including ``None``, for attribute or text use."""
    return html.escape("" if value is None else str(value), quote=True)


def local(moment: datetime | None) -> str:
    """A date and time an operator in Guadalajara can act on."""
    if moment is None:
        return "—"
    stamp = moment.astimezone(OPERATION_TIMEZONE)
    return (
        f"{stamp.day} {_MONTHS[stamp.month - 1]} {stamp.year}, "
        f"{stamp.strftime('%H:%M')}"
    )


def relative(moment: datetime | None, *, now: datetime) -> str:
    """How long ago, in words. Used beside the absolute time, never instead."""
    if moment is None:
        return "—"
    delta = now - moment
    seconds = int(delta.total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        text = "hace un momento"
    elif seconds < 3600:
        minutes = seconds // 60
        text = f"hace {minutes} min"
    elif seconds < 86400:
        hours = seconds // 3600
        text = f"hace {hours} h"
    else:
        days = seconds // 86400
        text = f"hace {days} día{'s' if days != 1 else ''}"
    if future:
        return text.replace("hace ", "en ")
    return text


def datetime_input_value(moment: datetime) -> str:
    """A ``datetime-local`` value in the operation's timezone."""
    return moment.astimezone(OPERATION_TIMEZONE).strftime("%Y-%m-%dT%H:%M")


def parse_datetime_input(raw: str) -> datetime | None:
    """Read a ``datetime-local`` value as an instant in the operation's zone.

    Returns ``None`` for anything unparseable rather than raising: the caller
    turns that into a Spanish validation message next to the field.
    """
    text = (raw or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return naive.replace(tzinfo=OPERATION_TIMEZONE)
    return None


@dataclass(frozen=True)
class NavLink:
    href: str
    label: str


#: The operator navigation. One list, so a surface cannot go missing from it.
NAV: tuple[NavLink, ...] = (
    NavLink("/crm", "Panel"),
    NavLink("/crm/bandeja", "Bandeja"),
    NavLink("/crm/agenda", "Agenda"),
    NavLink("/crm/oportunidades", "Oportunidades"),
    NavLink("/crm/contactos", "Contactos"),
    NavLink("/crm/asignacion", "Asignación"),
    NavLink("/crm/equipo", "Equipo"),
    NavLink("/crm/catalogo", "Catálogo"),
    NavLink("/crm/inventario-externo", "Inventario externo"),
)

# One stylesheet, inlined so a surface never renders unstyled while a separate
# request is in flight.
#
# The accessibility-relevant rules are grouped and commented, because they are
# the ones a later change is most likely to remove by accident.
STYLES = """
:root { color-scheme: light; --ink:#1f2933; --muted:#5b6472; --line:#d0d5dd;
  --brand:#1145b8; --bad:#a4231a; --ok:#026a3e; --warn:#8a5300;
  --surface:#fff; --bg:#f6f8fb; }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif }
header { background:var(--surface); border-bottom:1px solid var(--line) }
nav, main { max-width:1180px; margin:auto; padding:16px 20px }
nav { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center;
  justify-content:space-between }
nav ul { display:flex; flex-wrap:wrap; gap:4px; list-style:none; margin:0; padding:0 }
nav a { display:inline-block; padding:10px 12px; border-radius:6px;
  color:var(--brand); text-decoration:none; font-weight:600 }
nav a:hover { background:#e8eefc; text-decoration:underline }
/* The current surface is announced, not only coloured. */
nav a[aria-current="page"] { background:#e8eefc; color:#0b2d78 }
a { color:var(--brand) }

/* Keyboard users must always be able to see where they are. Never remove. */
a:focus-visible, button:focus-visible, input:focus-visible,
select:focus-visible, textarea:focus-visible, summary:focus-visible {
  outline:3px solid #0b57d0; outline-offset:2px }

/* Skip link: present for screen readers and keyboards, visible once focused. */
.skip { position:absolute; left:-9999px; top:0; background:var(--surface);
  padding:12px 16px; z-index:10 }
.skip:focus { left:8px }

h1 { font-size:1.5rem; margin:.2rem 0 1rem }
h2 { font-size:1.15rem; margin:1.6rem 0 .6rem }
h3 { font-size:1rem; margin:1.2rem 0 .4rem }
.card { background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:18px; margin:14px 0 }
.grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 20px }
.full { grid-column:1/-1 }
label { display:block; font-weight:650 }
input, select, textarea { width:100%; margin-top:5px; padding:11px 10px;
  border:1px solid #7b8698; border-radius:6px; font:inherit; background:#fff;
  min-height:44px }
textarea { min-height:96px; resize:vertical }
fieldset { border:1px solid var(--line); border-radius:8px; padding:12px 14px }
legend { font-weight:700 }
.actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:16px }
/* 44px minimum touch target on every control. */
button, .button { display:inline-flex; align-items:center; justify-content:center;
  min-height:44px; border:0; border-radius:6px; padding:11px 16px;
  background:var(--brand); color:#fff; font:inherit; font-weight:700;
  cursor:pointer; text-decoration:none }
button.secondary, .button.secondary { background:#3c4657 }
button.quiet { background:transparent; color:var(--brand);
  border:1px solid var(--line) }
button.danger { background:var(--bad) }
button:disabled { cursor:wait; opacity:.68 }
form[aria-busy="true"] { opacity:.82 }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0 }
.hint, .muted { color:var(--muted); font-size:.9rem }
.error { background:#fdf2f1; color:var(--bad); border-left:4px solid var(--bad);
  padding:12px 16px; border-radius:6px }
.ok { background:#ecfdf3; color:var(--ok); border-left:4px solid var(--ok);
  padding:12px 16px; border-radius:6px }
.warn { background:#fff8ec; color:var(--warn); border-left:4px solid var(--warn);
  padding:12px 16px; border-radius:6px }
table { width:100%; border-collapse:collapse; background:var(--surface) }
caption { text-align:left; padding:8px 4px; color:var(--muted); font-size:.9rem }
th, td { text-align:left; border-bottom:1px solid var(--line);
  padding:12px 10px; vertical-align:top }
th { font-size:.85rem; color:#3c4657 }
.tag { display:inline-block; padding:3px 9px; border-radius:999px;
  font-size:.8rem; font-weight:700; border:1px solid var(--line);
  background:#eef1f6; color:#2b3446 }
.tag.bad { background:#fdf2f1; border-color:#f1c8c4; color:var(--bad) }
.tag.ok { background:#ecfdf3; border-color:#bbe8cd; color:var(--ok) }
.tag.warn { background:#fff8ec; border-color:#f0d8ae; color:var(--warn) }
.filters { display:flex; flex-wrap:wrap; gap:10px 14px; align-items:flex-end }
/* Filter checkboxes: the box keeps its natural size, the label stays clickable
   at full width so the touch target is the whole row. */
label.check { display:flex; align-items:center; gap:8px; font-weight:400;
  min-height:44px }
label.check input { width:auto; min-height:auto; margin:0 }
.filters label { font-size:.9rem }
.filters .field { flex:1 1 180px }
.stats { display:grid; gap:12px;
  grid-template-columns:repeat(auto-fit,minmax(170px,1fr)) }
.stat { background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:14px }
.stat .value { font-size:1.6rem; font-weight:700 }
.thread { display:flex; flex-direction:column; gap:10px; margin:0; padding:0 }
.msg { border:1px solid var(--line); border-radius:10px; padding:12px 14px;
  background:var(--surface); max-width:46rem }
.msg.out { background:#eef4ff; margin-left:auto }
.msg .who { font-size:.8rem; color:var(--muted); font-weight:700 }
.msg .expired { font-style:italic; color:var(--muted) }
.empty { text-align:center; padding:34px 18px; color:var(--muted) }
dl.pairs { display:grid; grid-template-columns:minmax(9rem,auto) 1fr;
  gap:8px 16px; margin:0 }
dl.pairs dt { font-weight:700 }
dl.pairs dd { margin:0 }
ul.plain { list-style:none; margin:0; padding:0 }
[hidden] { display:none !important }
.checks { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px }
.checks label { min-height:44px; display:flex; align-items:center; font-weight:400 }
.checks input { width:auto; min-height:auto; margin:0 8px 0 0 }
.tabs { display:flex; flex-wrap:wrap; gap:4px; margin:10px 0 }
.tabs a { display:inline-flex; align-items:center; min-height:44px;
  padding:8px 12px; border-radius:6px; text-decoration:none }
.tabs a.current { background:#e8eefc; font-weight:700 }
.inline { display:inline }
.inline select { width:auto; margin:0 5px }
.status { font-weight:700 }
.Active { color:var(--ok) }
.Inactive { color:var(--bad) }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#101828;
  color:#f2f4f7; padding:16px; border-radius:8px }
textarea.preview { min-height:430px; font:13px/1.4 ui-monospace,monospace }
@media (max-width:760px) {
  .grid, .checks { grid-template-columns:1fr }
  /* Wide tables scroll horizontally instead of forcing the page to. */
  .table-scroll { overflow-x:auto }
  nav, main { padding:12px }
  nav ul { flex:1 1 100%; display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px }
  nav li, nav a { width:100% }
  .msg { max-width:100% }
  dl.pairs { grid-template-columns:1fr }
}
@media (prefers-contrast:more) {
  :root { --muted:#3c4657; --line:#8b95a5 }
}
"""


def layout(
    title: str,
    content: str,
    *,
    active: str = "",
    actor_label: str = "",
    role_label: str = "",
) -> HTMLResponse:
    """Wrap rendered content in the shared, accessible Spanish shell."""
    items = "".join(
        f'<li><a href="{escape(link.href)}"'
        f"{' aria-current="page"' if link.href == active else ''}>"
        f"{escape(link.label)}</a></li>"
        for link in NAV
    )
    who = ""
    if actor_label:
        who = (
            f'<p class="muted" style="margin:0">Sesión: '
            f"<strong>{escape(actor_label)}</strong>"
            f"{f' · {escape(role_label)}' if role_label else ''}</p>"
        )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Larevia</title>
<style>{STYLES}</style>
</head>
<body>
<a class="skip" href="#contenido">Ir al contenido principal</a>
<header>
<nav aria-label="Navegación principal">
<strong>Larevia · Operación</strong>
<ul>{items}</ul>
{who}
</nav>
</header>
<main id="contenido">
<h1>{escape(title)}</h1>
{content}
</main>
<div id="estado-envio" class="sr-only" role="status" aria-live="polite"></div>
<script>
document.addEventListener("submit", (event) => {{
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.dataset.submitting === "true") {{
    event.preventDefault();
    return;
  }}
  form.dataset.submitting = "true";
  form.setAttribute("aria-busy", "true");
  const button = event.submitter || form.querySelector('button[type="submit"]');
  if (button instanceof HTMLButtonElement) {{
    button.dataset.originalLabel = button.textContent || "";
    button.textContent = "Procesando…";
    button.disabled = true;
  }}
  const status = document.getElementById("estado-envio");
  if (status) status.textContent =
    "Procesando. Espera la confirmación del servidor.";
}});
window.addEventListener("pageshow", () => {{
  document.querySelectorAll('form[data-submitting="true"]').forEach((form) => {{
    form.removeAttribute("aria-busy");
    delete form.dataset.submitting;
    form.querySelectorAll("button[data-original-label]").forEach((button) => {{
      button.textContent = button.dataset.originalLabel || button.textContent;
      button.disabled = false;
      delete button.dataset.originalLabel;
    }});
  }});
  const status = document.getElementById("estado-envio");
  if (status) status.textContent = "";
}});
</script>
</body>
</html>"""
    )


def flash(message: str | None, kind: str = "ok") -> str:
    """One status region, announced politely, or nothing at all."""
    if not message:
        return ""
    return (
        f'<div class="{escape(kind)}" role="status" aria-live="polite">'
        f"{escape(message)}</div>"
    )


def errors_box(errors: list[str]) -> str:
    """Validation problems as a list, announced assertively."""
    if not errors:
        return ""
    items = "".join(f"<li>{escape(error)}</li>" for error in errors)
    return (
        '<div class="error" role="alert"><strong>No se guardó el cambio.</strong>'
        f"<ul>{items}</ul></div>"
    )


def empty(message: str, hint: str = "") -> str:
    """An empty state that tells the operator what to do next."""
    extra = f'<p class="hint">{escape(hint)}</p>' if hint else ""
    return (
        f'<div class="card empty"><p><strong>{escape(message)}</strong></p>'
        f"{extra}</div>"
    )


def table(
    caption: str,
    headers: tuple[str, ...],
    rows: str,
    *,
    empty_message: str = "",
    empty_hint: str = "",
) -> str:
    """One list, or one empty state.

    Every operator list goes through here so the accessibility contract cannot
    vary between them: a ``<caption>`` saying what the table holds, ``scope`` on
    every header, and a horizontal scroll container so a wide table does not
    force the whole page sideways on a phone. Thirteen hand-written copies held
    that contract only because they happened to agree.
    """
    if not rows:
        return empty(empty_message or "No hay nada que mostrar.", empty_hint)
    head = "".join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    return (
        '<div class="table-scroll"><table>'
        f"<caption>{escape(caption)}</caption>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def checkbox(name: str, label: str, checked: bool) -> str:
    """One filter checkbox, sized and labelled the same way everywhere."""
    return (
        f'<label class="check"><input type="checkbox" name="{escape(name)}"'
        f' value="1"{" checked" if checked else ""}> {escape(label)}</label>'
    )


def options(
    values: tuple[str, ...] | list[str],
    current: object,
    labels: dict[str, str] | None = None,
) -> str:
    """``<option>`` markup with the current value selected."""
    shown = labels or {}
    return "".join(
        f'<option value="{escape(value)}"'
        f"{' selected' if str(current) == value else ''}>"
        f"{escape(shown.get(value, value))}</option>"
        for value in values
    )

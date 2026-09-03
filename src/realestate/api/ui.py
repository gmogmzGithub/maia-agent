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
import re
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


def counted(count: int, singular: str, plural: str | None = None) -> str:
    """Render a natural Spanish count without mechanical ``(s)`` suffixes."""
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


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
    administrator_only: bool = False
    mobile_label: str | None = None


@dataclass(frozen=True)
class NavGroup:
    label: str
    links: tuple[NavLink, ...]


#: The approved information architecture. Role visibility is encoded here so
#: an unauthorized destination is absent from desktop, tablet and mobile alike.
NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup(
        "Trabajo",
        (
            NavLink("/crm", "Hoy"),
            NavLink("/crm/bandeja", "Bandeja"),
            NavLink("/crm/agenda", "Agenda"),
            NavLink("/crm/oportunidades", "Oportunidades", mobile_label="Oportun."),
        ),
    ),
    NavGroup("Relaciones", (NavLink("/crm/contactos", "Contactos"),)),
    NavGroup(
        "Inventario",
        (
            NavLink("/crm/catalogo", "Catálogo"),
            NavLink("/crm/inventario-externo", "Inventario externo", True),
        ),
    ),
    NavGroup(
        "Crecimiento",
        (
            NavLink("/crm/reactivacion", "Reactivación", True),
            NavLink("/crm/patrocinios", "Patrocinios", True),
        ),
    ),
    NavGroup(
        "Gestión",
        (
            NavLink("/crm/asignacion", "Asignación", True),
            NavLink("/crm/equipo", "Equipo"),
            NavLink("/crm/bi", "Inteligencia", True),
            NavLink("/crm/plataforma", "Configuración", True),
        ),
    ),
)

# Flat compatibility view for code that needs to assert route coverage rather
# than render the grouped information architecture.
NAV: tuple[NavLink, ...] = tuple(link for group in NAV_GROUPS for link in group.links)


# Restrained, line-based navigation symbols make the larger Administrator
# workspace easier to scan without replacing the visible Spanish labels. They
# are presentation only: the link text remains the accessible name.
_NAV_ICONS: dict[str, str] = {
    "/crm": '<path d="M4 10.5 10 5l6 5.5v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M8 16v-4h4v4"/>',
    "/crm/bandeja": '<path d="M3.5 5.5h13v9h-13z"/><path d="M3.5 11h3l1.5 2h4l1.5-2h3"/>',
    "/crm/agenda": '<rect x="3.5" y="4.5" width="13" height="12" rx="2"/><path d="M6.5 3v3M13.5 3v3M3.5 8h13"/>',
    "/crm/oportunidades": '<circle cx="10" cy="10" r="6.5"/><path d="m7.5 10 1.7 1.7 3.6-4"/>',
    "/crm/contactos": '<path d="M6.5 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM1.8 16.5c.4-3.1 2-4.7 4.7-4.7s4.3 1.6 4.7 4.7M13 8.5a2.5 2.5 0 0 0 0-5M13 11.8c2.5.2 3.8 1.8 4.1 4.7"/>',
    "/crm/catalogo": '<path d="M3.5 6.5 10 3l6.5 3.5v9L10 18l-6.5-2.5z"/><path d="M3.5 6.5 10 10l6.5-3.5M10 10v8"/>',
    "/crm/inventario-externo": '<circle cx="10" cy="10" r="6.5"/><path d="M3.8 8h12.4M3.8 12h12.4M10 3.5c2 2 2.7 4.2 2.7 6.5S12 14.5 10 16.5C8 14.5 7.3 12.3 7.3 10S8 5.5 10 3.5Z"/>',
    "/crm/reactivacion": '<path d="M4.5 7.5A6 6 0 1 1 4 12"/><path d="M3.5 4v4h4"/>',
    "/crm/patrocinios": '<path d="m10 3 2.1 4.2 4.7.7-3.4 3.3.8 4.7-4.2-2.2-4.2 2.2.8-4.7L3.2 8l4.7-.7z"/>',
    "/crm/asignacion": '<path d="M7 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2 16.5c.4-3 2-4.5 5-4.5 1.2 0 2.2.2 3 .7M12 10h5M14.5 7.5 17 10l-2.5 2.5"/>',
    "/crm/equipo": '<path d="M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM1.5 16.5c.4-3 1.9-4.5 4.5-4.5s4.1 1.5 4.5 4.5M13 9a2.5 2.5 0 1 0 0-5M13 12c2.6 0 4.1 1.5 4.5 4.5"/>',
    "/crm/bi": '<path d="M4 16.5v-5h3v5M8.5 16.5v-9h3v9M13 16.5v-12h3v12M3 16.5h14"/>',
    "/crm/plataforma": '<circle cx="10" cy="10" r="2.5"/><path d="M10 2.5v2M10 15.5v2M17.5 10h-2M4.5 10h-2M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4M15.3 15.3l-1.4-1.4M6.1 6.1 4.7 4.7"/>',
    "/crm/alertas": '<path d="M5 14.5h10l-1.2-1.8V9a3.8 3.8 0 0 0-7.6 0v3.7zM8.3 16.5h3.4"/>',
    "more": '<circle cx="4.5" cy="10" r="1" fill="currentColor" stroke="none"/><circle cx="10" cy="10" r="1" fill="currentColor" stroke="none"/><circle cx="15.5" cy="10" r="1" fill="currentColor" stroke="none"/>',
}


def _nav_icon(href: str) -> str:
    paths = _NAV_ICONS.get(href, '<circle cx="10" cy="10" r="5"/>')
    return (
        '<span class="nav-icon" aria-hidden="true">'
        '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths}'
        "</svg></span>"
    )


# One stylesheet, inlined so a surface never renders unstyled while a separate
# request is in flight.
#
# The accessibility-relevant rules are grouped and commented, because they are
# the ones a later change is most likely to remove by accident.
STYLES = """
@font-face { font-family:Inter; src:url('/crm-assets/fonts/inter/inter-variable.ttf')
  format('truetype'); font-weight:100 900; font-display:swap }
@font-face { font-family:Newsreader; src:url('/crm-assets/fonts/newsreader/newsreader-variable.ttf')
  format('truetype'); font-weight:200 800; font-display:swap }
:root { color-scheme:light; --ink:#17211d; --muted:#59675f; --line:#d9d6cd;
  --brand:#315c4c; --brand-deep:#12201b; --bad:#8b2520; --overdue:#7a2e22;
  --ok:#214f36; --warn:#664a05; --surface:#fff; --bg:#f7f5ef;
  --selected:#e5efeb; --attention:#fbf1d6; --blocked:#f9e8e3;
  --restricted:#f8e5e3; --confirmed:#e6f0e9; --neutral:#eceae3;
  --surface-soft:#fbfbf8; --line-soft:#e6e3dc; --rail:236px;
  --radius-small:10px; --radius:16px; --radius-large:22px;
  --shadow:0 1px 2px #17211d0a,0 10px 28px #17211d0a;
  --shadow-raised:0 14px 40px #17211d1a; }
* { box-sizing:border-box }
html { min-width:320px; background:var(--bg) }
body { margin:0; overflow-x:hidden; background:var(--bg); color:var(--ink);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,Inter,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility }
button, input, select, textarea { font-family:inherit }
a { color:var(--brand); text-underline-offset:3px }
.crm-shell { min-height:100vh; display:grid; grid-template-columns:var(--rail) minmax(0,1fr) }
.rail { position:sticky; top:0; height:100vh; overflow-y:auto; display:flex;
  flex-direction:column; padding:22px 14px 16px; background:#f2f2ee;
  border-right:1px solid var(--line-soft); color:var(--ink) }
.brand-lockup { display:flex; align-items:center; gap:11px; min-height:48px;
  padding:0 8px; margin-bottom:24px }
.brand-mark { display:inline-flex; align-items:center; justify-content:center; width:36px;
  height:36px; flex:0 0 36px; border-radius:11px; background:var(--brand); color:#fff;
  font-size:.95rem; font-weight:800; letter-spacing:-.04em; box-shadow:0 6px 18px #315c4c25 }
.brand-copy { min-width:0; display:flex; flex-direction:column }
.brand { overflow:hidden; color:var(--ink); font-size:1.05rem; line-height:1.2;
  font-weight:760; letter-spacing:-.018em; text-decoration:none; text-overflow:ellipsis;
  white-space:nowrap }
.powered { margin:2px 0 0; color:var(--muted); font-size:.68rem; font-weight:560;
  letter-spacing:.01em }
.rail-nav { display:block; margin:0; padding:0 }
.rail-nav ul { list-style:none; margin:0; padding:0 }
.nav-group { margin:0 0 18px }
.nav-group-title { margin:0 10px 6px; color:var(--muted); font-size:.68rem;
  font-weight:720; letter-spacing:.06em; text-transform:uppercase }
.rail-nav a, .mobile-more-menu a { display:flex; align-items:center; gap:10px;
  min-height:42px; padding:6px 9px; border-radius:11px; color:var(--ink);
  text-decoration:none; font-size:.91rem; font-weight:560 }
.nav-icon { display:inline-flex; align-items:center; justify-content:center; width:29px;
  height:29px; flex:0 0 29px; border:1px solid var(--line-soft); border-radius:9px;
  background:#fff; color:var(--muted) }
.nav-icon svg { width:18px; height:18px }
.nav-label { min-width:0; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
.rail-nav a:hover, .mobile-more-menu a:hover { background:#fff; color:var(--brand) }
/* The current surface is announced, not only coloured. */
.rail-nav a[aria-current="page"], .mobile-more-menu a[aria-current="page"] {
  background:var(--selected); color:var(--brand); font-weight:720 }
.rail-nav a[aria-current="page"] .nav-icon,
.mobile-more-menu a[aria-current="page"] .nav-icon {
  border-color:var(--brand); background:var(--brand); color:#fff }
.rail-footer { margin-top:auto; padding:14px 8px 0; border-top:1px solid var(--line-soft) }
.alerts-link { display:flex; align-items:center; gap:10px; min-height:44px; padding:6px 1px;
  color:var(--ink); text-decoration:none; font-size:.91rem; font-weight:650 }
.alerts-link .nav-label { flex:1 }
.alerts-link[aria-current="page"] { color:var(--brand) }
.alert-count { display:inline-flex; align-items:center; justify-content:center;
  min-width:25px; min-height:25px; padding:0 7px; border-radius:999px;
  background:var(--bad); color:#fff; font-size:.73rem; font-weight:800 }
.session { display:grid; grid-template-columns:34px minmax(0,1fr); gap:9px;
  align-items:center; margin:12px 0 0; padding:10px; border-radius:13px;
  background:#fff; color:var(--muted); font-size:.72rem; box-shadow:0 1px 2px #17211d0a }
.session-avatar { display:inline-flex; align-items:center; justify-content:center; width:34px;
  height:34px; border-radius:50%; background:var(--selected); color:var(--brand);
  font-size:.75rem; font-weight:800 }
.session-copy { min-width:0 }
.session strong { display:block; overflow:hidden; color:var(--ink); font-size:.8rem;
  font-weight:680; text-overflow:ellipsis; white-space:nowrap }
.main-wrap { min-width:0; width:100%; max-width:1460px; padding:40px 48px 100px }
.page-header { margin:0 0 30px }
.page-context { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:9px 0 0;
  color:var(--muted); font-size:.84rem }
.context-chip { display:inline-flex; align-items:center; min-height:28px; padding:4px 10px;
  border:1px solid var(--line-soft); border-radius:999px; background:#ffffffb8 }
.context-time { display:inline-flex; align-items:center; min-height:28px }
.mobile-top, .mobile-bottom { display:none }

/* Keyboard users must always be able to see where they are. Never remove. */
a:focus-visible, button:focus-visible, input:focus-visible,
select:focus-visible, textarea:focus-visible, summary:focus-visible {
  outline:3px solid #0b57d0; outline-offset:2px }

/* Skip link: present for screen readers and keyboards, visible once focused. */
.skip { position:fixed; left:-9999px; top:0; padding:12px 16px; z-index:100;
  border-radius:10px; background:var(--surface); box-shadow:var(--shadow-raised) }
.skip:focus { left:8px; top:8px }

h1, h2, h3, p { overflow-wrap:break-word }
h1 { max-width:62rem; margin:0; font-size:clamp(2rem,3vw,2.65rem); line-height:1.08;
  font-weight:760; letter-spacing:-.045em }
h2 { margin:2rem 0 .75rem; font-size:1.24rem; line-height:1.25;
  font-weight:720; letter-spacing:-.018em }
h3 { margin:1.25rem 0 .45rem; font-size:1rem; font-weight:700 }
.lead { max-width:72ch; margin:.25rem 0 1.5rem; color:var(--muted); font-size:1.02rem }
.card { margin:16px 0; padding:22px; border:1px solid var(--line-soft);
  border-radius:var(--radius); background:var(--surface); box-shadow:var(--shadow) }
.card > :first-child { margin-top:0 }
.card > :last-child { margin-bottom:0 }
.note { margin:14px 0; padding:14px 16px; border-radius:var(--radius-small);
  background:var(--selected); color:var(--brand) }
.grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px 20px }
.full { grid-column:1/-1 }
.field { min-width:0 }
label { display:block; color:var(--ink); font-size:.91rem; font-weight:650 }
input, select, textarea { width:100%; max-width:100%; min-width:0; min-height:46px; margin-top:6px; padding:11px 12px;
  border:1px solid #7b8698; border-radius:11px; background:#fff; color:var(--ink);
  font-size:1rem; line-height:1.35; transition:border-color .15s ease,box-shadow .15s ease }
input:hover, select:hover, textarea:hover { border-color:#59675f }
input:focus, select:focus, textarea:focus { border-color:var(--brand);
  box-shadow:0 0 0 4px #315c4c18 }
textarea { min-height:104px; resize:vertical }
fieldset { min-width:0; margin:0; padding:11px 14px; border:1px solid var(--line);
  border-radius:12px }
legend { padding:0 5px; font-size:.86rem; font-weight:680 }
.actions { display:flex; gap:9px; flex-wrap:wrap; margin-top:18px }
/* 44px minimum touch target on every control. */
button, .button { display:inline-flex; align-items:center; justify-content:center;
  min-height:44px; padding:10px 16px; border:1px solid transparent; border-radius:11px;
  background:var(--brand); color:#fff; font:inherit; font-size:.92rem; font-weight:690;
  cursor:pointer; text-decoration:none; box-shadow:0 1px 2px #17211d14;
  transition:transform .15s ease,background .15s ease,box-shadow .15s ease }
button:hover, .button:hover { background:#274c40; box-shadow:0 5px 16px #17211d18 }
button:active, .button:active { transform:translateY(1px); box-shadow:none }
button.secondary, .button.secondary { background:#46534c }
button.quiet, .button.quiet { border-color:var(--line); background:#fff; color:var(--brand);
  box-shadow:none }
button.quiet:hover, .button.quiet:hover { border-color:var(--brand); background:var(--selected) }
button.danger { background:var(--bad) }
button:disabled { cursor:wait; opacity:.68 }
form[aria-busy="true"] { opacity:.82 }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0 }
.hint, .muted { color:var(--muted); font-size:.88rem }
.error, .ok, .warn { margin:14px 0; padding:14px 16px; border:1px solid transparent;
  border-radius:14px }
.error { border-color:#edc8bd; background:var(--restricted); color:var(--bad) }
.ok { border-color:#bed8c5; background:var(--confirmed); color:var(--ok) }
.warn { border-color:#ead59b; background:var(--attention); color:var(--warn) }
.read-only { position:sticky; top:0; z-index:20; margin:-40px -48px 28px;
  padding:11px 48px; background:var(--attention); color:var(--warn);
  border-bottom:1px solid #d3a446; font-weight:700 }
.table-scroll { width:100%; overflow:auto; border:1px solid var(--line-soft);
  border-radius:var(--radius); background:var(--surface); box-shadow:var(--shadow) }
table { width:100%; border-collapse:collapse; background:transparent }
caption { padding:15px 18px 11px; color:var(--muted); text-align:left; font-size:.82rem }
th, td { padding:14px 16px; border-bottom:1px solid var(--line-soft);
  text-align:left; vertical-align:top }
tbody tr:last-child td { border-bottom:0 }
tbody tr { transition:background .12s ease }
tbody tr:hover { background:var(--surface-soft) }
th { color:#3c4657; background:var(--surface-soft); font-size:.75rem; font-weight:720;
  letter-spacing:.025em; text-transform:uppercase }
td > a:first-child { font-weight:650 }
.tag { display:inline-flex; align-items:center; min-height:25px; padding:3px 9px;
  border:1px solid var(--line); border-radius:999px; background:var(--neutral);
  color:#4c554f; font-size:.75rem; font-weight:680; white-space:nowrap }
.tag.bad { border-color:#edc8bd; background:var(--blocked); color:var(--overdue) }
.tag.ok { border-color:#bed8c5; background:var(--confirmed); color:var(--ok) }
.tag.warn { border-color:#ead59b; background:var(--attention); color:var(--warn) }
.filters { display:flex; flex-wrap:wrap; gap:13px 16px; align-items:flex-end }
.filters .field { flex:1 1 190px }
.filters label { font-size:.86rem }
label.check, label.checkbox { display:flex; align-items:center; gap:9px; min-height:42px;
  font-weight:450 }
label.check input, label.checkbox input, .checks input { width:18px; height:18px;
  min-height:18px; margin:0; accent-color:var(--brand) }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px }
.stat { min-width:0; padding:19px; border:1px solid var(--line-soft);
  border-radius:var(--radius); background:var(--surface); box-shadow:var(--shadow) }
.stat .value { margin:3px 0 7px; font-size:1.75rem; line-height:1.08;
  font-weight:740; letter-spacing:-.035em }
.stat a { display:inline-flex; margin-top:10px; font-size:.88rem; font-weight:650 }
.operational-summary { position:relative; margin:0 0 30px; padding:18px 20px 18px 52px;
  border:1px solid #ead59b; border-radius:var(--radius); background:#fff8e8;
  box-shadow:0 8px 24px #d3a44612 }
.operational-summary::before { content:""; position:absolute; left:20px; top:21px;
  width:12px; height:12px; border:4px solid #d3a446; border-radius:50% }
.operational-summary strong { display:block; margin-bottom:3px; font-size:1.02rem }
.priority-list { margin:0; padding:0; overflow:hidden; list-style:none;
  border:1px solid var(--line-soft); border-radius:var(--radius-large);
  background:var(--surface); box-shadow:var(--shadow) }
.priority-row { display:grid; grid-template-columns:88px minmax(250px,3fr)
  minmax(150px,1.1fr) minmax(118px,auto); gap:18px; align-items:center;
  padding:18px 20px; border-bottom:1px solid var(--line-soft) }
.priority-row:last-child { border-bottom:0 }
.priority-row:hover { background:var(--surface-soft) }
.priority-reason { font-size:1rem; font-weight:690; letter-spacing:-.008em }
.priority-meta, .priority-owner { color:var(--muted); font-size:.86rem }
.priority-owner { overflow-wrap:anywhere }
.priority-owner::before { content:"Responsable"; display:block; color:var(--muted);
  font-size:.64rem; font-weight:720; letter-spacing:.04em; text-transform:uppercase }
.priority-action { justify-self:end; min-width:112px }
.priority-now { background:var(--blocked); color:var(--overdue) }
.priority-today, .priority-review { background:var(--attention); color:var(--warn) }
.priority-soon { background:var(--selected); color:var(--brand) }
.priority-label { display:inline-flex; width:max-content; padding:5px 9px;
  border-radius:999px; font-size:.68rem; font-weight:800; text-transform:uppercase }
.work-section { margin-top:34px }
.work-section-header { display:flex; justify-content:space-between; gap:16px;
  align-items:end; margin-bottom:12px }
.work-section-header h2 { margin:0 }
.work-section-header p { margin:3px 0 0; color:var(--muted); font-size:.86rem }
.funnel { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:1px;
  overflow:hidden; margin:0; padding:1px; border:1px solid var(--line-soft);
  border-radius:var(--radius-large); background:var(--line-soft); box-shadow:var(--shadow);
  list-style:none }
.funnel-step { min-width:0; background:var(--surface) }
.funnel-step a { display:flex; min-height:104px; padding:17px; flex-direction:column;
  justify-content:space-between; color:var(--ink); text-decoration:none }
.funnel-step a:hover { background:var(--surface-soft) }
.funnel-count { font-size:1.75rem; line-height:1; font-weight:750; letter-spacing:-.04em }
.funnel-label { color:var(--muted); font-size:.78rem; font-weight:680 }
.funnel-states { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px;
  margin-top:9px }
.funnel-state { display:flex; align-items:center; justify-content:space-between; gap:12px;
  min-height:48px; padding:10px 14px; border:1px solid var(--line-soft);
  border-radius:12px; background:var(--surface); color:var(--ink); text-decoration:none }
.funnel-state span { color:var(--muted); font-size:.82rem }
.funnel-state strong { font-size:1.05rem }
.priority-more { margin:12px 4px 0; color:var(--muted); font-size:.86rem }
.secondary-work { margin-top:30px; border-top:1px solid var(--line-soft) }
.secondary-work > summary { width:max-content; max-width:100%; padding:16px 2px;
  font-size:.9rem }
.secondary-work-content { padding:0 0 16px }
.secondary-work-content > h2:first-child { margin-top:10px }
.next-obligation { padding:24px; border:1px solid var(--line-soft);
  border-radius:var(--radius-large); background:var(--surface); box-shadow:var(--shadow) }
.next-obligation h2 { margin:.7rem 0 .3rem; font-size:1.5rem }
.workspace { display:grid; gap:16px }
.conversation-workspace { grid-template-columns:minmax(220px,.78fr) minmax(400px,1.8fr)
  minmax(250px,.92fr); align-items:start }
.opportunity-workspace { grid-template-columns:minmax(0,2.4fr) minmax(260px,.85fr);
  align-items:start }
.workspace-panel { min-width:0; padding:20px; border:1px solid var(--line-soft);
  border-radius:var(--radius-large); background:var(--surface); box-shadow:var(--shadow) }
.workspace-panel > :first-child { margin-top:0 }
.queue-list { display:grid; gap:8px; margin:0; padding:0; list-style:none }
.queue-panel, .queue-list, .queue-item, .queue-item a { min-width:0 }
.queue-item a { display:block; min-height:44px; padding:13px; border:1px solid var(--line-soft);
  border-radius:13px; background:var(--surface); color:var(--ink); text-decoration:none }
.queue-item a:hover { border-color:var(--brand); background:var(--surface-soft) }
.queue-item.selected a { border-color:#b9d3ca; background:var(--selected);
  box-shadow:inset 3px 0 var(--brand) }
.queue-item strong { display:block; margin:7px 0 3px }
.queue-preview { overflow:hidden; color:var(--muted); font-size:.86rem;
  text-overflow:ellipsis; white-space:nowrap }
.queue-item .muted { display:block; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap }
.sticky-rail { position:sticky; top:24px }
.opportunity-summary { display:grid; grid-template-columns:repeat(5,minmax(120px,1fr));
  gap:1px; overflow:hidden; margin:0 0 20px; padding:1px;
  border:1px solid var(--line-soft); border-radius:var(--radius);
  background:var(--line-soft); box-shadow:var(--shadow) }
.opportunity-summary > div { padding:16px; background:var(--surface) }
.summary-label { display:block; color:var(--muted); font-size:.68rem; font-weight:700;
  letter-spacing:.035em; text-transform:uppercase }
.summary-value { display:block; min-width:0; margin-top:6px; font-weight:680;
  overflow-wrap:anywhere }
.opportunity-workspace .sticky-rail .grid { grid-template-columns:minmax(0,1fr) }
.opportunity-workspace .sticky-rail form,
.opportunity-workspace .sticky-rail label { min-width:0 }
.opportunity-workspace .sticky-rail .full { grid-column:auto }
.outcome-disclosure { margin-top:14px; border-top:1px solid var(--line-soft) }
.outcome-disclosure > summary { padding:13px 0; color:var(--ink); font-size:.95rem }
.outcome-body { padding:0 0 10px }
.criteria-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:9px }
.criterion { padding:13px 14px; border:1px solid #bed8c5; border-radius:12px;
  background:var(--confirmed) }
.criterion.pending { border-color:#ead59b; background:var(--attention) }
.timeline { margin:0; padding:0 0 0 18px; border-left:2px solid var(--line); list-style:none }
.timeline li { position:relative; padding:0 0 18px 12px }
.timeline li::before { content:""; position:absolute; left:-18px; top:.35rem; width:9px;
  height:9px; border:2px solid var(--surface); border-radius:50%; background:var(--brand) }
.thread { display:flex; flex-direction:column; gap:10px; margin:0; padding:0;
  list-style:none }
.msg { max-width:46rem; padding:12px 14px; border:1px solid var(--line-soft);
  border-radius:15px; background:var(--surface-soft) }
.msg.out { margin-left:auto; border-color:#c9ded6; background:var(--selected) }
.msg .who { margin-bottom:3px; color:var(--muted); font-size:.75rem; font-weight:680 }
.msg .expired { color:var(--muted); font-style:italic }
.empty { padding:38px 18px; text-align:center; color:var(--muted) }
.empty strong { color:var(--ink) }
dl.pairs { display:grid; grid-template-columns:minmax(8.5rem,auto) 1fr;
  gap:9px 16px; margin:0 }
dl.pairs dt { color:var(--muted); font-size:.83rem; font-weight:650 }
dl.pairs dd { min-width:0; margin:0; overflow-wrap:anywhere }
.context-panel dl.pairs { grid-template-columns:1fr; gap:2px }
.context-panel dl.pairs dd { margin-bottom:10px }
.context-panel .table-scroll { overflow:visible; border:0; border-radius:0;
  background:transparent; box-shadow:none }
.context-panel table, .context-panel thead, .context-panel tbody,
.context-panel tr, .context-panel th, .context-panel td { display:block; width:100% }
.context-panel thead { position:absolute; width:1px; height:1px; overflow:hidden;
  clip:rect(0,0,0,0) }
.context-panel tr { margin:0 0 10px; padding:12px; border:1px solid var(--line-soft);
  border-radius:12px; background:var(--surface-soft) }
.context-panel td { padding:6px 0; border:0; overflow-wrap:anywhere }
.context-panel td::before { content:attr(data-label); display:block; color:var(--muted);
  font-size:.64rem; font-weight:720; letter-spacing:.035em; text-transform:uppercase }
.context-panel caption { display:block; padding:8px 0 }
ul.plain { margin:0; padding:0; list-style:none }
[hidden] { display:none !important }
.checks { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px }
.checks label { display:flex; align-items:center; min-height:44px; font-weight:450 }
.tabs { display:inline-flex; flex-wrap:wrap; gap:3px; max-width:100%; margin:10px 0;
  padding:3px; border-radius:12px; background:var(--neutral) }
.tabs a { display:inline-flex; align-items:center; min-height:38px; padding:7px 11px;
  border-radius:9px; text-decoration:none; font-size:.88rem }
.tabs a.current { background:var(--surface); font-weight:680; box-shadow:0 1px 4px #17211d14 }
.inline { display:inline }
.inline select { width:auto; max-width:100%; margin:0 5px }
.status { font-weight:700 }
.Active { color:var(--ok) }
.Inactive { color:var(--bad) }
details > summary { min-height:44px; padding:10px 0; color:var(--brand); font-weight:650;
  cursor:pointer }
pre { padding:16px; border-radius:12px; background:#101828; color:#f2f4f7;
  white-space:pre-wrap; overflow-wrap:anywhere }
textarea.preview { min-height:430px; font:13px/1.4 ui-monospace,monospace }

@media (max-width:1180px) {
  .main-wrap { padding-right:32px; padding-left:32px }
  .read-only { margin-right:-32px; margin-left:-32px; padding-right:32px; padding-left:32px }
  .priority-row { grid-template-columns:78px minmax(230px,2fr) minmax(130px,1fr) auto;
    gap:14px; padding:16px }
}
@media (max-width:1023px) {
  .crm-shell { display:block }
  .rail { display:none }
  .mobile-top { position:sticky; top:0; z-index:35; display:flex; align-items:center;
    justify-content:space-between; gap:14px; min-height:66px; padding:9px 22px;
    border-bottom:1px solid var(--line-soft); background:#f7f5efeb; color:var(--ink);
    backdrop-filter:saturate(180%) blur(18px); -webkit-backdrop-filter:saturate(180%) blur(18px) }
  .mobile-top .brand-lockup { min-width:0; min-height:46px; margin:0; padding:0 }
  .mobile-top .brand-mark { width:34px; height:34px; flex-basis:34px; border-radius:10px }
  .mobile-top .brand { font-size:1rem }
  .mobile-top .powered { font-size:.64rem }
  .mobile-identity { display:flex; align-items:center; gap:8px; min-width:0;
    color:var(--muted); font-size:.76rem; text-align:right }
  .mobile-identity .session-avatar { flex:0 0 34px }
  .mobile-scope { display:block; max-width:130px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap }
  .main-wrap { max-width:none; padding:30px 28px 104px }
  .read-only { margin:-30px -28px 24px; padding:11px 28px }
  .conversation-workspace { grid-template-columns:minmax(215px,.65fr) minmax(0,1.45fr) }
  .conversation-workspace .context-panel { grid-column:1/-1 }
  .opportunity-summary { grid-template-columns:repeat(3,minmax(120px,1fr)) }
  .funnel { grid-template-columns:repeat(3,minmax(0,1fr)) }
}
@media (max-width:760px) {
  .grid, .checks { grid-template-columns:1fr }
  .main-wrap { padding:24px 16px 106px }
  .page-header { margin-bottom:24px }
  h1 { font-size:clamp(1.75rem,9vw,2.15rem); letter-spacing:-.04em }
  h2 { margin-top:1.7rem }
  .read-only { margin:-24px -16px 22px; padding:10px 16px }
  .mobile-top { padding:8px 14px }
  .mobile-identity .mobile-scope { display:none }
  .mobile-bottom { position:fixed; left:0; right:0; bottom:0; z-index:40;
    display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); min-height:72px;
    padding:5px max(3px,env(safe-area-inset-right)) max(5px,env(safe-area-inset-bottom))
      max(3px,env(safe-area-inset-left)); border-top:1px solid var(--line-soft);
    background:#fffffff2; box-shadow:0 -8px 28px #17211d0d;
    backdrop-filter:saturate(180%) blur(18px); -webkit-backdrop-filter:saturate(180%) blur(18px) }
  .mobile-bottom > a, .mobile-bottom summary { display:flex; flex-direction:column;
    align-items:center; justify-content:center; gap:1px; min-width:0; min-height:58px;
    padding:4px 1px; border-radius:11px; color:var(--muted); text-align:center;
    text-decoration:none; font-size:.64rem; line-height:1.05; font-weight:620;
    cursor:pointer; list-style:none }
  .mobile-bottom .nav-icon { width:29px; height:29px; border:0; background:transparent }
  .mobile-bottom .nav-icon svg { width:20px; height:20px }
  .mobile-bottom .nav-label { flex:0 1 auto; width:100%; overflow:visible;
    text-overflow:clip; white-space:normal }
  .mobile-bottom a[aria-current="page"] { background:var(--selected); color:var(--brand);
    font-weight:760 }
  .mobile-bottom a[aria-current="page"] .nav-icon { background:transparent; color:var(--brand) }
  .mobile-more { position:relative; min-width:0 }
  .mobile-more summary::-webkit-details-marker { display:none }
  .mobile-more-menu { position:absolute; right:4px; bottom:68px; width:min(310px,calc(100vw - 24px));
    max-height:72vh; overflow:auto; padding:10px; border:1px solid var(--line-soft);
    border-radius:18px; background:var(--surface); box-shadow:var(--shadow-raised) }
  .mobile-more-menu ul { margin:0; padding:0; list-style:none }
  .mobile-more-menu a { min-height:46px; padding:7px 9px }
  .card { padding:18px; border-radius:15px }
  .filters .field { flex-basis:100% }
  .actions > button, .actions > .button { flex:1 1 auto }
  .table-scroll { overflow:visible; border:0; border-radius:0; background:transparent;
    box-shadow:none }
  table, thead, tbody, tr, th, td { display:block; width:100% }
  thead { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0) }
  tr { margin:0 0 12px; padding:15px; border:1px solid var(--line-soft);
    border-radius:15px; background:var(--surface); box-shadow:var(--shadow) }
  td { padding:7px 0; border:0 }
  td::before { content:attr(data-label); display:block; color:var(--muted);
    font-size:.65rem; font-weight:720; letter-spacing:.035em; text-transform:uppercase }
  caption { display:block; padding:8px 2px 12px }
  .operational-summary { padding:17px 17px 17px 46px }
  .operational-summary::before { left:17px; top:20px }
  .priority-list { overflow:visible; border:0; border-radius:0; background:transparent;
    box-shadow:none }
  .priority-row { grid-template-columns:1fr; gap:8px; margin-bottom:12px; padding:17px;
    border:1px solid var(--line-soft); border-radius:15px; background:var(--surface);
    box-shadow:var(--shadow) }
  .priority-row:last-child { border-bottom:1px solid var(--line-soft) }
  .priority-owner::before { display:inline; margin-right:5px; content:"Responsable:";
    text-transform:none }
  .priority-action { justify-self:stretch; width:100%; margin-top:4px }
  .conversation-workspace, .opportunity-workspace { grid-template-columns:1fr }
  .conversation-workspace .context-panel { grid-column:auto }
  .workspace-panel { padding:17px; border-radius:17px }
  .sticky-rail { position:static }
  .opportunity-summary { grid-template-columns:1fr 1fr }
  .opportunity-summary > div { padding:13px }
  .work-section-header { display:block }
  .work-section-header > a { display:inline-flex; margin-top:8px }
  .funnel { grid-template-columns:repeat(2,minmax(0,1fr)) }
  .funnel-step a { min-height:88px; padding:14px }
  .funnel-states { grid-template-columns:1fr }
  .msg { max-width:94% }
  dl.pairs { grid-template-columns:1fr; gap:2px }
  dl.pairs dd { margin-bottom:10px }
  .inline { display:block }
  .inline select { width:100%; margin:6px 0 }
}
@media (max-width:380px) {
  .main-wrap { padding-right:13px; padding-left:13px }
  .mobile-bottom > a, .mobile-bottom summary { font-size:.6rem }
  .opportunity-summary { grid-template-columns:1fr }
}
@media (prefers-contrast:more) {
  :root { --muted:#354039; --line:#65726b; --line-soft:#65726b }
  .card, .workspace-panel, .priority-list, .table-scroll, .stat { box-shadow:none }
}
@media (prefers-reduced-motion:reduce) {
  *, *::before, *::after { scroll-behavior:auto !important; transition:none !important;
    animation-duration:.01ms !important; animation-iteration-count:1 !important }
}
"""


def layout(
    title: str,
    content: str,
    *,
    active: str = "",
    actor_label: str = "",
    role_label: str = "",
    organization_label: str = "Larevia",
    is_administrator: bool = False,
    read_only: bool = False,
    support_expires_at: datetime | None = None,
    support_reason: str | None = None,
    alert_count: int = 0,
) -> HTMLResponse:
    """Wrap rendered content in the shared, accessible Spanish shell."""
    visible_groups = tuple(
        NavGroup(
            group.label,
            tuple(
                link
                for link in group.links
                if is_administrator or not link.administrator_only
            ),
        )
        for group in NAV_GROUPS
    )
    visible_groups = tuple(group for group in visible_groups if group.links)

    def nav_link(link: NavLink, *, badge: bool = False, mobile: bool = False) -> str:
        count = (
            f'<span class="alert-count" aria-label="{alert_count} alertas abiertas">'
            f"{alert_count}</span>"
            if badge and alert_count
            else ""
        )
        label = link.mobile_label if mobile and link.mobile_label else link.label
        return (
            f'<a href="{escape(link.href)}"'
            f"{' aria-current="page"' if link.href == active else ''}>"
            f'{_nav_icon(link.href)}<span class="nav-label">{escape(label)}</span>'
            f"{count}</a>"
        )

    groups = "".join(
        '<section class="nav-group">'
        f'<p class="nav-group-title">{escape(group.label)}</p><ul>'
        + "".join(f"<li>{nav_link(link)}</li>" for link in group.links)
        + "</ul></section>"
        for group in visible_groups
    )
    more_links = "".join(
        f"<li>{nav_link(link)}</li>"
        for group in visible_groups
        for link in group.links
        if link.href
        not in {"/crm", "/crm/bandeja", "/crm/agenda", "/crm/oportunidades"}
    )
    more_links += (
        '<li><a href="/crm/alertas"'
        f"{' aria-current="page"' if active == '/crm/alertas' else ''}>"
        f'{_nav_icon("/crm/alertas")}<span class="nav-label">Alertas</span>'
        + (
            f'<span class="alert-count" aria-label="{alert_count} alertas abiertas">'
            f"{alert_count}</span>"
            if alert_count
            else ""
        )
        + "</a></li>"
    )
    scope = f"Toda {organization_label}" if is_administrator else "Mi trabajo"
    if read_only:
        scope = f"{scope} · Sólo lectura"
    now_label = local(datetime.now(tz=OPERATION_TIMEZONE))
    support_banner = ""
    if read_only:
        expiry = (
            local(support_expires_at) if support_expires_at else "hora no disponible"
        )
        reason = (
            f'<span class="muted"> · Motivo: {escape(support_reason)}</span>'
            if support_reason
            else ""
        )
        support_banner = (
            '<div class="read-only" role="status">Soporte Maia · Sólo lectura · '
            f"Acceso hasta {escape(expiry)}{reason}</div>"
        )
    initials = "".join(part[:1] for part in actor_label.split()[:2]).upper() or "—"
    brand_lockup = (
        '<div class="brand-lockup"><span class="brand-mark" aria-hidden="true">M</span>'
        '<div class="brand-copy">'
        f'<a class="brand" href="/crm">{escape(organization_label)}</a>'
        '<span class="powered">Operado con Maia</span></div></div>'
    )
    rendered_content = content
    if read_only:
        # Support uses the ordinary authorized view, but mutation controls are
        # absent rather than left in place to fail after selection. GET filters
        # and navigation remain useful and are deliberately preserved.
        rendered_content = re.sub(
            r"<form\b(?=[^>]*\bmethod\s*=\s*[\"']post[\"'])[^>]*>.*?</form>",
            "",
            rendered_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · {escape(organization_label)}</title>
<style>{STYLES}</style>
</head>
<body>
<a class="skip" href="#contenido">Ir al contenido principal</a>
<div class="crm-shell">
<aside class="rail">
{brand_lockup}
<nav class="rail-nav" aria-label="Navegación principal">{groups}</nav>
<div class="rail-footer">
<a class="alerts-link" href="/crm/alertas"{' aria-current="page"' if active == "/crm/alertas" else ""}>
{_nav_icon("/crm/alertas")}<span class="nav-label">Alertas</span>{f'<span class="alert-count" aria-label="{alert_count} alertas abiertas">{alert_count}</span>' if alert_count else ""}</a>
<p class="session"><span class="session-avatar" aria-hidden="true">{escape(initials)}</span>
<span class="session-copy"><strong>{escape(actor_label)}</strong>{escape(role_label)}</span></p>
</div>
</aside>
<header class="mobile-top">
{brand_lockup}
<div class="mobile-identity"><span class="mobile-scope">{escape(scope)}</span>
<span class="session-avatar" aria-hidden="true">{escape(initials)}</span></div>
</header>
<main id="contenido" class="main-wrap">
{support_banner}
<header class="page-header"><h1>{escape(title)}</h1>
<p class="page-context"><span class="context-chip">{escape(scope)}</span>
<span class="context-time">Actualizado {escape(now_label)}</span></p></header>
{rendered_content}
</main>
<nav class="mobile-bottom" aria-label="Navegación móvil">
{nav_link(NavLink("/crm", "Hoy"), mobile=True)}
{nav_link(NavLink("/crm/bandeja", "Bandeja"), mobile=True)}
{nav_link(NavLink("/crm/agenda", "Agenda"), mobile=True)}
{nav_link(NavLink("/crm/oportunidades", "Oportunidades", mobile_label="Oportun."), mobile=True)}
<details class="mobile-more"><summary>{_nav_icon("more")}<span class="nav-label">Más</span></summary>
<div class="mobile-more-menu"><ul>{more_links}</ul></div></details>
</nav>
</div>
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
    row_pattern = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
    cell_pattern = re.compile(r"<td(?![^>]*data-label)([^>]*)>")

    def label_row(match: re.Match[str]) -> str:
        index = 0

        def label_cell(cell: re.Match[str]) -> str:
            nonlocal index
            label = headers[index] if index < len(headers) else "Dato"
            index += 1
            return f'<td data-label="{escape(label)}"{cell.group(1)}>'

        return "<tr>" + cell_pattern.sub(label_cell, match.group(1)) + "</tr>"

    labelled_rows = row_pattern.sub(label_row, rows)
    head = "".join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    return (
        '<div class="table-scroll"><table>'
        f"<caption>{escape(caption)}</caption>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{labelled_rows}</tbody></table></div>"
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

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
            NavLink("/crm/oportunidades", "Oportunidades"),
        ),
    ),
    NavGroup("Relaciones", (NavLink("/crm/contactos", "Contactos"),)),
    NavGroup(
        "Inventario",
        (
            NavLink("/crm/catalogo", "Catálogo"),
            NavLink(
                "/crm/inventario-externo", "Inventario externo", True
            ),
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
NAV: tuple[NavLink, ...] = tuple(
    link for group in NAV_GROUPS for link in group.links
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
  --rail:248px; }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif }
.crm-shell { min-height:100vh; display:grid; grid-template-columns:var(--rail) minmax(0,1fr) }
.rail { position:sticky; top:0; height:100vh; overflow-y:auto; display:flex;
  flex-direction:column; padding:34px 22px 22px; background:var(--brand-deep); color:#fff }
.brand { color:#fff; font:650 2.15rem/1 Newsreader,serif; text-decoration:none }
.powered { margin:8px 0 28px; color:#b8c4bf; font-size:.75rem; font-weight:650;
  letter-spacing:.08em; text-transform:uppercase }
.rail-nav { display:block; padding:0; margin:0 }
.rail-nav ul { list-style:none; margin:0; padding:0 }
.nav-group { margin:0 0 20px }
.nav-group-title { margin:0 0 6px; color:#93a49d; font-size:.72rem;
  font-weight:750; letter-spacing:.12em; text-transform:uppercase }
.rail-nav a { display:flex; align-items:center; justify-content:space-between;
  min-height:44px; padding:9px 12px; border-radius:7px; color:#f5f7f6;
  text-decoration:none; font-weight:550 }
.rail-nav a:hover { background:#20332b; text-decoration:underline }
/* The current surface is announced, not only coloured. */
.rail-nav a[aria-current="page"] { background:#356654; color:#fff; font-weight:750 }
.rail-footer { margin-top:auto; padding-top:18px; border-top:1px solid #405149 }
.alerts-link { display:flex; justify-content:space-between; align-items:center;
  min-height:44px; color:#fff; text-decoration:none; font-weight:650 }
.alert-count { display:inline-flex; align-items:center; justify-content:center;
  min-width:28px; min-height:28px; padding:0 8px; border-radius:999px;
  background:#c16a4d; color:#fff; font-size:.8rem; font-weight:800 }
.session { margin:22px 0 0; color:#b8c4bf; font-size:.8rem }
.session strong { display:block; color:#fff; font-size:.9rem }
.main-wrap { min-width:0; width:100%; max-width:1480px; padding:42px 52px 96px }
.page-context { margin:-5px 0 24px; color:var(--muted); font-size:.9rem }
.mobile-top, .mobile-bottom { display:none }
a { color:var(--brand) }

/* Keyboard users must always be able to see where they are. Never remove. */
a:focus-visible, button:focus-visible, input:focus-visible,
select:focus-visible, textarea:focus-visible, summary:focus-visible {
  outline:3px solid #0b57d0; outline-offset:2px }

/* Skip link: present for screen readers and keyboards, visible once focused. */
.skip { position:fixed; left:-9999px; top:0; background:var(--surface);
  padding:12px 16px; z-index:100 }
.skip:focus { left:8px }

h1 { max-width:62rem; font-size:clamp(1.8rem,3vw,2.4rem); line-height:1.12;
  letter-spacing:-.025em; margin:0 0 1rem }
h2 { font-size:1.25rem; line-height:1.25; margin:1.75rem 0 .7rem }
h3 { font-size:1rem; margin:1.2rem 0 .4rem }
.card { background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:20px; margin:14px 0 }
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
button.secondary, .button.secondary { background:#46534c }
button.quiet { background:transparent; color:var(--brand);
  border:1px solid var(--brand) }
.button.quiet { background:transparent; color:var(--brand); border:1px solid var(--brand) }
button.danger { background:var(--bad) }
button:disabled { cursor:wait; opacity:.68 }
form[aria-busy="true"] { opacity:.82 }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0 }
.hint, .muted { color:var(--muted); font-size:.9rem }
.error { background:var(--restricted); color:var(--bad); border-left:4px solid var(--bad);
  padding:12px 16px; border-radius:6px }
.ok { background:var(--confirmed); color:var(--ok); border-left:4px solid var(--ok);
  padding:12px 16px; border-radius:6px }
.warn { background:var(--attention); color:var(--warn); border-left:4px solid #d3a446;
  padding:12px 16px; border-radius:6px }
.read-only { position:sticky; top:0; z-index:20; margin:-42px -52px 28px;
  padding:11px 52px; background:var(--attention); color:var(--warn);
  border-bottom:1px solid #d3a446; font-weight:700 }
table { width:100%; border-collapse:collapse; background:var(--surface) }
caption { text-align:left; padding:8px 4px; color:var(--muted); font-size:.9rem }
th, td { text-align:left; border-bottom:1px solid var(--line);
  padding:12px 10px; vertical-align:top }
th { font-size:.85rem; color:#3c4657 }
.tag { display:inline-flex; align-items:center; padding:3px 9px; border-radius:999px;
  font-size:.8rem; font-weight:700; border:1px solid var(--line);
  background:var(--neutral); color:#4c554f }
.tag.bad { background:var(--blocked); border-color:#edc8bd; color:var(--overdue) }
.tag.ok { background:var(--confirmed); border-color:#bed8c5; color:var(--ok) }
.tag.warn { background:var(--attention); border-color:#ead59b; color:var(--warn) }
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
  border-radius:8px; padding:16px }
.stat .value { font-size:1.6rem; font-weight:700 }
.operational-summary { margin:0 0 28px; padding:18px 20px; background:#fff8e8;
  border:1px solid #ead59b; border-left:5px solid #d3a446; border-radius:8px }
.operational-summary strong { display:block; font-size:1.05rem; margin-bottom:3px }
.priority-list { margin:0; padding:0; list-style:none; background:var(--surface);
  border:1px solid var(--line); border-radius:10px; overflow:hidden }
.priority-row { display:grid; grid-template-columns:minmax(95px,.65fr) minmax(260px,3fr)
  minmax(150px,1.2fr) minmax(130px,auto); gap:18px; align-items:center;
  padding:20px; border-bottom:1px solid var(--line) }
.priority-row:last-child { border-bottom:0 }
.priority-reason { font-size:1.05rem; font-weight:750 }
.priority-meta, .priority-owner { color:var(--muted); font-size:.9rem }
.priority-action { justify-self:end }
.priority-now { background:var(--blocked); color:var(--overdue) }
.priority-today, .priority-review { background:var(--attention); color:var(--warn) }
.priority-soon { background:var(--selected); color:var(--brand) }
.priority-label { display:inline-flex; width:max-content; padding:5px 10px;
  border-radius:999px; font-size:.72rem; font-weight:800; text-transform:uppercase }
.work-section { margin-top:30px }
.work-section-header { display:flex; justify-content:space-between; gap:16px;
  align-items:end; margin-bottom:10px }
.work-section-header h2 { margin:0 }
.work-section-header p { margin:0; color:var(--muted); font-size:.9rem }
.next-obligation { border:1px solid var(--line); border-radius:12px;
  background:var(--surface); padding:24px }
.next-obligation h2 { margin:.7rem 0 .3rem; font-size:1.5rem }
.workspace { display:grid; gap:20px }
.conversation-workspace { grid-template-columns:minmax(230px,.85fr) minmax(420px,2fr)
  minmax(260px,1fr); align-items:start }
.opportunity-workspace { grid-template-columns:minmax(0,2.5fr) minmax(260px,.85fr);
  align-items:start }
.workspace-panel { background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:20px; min-width:0 }
.workspace-panel > :first-child { margin-top:0 }
.queue-list { list-style:none; margin:0; padding:0; display:grid; gap:10px }
.queue-item a { display:block; min-height:44px; padding:14px; color:var(--ink);
  text-decoration:none; background:var(--surface); border:1px solid var(--line);
  border-radius:8px }
.queue-item a:hover { border-color:var(--brand) }
.queue-item.selected a { background:var(--selected); border:2px solid var(--brand) }
.queue-item strong { display:block; margin:7px 0 3px }
.queue-preview { color:var(--muted); font-size:.9rem; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap }
.sticky-rail { position:sticky; top:24px }
.opportunity-summary { display:grid; grid-template-columns:repeat(5,minmax(130px,1fr));
  gap:18px; margin:0 0 22px; padding:20px; background:var(--surface);
  border:1px solid var(--line); border-radius:10px }
.summary-label { display:block; color:var(--muted); font-size:.74rem;
  font-weight:700; letter-spacing:.03em; text-transform:uppercase }
.summary-value { display:block; margin-top:6px; font-weight:750 }
.criteria-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:10px }
.criterion { padding:12px 14px; border-radius:8px; background:var(--confirmed) }
.criterion.pending { background:var(--attention) }
.timeline { list-style:none; margin:0; padding:0 0 0 18px; border-left:2px solid var(--line) }
.timeline li { position:relative; padding:0 0 18px 12px }
.timeline li::before { content:""; position:absolute; left:-19px; top:.35rem;
  width:10px; height:10px; border-radius:50%; background:var(--brand) }
.thread { display:flex; flex-direction:column; gap:10px; margin:0; padding:0 }
.msg { border:1px solid var(--line); border-radius:10px; padding:12px 14px;
  background:var(--surface); max-width:46rem }
.msg.out { background:var(--selected); margin-left:auto }
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
.tabs a.current { background:var(--selected); font-weight:700 }
.inline { display:inline }
.inline select { width:auto; margin:0 5px }
.status { font-weight:700 }
.Active { color:var(--ok) }
.Inactive { color:var(--bad) }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#101828;
  color:#f2f4f7; padding:16px; border-radius:8px }
textarea.preview { min-height:430px; font:13px/1.4 ui-monospace,monospace }
@media (max-width:1023px) {
  .crm-shell { display:block }
  .rail { display:none }
  .mobile-top { display:flex; align-items:center; justify-content:space-between;
    gap:14px; min-height:70px; padding:12px 20px; background:var(--brand-deep); color:#fff }
  .mobile-top .brand { font-size:1.7rem }
  .mobile-top .powered { margin:2px 0 0; font-size:.62rem }
  .mobile-identity { color:#d5ddd9; font-size:.8rem; text-align:right }
  .main-wrap { max-width:none; padding:30px 28px 100px }
  .read-only { margin:-30px -28px 24px; padding:11px 28px }
  .conversation-workspace { grid-template-columns:minmax(220px,.7fr) minmax(0,1.5fr) }
  .conversation-workspace .context-panel { grid-column:1/-1 }
  .opportunity-summary { grid-template-columns:repeat(3,minmax(130px,1fr)) }
}
@media (max-width:760px) {
  .grid, .checks { grid-template-columns:1fr }
  .main-wrap { padding:26px 16px 104px }
  .read-only { margin:-26px -16px 22px; padding:10px 16px }
  .mobile-top { padding:10px 16px }
  .mobile-bottom { position:fixed; left:0; right:0; bottom:0; z-index:40;
    display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); min-height:68px;
    background:var(--surface); border-top:1px solid var(--line) }
  .mobile-bottom > a, .mobile-bottom summary { display:flex; align-items:center;
    justify-content:center; min-width:0; min-height:48px; padding:8px 3px;
    color:var(--ink); text-align:center; text-decoration:none; font-size:.72rem;
    font-weight:650; cursor:pointer; list-style:none }
  .mobile-bottom a[aria-current="page"] { color:var(--brand); font-weight:800 }
  .mobile-more { position:relative }
  .mobile-more summary::-webkit-details-marker { display:none }
  .mobile-more-menu { position:absolute; right:8px; bottom:62px; width:min(300px,92vw);
    max-height:70vh; overflow:auto; padding:12px; background:var(--surface);
    border:1px solid var(--line); border-radius:10px; box-shadow:0 14px 36px #17211d33 }
  .mobile-more-menu ul { list-style:none; padding:0; margin:0 }
  .mobile-more-menu a { display:flex; min-height:44px; align-items:center;
    padding:8px 10px; border-radius:6px; text-decoration:none }
  .mobile-more-menu a[aria-current="page"] { background:var(--selected) }
  .table-scroll { overflow:visible }
  table, thead, tbody, tr, th, td { display:block }
  thead { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0) }
  tr { margin:0 0 12px; padding:14px; background:var(--surface);
    border:1px solid var(--line); border-radius:9px }
  td { border:0; padding:6px 0 }
  td::before { content:attr(data-label); display:block; color:var(--muted);
    font-size:.72rem; font-weight:700; text-transform:uppercase }
  caption { display:block }
  .msg { max-width:100% }
  dl.pairs { grid-template-columns:1fr }
  .priority-row { grid-template-columns:1fr; gap:8px; padding:18px }
  .priority-action { justify-self:stretch; width:100%; margin-top:5px }
  .conversation-workspace, .opportunity-workspace { grid-template-columns:1fr }
  .conversation-workspace .context-panel { grid-column:auto }
  .sticky-rail { position:static }
  .opportunity-summary { grid-template-columns:1fr 1fr }
  .work-section-header { display:block }
}
@media (prefers-contrast:more) {
  :root { --muted:#354039; --line:#65726b }
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

    def nav_link(link: NavLink, *, badge: bool = False) -> str:
        count = (
            f'<span class="alert-count" aria-label="{alert_count} alertas abiertas">'
            f"{alert_count}</span>"
            if badge and alert_count
            else ""
        )
        return (
            f'<a href="{escape(link.href)}"'
            f"{' aria-current="page"' if link.href == active else ''}>"
            f"<span>{escape(link.label)}</span>{count}</a>"
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
        if link.href not in {"/crm", "/crm/bandeja", "/crm/agenda", "/crm/oportunidades"}
    )
    more_links += (
        '<li><a href="/crm/alertas"'
        f"{' aria-current="page"' if active == '/crm/alertas' else ''}>"
        f"<span>Alertas</span>"
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
        expiry = local(support_expires_at) if support_expires_at else "hora no disponible"
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
<a class="brand" href="/crm">{escape(organization_label)}</a>
<p class="powered">Operado con Maia</p>
<nav class="rail-nav" aria-label="Navegación principal">{groups}</nav>
<div class="rail-footer">
<a class="alerts-link" href="/crm/alertas"{' aria-current="page"' if active == '/crm/alertas' else ''}>
<span>Alertas</span>{f'<span class="alert-count" aria-label="{alert_count} alertas abiertas">{alert_count}</span>' if alert_count else ''}</a>
<p class="session"><strong>{escape(actor_label)}</strong>{escape(role_label)}</p>
</div>
</aside>
<header class="mobile-top">
<div><a class="brand" href="/crm">{escape(organization_label)}</a>
<p class="powered">Operado con Maia</p></div>
<div class="mobile-identity"><strong>{escape(initials)}</strong><br>{escape(scope)}</div>
</header>
<main id="contenido" class="main-wrap">
{support_banner}
<h1>{escape(title)}</h1>
<p class="page-context">{escape(scope)} · Consultado {escape(now_label)}</p>
{rendered_content}
</main>
<nav class="mobile-bottom" aria-label="Navegación móvil">
{nav_link(NavLink('/crm', 'Hoy'))}
{nav_link(NavLink('/crm/bandeja', 'Bandeja'))}
{nav_link(NavLink('/crm/agenda', 'Agenda'))}
{nav_link(NavLink('/crm/oportunidades', 'Oportunidades'))}
<details class="mobile-more"><summary>Más</summary>
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

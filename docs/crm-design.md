# CRM Design System

This document defines the approved visual and interaction system for Maia's
operational CRM. It adapts the warm restraint of the
[Public Site Design System](public-site-design.md) to dense, consequential work.
The public experience is property first; the CRM is **work first**.

The system covers both role-specific homes and every human-visible operational
surface. It does not change Product authority, add a frontend implementation,
or authorize reference content as business truth. Product remains responsible
for identity, organization isolation, authorization, PostgreSQL truth,
deterministic policy, side effects, audit, retries, ambiguity, and safety.

## Experience principles

1. **Work before reporting.** The first screen leads with people and commitments
   requiring action. Aggregate performance follows.
2. **One clear priority, complete operational context.** Every screen makes the
   next permitted action obvious without hiding other risks or obligations.
3. **Authority is visible.** Scope, role, owner, handling mode, restriction, and
   read-only state appear where a decision is made.
4. **Truth includes uncertainty.** Pending, stale, incomplete, unavailable, and
   refused are first-class states. None is silently rendered as zero or success.
5. **Calm density.** The interface carries substantial information without
   decorative cards, oversized type, gratuitous color, or hidden operational
   facts.
6. **Role-shaped, not role-fragmented.** Administrator and Advisor share a
   system but receive different homes, navigation, scope, and permitted actions.
7. **Mexican Spanish throughout.** Copy is direct, calm, specific, and
   outcome-led. Internal English identifiers and portal jargon never leak into
   the interface.
8. **Recovery is part of the design.** Every refusal, partial success, stale
   value, and failed side effect explains what remains true and what may happen
   next.
9. **No AI theatre.** Maia appears as an operating product and conversational
   authority where relevant, never as a mascot, magic score, unsolicited panel,
   or animation.
10. **No cross-Organization affordance.** The absence of an Organization
   switcher, global search, and cross-customer reporting is deliberate.

## Visual foundation

### Brand tokens

The CRM inherits the public palette but assigns it operational roles.

| Token | Value | CRM role |
| --- | --- | --- |
| **Marfil** | `#f7f5ef` | Page canvas and calm negative space |
| **Tinta** | `#17211d` | Primary text, navigation depth, confident facts |
| **Agave** | `#315c4c` | Primary actions, links, selected navigation, normal progress |
| **Arcilla** | `#a85f45` | Overdue work and materially blocked attention |
| **Maíz** | `#d3a446` | Attention required soon |
| **Piedra** | `#d9d6cd` | Separators, quiet structure, historical and unavailable states |
| **Blanco** | `#ffffff` | Main surfaces, tables, panels, and action text |

These colors do not encode meaning by themselves. Every semantic state includes
a visible label and, where needed, an icon and explanation.

### Semantic tokens

| State | Surface | Text or action | Use |
| --- | --- | --- | --- |
| **Selected / informative** | `#e5efeb` | `#315c4c` | Current navigation, explanatory state, normal progress |
| **Attention** | `#fbf1d6` | `#664a05` | Due soon, incomplete but workable |
| **Overdue / blocked** | `#f9e8e3` | `#7a2e22` | Overdue obligation or material blocker |
| **Destructive / restricted** | `#f8e5e3` | `#8b2520` | Destructive action, Do Not Contact, confirmed failure |
| **Confirmed success** | `#e6f0e9` | `#214f36` | Server-confirmed completion or healthy state |
| **Neutral / historical** | `#eceae3` | `#4c554f` | Inactive, historical, unavailable, or not applicable |

Large action fills use Blanco text only where the pair meets WCAG 2.2 AA.
Piedra is never the only boundary around a control, the only focus indication,
or the only distinction between states. Green is reserved for confirmed truth;
it never means “no alert was observed.”

### Typography

Self-host variable **Inter** carries all operational content: navigation,
controls, dates, tables, metrics, conversations, statuses, and body copy.
Self-host **Newsreader** may appear only in a restrained Brokerage Brand or page
identity moment. It never carries workflow status, dense facts, filters, or
metrics.

| Role | Intended size | Notes |
| --- | --- | --- |
| Metadata and table labels | 13–14px | Never the only location for critical facts |
| Body, rows, and controls | 16px | Editable fields remain at least 16px on mobile |
| Section heading | 18–22px | Compact and descriptive |
| Page title | 28–36px | One semantic `h1` only |
| Headline operational value | 28–40px | Used sparingly; always paired with context |

Weights remain restrained. Use regular text for most content, medium emphasis
for hierarchy, and bold only for the current priority, amount, or state that
requires fast scanning. Uppercase is limited to short metadata where it does
not impair reading.

### Spacing, shape, and elevation

Spacing follows the public four-pixel base: `8`, `12`, `16`, `24`, `32`, `48`,
`64`, and `96` pixels. Operational surfaces primarily use `8` through `32`.

- Cards use an eight-pixel radius.
- Large panels and drawers use twelve pixels.
- Only status chips and compact counters are fully rounded.
- Borders provide structure before shadows.
- Shadows indicate a real overlay, menu, or mobile sheet; they are not card
  decoration.
- A section changes background only when it represents a distinct task or
  authority boundary.

## Global shell

### Desktop

At widths of `1024px` and above, the shell uses:

- a persistent `240–256px` left navigation rail;
- Brokerage Brand name or approved mark at the top;
- restrained `Operado con Maia` attribution;
- grouped, role-aware navigation;
- a global Alerts destination and actionable count;
- signed-in person, canonical role, and read-only state;
- a fluid main canvas with a readable maximum line length for prose and enough
  width for operational lists.

The rail uses Tinta as its deepest surface, with Blanco text and Agave-adjacent
selection treatment that remains distinct in high-contrast mode. The main
canvas uses Marfil with Blanco work surfaces.

The current Organization is identity, not a selector. The current role and data
scope appear near the page title: `Toda Larevia` for an Administrator and
`Mi trabajo` for an Advisor.

### Tablet

Between `768px` and `1023px`, the interface replaces the persistent rail with a
compact top navigation that names the current section and opens a fully labeled
menu. Primary destinations never become unexplained icons. Split workspaces
reduce from three regions to two or move the queue to its own view.

### Mobile

Below `768px`, the shell uses:

- a compact top bar for Brokerage Brand, role/scope, and Alerts;
- a bottom navigation for `Hoy`, `Bandeja`, `Agenda`, `Oportunidades`, and
  `Más`;
- one primary content column;
- sticky actions only when they do not obscure content or the keyboard;
- full-width sheets for filters or secondary actions, never critical truth.

At `320px`, labels may wrap within their targets but remain visible. The mobile
experience never becomes a horizontally scaled desktop page.

## Page hierarchy

Every page follows the same reading order:

1. Breadcrumb or section context when needed.
2. One `h1` naming the work surface.
3. Scope, period, and freshness where applicable.
4. One-sentence operational summary or exception banner.
5. Primary action or priority queue.
6. Supporting facts, filters, and secondary actions.
7. History, methodology, or configuration detail.

The shell owns the page title. A surface never injects a second `h1`.

## Dashboard information contracts

### Administrator: Operación de {Brokerage Brand}

The desktop composition uses four layers.

#### 1. Scope and immediate condition

The header shows `Toda {Brokerage Brand}`, local update time, and any actionable
partial-data warning. It summarizes open work in a sentence, for example:

> 7 asuntos requieren atención: 2 personas esperan, 3 acciones están vencidas,
> 1 oportunidad no tiene asesor y 1 visita requiere revisión.

#### 2. Priority queue

This is the dominant surface. Each row contains:

- priority label;
- Contact or opaque reference as permitted;
- concrete reason;
- absolute due time plus relative waiting or overdue time;
- Responsible Advisor or `Sin asesor`;
- current stage or appointment state;
- one next permitted action.

The default ordering is `Ahora`, `Hoy`, `Revisión`, then `Próximamente`, with
oldest wait or earliest due first inside a priority.

#### 3. Operational health

Compact metrics show Follow-up Coverage, opportunities without an Advisor,
overdue Next Actions, and appointments requiring review. Each includes scope,
definition, freshness, and a link to the underlying work. Metric tiles never
become the page's largest visual area.

#### 4. Workload and recent performance

Team workload, pipeline distribution, and recent business performance appear
after immediate work. Trends use comparable periods only and link to Business
Intelligence for methodology.

### Advisor: Mi trabajo

The mobile-first composition begins with the single next obligation, followed
by a chronological and priority-aware work list.

- `Ahora`: conversations and immediate appointment risks.
- `Hoy`: Next Actions, visits, and new assignments due today.
- `Próximamente`: the next seven days.
- `Revisión`: blocked or partial work the Advisor can resolve or escalate.

The header names the Advisor and personal scope. Organization-wide metrics,
peer rankings, and unavailable Administrator filters are absent.

### Metric anatomy

Every metric component contains:

- plain-language name;
- value or explicit non-value state;
- scope;
- period;
- last update;
- definition or version when it can change;
- quality state: current, delayed, incomplete, unavailable;
- authorized drill-through or explanation.

`0`, `Sin registrar`, and `No calculable` are visually and semantically distinct.
An unavailable value does not render as an empty chart.

## Component library

### Priority row

The priority row is the fundamental dashboard unit. It favors a short reason
over a generic title. The owner and time are adjacent to the reason, not hidden
in separate columns at the far edge. The action uses a specific verb such as
`Responder`, `Asignar`, `Revisar visita`, or `Registrar resultado`.

### Metric summary

A metric summary is compact, left-aligned, and free of decorative illustration.
It may show a small comparable trend. It never uses a gauge, a health score, or
an unexplained percentage ring.

### Status label

Status labels use canonical Mexican-Spanish vocabulary and combine text with a
semantic surface. Avoid raw enum values such as `Active`, `Won`, or
`TemporarilyUnavailable`.

### Operational table

Desktop tables use medium density, a descriptive caption, semantic headers,
and server-backed search, filters, sorting, and pagination. A row exposes owner,
state, urgency, and Next Action without requiring record navigation.

Rows do not contain several equally weighted buttons. The record name is the
primary navigation target; one common action may appear at the end. Additional
actions live in the record workspace.

There are no bulk mutations in the approved initial experience. Future bulk
selection may support authorized non-destructive exports, but it does not imply
bulk reassignment, outreach, publication, or deletion.

### Mobile record card

A mobile record card is a recomposition of one table row, not a reduced subset.
Its reading order is:

1. record identity and priority;
2. reason and state;
3. owner and due/wait time;
4. critical restriction or quality state;
5. next permitted action.

### Filter bar

Essential filters remain visible and role-coherent. Advanced filters use a
desktop drawer or mobile full-screen sheet. The applied state is summarized in
plain language and can be cleared in one action. An Advisor never sees a filter
for records their authorization cannot return, such as unassigned
organization-wide Opportunities.

### Conversation workspace

Desktop uses a prioritized queue, conversation, and context/action rail. The
conversation region distinguishes Contact, Maia, and human messages without
turning the thread into consumer-chat decoration. It shows absolute and relative
times, expired content, delivery state, and handling authority.

The context rail keeps Contact, Opportunity, Advisor, Next Action, appointment,
and communication restriction visible. The reply control appears only for the
current authorized human holder. Taking or releasing the conversation clearly
states what happens to Maia.

### Opportunity summary and action rail

The sticky summary names stage, Responsible Advisor, Follow-up Coverage, Next
Action, urgency, and last activity. The action rail contains only operations
valid for the role and state. A disabled control is used only when seeing the
unavailable operation and its reason helps the person understand the workflow;
otherwise it is absent.

### Agenda item

An agenda item shows authoritative state first: `Confirmada`, `Requiere
revisión`, `Cancelada`, or `No asistió`. It then names Contact, property,
Responsible Advisor, conducting Advisor, local time, reminder state, and next
required action. Provider delivery success never substitutes for appointment
confirmation.

### Alert

An Internal Operational Alert shows severity, age, affected record, owner,
delivery state, and next action. Open actionable alerts contribute to the global
count. Resolved or informational history does not.

### Banner and inline message

- **Informative:** explains scope or process without demanding action.
- **Attention:** names incomplete work and the next safe action.
- **Error:** names what failed, what remains true, and how to recover.
- **Partial success:** confirms the committed part and isolates the failed side
  effect.
- **Read-only:** remains persistent throughout support access.

Success messages use an `aria-live` region and confirm authoritative server
completion. They never claim a provider side effect that is only queued.

### Empty state

An empty state distinguishes:

- no records exist;
- no records match filters;
- the person lacks scope for that work;
- data has not been projected or synchronized;
- the source is unavailable.

Each state supplies the next useful action when one exists. It does not use
illustrations to disguise missing truth.

### Trend and distribution charts

Charts are subordinate to operational work.

- Small lines show comparable trends over time.
- Horizontal bars compare pipeline stages or workload on one scale.
- Compact funnels appear only when every stage and exclusion is defined.
- Labels and values remain visible without hover.
- `Sin registrar`, exclusions, and incomplete projection are shown beside the
  chart.

Do not use gauges, decorative doughnuts, 3D charts, traffic-light matrices,
unexplained scores, or a different color for every peer.

### Consequential-action review

The review surface shows exact record, current state, requested change,
customer or operational consequence, evidence or reason, reversibility, and a
specific final verb. Destructive or restricted actions use the destructive
token only at the final decision point, not across the entire page.

## Human-visible route, role, and state matrix

| Family | Permitted roles | Primary decision | Critical facts | Principal action | Required exceptional states |
| --- | --- | --- | --- | --- | --- |
| **Operación** | Administrator | What threatens today's organization-wide commitments? | Scope, freshness, waiting time, owner, coverage, review queues | Open the highest-priority work | Complete, no active work, partial data, stale data, source failure |
| **Mi trabajo** | Advisor | What must I do next? | Personal scope, next obligation, conversations, visits, due work | Perform the next obligation | No work today, overdue, newly assigned, blocked, read-only support |
| **Bandeja** | Administrator; scoped Advisor | Which conversation needs attention and who may answer? | Handling mode, wait, holder, Opportunity, restrictions, Next Action | Open or take the conversation | Empty, filtered zero, expired content, human request, restricted, delivery failure |
| **Conversation** | Administrator; owning/scoped Advisor | What may be said or changed now? | Thread, handling authority, service window, Contact, Opportunity, restrictions | Reply, take, release, or open related work | Maia active, human active, awaiting Contact, Admin review, Do Not Contact, partial send failure |
| **Agenda** | Administrator; scoped Advisor | Which appointment needs preparation or intervention? | Confirmation, local time, owner, conducting Advisor, reminders, outcome | Open appointment or resolve review | Empty day, needs review, reminder withheld, delivery failure, cancelled, missed |
| **Opportunities** | Administrator; scoped Advisor | Which pursuit is at risk or ready to advance? | Stage, owner, Next Action, coverage, activity, outcome | Open Opportunity | Filtered zero, unassigned, overdue, exception, dormant, lost, won |
| **Opportunity** | Administrator; owning Advisor | What is known, owed, and blocking progress? | Need, criteria, stage, owner, Next Action, exception, origin, history | Perform current permitted action | Missing need, pending criterion, no owner, overdue, blocked, evidence required, read-only |
| **Contacts** | Administrator; scoped Advisor | Which known person or history is relevant? | Trusted identities, conversations, Opportunities, restrictions, retention-visible facts | Open Contact | No match, restricted, expired content, multiple Opportunities, not found |
| **Contact** | Administrator; scoped Advisor | What relationship and authority exist across time? | Identities, Needs, Opportunities, appointments, consent, suppression | Open related work | No trusted channel, Do Not Contact, stale Need, expired content, not found |
| **Assignment** | Administrator | Who must own an unassigned Opportunity? | Queue age, need, property expertise, eligibility, absence, default Advisor | Assign Responsible Advisor | Empty queue, no eligible Advisor, conflict, already assigned, retry replay |
| **Team** | Administrator; Advisor read-only subset | Who may own, conduct, specialize, or receive alerts? | Role, eligibility, calendar, alerts, load, absences, expertise | Manage member or inspect responsibility | No calendar, absent, ineligible, alert channel missing, read-only |
| **Catalog** | Administrator; scoped Advisor | Is this inventory ready and authorized for its intended use? | Property, Listing, Offer, availability, authority, publication, readiness, freshness | Open record or begin authorized capture | Empty, filtered zero, incomplete facts, unavailable, withdrawn, hidden price, stale source |
| **Property capture** | Administrator | What evidence is required before capture or publication? | Document version, source, facts, media, provenance, validation | Review and record the next safe step | Validation error, duplicate identity, unsupported file, partial extraction, refusal |
| **External inventory** | Administrator | What external evidence is fresh and what remains blocked? | Source health, freshness, mapping, credential reference, legal and retention gates | Synchronize, map, review, or withdraw | No credential, source down, stale evidence, mapping conflict, gate closed, cleanup failure |
| **Reactivation** | Administrator | Which exact contact is eligible for an exact authorized message? | Consent, suppression, template, language, content, reason, audience, frequency | Review or authorize exact outreach | No eligible candidates, exclusion, expired template evidence, provider unavailable, denied send |
| **Sponsorship** | Administrator | What capacity, commitment, and delivery obligation exists? | Capacity, price version, quote, campaign, delivery, collection, data quality | Open campaign or next fulfillment step | No capacity, quote expired, uncollected, paused, incomplete day, report unavailable |
| **Inteligencia** | Administrator | What can the Organization conclude from current aggregate evidence? | Scope, period, definition, freshness, completeness, exclusions | Inspect explanation or underlying aggregate | Zero, Sin registrar, No calculable, late data, projection pending, replay failure |
| **Alertas** | Administrator; scoped Advisor | Which durable operational exceptions need action? | Severity, age, affected record, owner, delivery state | Open the affected work | No open alerts, undelivered alert, resolved history, stale alert |
| **Configuración** | Administrator | What governs this Organization and which limits apply? | Configuration version, entitlements, usage, channel binding, secret references, holds, support access | Review or begin separately authorized change | Missing binding, limit reached, stale version, support active, retention hold, read-only |
| **Global** | Authorized CRM person | Can this surface truthfully continue? | Organization, role, scope, request state | Recover, navigate back, or stop | 404/hidden refusal, validation, duplicate submission, partial success, service failure, maintenance |

Machine-only APIs, webhooks, provider callbacks, and Platform Operator runbook
responses do not receive a CRM visual layer.

## Responsive behavior by component

Verify at `320`, `390`, `768`, `1024`, `1440`, and `1920` pixel widths.

| Component | Desktop | Tablet | Mobile |
| --- | --- | --- | --- |
| Navigation | Persistent grouped rail | Labeled top menu | Five-destination bottom navigation plus `Más` |
| Administrator priority queue | Structured rows with aligned owner/time/action | Two-line rows | Full record cards retaining every fact |
| Conversation | Queue + thread + context rail | Thread + context; queue separate | Queue, thread, and context as sequential screens |
| Opportunity | Main workflow + sticky action rail | Main workflow + inline actions | Summary first, sections stacked, one safe sticky action |
| Tables | Medium-density semantic table | Reduced column grouping | Ordered record cards; no removed material facts |
| Filters | Visible essentials + drawer | Summary + sheet | Summary + full-screen sheet |
| Metrics | Compact row or small grid | Two columns | One column; context never detached from value |
| Charts | Direct labels and comparative scale | Simplified labels | Stacked or horizontally listed, never shrunk illegibly |
| Consequential review | Focused panel or page | Full-width panel | Dedicated page/sheet with unambiguous final action |

No component may force horizontal page overflow. A contained table may scroll
only when the data cannot be faithfully recomposed, and the primary mobile flow
must still expose a card alternative.

## Accessibility and resilient interaction

- Conform to WCAG 2.2 AA for contrast, focus, semantics, names, error handling,
  and target size.
- Use `lang="es-MX"` and Mexican-Spanish visible copy.
- Provide one semantic `h1`, ordered headings, a skip link, landmarks, table
  captions and header scopes, and visible focus.
- Every interactive target is at least 44 by 44 pixels on coarse pointers.
- Focus and errors use an independent high-contrast indicator; color is never
  the only signal.
- Announce server-confirmed success through a polite live region and validation
  failures through an alert region.
- Preserve submitted values after validation errors and place recovery guidance
  beside the affected field.
- Absolute local time accompanies relative time. The operational timezone is
  `America/Mexico_City`.
- Honor reduced-motion preferences. No essential understanding depends on
  animation, smooth scrolling, autoplay, or transient timing.
- Essential workflows remain server-backed and usable without JavaScript.
  JavaScript may enhance menus, filters, pending state, and split-pane focus but
  never owns authorization, idempotency, business policy, or success.
- A double submission replays the same rendered command rather than creating a
  second business action.
- A refused or hidden record does not disclose cross-Organization or other
  Advisor ownership through status, copy, timing, or control state.

## Content design

Copy uses canonical terms and specific verbs:

- `Responder`, not `Procesar`.
- `Asignar asesor responsable`, not `Actualizar owner`.
- `Registrar siguiente acción`, not `Guardar seguimiento`.
- `Requiere revisión`, not `Error` when Product truth is ambiguous rather than
  failed.
- `Sin registrar`, not `0` when evidence is absent.
- `No calculable`, not an empty percentage.

Avoid `lead`, `pipeline score`, `customer record`, raw provider states, raw UUIDs,
and phone number as identity. Never imply that Maia completed a visit, negotiated
an offer, approved a template, confirmed provider delivery, or established
business truth when Product has not recorded that outcome.

## Reference-screen content

The reference package uses a coherent invented operational snapshot documented
in [CRM Reference Screens](crm-mocks.md). The rendered screens look complete and
natural; they contain no environment banner, placeholder label, or fictionality
notice.

Reference content is public-safe and contains no real Contacts, conversations,
phone numbers, street addresses, credentials, provider identifiers, customer
documents, or claims about real properties. It remains documentation content and
must never enter Product truth.

## Visual acceptance

The CRM design is visually accepted only when evidence proves all of the
following.

### Ten-second comprehension

A reviewer unfamiliar with Maia can identify within ten seconds:

1. the Brokerage Organization and current role;
2. what requires attention first;
3. why it requires attention;
4. who owns it;
5. how long it has waited or when it is due;
6. the next permitted action;
7. whether the displayed information is current and complete.

### Route and state coverage

- Every family in the route/role/state matrix is represented in a component or
  page specification.
- Administrator, Advisor, and read-only support states are reviewed.
- Empty, filtered-zero, stale, partial, unavailable, validation, refusal,
  success, duplicate-submission, and not-found states are reviewed.
- Current, overdue, blocked, restricted, confirmed, cancelled, dormant, lost,
  and won business states remain visually distinct and truthful.

### Responsive and accessible evidence

- Review `320`, `390`, `768`, `1024`, `1440`, and `1920` widths.
- No horizontal page overflow, overlap, clipping, or inaccessible sticky action.
- Mobile retains all material facts and the same authority boundaries.
- Keyboard navigation, focus order, skip link, headings, tables, dialogs,
  sheets, live regions, and error recovery are verified.
- Contrast meets WCAG 2.2 AA, targets meet the 44-pixel floor, and reduced motion
  removes decorative movement.
- Essential workflows remain complete with JavaScript disabled.

### Data and authority evidence

- Scope, period, freshness, definition, and completeness accompany every metric.
- `0`, `Sin registrar`, and `No calculable` remain distinct.
- Restricted, stale, partial, and provider-failed states do not claim success.
- Role-inappropriate navigation, filters, records, and actions are absent.
- No Organization selector or cross-Organization discovery path exists.
- Reference content remains isolated from Product data and contains no real or
  private information.

### Comparison

Compare the final implementation against the current CRM at both desktop and
mobile widths. The accepted result follows this document, removes the flat
navigation wall and legacy visual discontinuities, and preserves every tested
authorization, no-JavaScript, idempotency, accessibility, and recovery contract.

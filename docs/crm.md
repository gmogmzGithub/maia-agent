# Maia CRM

This document defines the approved experience contract for Maia's operational
CRM. It describes who the workspace serves, what each person must be able to
decide, how work is organized, and which authority boundaries the interface
must make visible. The complete visual system is defined in
[CRM Design System](crm-design.md), with representative screens in
[CRM Reference Screens](crm-mocks.md).

The CRM is a finished operational product surface, not an analytics portal and
not an alternate source of business truth. It presents Product authority so a
person can understand what needs attention, why, who owns it, and what may
happen next.

## Experience promise

Every CRM surface must let an authorized person answer the following questions
without reconstructing the workflow from several pages:

1. What requires attention first?
2. Why does it require attention?
3. Who is responsible?
4. How long has it waited, or when is it due?
5. What action is permitted next?
6. Is the information current and complete?

The design is **work first**. Operational obligations precede aggregate
performance. Metrics explain the health of the operation; they never displace
the people and commitments that require action.

## People and authority

The CRM uses the canonical language in [CONTEXT.md](../CONTEXT.md). “Admin” and
“user” are not product roles.

| Person or authority | CRM experience |
| --- | --- |
| **Organization Administrator** | Sees organization-wide operational work and may perform the administrative actions Product authorizes. |
| **Real Estate Advisor** | Sees owned or assigned commercial work and may perform the actions Product authorizes for that work. |
| **Temporary support member** | Uses the appropriate CRM view in a conspicuous read-only state that names the support purpose and expiry. |
| **Platform Operator** | Remains outside the CRM. Platform operations use the separately authenticated runbook/API surface and never become a CRM superadmin. |
| **Contact** | Has no CRM account. Customer-facing public and shared-report surfaces remain outside the CRM. |

One shared product shell adapts to role and authority. It is not two separate
applications. A person never sees an action they cannot take merely to discover
the refusal after selecting it. A read-only support session retains the same
facts but removes mutation controls and remains visibly read-only throughout.

No page provides an Organization switcher, cross-Organization search,
cross-Organization comparison, or fallback Organization. Every surface is
scoped to the Brokerage Organization resolved by authorization, consistent with
[the managed-platform boundary](managed-platform.md).

## Identity and branding

The active Brokerage Brand leads the CRM identity. The founding Organization's
workspace therefore presents **Larevia** in the reference screens. Maia appears
as the restrained operating product through `Operado con Maia`; it is never an
AI spectacle, chatbot mascot, or substitute for the signed-in person's role.

An Organization may supply its approved name and mark. Layout, typography,
semantic colors, interaction behavior, and accessibility remain part of Maia's
fixed operational system. Arbitrary themes are not part of this design. There
is no invented Platform Brand.

## Role-specific home

The `/crm` route resolves to a home that names its scope explicitly.

### Administrator: Operación de {Brokerage Brand}

The Administrator home is an action-first control surface ordered as follows:

1. Conversations waiting for a human response.
2. Overdue Next Actions.
3. Opportunities without a Responsible Advisor.
4. Appointments requiring review or intervention.
5. Follow-up Coverage and team workload.
6. Pipeline and recent business performance.

Integration or projection problems appear above this order only when the person
can act on them. Business intelligence, sponsorship performance, and detailed
analytics remain one clear navigation step away.

### Advisor: Mi trabajo

The Advisor home is a personal work plan rather than a smaller copy of the
Administrator dashboard:

1. The next action the Advisor must perform.
2. Conversations awaiting the Advisor's response.
3. Today's appointments and preparation.
4. Newly assigned Opportunities.
5. Overdue commitments.
6. Work due in the next seven days.

The Advisor home does not show an organization-wide conversion scoreboard or a
ranking against other Advisors. Follow-up Coverage is a service promise, not a
performance score.

### Temporary support: explicit read-only mode

A support session uses the relevant operational view with a persistent label in
this form:

> Soporte Maia · Solo lectura · Acceso hasta 29 ago 2026, 17:00

The label names the expiry and never suggests broader authority. Mutation
controls are absent. The support grant and its use remain visible to the
Organization as defined by the managed-platform contract.

## Information architecture

Desktop navigation uses a persistent left rail. It shows destinations applicable
to the current role and groups them by the decision they support.

| Group | Destinations | Administrator | Advisor |
| --- | --- | :---: | :---: |
| **Trabajo** | Hoy, Bandeja, Agenda, Oportunidades | Yes | Yes |
| **Relaciones** | Contactos | Yes | Yes, scoped |
| **Inventario** | Catálogo | Yes | Yes, scoped and read-only where required |
| **Crecimiento** | Reactivación, Patrocinios | Yes | No |
| **Gestión** | Asignación, Equipo, Inteligencia, Configuración | Yes | Team information only where authorized |
| **Global** | Alertas, session and role | Yes | Yes, scoped |

On mobile, `Hoy`, `Bandeja`, `Agenda`, and `Oportunidades` remain immediately
available, with `Más` exposing the remaining role-appropriate destinations.
The mobile experience never reproduces the current wall of navigation links.

An unauthorized destination is absent. A record that exists outside the
person's authorized Organization or Advisor scope remains indistinguishable
from a record that does not exist.

## Operational priority

Urgency is deterministic and explained in words.

| Priority | Meaning | Required presentation |
| --- | --- | --- |
| **Ahora** | A person is waiting or an appointment is at immediate risk. | Reason, elapsed time, owner, and immediate permitted action. |
| **Hoy** | An obligation is due or overdue today. | Due time, overdue duration where applicable, owner, and next action. |
| **Próximamente** | Work is due within the next seven days. | Due date, owner, and preparation context. |
| **Revisión** | Work is blocked, ambiguous, incomplete, or failed. | Blocking reason, last trustworthy fact, and safe recovery action. |
| **Al día** | No intervention is required. | Confirmed state and last update; never an inferred green state. |

Priority never derives from a hidden model score. Color reinforces the label
but does not replace it. Queue ordering is stable and explainable: priority,
then due or waiting time, then a deterministic tie-breaker.

## Core workspaces

### Bandeja de conversaciones

Desktop uses three coordinated regions:

- a prioritized conversation queue;
- the selected conversation history and current handling state;
- Contact, Opportunity, ownership, Next Action, restrictions, and permitted
  actions.

The selected record must make Conversation Handling Mode explicit. A person can
see whether Maia may converse, a human is handling the Contact, the operation is
awaiting the Contact, or Admin review is required. A Human Handling Request
shows its age, who was alerted, and the current holder. It never implies an
automatic reassignment.

Do Not Contact, denied outbound reasons, expired content, delivery failures, and
the customer service window are visible at the decision point. They are not
hidden in history or exposed only after a send attempt.

### Opportunity workflow

An Opportunity is presented as a workflow, not a database record or a stack of
unrelated forms.

- The sticky summary names stage, Responsible Advisor, Follow-up Coverage,
  Next Action, urgency, and last activity.
- The main column presents Property Need, confirmed and pending criteria,
  current activity, and outcome.
- The action rail presents only actions currently permitted for the role and
  state.
- Assignment, stage, Next Action, exception, and outcome history follow the
  current work rather than competing with it.

The page must answer `¿Qué busca?`, `¿Quién responde?`, `¿Qué sigue?`, `¿Cuándo?`,
and `¿Qué impide avanzar?`

### Agenda

Agenda distinguishes confirmed appointments from appointments requiring review.
It names the Responsible Advisor and the Advisor conducting the visit when they
differ. Reminder state, attendance, outcome, authoritative rescheduling options,
and partial delivery failures remain visible. An appointment is never styled as
confirmed when Product only holds a request or review state.

### Contacts

A Contact page joins authorized channel identities, conversations, Property
Needs, Opportunities, appointments, communication restrictions, consent, and
retention-visible history without treating a phone number as identity. Contact
and Opportunity remain distinct.

### Team and assignment

Team surfaces distinguish member role, opportunity ownership eligibility,
calendar authority, alert channel, default-Advisor configuration, load,
Advisor Absence, and Property expertise. Property Expert never appears as a
synonym for Responsible Advisor.

Assignment explains why Product kept an owner, selected an expert or backup,
used the default Advisor, or placed the Opportunity in the Assignment Queue.
The interface must not imply round-robin or hidden load scoring.

### Catalog and external inventory

The Catalog keeps Property, Listing, and Listing Offer distinct. Capture never
means publication. Availability, publication state, authority, fact review,
presentation readiness, price visibility, media provenance, and freshness are
shown as separate facts.

External inventory presents source health, last successful evidence, freshness,
mapping issues, credential-reference presence, withdrawal state, and the legal
or retention gates that block authority. Synchronization never makes an external
record authoritative by itself.

The responsibilities of the legacy `/admin/properties` and English `/upload`
interfaces belong in Catálogo and its guided property-document workflow. Those
legacy routes are transitional surfaces to retire and are not part of the
approved CRM experience.

### Reactivation, sponsorship, and intelligence

Reactivation remains Administrator-only and exposes consent, provider,
template, audience, frequency, and exact-content authorization before outreach.
Candidate or audience views use opaque Product references rather than exposed
Contact identity where the domain requires it.

Sponsorship separates capacity, pricing, quote, campaign, delivery, collection,
and reporting states. Presentation Tier never changes operator service quality
or CRM styling.

Business Intelligence remains aggregate-only. It displays measurement version,
scope, period, freshness, completeness, late projection state, and exclusions.
It distinguishes `0`, `Sin registrar`, and `No calculable`.

### Alertas

Alertas is a durable center, not a transient toast stream. The global count
contains only open, actionable Internal Operational Alerts visible to the
current role. Each item names severity, age, affected record, owner, delivery
state, and next action. Resolved history remains searchable but leaves the
badge.

## Consequential actions

Routine reversible work remains inline. A consequential action uses an explicit
review step that states:

- the exact record and current state;
- the requested change;
- the customer or operational consequence;
- required evidence or reason;
- what cannot be undone;
- a final button with a specific verb.

Closing an Opportunity, changing ownership, publishing inventory, authorizing
outreach, cancelling a visit, or changing Organization configuration never
relies on a generic browser confirmation.

## Metric contract

Every reported number shows its scope, period, last update, and definition or
calculation basis. It declares whether the value is current, delayed,
incomplete, or unavailable and links to the records or explanation behind it
when authorization permits.

Comparisons appear only when their periods and definitions are compatible.
Current operational state, rolling 30-day intelligence, calendar-month usage,
30-day sponsorship capacity, and campaign-period reporting are never presented
as though they share one time window.

## Reference-content boundary

The reference screens use one coherent set of invented, public-safe operational
information. Names, conversations, opportunities, properties, appointments,
amounts, and metrics are intentionally fictional. They contain no real phone
numbers, street addresses, credentials, provider identifiers, customer text, or
private property documents.

Rendered CRM screens contain no environment banner, placeholder label, or
fictionality notice. The safety rule lives in documentation and asset metadata,
not in the depicted product. Reference content must never be imported into
Product as authoritative CRM, Contact, inventory, or analytics data.

This rule is specific to the CRM reference package. It does not alter the
separate public-site media and local-preview rules in
[Public Site Design System](public-site-design.md).

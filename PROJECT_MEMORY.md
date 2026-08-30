# Maia Project Memory

This file is the public, curated memory for Maia. It is meant to help future
contributors and AI coding agents continue the project without relying on
private Codex memory.

## Name

The product name is **Maia**.

Reasoning:

- Maia is short, person-like, and easy in English and Spanish.
- It has a warm guide/operator feel that fits real estate conversations.
- It has a subtle mythological connection to Hermes without sounding like a
  derivative product name.

## Product Goal

Maia is a real estate lead agent for WhatsApp-driven property inquiries. It
should qualify leads, answer grounded property questions, schedule visits, and
follow up consistently.

The product is not just a chatbot. It is an agentic product where Hermes handles
conversation and the Maia backend provides deterministic authority.

## Business Direction

Maia will first support a technology-enabled Mexican real-estate brokerage led
operationally by Santiago. Santiago begins as its only Real Estate Advisor; the
team can later add Advisors, designate a primary Property Expert and backups,
assign each Opportunity to one Responsible Advisor, and preserve commercial
attribution without initially calculating or paying commissions.

The core operating promise is: **no qualified Opportunity is left without a
Responsible Advisor, a next action, or a recorded outcome**. The first CRM is an
operational inbox for enforcing that promise, not a general-purpose enterprise
CRM.

The brokerage is the first business. A multi-agency software platform remains a
possible later product, so organizational ownership and integration boundaries
should be explicit without prematurely building SaaS onboarding, billing, or
dedicated deployments.

The Brokerage Organization's own Authorized Inventory comes first. EasyBroker may later provide
organization-authorized collaborator inventory, but it is not assumed to contain
every property in Mexico and must remain a replaceable external source with
provenance, freshness, attribution, and permission controls.

An Opportunity is Qualified once its transaction intent, acceptable area,
economic range, approximate horizon, essential requirements, and legitimate
contact path are known well enough to advance. Its commercial stages are New, In
Conversation, Qualified, Searching, Visiting, Negotiating, and the terminal or
paused outcomes Won, Lost, and Dormant. Assignment, appointments, consent, and
Do Not Contact remain independent state rather than being overloaded into that
pipeline.

An Organization Administrator can see the whole operation. Advisors have scoped
commercial access. The initial absence rule stays deliberately simple: only an
Organization Administrator records or ends an Advisor's absence, and Maia
excludes that Advisor from new assignments during the declared period. Existing
Opportunities and appointments are not silently reassigned or cancelled; they
are surfaced for Administrator review.

CRM, assignment, follow-up, inventory, appointments, integration policy, and
operational analytics begin as modules of one Product sharing PostgreSQL.
The public site and Hermes remain separate processes. Product, not EasyBroker,
owns the authoritative Contact, Opportunity, consent, assignment, and outcome
state.

The public site initially uses WhatsApp as its primary lead-entry CTA. The site
shows only Organization Listings and Collaborator Listings with explicit current
publication authority. The same physical Property may have several Listings;
Product preserves each Listing's source and does not merge them without evidence
that they represent the same Property.

New-inventory reactivation starts as an explainable match reviewed and authorized
by an Organization Administrator. Development announcements are explicit
Campaigns with audience, consent, exclusions, limits, and measurable results,
not an unrestricted send-to-all action.

The initial unanswered-inquiry hypothesis is deliberately conservative: an
immediate response followed, when permitted, by WhatsApp contacts on days 1, 3,
7, 14, and 28. Any reply stops the generic sequence; a Qualified Opportunity
instead follows its contextual Next Actions. At day 28, silence produces a
Dormant Opportunity with a recorded reason, not a Lost outcome. Calls remain
human actions recorded in the CRM, and automated email follow-up is deferred
until customer behavior demonstrates that it is useful.

The operational metric is Follow-up Coverage: the proportion of active Qualified
Opportunities that have a Responsible Advisor, an updated stage, and a Next
Action that is not overdue. The target is 100 percent; conversion and harm
metrics remain separate.

The initial pilot scorecard contains time to first response, contacted rate,
qualification rate, Follow-up Coverage, appointments scheduled, appointment
attendance, and outcome completeness. Closed sales remain an essential business
result but are too delayed to serve as the only early product signal.

Hermes conversation context and full message bodies expire by default after 90
consecutive days without interaction; a later contact begins a new Conversational
Session. This does not erase the commercial model. Contact identity,
Opportunities, outcomes, consent, Suppression Records, attribution, and minimal
audit evidence follow purpose-specific retention rules. A Property Need becomes
Stale after 90 days without confirmation and must be reconfirmed before Maia uses
it as current truth.

Historical Stale Property Needs may identify candidates for Administrator-reviewed
reactivation, subject to consent and suppression. Long-lived BI should retain
business events without indefinite message bodies or unnecessary identity, using
aggregation or anonymization when identification is no longer needed. Final
retention periods remain subject to Mexican legal review.

An external Listing may be indexed locally to find candidates, but Maia must
revalidate its availability, price, authority, attribution, and commission before
actively recommending it or scheduling a visit. An Organization Listing takes
priority over a Collaborator Listing for the same proven Property; Listings are
never merged automatically from textual or image similarity alone.

The initial Service Area is the Guadalajara Metropolitan Area, limited to
Guadalajara, Zapopan, and Tlaquepaque. Access to a Listing elsewhere does not mean
the Brokerage Organization can responsibly promise service there.

Out-of-area search, referral, and transaction workflows are deferred to a later
version. During the MVP, Maia does not search or promise service outside the
Service Area; it states the limitation and records the Opportunity outcome as Out
of Service Area.

The MVP has two product roles. The Organization Administrator sees the entire
operation and controls team, absences, assignments, Listings, and configuration.
A Real Estate Advisor works scoped Opportunities and Properties for which they
are the expert; Santiago initially has both roles.

Assignment stays deterministic: preserve an existing Responsible Advisor; for a
new Listing-specific Opportunity choose the present Property Expert; otherwise
use the configured default Advisor; if that Advisor is absent, place the
Opportunity in the Assignment Queue for Admin action. No round-robin, load
scoring, or acceptance SLA belongs in the MVP.

Human Advisors reply through the CRM using the Brokerage Organization's official
WhatsApp channel rather than fragmenting the relationship across personal
numbers. Conversation Handling Mode explicitly prevents Maia and a human from
replying concurrently. The first CRM surfaces are Inbox, Opportunities, Contacts,
Listings, and Calendar.

When a customer asks for a human, Maia acknowledges warmly, alerts the Advisor
immediately, and does not expose a formal service-level deadline or claim to know
the Advisor's availability. Suitable customer copy is: "Perfecto, le avisaré al
asesor. No puedo confirmar su disponibilidad en este momento, pero haré todo lo
posible para que se comunique contigo en los próximos minutos." The internal
operation still records and monitors the handoff so the request cannot disappear.

The assigned Advisor receives the human-handoff alert immediately. If nobody has
taken handling authority after 15 minutes, the Organization Administrator receives
a visible alert; Product does not automatically reassign the Opportunity in the
MVP.

Every human-visible product and operational surface uses Mexican Spanish: the
public site, CRM, forms, navigation, statuses, notifications, reports, validation,
and error messages. Customer-facing real-estate vocabulary is Mexican, including
`recámaras`, `baños`, `metros cuadrados`, `renta`, `venta`, `asesor inmobiliario`,
and `agendar una visita`; internal labels such as `lead`, `listing`, `pipeline`,
and `property expert` never leak into the interface. Internal source-code
identifiers and engineering documents may remain in English.

Maia uses friendly, professional Mexican Spanish and `tú` by default, while
matching `usted` when a Contact clearly uses or requests that register. The
product interface remains in Mexican Spanish, but Maia may converse in any
language the Contact uses or explicitly requests. Language is a conversation
choice, not an inferred nationality or permanent personal attribute.

Maia's multilingual ability does not turn it into an interpreter for Advisors.
Before confirming a human handoff or appointment in another language, Maia tells
the Contact plainly that the Advisors provide service in Spanish. Product does
not translate live Advisor conversations or let an Advisor use Maia as a
bidirectional translation relay.

Multilingual service applies freely to customer-initiated conversations, but a
proactive WhatsApp follow-up may use only a template approved for that language.
The MVP begins with Spanish proactive templates and adds languages only when real
demand justifies approval; lacking an approved template means no proactive message
in that language. CRM retains the original message and conversation language plus
an operational summary in Spanish, not a permanently stored translated duplicate
of every message.

Prices default to MXN and areas to square metres. A Listing legitimately priced
in another currency retains that currency; Product never presents an automatic
conversion as an authoritative contractual price.

Product may create deterministic Next Actions, while Maia may propose actions
derived from a conversation for an Advisor to accept, change, or replace. Every
appointment belongs explicitly to an Advisor and uses that Advisor's availability;
Santiago's calendar is the only initial connection. A Property Expert conducts a
visit instead of the Responsible Advisor only when that responsibility is made
explicit.

The Appointment Handoff makes the Advisor responsible for subsequent service,
negotiation, documents, offers, reservations, contracts, and closing. Maia may
continue bounded Appointment Logistics and may later re-enter as a Transaction
Journey coordinator only after an authorized Organization Member explicitly
starts that Journey in the CRM. Product freezes a versioned milestone plan and
humans confirm every material state; Maia communicates those confirmed states,
pending work, reminders and delays without negotiating, interpreting documents
legally, approving financing, inferring completion or declaring the sale Won.

Appointment confirmations and reminders are deterministic Larevia system
messages rather than open-ended sales messages composed by Maia. The starting
hypothesis is confirmation immediately after booking, one reminder 24 hours
before, and another on the appointment day. A reply concerning appointment
logistics may be handled by Maia.

After an Appointment Handoff, Product routes clear confirmation, rescheduling,
or cancellation requests to Maia and commercial or visit questions to the
Advisor; ambiguity goes to the Advisor. Rescheduling is atomic from the
customer's perspective: Product secures the new valid slot before releasing the
old one, and failure preserves the original appointment. A later explicitly
started Transaction Journey creates a separate bounded authority for Maia to
explain and communicate its human-confirmed milestones.

Cancelling an appointment never closes the Opportunity. Maia confirms the
cancellation and asks once whether the Contact wants another time; the Advisor
later decides whether the Opportunity remains active, becomes Dormant, or is
Lost. A Missed Appointment is recorded by the Advisor and triggers a Maia
rescheduling invitation only when the Advisor explicitly authorizes one.

The MVP retains the existing 90-minute appointment duration. Per-Property or
per-Advisor duration configuration is deferred.

An automated appointment in the MVP is one confirmed 90-minute Property visit
linking one Contact, one Advisor, and one Property. Calls, video calls, office
meetings, and multi-property tours remain manually coordinated Advisor activities.
There is no `soft` versus `solid` appointment vocabulary: Product says Confirmed
only after both its own state and the authoritative calendar event succeed.

Product does not calculate traffic or travel routes. Advisors protect additional
travel time with busy blocks in their authoritative Google Calendars. Accompanying
visitor names and counts are optional and captured only when volunteered or when
a Property's access policy explicitly requires them.

After the visit, the Advisor records whether it occurred, the Contact's known
interest, the Next Action, and the outcome; Product reminds the Advisor internally
when this record is missing. Maia does not independently pursue the Contact, but
an authorized member may start the accepted buyer Transaction Journey when the
deal begins formal processing. A later Administrator-authorized match with
genuinely relevant new inventory may still open a separate reactivation
conversation whose commercial objective is another appointment.

A Development groups multiple houses, apartments, or lots that may be marketed
in volume and may differ in their characteristics. It is not itself one Property
or Listing.

The CRM recognizes Demand Opportunities from people seeking to buy or rent and
Listing Acquisition Opportunities from owners seeking help to sell or rent. The
MVP handles Listing Acquisition minimally: Maia captures basic facts and hands the
case to the Admin without automatic valuation, commission promises, document
acceptance, or publication.

A Development may contain identifiable Properties and repeatable Unit Models; a
Listing can offer a specific Property or Unit Model without creating fictitious
physical units. Listing Availability, Publication State, and Authority remain
separate, and all must permit the intended action before Maia presents an offer.

Every Opportunity preserves its first known commercial origin and supporting
source, channel, campaign, advertisement, Listing, referral, and participant when
available. Maia may persist explicit criteria, but material interpretations or
normalizations remain Pending Criteria until the Contact confirms them.

Only an Organization Administrator marks an Opportunity Won. A visit, reservation,
or accepted offer is not itself a win; the accepted terminal evidence is a legally
completed sale, signed rental agreement, or binding presale contract accepted by
the operation. A separate Transaction records the resulting Contact, Listing or
Property, participants, dates, known final price, attribution, and manually entered
expected, earned, and collected gross commission. The MVP does not automate
commission splits, invoicing, taxes, or payments.

A Listing Acquisition Opportunity never publishes a Listing automatically. The
Admin first reviews ownership, Property facts, commercial conditions,
authorization, and documentation; Listing Authority remains Pending until that
human process is complete.

EasyBroker production integration is gated on Santiago's account access and
written clarification of MLS scope, search, publication, caching, retention,
attribution, and future multi-organization use. Staging exploration may proceed,
but no production key or external catalog promise precedes that gate.

The intended build order is: commercial model and CRM foundation; organization,
roles, Contacts, Property Needs, Opportunities, assignment and Inbox; Human
Handling and Next Actions; remodel the current Property documents into physical
Properties, commercial Listings, and Listing Offers with organization ownership
and independent Availability, Publication State, and Authority; only then build
catalog search, the public site, and Organization Listings; Advisor scheduling;
read-only Service Area-limited EasyBroker integration; Admin-reviewed
reactivation; Development Campaigns; then advanced analytics and experiments.

The next MVP excludes multi-organization SaaS, dedicated customer deployments,
out-of-area operation, automated commission payment, automated valuation,
contracting or signature, automatic publication of acquired Listings, fully
automatic Campaigns, predictive scoring, a separate data warehouse, and a native
mobile application.

The eventual external product is a narrow real-estate operating platform, not a
general-purpose CRM. Its commercial promise is to prevent Qualified Opportunities
from being lost without a Responsible Advisor, Next Action, or relevant follow-up.
It should begin as a managed service with accompanied onboarding rather than a
self-service signup or dedicated server per customer.

Future commercial packaging is expected to combine a base organization fee,
Advisor-based tiers, transparent WhatsApp/model usage, paid onboarding, and
optional integration add-ons. Per-lead or commission-percentage pricing is not the
initial model. Each Brokerage Organization owns its identifiable operational data;
cross-organization access, credential sharing, or model training on mixed customer
data is prohibited. A Brokerage Organization may contribute selected Property,
sale and Purchase Profile analytical facts into a separate Platform-wide Shared
Market Dataset. That projection contains no Contact identity, channel identity,
document or conversation and never grants one brokerage access to another's CRM.

Listings and Developments are administered in the Platform's authoritative catalog and
consumed by the public site. A second independently editable website catalog or CMS
must not create competing price, availability, or publication truth.

Listing Media is a Platform and public-site responsibility, not a Maia Agent
capability. The MVP accepts Administrator-approved JPG, PNG, and WebP photographs
with known provenance and publication authority. The Administrator selects the
cover and gallery order; Maia neither chooses, analyzes, captions, nor moderates
the images.

Each published Listing has two intentional destinations: a distinctive,
mobile-first Listing Gallery URL focused on its photographs, and a Listing
Technical Sheet URL focused on authorized facts. During lead service Maia may
share either or both approved URLs, but does not send a full image gallery through
WhatsApp. Videos, 360-degree tours, interactive renders, downloadable plans, and
PDF media are deferred from the MVP.

The Listing Gallery and Listing Technical Sheet are separate, mutually linked
experiences. The Gallery uses a full-screen cover, customer-controlled swipe
navigation, progress count, optional thumbnail grid, and Administrator-assigned
groups such as facade, social areas, kitchen, bedrooms, bathrooms, exteriors, and
amenities. It never auto-advances.

Photography remains visually dominant. Overlays are limited to the short Listing
name, Public Location, price, a Technical Sheet link, and a persistent but discreet
`Me interesa esta propiedad` action. That action preserves Listing context and
offers `Seguir por WhatsApp` or `Continuar en el sitio`. Visitors may share the
Gallery URL; bulk download and default watermarks are excluded from the MVP.

The Gallery is mobile-first across ages and economic contexts: optimized responsive
variants, immediate cover loading, next-image preloading, progressive remaining
media, readable controls, accessible contrast, and no interaction that depends on
fine motor precision or technical familiarity.

Presentation varies by Listing value, never by inferred Contact wealth or social
class. Every tier preserves the same speed, accessibility, factual clarity,
sharing, Technical Sheet, Maia access, and appointment path. Each tier has exactly
one product-owned template: `Larevia` is the excellent default treatment;
`Premium` adds more editorial spacing, curated visual sequencing, typography, and
restrained transitions; `Super Premium` adds a more cinematic full-bleed
composition, visual chapters, and an accessible exclusive palette without
changing the interaction model. Administrators cannot customize colors or create
per-Listing theme variants.

For houses and apartments offered for sale, analytics bands are below MXN 5M,
MXN 5M-8M, MXN 8M-12M, MXN 12M-20M, and above MXN 20M. Presentation Tier is
Larevia below MXN 12M, Premium from MXN 12M through MXN 20M, and Super Premium
above MXN 20M.

For houses and apartments offered for rent, the Administrator enters the actual
monthly rent; Product never derives or recommends it from a sale price. The
initial analytics bands are below MXN 20K, MXN 20K-35K, MXN 35K-50K, MXN
50K-85K, and above MXN 85K monthly. Presentation Tier is Larevia below MXN 50K,
Premium from MXN 50K through MXN 85K, and Super Premium above MXN 85K.

Product assigns Presentation Tier automatically from the current manually entered
price and configured thresholds. It also performs deterministic Presentation
Readiness checks rather than subjective AI aesthetic scoring. An Organization
Administrator may explicitly override the assigned tier or readiness result. The
thresholds are configuration reviewed every six months, not permanent constants.
These tiers initially apply only to houses and apartments; land and Developments
require later presentation rules.

Any active Listing Offer denominated in USD contributes Premium regardless of the
USD amount. A Listing with several active Offers uses the highest contributed
Presentation Tier, unless an Administrator explicitly overrides it. The Platform
does not convert or display that price in MXN.

An Administrator may manually set an Offer's Public Price Visibility to hidden.
The authoritative manually entered price remains required internally, while the
site shows `Precio disponible previa consulta` and a `Solicitar precio` action in
place of the number. Concealment is never inferred automatically. When a Contact
privately requests the price, Maia may disclose the authoritative amount directly.

One Listing and public URL may contain both a sale Offer and a rental Offer,
sharing Property facts, Listing Media, attribution, and gallery while retaining
operation-specific price, currency, visibility, terms, and availability.

The Technical Sheet presents the active sale and rental Offers as distinct sections
within that one Listing. Product passes the selected Offer as conversation context
when available, but never forces the Contact through a buy-versus-rent form: Maia
follows the natural conversation and asks only when operation intent is genuinely
ambiguous.

Offer availability is independent. A completed sale disables both sale and rental
Offers; a completed rental disables the rental Offer while the Administrator
decides whether the sale Offer remains active. Hidden prices still participate in
authorized matching, filtering, bands, and tier selection without appearing on
public surfaces.

Presentation Readiness initially requires a cover, at least 6 approved photographs,
and complete required facts for Larevia; a high-resolution cover, at least 12
approved photographs, and 4 space groups for Premium; and a high-resolution cover,
at least 20 approved photographs, and 6 space groups for Super Premium. An
Administrator may override a failed check.

Changing a Listing price automatically recalculates its Presentation Tier unless
an Administrator override is active; an override remains until explicitly removed.
The Administrator does not enter a reason for an override, while Product records
the actor and time automatically as ordinary audit evidence.
Gallery and Technical Sheet URLs never change with the tier. Product measures
gallery opens, photographs viewed, exploration depth, Technical Sheet opens,
conversation starts, and appointments by Listing and tier, while avoiding causal
claims from unmatched price bands.

Published Premium and Super Premium Galleries remain public and require no
customer account. Publication Authority, not price or Presentation Tier, controls
visibility; private or off-market access is deferred as a separate capability.

Unpublishing a Listing removes its media from every public surface immediately.
The Platform may retain it internally only while an operational purpose and media
authority remain; revoked media authority requires deletion from storage and
public caches.

The public site's navigation and Listing pages remain in Mexican Spanish. Maia
may explain an authorized Listing in the Contact's requested language without
requiring a translated copy of the entire site.

Saving a Listing requires no account. Product creates a server-authoritative Saved
Collection and gives the browser an opaque first-party session identifier through
a Secure, HttpOnly, SameSite cookie; the token contains no personal data and is
not used for advertising. A local cache makes the interface immediate and can
queue offline intent, but it is never the only copy or authoritative confirmation.

The save control distinguishes `Guardada` only after server confirmation from
`Pendiente de guardar` while offline or retrying. Add and remove operations are
idempotent, automatically retried, deduplicated across tabs, and reconciled after
reconnection without silently discarding a Listing.

A customer may voluntarily protect and synchronize the Saved Collection through
their verified WhatsApp Contact without creating a password-based account. Product
does not link an anonymous collection to a Contact merely because they start a
conversation; the customer explicitly chooses to share or protect it. When a saved
Listing becomes unavailable, the collection retains a clearly marked historical
item and may offer authorized alternatives rather than removing it silently.

The control combines a heart with the explicit verb `Guardar`, and the destination
is `Mis propiedades guardadas`. Product displays `Guardada` only after server
confirmation, `Pendiente de guardar` while offline or retrying, and a clear retry
action after a conclusive failure. After the first successful save, a non-blocking
prompt may offer `Proteger con WhatsApp`; saving never requires that step.

Protection opens the official WhatsApp channel with an opaque reference and links
the collection only after verified-channel confirmation. Product explains that an
unprotected anonymous collection cannot be recovered after the browser data is
cleared and never substitutes fingerprinting. Anonymous collections expire after
12 months without activity; protected collections follow Contact retention, and
customers may empty or delete them at any time.

`Compartir mi selección` creates a revocable opaque read-only URL containing no
identity or conversations. `Hablar con Maia sobre mis propiedades guardadas`
explicitly shares the selected Listing identifiers with Maia; beginning an ordinary
conversation never shares them automatically.

Protecting a collection merges the anonymous browser collection with any existing
Protected Saved Collection for that verified Contact, deduplicating Listings; all
linked devices then use the same server-authoritative collection. A Shared
Selection is a fixed snapshot: later collection edits do not change an already
shared link. A recipient may copy Listings into their own independent collection
but cannot edit the sender's snapshot.

Sharing with Maia is also a point-in-time selection, not permanent visibility into
future saves. The MVP has one Saved Collection rather than user-created folders;
customers create focused subsets through Shared Selections. An unavailable item
may offer `Ver propiedades similares` through deterministic nonsensitive matching
or `Preguntarle a Maia`, neither of which authorizes proactive outreach or shares
the full collection.

`Vaciar mis propiedades guardadas` deletes collection contents only. It never
silently deletes Contact identity, Conversations, Opportunities, consent, or other
records governed by separate retention and data-rights processes.

The consumer-facing brand architecture is deliberately simple: customers see
**Larevia** as the Brokerage Brand and **Maia** as the named assistant. Larevia is
a working name pending formal trademark clearance. The future B2B Platform Brand
remains unnamed and invisible during the brokerage MVP; `Product` is only an
internal generic label, not customer-facing copy. A separate platform name should
be selected only after a real external platform offer has been validated.

The Larevia site must have a recognizable, more-premium service personality while
remaining plain, welcoming, and usable across ages and socioeconomic contexts.
TuHabi is a reference for a clear promise, immediate action, short process, and
visible trust; Vecore is a reference for naming a human service posture. Neither
site is a template, specification, or source of copy. Larevia will not copy
Vecore's `Consejeros Inmobiliarios` identity or TuHabi's direct-purchase promise.

Larevia's working central promise is **Acompañamiento inmobiliario que sí
continúa**. It expresses the operation's differentiator—persistent, accountable
follow-up—without implying that Larevia buys properties, guarantees a transaction,
or serves only affluent customers. Publicly, the team is described as
**Especialistas inmobiliarios** and a designated Property Expert appears on a
Listing as **Tu especialista en esta propiedad**.

The homepage gives two equally clear paths: `Cuéntale a Maia qué estás buscando`
and `Explorar propiedades`. Maia remains available but never opens automatically.
Contextual invitations may open Maia with the current Listing's opaque identifier
and authorized facts. The homepage presents a curated set of six to eight
Listings rather than embedding the complete catalog; operation, type, and zone
provide the main routes into search.

The catalog begins with only operation, zone, and property type, then displays
results immediately. Price is always available as a primary refinement; other
criteria live under `Más filtros` and appear only when applicable to the selected
property type. `Dile a Maia qué buscas` provides a parallel natural-language path:
Maia confirms ambiguity and compiles the same authoritative search criteria rather
than using a separate hidden catalog.

Search results are card-first with an optional `Ver en mapa` view based only on
Public Location. A card shows its cover, short name, Public Location, operation,
public price or consultation message, three or four applicable characteristics,
and `Guardar`. Advisor identity, complete description, and full amenities belong
to the Listing Technical Sheet.

The default `Más relevantes` order is deterministic from explicit criteria,
current availability and authority, and update freshness. Customers may choose
`Más recientes`, `Menor precio`, or `Mayor precio`. Any paid placement is visibly
labeled **Patrocinada**; payment never masquerades as organic relevance. The
commercial rules for sponsored inventory require a separate explicit decision.

A Sponsored Placement may be purchased initially by a property owner, Developer,
or External Collaborator for an eligible authorized Listing through a manually
administered 30-day Sponsorship Campaign. It purchases additional visibility on
search, homepage, or both, never guaranteed leads, appointments, or a transaction.
An unpaid editorial selection is `Destacada`, not `Patrocinada`.

A sponsored Listing must satisfy every hard search criterion and retains its
ordinary Presentation Tier. Search shows at most one Sponsored Placement per six
visible results, including the first position only when relevant; the homepage has
at most two in a clearly sponsored section. The `Patrocinada` label appears above
the Listing name and is programmatically available to assistive technology.

Sponsorship never affects Maia recommendations. Maia selects Listings from
confirmed need, availability, authority, and match quality. A campaign also cannot
waive publication, media, availability, or Presentation Readiness requirements.
Product automatically pauses an ineligible campaign, preserves remaining paid
days, and permits an Administrator to resume it after revalidation or move the
remaining value according to the commercial resolution.

One confirmed physical Property may occupy only one sponsored position in a
result set. The Sponsorship Campaign remains attached to the paying source Listing
for attribution and routing. Each Brokerage Organization controls sponsorship
only on its own surfaces and authorized inventory; cross-organization advertising
is a distinct future business, not an MVP platform feature.

Sponsorship reporting preserves first Opportunity Origin and separately records
sponsored exposure and engagement. The buyer receives campaign delivery,
impressions, Listing Technical Sheet opens, Gallery exploration, saves, Maia
starts, WhatsApp handoffs, verified appointments, and known outcomes without any
claim that exposure alone caused them. Sponsorship analytics require an internal
Administrator dashboard and a separate buyer-safe presentation designed to sell
and explain the product simply without exposing Contact identity or conversations.

Sponsorship analytics provides three purpose-specific views over the same metric
definitions: an internal Administrator dashboard for operations, capacity,
revenue, and data quality; a simple presale presentation using safe historical
comparables; and a campaign-scoped buyer report. The buyer report is delivered
through a revocable expiring read-only link and exportable PDF rather than a CRM
account in the MVP.

The official sponsorship funnel is Visible Impression, Listing Technical Sheet
open, Gallery open, Significant Gallery Exploration, saved or shared, Maia start,
WhatsApp handoff, appointment request, verified appointment, attended appointment,
and known Opportunity outcome. A Served Impression is distinct from a Visible
Impression. The initial visible definition requires at least 50 percent of the card
for one second; Significant Gallery Exploration requires at least five photographs
or 30 percent of the gallery. Definitions and their versions are retained so
historical reports remain explainable.

Presale evidence uses comparable operation, municipality, property type,
Commercial Price Band, Presentation Tier, and sponsored surface. It reports
medians, ranges, periods, and sample size for 30- and 90-day demand and downstream
actions. Insufficient history is disclosed as `Estimación inicial sin historial
suficiente`; no leads or appointments are guaranteed. Before causal experiments
are supported, the report says an outcome occurred after sponsored exposure or
engagement, never that sponsorship caused it.

Attribution initially uses up to seven days after a viewable impression without an
open and up to 90 days after a sponsored Listing open, reporting view-through and
engaged outcomes separately. It preserves first Opportunity Origin and permits
comparison with the Listing's own prior period, comparable organic Listings, the
median of comparable sponsorships, and each purchased surface.

Buyer-visible reports contain only counts, rates, trends, campaign price, and
campaign unit economics. They never expose Contact identity, phone numbers,
conversations, individual searches, or individual Saved Collections. Internal
views add contract price, discount, currency, collection state, sold and available
inventory, active and remaining days, contracted and collected revenue, and
effective cost per thousand Visible Impressions, open, conversation, and verified
appointment.

The top buyer view contains four headline measures—Visible Impressions, Listing
opens, conversations, and verified appointments—followed by one funnel, daily
delivery trend, interest actions, campaign status, days remaining, and plain
Mexican-Spanish definitions. Interaction data may lag up to 15 minutes; business
outcomes update when recorded; comparable benchmarks recalculate daily.

Unknown appointment and Opportunity outcomes remain `Sin registrar`. The internal
dashboard shows Follow-up Data Completeness rather than treating missing work as a
loss or zero conversion. Known bots, internal and Administrator traffic, tests,
abnormal repetition, and duplicate event identifiers are excluded and reported as
invalid traffic.

Product emits immutable, idempotent analytics events through its durable Outbox.
The MVP stores raw pseudonymous events in a separate PostgreSQL analytics schema
and builds versioned aggregates and materialized views for dashboards. This
preserves a later replication path to a dedicated analytical warehouse without
making one an MVP dependency. Analytics events remain separate from conversations
and direct personal data; exact raw and aggregate retention requires a later legal
and privacy decision.

Sponsorship Campaign state is Draft, Quoted, Reserved, Scheduled, Active, Paused,
Completed, or Cancelled. A quote is valid for seven days but does not consume
capacity; an Administrator reserves capacity after sufficient commercial
acceptance. Product forecasts capacity from eligible historical searches,
available sponsored positions, and active reservations and refuses inventory that
would dilute expected delivery excessively.

When several active Sponsored Placements qualify, Product rotates them equitably
according to delivered opportunity share. A Listing receives at most three paid
Visible Impressions per anonymous session per day, after which it may still appear
organically. Campaign buyers cannot supply separate advertising creative: the
authorized Listing card, media, facts, and accessible `Patrocinada` label are the
only presentation.

Sponsorship pricing uses an Administrator-managed, versioned catalog for search,
homepage, and both surfaces. A quoted campaign preserves its quoted catalog
version. An Administrator may apply a launch, repeat-customer, multi-property,
compensation, or negotiated discount with a recorded reason. Prices are not
hard-coded, auctioned, or billed per click in the MVP.

A one-page sponsorship quote shows the exact Listing preview, surfaces, active
period, final price, quote expiration, safe comparable demand, estimated Visible
Impression range, aggregate funnel, visible sponsorship disclosure, and explicit
absence of lead, appointment, or transaction guarantees. The Platform records
agreed price, currency, collection state, date, and external reference, while
payments, transfers, invoicing, and tax accounting remain external.

Campaigns do not auto-renew. Product notifies the Administrator seven and three
days before completion; a later campaign requires a new quote and may use prior
results as evidence. Paused paid days remain available for the same revalidated
Listing, transfer to another eligible Listing of the same buyer, extension of
another campaign, or an externally resolved refund, with the Administrator's
decision recorded and no automatic money movement.

Eligibility is checked daily and again before each paid exposure. The campaign
contract records the contracting person or entity, representative, contact,
relationship and authority over the Listing, accepted terms, commercial price,
currency, discount, collection reference, and external documents. The buyer must
accept publication/media authority, truthful Listing facts, visible sponsorship
labeling, eligibility-based suspension, aggregate-only reporting, non-guaranteed
results, and the fact that payment never changes Maia or Advisor judgment.

The first sponsorship price is not fixed before traffic instrumentation and a
small controlled pilot. Actual eligible impressions, engagement, and verified
appointments will support a founding price and later stable price catalog rather
than an invented amount.

Real-estate and sales assumptions requiring Santiago's review are maintained in
`docs/open-questions/SANTIAGO_REAL_ESTATE_REVIEW.md`. That document is the single review queue
for operational expertise; it does not give Santiago responsibility for software,
security, privacy-law, or infrastructure decisions outside his domain.

When multiple source Listings are confirmed to describe the same Property, public
search presents one result and prefers the Organization Listing while preserving
source-specific truth and attribution internally. Product never merges unconfirmed
physical identity.

A zero-result search preserves every chosen criterion and explains that there is
no exact match. It offers explicit actions to ask Maia for additional authorized
inventory or relax one zone, budget, or characteristic constraint. It never
silently broadens the search, and Maia distinguishes exact matches from approximate
alternatives.

Dynamic filter URLs are shareable but non-indexable by default. Only curated,
useful search landing pages with sufficient current inventory and verified local
content become canonical indexable pages. Results load in groups of approximately
24 through `Mostrar más`; filters, result state, and scroll position survive back
navigation rather than relying on endless scrolling.

The catalog does not personalize invisibly from age, device, inferred location,
or passive behavior. The same explicit search produces essentially the same
organic results. Personalization requires criteria consciously shared with Maia
or an explicit Saved Collection action. The MVP has no separate Saved Search:
confirmed Property Needs and consented reactivation already own new-match alerts.
A shared search URL contains only non-sensitive filters and resolves current
availability when opened, never identity, conversation, or Maia inference.

The customer experience may continue either in an anonymous Website Conversation
with Maia Agent or through WhatsApp. Both channels use the same product authority
and may contribute to one Opportunity, but retain channel-specific conversations.
No customer account is required for the MVP. A short-lived signed handoff carries
only an opaque reference when moving to WhatsApp; Product resolves it, verifies
identity before linking the Contact, and never places message history or personal
data in the URL.

The Website Conversation begins anonymously. Maia asks for personal contact data
only when the customer chooses to continue through WhatsApp, protect a Saved
Collection, request Human Handling, or schedule a Property Visit Appointment.
Browsing, asking questions, and receiving authorized recommendations do not
require identity. A Property Visit Appointment is not confirmed until the
customer completes verification through the official WhatsApp channel; the site
must explain this as appointment protection and continuity, not as an account.

On the site, Maia retains the same bounded commercial objective as on WhatsApp:
understand the Property Need, answer from authorized Listing facts, recommend
relevant options, and obtain a Property Visit Appointment. Site navigation,
galleries, saved collections, and general website support do not expand Maia's
role.

Human Handling also applies to Website Conversations, and Advisors answer both
channels from the CRM Inbox while seeing the outbound channel explicitly. Website
conversation content follows the same 90-day inactivity expiration as WhatsApp.

Public-site measurement is event-based and minimal. It records useful product and
commercial outcomes such as Listing impressions, gallery engagement, saves,
Maia conversations, WhatsApp handoffs, appointment attempts, confirmations, and
known Opportunity Origin. It does not record message keystrokes, mouse trails,
session-replay video, or advertising profiles. The first-party cookie required to
recover an anonymous Saved Collection is essential product storage, disclosed
separately from optional analytics and never repurposed for advertising.

Organic discovery is a first-class product capability from the first public
release, not a later marketing retrofit. Public Listing pages use stable canonical
URLs, indexable server-rendered or statically generated HTML, accurate Mexican
Spanish content, structured data consistent with visible facts, image discovery,
automatically generated sitemaps, meaningful publication and removal responses,
and measured page experience. The same public, current, attributable information
is made legible to search-assisted systems. This work maximizes eligibility and
usefulness but never claims to guarantee first place in Google or inclusion in a
particular assistant.

Initial local editorial discovery is limited to genuinely useful pages for
Guadalajara, Zapopan, and Tlaquepaque, followed by neighborhood guides only when
inventory, demand, and verified local expertise justify them. The operation does
not generate combinatorial pages for every neighborhood, price, or keyword.

EasyBroker query access never grants publication authority. Only Listings with
current permission to publish their facts and media, and whose availability can
be maintained, receive indexable Larevia pages. A withdrawn Listing initially
keeps its stable URL with an honest `Esta propiedad ya no está disponible` state
and authorized alternatives. It redirects only to a genuinely equivalent
replacement; otherwise Product later removes it from the index with the correct
HTTP and indexing state rather than redirecting it to the homepage.

Crawler policy distinguishes public search or user-requested retrieval from
model-training collection. The launch policy allows verified search/retrieval
crawlers needed for organic discovery and blocks training-only crawlers until the
Organization makes an explicit legal and commercial decision. Provider identities
and official policies must be reverified before launch and monitored afterward.

The primary organic-discovery business measure is the count and conversion rate of
verified Property Visit Appointments with an unpaid Opportunity Origin. Rankings,
impressions, clicks, assistant citations, gallery engagement, Maia starts, and
WhatsApp handoffs are diagnostic funnel measures, not the final success metric.

## Stage 10 — Customer Experience and Market Intelligence

Customer Experience becomes the operating priority after the existing stages.
The first new path is a versioned buyer Transaction Journey, opened explicitly
from the CRM and accompanied by Maia only through human-confirmed milestones. It
adds a manually maintained Purchase Profile and Market Sale Record whose simple
price vocabulary is Paid Price, Published Price and Appraisal Value. A purchase
Opportunity cannot become Won without the Property, type, municipality,
completion date, Paid Price and currency.

Market Intelligence starts from zero with new facts entered by participating
real-estate operators. It performs no historical backfill and ingests no public,
registry, cadastral, demographic, portal or MLS data. Durable Market
Contributions project the accepted analytical facts into a Platform-wide dataset
without cross-Organization CRM access. Direct SQL corrections create revisions
and republish through PostgreSQL triggers; co-brokered duplicate contributions
require human resolution; only completed records are Comparable Sales; and
aggregate reports require at least five applicable sales.

The accepted design and implemented composition are captured by ADR-0056 through
ADR-0059. ADR-0056 supersedes the old post-appointment boundary; ADRs 0057 to
0059 record contribution, minimum sale facts and direct-SQL correction
propagation.

Local implementation is complete in migration 0028 and the Product, CRM,
Hermes-plugin, worker and test layers. The buyer template remains an operational
gate rather than a silent default: Santiago must review and an Organization
Administrator must approve it before any Journey can start. The separate Market
Intelligence Analyst credential must also be configured. No real brokerage has
accepted or activated this stage, no historical data was imported, and no
external dataset was connected.

## Current Stage

Local Stage 10 adds the buyer Transaction Journey and the privacy-bounded shared
market dataset described above. Its operational activation is pending Santiago's
template review; “implemented” here describes the local Product and its verified
runtime contracts, not live customer use.

Local Stage 9 turns the product into a managed platform on which a second
Brokerage Organization can operate — accompanied — without reaching Larevia's
data, credentials, conversations, configuration, inventory or analytics, using the
same product and the same modules.

The bulk of the stage is isolation. Revisions 0012 to 0015 had scoped the
commercial roots; what they had not reached was the operational layer beneath them
— Inbox, Outbox, delivery callbacks, consent, suppression, availability snapshots,
Hermes session bindings, the audit trail — each of which was reachable only through
a join, and each of which was one forgotten join away from answering with another
brokerage's work. Every such table now names its Organization with a composite
foreign key that makes the column and its parent agree, every business key that
was globally unique is unique per Organization instead, and every inbound
identifier resolves through an explicit channel binding whose absence is a refusal
rather than a default to the founding Organization. A written scoping table
classifies all 91 tables, and a test refuses an unclassified one.

On that foundation the stage adds what a managed service needs: resumable and
individually reversible provisioning, versioned configuration documents that
cannot carry a credential, per-Organization secret *references* that never store
one, append-only entitlements with a base package and Advisor-seat tiers and no
prices, measured monthly usage, a dry-run-first initial import with per-record
findings and rollback by stored identifier, per-Organization export and deletion
bounded by recorded retention holds, and temporary, explained, expiring and
counted internal support access in place of a superadmin.

No external inmobiliaria has been onboarded. The stage's own entry condition —
Larevia demonstrably operating *and* the real needs of at least one candidate
external brokerage — is half met: the platform is implemented against the
operating model Larevia proved, and the second half is not. Nothing is priced,
nothing is charged, and no capacity claim is made for any number of Organizations.

Stage 8 remains as it was: measurement and one sellable paid-visibility offer on top of
the Stage 7 engagement boundary. Product emits a versioned, idempotent domain-event
taxonomy through a durable analytics Outbox, projects it into a separate
pseudonymous PostgreSQL schema, and reports its own operation with "nobody
recorded it" as a first-class answer. On that basis it sells a manually
administered `Patrocinada` campaign whose placements are labelled, capped,
equitably rotated and provably unable to influence organic relevance. The first
price is deliberately unset: publishing one requires a written reference to
measured pilot traffic. No money moves, no warehouse exists, and analytics
retention remains an unresolved privacy and legal decision.

Stage 7 remains as it was: reviewed reactivation and Development-campaign planning
on top of the Stage 6 external-inventory boundary and Stage 4 authoritative
catalog. Product proposes explainable work from confirmed demand, keeps every
audience explicit and bounded, and routes accepted attempts through the existing
outbound eligibility gate. Real Marketing dispatch remains `Denied`; legal,
consent, provider, operational and real-customer acceptance remain explicitly
unclaimed.

Implemented locally:

- FastAPI product backend;
- PostgreSQL persistence;
- Alembic migrations;
- property document ingestion;
- Hermes runtime integration over local JSON-RPC;
- standalone Hermes plugin for Maia tools;
- WhatsApp webhook handling and durable delivery workflow;
- one Product-owned eligibility gate for every customer-facing WhatsApp Outbox
  row, with a second check immediately before Meta delivery;
- transactional explicit opt-out, durable Suppression and Consent evidence, and
  fail-closed quarantine of pre-gate unsent rows;
- an explicit Brokerage Organization that owns Properties, channel identities,
  Conversations, appointments, and every commercial record;
- Organization Administrator and Real Estate Advisor resolved from a reconciled
  member directory rather than implied by a credential (ADR-0046);
- Contact separated from Conversation and from channel identity, deduplicated
  only on a trusted identifier and never on a look-alike one;
- Property Needs with confirmed criteria, Pending interpretations, and a Stale
  state after 90 days without confirmation;
- Demand and Listing Acquisition Opportunities with the accepted stages,
  evidence-bearing outcomes, and preserved first attribution;
- deterministic assignment, a derived Assignment Queue with recorded reasons,
  and one Next Action per Opportunity with a required result on completion;
- Follow-up Coverage measured with its gaps attached, and auditable exceptions
  where no Next Action is owed;
- server-rendered Mexican Spanish surfaces for the panel, Inbox, Opportunities,
  Contacts, and the Assignment Queue, showing denied outbound decisions and
  communication restrictions without any path to send;
- Property administration and document upload restricted to the Organization
  Administrator, which they were not before: those routes accepted any
  configured credential with no role lookup;
- render-time idempotency keys on every operator form, so a double submission
  replays instead of opening a second Opportunity or owing a second action;
- conversation-content expiry separated from commercial history, with a
  background pass for staleness, day-28 dormancy, and content retention;
- Organization Administrator management of the team: adding members, an
  Advisor's authoritative calendar and alert channel, deactivation that never
  removes the last administrator, and the deterministic assignment fallback,
  without startup reconciliation deleting what the Administrator created
  (ADR-0047);
- Advisor Absences that only an Administrator records or ends, cannot overlap,
  exclude somebody from new assignments and new bookings, and never reassign an
  Opportunity or cancel a visit — with an alert naming the work they left alone;
- Property Expert principal and backup designations kept explicitly distinct from
  the Responsible Advisor, revoked rather than deleted;
- the complete deterministic assignment rule: preserve the existing owner, then
  the present Property Expert, then present backups by rank, then the default
  Advisor, then the Assignment Queue with a reason that distinguishes "everybody
  is away" from "nobody is configured";
- Conversation Handling Mode arbitrating Maia against a human and one human
  against another, with the Lead worker re-checking under a row lock at
  settlement so a human arriving mid-turn wins and the draft is withheld rather
  than duplicated;
- human replies sent from the CRM on the Brokerage Organization's own WhatsApp
  channel, through the same outbound eligibility gate as everything else;
- Human Handling requests recognised deterministically from the Contact's own
  words or raised by a typed tool, an immediate alert to the responsible Advisor,
  Product's own approved acknowledgement to the Contact, and an alert to the
  Organization Administrator after 15 minutes — exactly once across restarts, and
  never an automatic reassignment;
- a durable internal alert channel, separate from the customer Outbox, whose
  undeliverable notices stay visible in the CRM (ADR-0049);
- per-Advisor authoritative calendars, where an unconfigured or unreadable
  calendar is a named refusal rather than an empty week (ADR-0048);
- Advisor-owned appointments with an explicit conducting expert only when stated,
  atomic rescheduling that preserves the original on any failure, cancellation
  that decides nothing commercial, and Missed or Attended outcomes recorded only
  by a human;
- deterministically scheduled visit reminders whose dispatch is blocked with a
  recorded reason until the cadence is validated;
- deterministic post-appointment routing that keeps bounded Appointment Logistics
  with Maia and sends commercial, visit-specific and ambiguous messages to the
  Advisor;
- server-rendered Mexican Spanish surfaces for Team, Absences, Specialists, the
  visit Calendar, pending human-handling requests and conversation handling;
- Google Calendar availability and appointment booking;
- Telegram administrative role;
- deterministic lead follow-up worker whose current attempts are intentionally
  blocked until the accepted commercial states, real consent, approved Meta
  templates, and explicit policy activation exist;
- Docker Compose single-host topology;
- credential-free CI for every push and pull request, including a vertical
  WhatsApp-to-booking-to-Telegram scenario;
- pytest suite for domain, API, worker, plugin, and channel behavior.
- an authoritative real-estate catalog in Product: Property is physical truth,
  each Listing preserves one Organization or Collaborator source, each Offer
  owns its operation/price/terms, and Development/Unit Model records do not
  manufacture physical units;
- `CatalogAdministration.record`, `OfferManagement.record`,
  `MediaAdministration.record`, `ListingEligibility.evaluate` and
  `CatalogProjection.get_authorized_listing` as the invariant-bearing seams;
- independent Listing Availability, Publication State and Authority, with
  evidence, freshness/revalidation, deterministic presentation readiness,
  automatic tiers and auditable Administrator overrides;
- a recoverable media lifecycle for JPG/PNG/WebP whose local Compose adapter
  stores originals durably, revokes public eligibility before cleanup, and
  resumes storage/cache deletion idempotently after restart;
- Mexican Spanish catalog administration where Advisors have read-only access
  only to Properties for which they are currently designated experts, while
  only Administrators can change catalog state;
- one-way compatibility import of accepted Property Documents: immutable
  artifacts remain provenance and narrative, while their price and operation
  are copied only once and thereafter only Listing Offers are editable;
- Maia property disclosure, inventory lists and new-visit checks routed through
  Listing Eligibility rather than treating a legacy Property status or document
  as permission;
- a separate Mexican Spanish public Site process with no database or provider
  credentials, reached only through Product's approved-path reverse proxy and
  authenticated Product contracts over loopback;
- a warm editorial Larevia visual system across the landing page, explicit
  shareable search, curated Guadalajara/Zapopan/Tlaquepaque pages, Technical
  Sheets, and separate keyboard-operable galleries, with consistent interaction
  across Larevia, Premium, and Super Premium presentation tiers;
- progressive server-backed Saved Collections with an opaque HttpOnly cookie,
  idempotent lifecycle commands, withdrawn-item history, expiring fixed shares,
  and explicit multi-device protection through verified WhatsApp identity rather
  than browser fingerprinting;
- anonymous Website Conversation with Product-owned PII rejection, eligible
  Listing context, 90-day content expiry, and Hermes Sales-role continuity;
- opaque, expiring, single-use channel handoffs that bind Website Conversation,
  Saved Collection, and Listing context only after verified Meta intake, while a
  website appointment request remains unconfirmed and creates no Appointment;
- public discovery projected from the same eligible Listing truth: stable
  canonical URLs, visible-fact structured data, responsive authorized media,
  image sitemap entries, honest 410 withdrawal, and curated local pages;
- differentiated crawler policy allowing search and user-requested retrieval
  while blocking training-only crawlers until explicit legal and commercial
  approval, with launch-time provider-policy reverification still required;
- allowlisted public funnel events without free text, keystrokes, session replay,
  advertising identifiers, or behavioral profiles;
- automated public-site domain, boundary, SSR, migration, recovery, accessibility,
  security-header, and frontend-budget checks. Desktop and narrow-mobile browser
  acceptance remains manual: no browser automation exists in this repository.
- a stable external-inventory module, read-only EasyBroker HTTP adapter, strict
  Guadalajara/Zapopan/Tlaquepaque filter, lossless candidate Listing/Offer
  mapping, page/cursor translation, bounded retry/rate-limit handling, and
  sanitized source health;
- Organization-first authorized search, with external candidates only as a
  fallback and exact versus approximate results made explicit;
- use-time refresh and recorded `Eligible`/`Pending`/`Denied` decisions for each
  recommendation, share, or appointment, serialized against concurrent refresh;
- immediate external withdrawal invalidation and 24-hour due-cache cleanup, with
  an Administrator surface that never exposes the provider credential;
- two thin Stage 6 Hermes tools that route inventory discovery and revalidation
  through Product rather than exposing EasyBroker or PostgreSQL to Hermes.
- an `inventory-match-v1` comparison of authorized Listings with confirmed
  Property Needs, including exact, approximate and contradictory criterion-level
  explanations and mandatory reconfirmation after the existing 90-day stale rule;
- reviewed Reactivation Candidates that never auto-send and whose only objective
  after a reply is reconfirming interest or arranging a new appointment;
- explicit `development-audience-v1` campaign plans with dry-run parity,
  PII-safe audience references, exclusions, quiet hours, frequency and recipient
  caps, pause/cancel and measurable per-member results;
- Meta-owned Message Template observations with exact Marketing category,
  language, static body, lifecycle and a 24-hour Product evidence window, with
  no local approve operation;
- evidence-bearing, scope-specific Marketing consent checks at request and
  delivery time, while consent capture itself remains `Denied` under SAN-010;
- a Stage 7 worker whose Candidate/audience outcome, outbound decision, Outbox
  row and Marketing touch share one transaction and whose queued work is
  quarantined when a pause/cancel commits before provider delivery;
- Mexican-Spanish `/crm/reactivacion` controls for templates, candidates,
  explicit Development audiences, limits and PII-safe results;
- `MARKETING_OUTBOUND_ACTIVATED=false` as the default and current real-activation
  gate; fixture approvals and consent records verify contracts only.
- a closed, additive `analytics-events-v1` domain-event taxonomy where every
  event declares its schema version and its allowed attributes, and an attribute
  that is not numeric, boolean or enumerated is refused rather than stored — so
  no phone number, message or search phrase has a column it would fit in;
- a durable `analytics.analytics_outbox`, deliberately separate from
  `outbox_messages`, so a stuck measurement row never shares a queue, a retry
  budget or a failure mode with a message somebody is waiting for;
- `AnalyticsProjection.refresh`, which consumes in sequence order, leaves rows
  `Pending` until the transaction that stores their event commits, inserts
  idempotently, and *recomputes* each touched period rather than incrementing it
  — so a restart repeats a batch, a replay from zero rebuilds the identical
  store, and a late event corrects its own period instead of landing on today;
- `analytics.measurement_definitions` seeded with `measurement-v1`: 50 percent
  for 1000 continuous milliseconds for a Visible Impression, five photographs or
  30 percent of a gallery for Significant Gallery Exploration, the eleven-step
  funnel, 7- and 90-day attribution windows, one sponsored result per six visible
  ones, two on the homepage, and three paid Visible Impressions per session per
  day — all inclusive at the border and all read back so a historic report stays
  reproducible;
- Served Impression separated from Visible Impression: serving is Product's own
  fact recorded server-side as the response is built, while visibility is a
  browser measurement whose *threshold* Product applies, so a modified client
  cannot manufacture one;
- invalid traffic stored, classified and reported rather than deleted — bot, then
  test, then internal, then implausible rate, in that fixed precedence — with
  duplicate emissions counted on the Outbox row rather than silently dropped;
- pseudonymisation with a separate salt per purpose, generated once per
  Organization into the analytics schema rather than read from configuration, so
  a session reference and a subject reference cannot be joined to link an
  anonymous session to a known Contact;
- an operational scorecard where `Sin registrar` is never zero and never a loss,
  a ratio with no denominator reads `No calculable`, and Follow-up Coverage is
  read from the one existing implementation rather than recomputed;
- Administrator-recorded Harm Signals for the SAN-079 stop conditions, with
  written evidence, idempotent on their command key;
- `SponsoredEligibility.evaluate`, which reuses the same `PublicShare` decision
  the unpaid site gets and adds only what money introduces: a written commercial
  clearance standing in for the still-Pending SAN-065, one sponsored position per
  confirmed physical Property, and the campaign's own state and remaining days —
  with daily and per-exposure refusals recorded so a buyer's question has an
  answer months later;
- `SponsoredDelivery.select`, which returns paid slots as their own list and
  leaves the organic ordering untouched: `PublicCatalog` imports nothing from
  sponsorship and a test asserts that absence, so payment cannot buy relevance
  even by accident;
- deficit-based rotation (`delivered_days / paid_days` ascending), a durable
  per-session daily cap, a skip for a Listing already visible organically on the
  page, and an empty slot rather than a substitution when a Listing is withdrawn
  mid-render;
- `Patrocinada` rendered as a visible chip, an `aria-label` on the article and a
  non-colour border on every paid exposure, with `Destacada` reserved for unpaid
  editorial selection and absent from every sponsorship module;
- an Administrator-managed versioned price catalog that cannot be published
  without a written reference to pilot traffic — enforced by the module and by a
  check constraint — with exactly one published version at a time;
- `SponsorshipQuoting.quote`: seven-day validity, the catalog version and amounts
  preserved on the row, a discount refused without a recorded reason, and no
  capacity held until the quote is accepted;
- two independent ceilings kept apart — the delivery ratio bounds what a page
  shows, the sales ceiling bounds how many campaigns may hold a surface over the
  same days — with reservations taken under a per-surface lock and peak overlap
  deciding, so consecutive campaigns do not compete and concurrent acceptances
  cannot oversell;
- a campaign lifecycle where a paid day is consumed by being *delivered*, so a
  Listing withdrawn for a week returns that week; automatic pause with recorded
  reasons, automatic resume, completion with no successor, and no auto-renewal;
- external collection state recorded as an observation: Product issues no
  invoice, charges nothing and moves no money;
- `SponsorshipReporting.generate`, one computation at two audiences, so the buyer
  report and the Administrator report cannot disagree about the same month;
- comparables grouped by operation, municipality, property type, Commercial Price
  Band, Presentation Tier and surface, with the subject campaign excluded, period
  and sample size disclosed, and `Estimación inicial sin historial suficiente`
  below three comparable campaigns;
- attribution reported inside the declared 7- and 90-day windows, never
  overwriting first Opportunity Origin and never described as lift, with the
  non-causal statement on every buyer surface;
- expiring, revocable, read-only buyer links stored only as a `sha256` digest,
  where expiry, revocation and an unknown token give the same refusal, and an
  exportable PDF written by a small in-repository module rather than a new
  dependency;
- one opaque, HttpOnly, one-day site cookie used for exactly one thing — the
  per-session cap — pseudonymised before anything derived from it is stored, and
  explicitly not an advertising identifier;
- Mexican-Spanish `/crm/bi` and `/crm/patrocinios` surfaces, both
  Administrator-only, with the data-quality panel on the same page as the results
  so a coverage number always appears next to how much of it is unrecorded.
- `organization_id` on every table that holds a Brokerage Organization's data,
  including the operational layer that previously reached it only through a join —
  Inbox, Outbox, delivery callbacks, consent, suppression, outbound decisions,
  availability snapshots, Hermes session bindings, appointment reminders, saved
  items, website messages, engagement cycles, follow-ups, admin messages, channel
  cursors and the audit trail — each with a composite foreign key so the column
  and its parent cannot disagree;
- per-Organization business keys where they used to be global: Property Key,
  Property normalized name, appointment reference, `wamid`, Outbox idempotency
  key, outbound-decision key, Telegram `update_id`, website command key, gallery
  and technical-sheet paths, and the analytics event keys — so a second
  Organization no longer discovers another's inventory from a constraint
  violation;
- `realestate.domain.platform.scoping`, a written classification of every table as
  one Organization's data or as deliberately platform-wide with a stated reason,
  read by the export, by deletion and by the isolation matrix, with a test that
  refuses an unclassified table and a deletion order derived from the schema
  rather than hand-maintained;
- `OrganizationRouting.resolve`, the mapping ADR-0019 named as a future seam:
  WhatsApp phone number, WhatsApp Business Account, Telegram bot and public
  hostname each claimed by exactly one Organization, globally unique while active,
  and an unbound identifier refused and logged rather than defaulted — the webhook
  counts it `unroutable` instead of answering;
- `OrganizationProvisioning.provision` / `deprovision`: seven named steps
  committed individually, an Organization created `Provisioning` and activated only
  in the last one, resume from the first incomplete step on the same command key,
  rollback that retires bindings, revokes references and deactivates members while
  keeping the configuration and entitlement history that explains what happened,
  and a login another Organization holds refused *by name* before anything is
  written;
- `OrganizationConfiguration.record`: one immutable checksummed document per
  version with a required written reason, no new version for an identical
  document, an allowlist of sections, and recursive refusal of any key whose name
  looks like a credential's home — because the danger is
  `channels.whatsapp.access_token`, not a top-level `token`;
- `IntegrationCredentials.resolve`: a credential is never inherited. The
  Organization's own `Active` reference, then its own `Rotating` one, then the
  process environment *only* for the founding Organization named in
  configuration, then a named refusal. Rotation appends and proves the change with
  a fingerprint, and Product never claims the provider accepts the value;
- `Entitlements.evaluate`: fourteen named capabilities, two of them bounded,
  append-only with a source and an author, a capability with no recorded
  entitlement refused rather than permitted, unsold add-ons recorded `Disabled`
  rather than omitted, and three Advisor-seat tiers with monthly conversation
  allowances and no prices;
- five real enforcement seams, each in the module that performs the work rather
  than a surface that could be bypassed: the Advisor seat ceiling before an
  `AddMember` row is claimed, collaborator-inventory synchronisation, reactivation
  discovery, Development-campaign planning and sponsorship quoting — while the
  base-package capabilities and the monthly conversation allowance are reported
  and not enforced, with the reason written down;
- support access as an ordinary read-only, unassignable Advisor member row inside
  one Organization from an expiring grant with a written reason and a use count —
  refused at login resolution the moment it lapses, deactivated by a sweep, and
  listed on the customer's own `/crm/plataforma` page. No account reads every
  Organization;
- `OrganizationDataLifecycle.export` / `delete`: an artifact with per-table row
  counts and every withheld column named — salts, credential fingerprints, live
  token digests and model session handles — and a deletion that takes a scope,
  refuses outright when a retention hold is live, and never removes the evidence
  that it ran;
- `OrganizationImport.plan` / `apply` / `roll_back`: the same code path with a
  mode, an apply that requires a dry run over the identical source checksum, one
  finding per record carrying the source's own reference, only unreviewed physical
  Properties created, and rollback by stored identifier that leaves a referenced
  record in place and reports it;
- eight monthly usage measures per Organization, recomputed rather than
  incremented, with model turns counted as settled Inbox groups rather than
  messages;
- per-Organization background work: the analytics pass, the sponsorship day
  accounting and quote expiry run once per operating Organization with their own
  Actor; content expiry and Property Need staleness carry each row's Organization
  into its audit event; the platform worker expires support grants and refreshes
  usage on their own cadences;
- a `/platform` JSON surface authenticated by its own credential *and* a mandatory
  operator-name header, refusing every mutation without a written reason, plus a
  read-only Mexican-Spanish `/crm/plataforma` panel where an Organization's own
  Administrator sees their configuration version, plan, integration references,
  channels, measured usage and every support access anybody was granted into their
  records;
- a startup bootstrap that binds the founding Organization's channels and names
  its existing credentials as references, idempotently, without moving a single
  secret and without being able to touch any other Organization.

Not yet proven or claimed:

- production deployment;
- real customer pilot;
- cloud-managed operations;
- legal/privacy readiness for real lead data;
- live approved WhatsApp Marketing templates, legitimate marketing-consent
  capture, accepted numeric policy, account quality/capacity proof and proactive
  delivery;
- a real external brokerage onboarded, or its real needs known;
- any price, invoice or charge for the packaging structure that now exists;
- measured capacity for any number of Organizations;
- horizontal scaling;
- a real sponsorship sale, a measured pilot, or any published price;
- self-managed multi-brokerage onboarding, billing, round-robin assignment, load
  scoring, automatic commissions, live EasyBroker activation, paid acquisition,
  and the data warehouse — all deliberately later stages.

## Known Stage 9 Limitations

- **No external inmobiliaria has been onboarded.** The stage's own entry
  condition was Larevia demonstrably operating *and* the real needs of at least
  one candidate external brokerage. The second half is unmet, so the shape of
  onboarding, support, packaging and configuration is derived from the operating
  model Larevia proved and will move when a real customer disagrees with it.
- Nothing is priced and nothing is charged. The packaging structure — base
  package, Advisor-seat tiers, integration add-ons, measured usage — exists so the
  product can enforce and report it; charging is a separate decision that has not
  been authorised (ADR-0053).
- Seat tiers (3 / 10 / 25 Advisors) and monthly conversation allowances
  (1 000 / 5 000 / 15 000) are conservative Product hypotheses chosen to be
  enforceable, not measurements.
- **The monthly conversation allowance is reported, not enforced.** The outbound
  eligibility gate is the single path to a customer (ADR-0045) and giving it a
  second reason to refuse is its own decision. What is enforced is the Advisor
  seat ceiling and the four add-ons.
- Where a ceiling *is* enforced it is compared against the last hourly usage
  refresh rather than a live count, so a customer just over the line may be
  reading a stale number. The surface reporting it says so.
- **The login namespace is platform-wide.** HTTP Basic carries no Organization, so
  a username identifies one member row across the whole installation.
  Provisioning refuses a taken login by name rather than attaching it to the wrong
  brokerage, but the collision itself discloses that some other Organization holds
  it. A per-Organization login namespace needs a different authentication scheme.
- **Telegram is separated per Organization.** Product resolves one token reference
  and active `TelegramBotId` binding per Organization, verifies they name the same
  bot, and gives that worker only the Organization's active Administrator chat ids.
  Missing or mismatched configuration fails closed.
- **One public-site process per public origin.** The site tells Product which
  hostname it serves; two brands means two site processes today.
- Google Calendar separates per Advisor calendar, but the service account is one
  credential per reference. An Organization wanting its own records its own
  reference; nothing forces it to.
- Meta's account health, quality rating and messaging limits belong to whoever
  owns the WABA and cannot be separated by us.
- **A platform operator can grant themselves support access to any
  Organization.** Bounded to read-only, expiring within eight hours, named,
  counted and visible on the customer's own page — but real, and stated rather
  than implied (ADR-0054).
- **Only bounded local load has been measured.** The isolation matrix accepts
  100 synthetic inquiries across two Organizations with concurrency ten and a
  broad 30-second regression guard. It catches contention and scope regressions;
  no production throughput or latency claim is made.
- Analytics retention remains unresolved (ADR-0044). Deletion can now remove
  analytics rows on request, which is not an expiry policy.
- Provisioning reports whether a credential *reference resolves*, never whether
  the provider accepts the value. Only the provider knows that, and the runbook
  makes verifying it a separate manual step.
- Deliberately absent: a marketplace, self-service signup, self-service billing, a
  dedicated server per customer, cross-organization model training, identifiable
  cross-organization benchmarks, and any geographic expansion.

## Known Stage 8 Limitations

- The first sponsorship price is not set and no catalog ships published. SAN-062
  needs pilot clients, a defensible introductory price and conditions that allow
  learning without giving the service away indefinitely. Until then quoting is
  refused with that reason rather than offering an empty field.
- SAN-065 is Pending: which defects of file, price, availability, photography or
  owner relationship block accepting money is Santiago's to enumerate. Product
  requires a written Administrator clearance in the meantime. That records
  authority; it does not substitute for the rule.
- SAN-059, SAN-061, SAN-063, SAN-064, SAN-066 and SAN-067 also remain Pending —
  the likely buyer, the package shape, what a quote needs to close, whether
  buyers will demand zone or period exclusivity, which figures convince, and when
  renewal should be recommended.
- Capacity defaults to two concurrent campaigns per surface, and the
  measured-exposure forecast reports insufficient history below seven measured
  days. Both are conservative Product choices, not measurements.
- Analytics retention is unresolved. Event-level and aggregate retention is an
  explicit privacy and legal decision (ADR-0044) and nothing in Stage 8 expires
  an analytics row.
- Browser acceptance remains manual. There is no browser automation in this
  repository, so the visibility observer, the gallery-depth reporting and the
  rendered contrast of the label are asserted at the contract and template level
  only.
- The reported numbers are all from synthetic fixtures. No real traffic, no real
  buyer and no real campaign has been measured.
- Auctions, pay-per-click billing, auto-renewal, payments, invoicing, tax
  accounting, advertising profiles, session replay, cross-organization benchmarks
  and a data warehouse are all deliberately absent.

## Known Stage 7 Limitations

- The real activation flag remains false. The repository has no approved
  SAN-010 notice or legitimate consent-capture route, and an Administrator cannot
  assert opt-in for a Contact. There are no verified real WABA template, quality
  or capacity observations in the implementation evidence.
- One touch per 30 days, 20:00–09:00 `America/Mexico_City` quiet hours, 50
  recipients by default and 500 as the hard explicit-audience ceiling are
  conservative Product hypotheses. They are not presented as law or Meta's
  universal limits and require legal and operational acceptance before dispatch.
- Provider template observations expire after 24 hours as a conservative Product
  freshness rule. Stage 7 supports static template bodies only; any `{{...}}`
  parameterized body is denied until an explicit binding interface exists.
- Campaign criteria are intentionally limited to named Property Needs,
  transaction intent and service-area text. There is no predictive score,
  purchased audience, inferred sensitive segment or unrestricted bulk upload.
- A Development campaign requires approved facts containing
  `marketing_authority_confirmed: true`. This records Product authority to
  promote the Development; it does not replace individual consent.
- The local Meta adapter observes template truth only. Account health, billing,
  business verification and provider sending capacity remain external release
  gates, and the fixture-backed tests claim none of them.
- Outcomes are Product events (`Included`, `Excluded`, `Queued`, `Denied`,
  `Responded`) correlated with Outbox state. Provider delivery callbacks remain
  authoritative for actual delivery; Stage 7 does not invent opens or conversion
  attribution beyond a response and a later Campaign-origin Opportunity.

## Core Boundary

Hermes owns:

- natural-language reasoning;
- memory/session continuity;
- interpreting fragmented WhatsApp messages;
- selecting tools;
- composing user-facing Spanish replies.

Product owns:

- trusted channel identity;
- PostgreSQL truth;
- business rules;
- property document acceptance;
- appointment authority;
- follow-up cadence;
- Meta/Calendar/Telegram side effects;
- retry and ambiguity classification;
- audit trail.

This boundary is the central design decision. Do not let the model directly own
business truth or side effects.

## Channel Direction

WhatsApp is the customer channel; Telegram is the private Broker/Administrator
channel and never the Lead entry point. `docs/architecture/architecture.md` states the full
boundary, including which Telegram notices Product owns — read it there rather
than restating it here.

## Public Repository Positioning

This repository is intended to be visible to recruiters and hiring managers.
The public story should emphasize:

- backend/platform engineering for AI products;
- typed tool authority beneath agentic conversation;
- durable workflow design;
- external API integration;
- recovery and operational thinking;
- pragmatic separation between model behavior and system authority.

Avoid public wording that overclaims:

- production readiness;
- legal compliance;
- real customer deployment;
- guaranteed model accuracy;
- autonomous business authority.

## Branching Policy

Use:

- `main` for public, recruiter-visible material;
- `codex/<topic>` or `feature/<topic>` for normal implementation work;
- `private/<topic>` only for local branches that must not be pushed to the
  public GitHub remote.

`main` should contain clean product code, public-safe docs, and reproducible
development instructions. Private notes, raw memory, and rough planning belong
outside `main`.

In a public GitHub repository, pushed branches are visible. Protected branches
prevent unsafe changes to `main`; they do not hide sensitive content. Private
material should stay in ignored local files, local-only branches, or a separate
private repository.

## Known Stage 3 Limitations

- Contact-facing visit reminders are scheduled but never sent.
  `REMINDER_POLICY_ACTIVATED` is `False` because SAN-036 has not validated the
  cadence, and a due reminder is settled with the reason `PolicyNotValidated`.
  Turning it on would still meet the outbound gate, which denies free-form text
  outside Meta's 24-hour window — so reminders are structural template work.
- The Weekly Bookable Schedule, the 90-minute visit and the booking horizon stay
  Organization-wide. Per-Advisor working hours are not modelled because SAN-031
  and SAN-032 are unanswered; an Advisor expresses their limits as busy time in
  their own calendar.
- Appointments booked before Stage 3 have no Advisor. They are surfaced to an
  Administrator as requiring a decision rather than backfilled with a guess, and
  reconciliation resolves their calendar through the default Advisor because a
  pre-Stage-3 event can only be on the one calendar the operation had.
- The post-appointment routing whitelist is a phrase list. A logistics request
  phrased unusually reaches the Advisor, which is the safe direction, and the
  courtesy list matches the whole message so "gracias, pero…" is not a
  pleasantry. Neither list is a classifier and neither should become one without
  real conversation data.
- An internal alert can be delivered twice if the process dies between the
  Telegram send and the stamp. That trade is deliberate for an operator alert and
  is the opposite of the Lead-facing choice in P-036.
- A human handoff names the responsible Advisor as the handling holder
  immediately, so Maia stops. That is not the Advisor confirming they are on it;
  acknowledgement is a separate recorded fact, and the 15-minute escalation reads
  the second one.
- The model-facing tool surface grew by two names — `reschedule_appointment` and
  `request_human_handoff`. Both are required by ADR-0037 and ADR-0029 and
  neither can be expressed with the Stage 0 surface, but the frozen-surface guard
  and its test were edited to admit them, which is the kind of change that
  deserves review rather than a passing test.
- Recording a visit outcome uses a deliberately minimal form. SAN-038 asks
  Santiago to design the real one, and a longer form Product invented would be a
  form nobody fills in.
- `Appointments.book` commits three times: the attempt, the Calendar result, and
  the handoff. A single transaction across an external side effect is impossible,
  and pretending otherwise would be the bug — but it does mean a crash mid-flight
  leaves work for reconciliation rather than nothing at all.

## Known Stage 2 Limitations

- Membership is now managed by an Organization Administrator in `/crm/equipo`,
  and configuration remains the bootstrap. A member row records which of the two
  provisioned it so startup reconciliation cannot delete the other's work
  (ADR-0047).
- The time-driven commercial rules — Property Need staleness, day-28 dormancy,
  conversation-content expiry — run on a 15-minute interval inside
  `CommercialUpkeepWorker` rather than on the background loop's one-second
  cadence. The interval is declared beside the rules it paces.
- `require_actor` opens its own session to resolve the member row, so a CRM
  request checks out two connections and reads two snapshots. Harmless for one
  operator on an internal surface; the fix is a request-scoped session shared by
  every handler, which is a broad refactor and was not done.
- `domain/inbox.py` imports the commercial layer, because a Contact and an
  Opportunity must land in the transaction that persists the message. The tidier
  shape is a coordinator above both; hoisting commit ownership out of
  `InboxService.accept` would rewrite a Stage 1 recovery path and was deferred
  rather than hidden.
- CONTEXT.md now defines **Channel Identity**, while the table is still called
  `leads` and the column `lead_id`. Internal identifiers may stay English
  (PROJECT_MEMORY), so this is a naming inconsistency rather than a leak — no
  operator-visible string says "lead" — but renaming the table is its own
  migration.
- A WhatsApp phone number does not identify a Brokerage Organization. The
  single-Organization MVP resolves it by slug in one place.
- Child tables reach the Organization through a NOT NULL foreign key to
  Properties, channel identities, Conversations, or appointments rather than
  carrying a redundant column that could disagree.
- Proactive follow-up remains denied. Stage 2 removes one of ADR-0045's four
  preconditions — the commercial states now exist — but marketing consent
  capture, real approved Meta templates, and explicit policy activation do not.
  Stage 3's visit reminders are denied for the same structural reason plus an
  unvalidated cadence.
- Downgrading revision 0013 drops the commercial tables, so the history they
  hold does not survive it. Revision 0012's downgrade likewise drops the
  Contacts it derived; the Leads they came from are untouched.

## Points For Codex — Stage 9 Close

These are decisions the implementation deliberately did not take, phrased so a
"no" is as usable as a "yes".

1. **The entry condition is half met.** The stage was to begin after Larevia
   demonstrably operates *and* the real needs of at least one candidate external
   inmobiliaria are known. The platform is built against the model Larevia proved;
   no candidate has been interviewed. Does Stage 9 close on the implementation, or
   stay open until a candidate's needs are on paper and reconciled against what
   was built?
2. **Pricing and charging.** The packaging structure exists and enforces itself.
   Nothing is priced and no money moves. Charging is a separate authorisation
   (ADR-0053) — is it in scope next, or does it wait for a signed customer?
3. **Seat tiers and the conversation allowance** (3/10/25 Advisors,
   1 000/5 000/15 000 conversations) are round numbers chosen to be enforceable.
   Confirm, replace with measured ones, or drop the ceilings until a customer
   argues about them.
4. **The platform-wide login namespace.** HTTP Basic carries no Organization, so a
   username identifies one member row across the whole installation. Provisioning
   refuses a taken login by name, but the collision discloses that somebody else
   holds it. Accept, or is a per-Organization authentication scheme the next
   stage's work?
5. **One public-site process per Organization.** Telegram now polls separate bots
   inside Product, but each branded public origin still needs its own `site`
   process. Accept that deployment shape for the accompanied onboarding, or put
   hostname dispatch inside one site process?
6. **Support access remains grantable by any platform operator** to any
   Organization — bounded, expiring, counted and visible to the customer, but
   real. Is that the promise to make in writing, or does a customer-approval step
   belong in front of it?
7. **Analytics retention is still unresolved** (ADR-0044). Deletion can now remove
   analytics rows on request; an expiry policy is a different decision and is
   still owed.
8. **Only local contention has been measured.** The 100-inquiry rehearsal is a
   regression guard, not a deployment benchmark. What target environment and
   workload must be measured before a real second customer?
9. **Deprovisioning retains data by default.** Removal is a separate, separately
   authorised request bounded by retention holds. Confirm that default, and
   confirm who inside Maia may authorise a deletion.
10. **Roadmap.** With the platform in place and no external customer onboarded,
    the next work is either the pilot Stage 8 left unmeasured, or the first
    accompanied onboarding. Codex decides which, and whether the current roadmap
    closes here.

## Open Next Work

- Interview at least one candidate external inmobiliaria and reconcile their real
  needs against what Stage 9 built, before onboarding anybody.
- Rehearse an onboarding end to end against `docs/runbooks/organization-onboarding.md`
  with synthetic data, and correct the runbook from what actually happened.
- Rename Python package and plugin identifiers from the original
  `realestate`/`realestate-hermes-plugin` naming to Maia-specific names if the
  project moves beyond this port.
- Decide whether the first public demo should use synthetic property fixtures,
  screenshots, or a short architecture walkthrough.
- `docs/run/deployment.md` and ADR-0060 now describe the three Deployment
  Environments and the Sandbox/Pilot targets. They are a plan, not a verified
  runbook: correct both from what actually happens as each environment is stood
  up.

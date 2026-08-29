# Stage 8 business intelligence and paid visibility

Stage 8 gives Larevia two things it did not have: an honest picture of its own
operation, and one sellable `Patrocinada` offer built on that picture. It adds no
new authority over conversations, appointments or outbound messaging. Measurement
observes what other stages already decided; sponsorship sells position on
surfaces the catalog already authorises.

Two ideas run through the whole stage.

**A definition is data, not a constant.** Every threshold a number depends on —
half the card for one second, five photographs or thirty percent of a gallery,
seven- and ninety-day attribution — is stored under a version. A report generated
in March still reproduces in September after a threshold moved, because it
resolves the version it was generated under (ADR-0044).

**Not knowing is reportable.** `Sin registrar` is a first-class answer and never
a zero or a loss. `No calculable` is what a ratio with no denominator says.
`Estimación inicial sin historial suficiente` is what a comparable cohort says
below its minimum sample. And the first sponsorship price is refused outright
until somebody records the pilot traffic that justifies it (SAN-062).

## The event dictionary

The taxonomy is `analytics-events-v1`, closed and additive. Every event declares
its schema version and its allowed attributes; an undeclared attribute, a
non-enumerated string, or free text of any kind is refused rather than stored.
There is no accepted attribute anywhere in the taxonomy that a phone number, a
message or a search phrase would fit in.

| Event | Attributes | Source |
|---|---|---|
| `SponsoredServedImpression` | `surface`, `position` | Product, as the surface response is built |
| `SponsoredVisibleImpression` | `surface`, `visible_fraction`, `continuous_milliseconds`, `position` | Browser measurement, threshold applied by Product |
| `ListingOpened` | `surface`, `origin` | Product, when the Technical Sheet is served |
| `GalleryOpened` | `origin` | Public funnel |
| `GalleryDepthReached` | `photographs`, `gallery_fraction` | Browser measurement |
| `SignificantGalleryExploration` | `photographs`, `gallery_fraction` | Derived by Product from the depth and the version |
| `ListingSaved` / `SelectionShared` | `origin` / `count` | Public funnel |
| `MaiaStarted` / `WhatsAppHandoff` | `surface` | Public funnel |
| `AppointmentRequested` / `AppointmentVerified` | `origin` | Emitted from Appointment truth |
| `AppointmentAttended` | `attendance` | Emitted only once a human recorded it |
| `OpportunityOutcomeKnown` | `outcome` | Emitted from a closed Opportunity |
| `FirstResponseRecorded` | `response_minutes` | Emitted from first inbound and first sent reply |
| `OpportunityQualified` | — | Emitted from `qualified_at` |
| `HarmSignalRecorded` | `harm_kind` | Emitted from an Administrator-recorded signal |

Operational events are emitted from the product tables with keys derived from the
subject — `qualified:<opportunity>`, `appointment-attended:<appointment>` — so a
second pass, a restart or a replay cannot produce a second event.

### Served, visible, and significant

`measurement-v1` fixes the borders, inclusively on both sides:

- **Served Impression** — the placement was in the response. Product's own fact.
- **Visible Impression** — at least 50 percent of the placement for at least
  1000 continuous milliseconds. Exactly 0.5 and exactly 1000 count; 0.4999 and
  999 do not.
- **Significant Gallery Exploration** — at least 5 photographs **or** at least
  30 percent of the gallery. Either suffices: requiring both would make the
  milestone unreachable on a six-photograph Larevia gallery and trivial on a
  twenty-photograph Super Premium one.

The browser reports the measured fraction and duration; it never reports a
verdict. Product applies the stored threshold, so a modified client cannot
manufacture a Visible Impression.

### The official funnel

`SponsoredVisibleImpression` → `ListingOpened` → `GalleryOpened` →
`SignificantGalleryExploration` → `SavedOrShared` → `MaiaStarted` →
`WhatsAppHandoff` → `AppointmentRequested` → `AppointmentVerified` →
`AppointmentAttended` → `OpportunityOutcomeKnown`.

Each step is reported with its conversion from the step above it, not from the
top, because "much exploration and no appointment" (SAN-067) is a question about
one boundary.

## The pipeline

```
AnalyticsEvents.record  →  analytics.analytics_outbox  →  AnalyticsProjection.refresh
                                                              ├─ analytics.domain_events
                                                              ├─ analytics.funnel_aggregates
                                                              ├─ analytics.mv_sponsored_delivery
                                                              └─ analytics.projection_runs
```

The Outbox is deliberately not `outbox_messages`: a stuck analytics row must
never share a queue, a retry budget or a failure mode with a message somebody is
waiting for. Rows are consumed in sequence order and stay `Pending` until the
same transaction that stores their event marks them `Projected`, so a restart
mid-batch repeats the batch instead of skipping it.

An aggregate cell is deleted and rewritten from the stored events, never
incremented. That is what makes a late event correct: an event arriving today for
last Tuesday rebuilds last Tuesday rather than landing on today or being dropped.
Replaying from sequence zero reproduces the identical store and aggregates.

### Invalid traffic

Bots, internal and administrative use, synthetic test data and implausible event
rates are all **stored, classified and reported as excluded volume**. Nothing is
deleted. Precedence is fixed — bot, then test, then internal, then rate — so "how
much of this month was a crawler" and "how much was a fixture" stay separable.
Duplicate emissions never create a second event and are counted on the Outbox
row, because a duplicate rate nobody can see is the difference between "we
deduplicate" and "we hope we deduplicate".

The user agent is inspected at the site boundary and sent to Product as a
boolean. Excluding bot traffic must not become a reason to store a fingerprint.

## Privacy

The analytics schema is a separate PostgreSQL schema with no foreign key to a
Contact. Session and subject identifiers are replaced by salted digests before
anything is stored, with a **separate salt per purpose** so a session reference
and a subject reference cannot be joined to confirm that an anonymous session
belongs to a known Contact. The salt is generated once per Organization and
purpose and stored in the analytics schema — never read from configuration, where
it could be empty, shared between environments or committed by accident.

The site mints one opaque, HttpOnly, one-day `larevia_sesion` cookie used for
exactly one thing: the per-session daily cap on paid Visible Impressions. It is
random, carries no identity, and is pseudonymised before anything derived from it
is stored. It is not an advertising identifier and there is no profile behind it.

## Paid visibility

### Eligibility

`SponsoredEligibility.evaluate` re-uses the *same* `PublicShare` decision the
unpaid site gets — authority, evidence, availability, publication, media,
Presentation Readiness — and adds only what money introduces:

- a written commercial clearance from a named Administrator, because SAN-065 is
  still Pending and Product refuses to assume it away;
- one sponsored position per confirmed physical Property, refused at quoting
  rather than discovered on the delivery day;
- the campaign's state, start date, package surfaces and remaining paid days.

Daily and per-exposure decisions are recorded, so "why were five days not
delivered" has an answer that does not depend on somebody remembering.

### Delivery

`SponsoredDelivery.select` returns paid slots as their own list. The organic
result list arrives already ordered by `PublicCatalog` — which imports nothing
from sponsorship, and is tested for that — and leaves unchanged.

- **Search**: one slot per six visible results, by integer division. A
  five-result page sells nothing.
- **Homepage**: at most two, in a dedicated labelled section.
- **Cap**: three paid Visible Impressions per Listing per anonymous session per
  day, counted durably so the cap does not depend on the projection having run.
- **Rotation**: by delivery deficit — `delivered_days / paid_days` ascending — so
  the campaign furthest behind gets the slot. Deterministic, and therefore
  assertable.
- A Listing already visible organically on the page is skipped: a buyer should
  not pay for a second copy of a card the visitor can already see.
- A Listing withdrawn between the check and the render leaves its slot empty
  rather than substituted; a substitution would bill the wrong campaign.

Every paid exposure carries `Patrocinada` as a visible chip, an `aria-label` on
the article, and a non-colour border. `Destacada` is unpaid editorial selection
and never appears on a campaign (SAN-060).

### Capacity, pricing and quoting

Two independent ceilings. The *delivery* ratio bounds what a page shows; the
*sales* ceiling bounds how many campaigns may hold a surface over the same days.
A product that respected only the first could sell twenty concurrent campaigns
and deliver each buyer a twentieth of what they expected. Reservations are taken
under a per-surface lock and the peak overlap decides, so two consecutive
fifteen-day campaigns do not compete.

Pricing is an Administrator-managed versioned catalog. Publishing requires a
written reference to the pilot traffic that justifies the numbers, enforced by the
module and by a check constraint. Until a version is published, quoting is
refused with that reason.

A quote preserves its catalog version and amounts, expires after seven days,
reserves no capacity while it lives, and refuses a discount without a written
reason. Accepting it reserves capacity for every surface in the package or none.

### Campaign lifecycle

`Draft → Quoted → Reserved → Scheduled → Active → Paused → Completed`, plus
`Cancelled`. A day is consumed by being **delivered**, not by passing on a
calendar, so a Listing withdrawn for a week returns that week rather than
producing an apology. The daily pass pauses an ineligible campaign with its
reasons, resumes it when the reasons are gone, and completes it when the paid days
are delivered. Nothing auto-renews and completion creates no successor.

Product records an external collection state. It issues no invoice, charges
nothing and moves no money.

## Reporting

`SponsorshipReporting.generate(campaign_id, audience)` is one computation exposed
at two levels. Two implementations would drift, and a buyer noticing that their
report and the Administrator's do not add up is unrecoverable.

A **buyer** receives aggregate delivery, aggregate interaction, aggregate
outcomes, their own price and their own unit economics, the comparable cohort
with its period and sample size, attribution inside both declared windows, and
the two fixed statements. They receive no Contact identity, no phone number, no
conversation content, no individual search and no Saved Collection.

An **Administrator** additionally receives commercial terms, the catalog version,
the discount and its reason, external collection state, surface capacity, invalid
traffic, suppressed duplicates and Follow-up Data Completeness.

Comparables group by operation, municipality, property type, Commercial Price
Band, Presentation Tier and sponsored surface, exclude the campaign being
reported, and disclose period, sample size, median and range. Below three
comparable campaigns the answer is `Estimación inicial sin historial suficiente`
and there is no number at all: a median of one campaign is that campaign.

Attribution reports outcomes within seven days of an exposure and within ninety
days of an engagement. It never overwrites an Opportunity's first origin and never
describes itself as lift. Every buyer surface carries the non-causal statement,
and the test suite strips the two fixed statements before searching the rest for
causal language.

### Buyer sharing

An Administrator mints an expiring, revocable, read-only link. Only its
`sha256` digest is stored, for the same reason a password is not. Expiry and
revocation give the *same* refusal as an unknown token, because telling a holder
that a link existed and was withdrawn discloses a commercial relationship. The
link resolves to one campaign's buyer report and nothing else; there is no route
from a token to a mutation, to a second campaign, or to a CRM account.

The structured page and the PDF are derived from the same buyer-scoped aggregate
report. Product explicitly allowlists the page fields and the PDF renderer reads
only that report, so neither surface can reach CRM identities or internal
commercial terms. The PDF is written by a small module in this repository rather
than a new dependency: one page size, one built-in font, text lines only — a
document that can only contain the characters somebody passed in.

## Surfaces

| Surface | Audience | Contents |
|---|---|---|
| `/crm/bi` | Administrator | Follow-up Coverage, time to first response, qualification, appointment attendance, outcome completeness, Follow-up Data Completeness, harm signals, invalid traffic, projection runs, manual project and replay |
| `/crm/patrocinios` | Administrator | Capacity, price catalog versions, campaigns, quotes, delivery, external collection, internal report, buyer links |
| `/crm/patrocinios/campanas/{id}/reporte` | Administrator | The buyer's figures plus the commercial half |
| `/reportes/{token}` | Buyer | Aggregate campaign report, labelled, with the PDF |
| `/reportes/{token}/patrocinio.pdf` | Buyer | The same figures as a file |

## Operating limits and open decisions

- **The first price is not set.** No catalog ships published. SAN-062 needs pilot
  clients, a defensible introductory price and conditions that allow learning
  without giving the service away indefinitely.
- **SAN-065 is Pending.** Which defects of file, price, availability, photography
  or owner relationship block accepting money is Santiago's to enumerate. Product
  requires a written Administrator clearance in the meantime; that records
  authority, it does not substitute for the rule.
- **SAN-059, SAN-061, SAN-063, SAN-064, SAN-066 and SAN-067 remain Pending.** The
  buyer profile, the package shape, what a quote must contain to close, whether
  buyers will demand zone or period exclusivity, which figures convince, and when
  renewal should be recommended are all commercial answers.
- **Capacity defaults to two concurrent campaigns per surface** and the
  measured-exposure forecast reports insufficient history below seven measured
  days. Both are conservative Product choices, not measurements.
- **Retention is unresolved.** Event-level and aggregate retention in the
  analytics schema is an explicit privacy and legal decision (ADR-0044) and has
  not been made. Nothing in Stage 8 expires an analytics row.
- **Browser acceptance remains manual.** There is no browser automation in this
  repository, so the visibility observer, the gallery-depth reporting and the
  label's rendered contrast are asserted at the contract and template level only.
- **No warehouse, no auction, no pay-per-click, no billing.** Deliberately out of
  scope, along with cross-organization benchmarks, advertising profiles, session
  replay and buyer-supplied creative.

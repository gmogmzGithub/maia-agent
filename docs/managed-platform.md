# Stage 9: the managed multi-organization platform

Stage 9 is the point at which Maia stops being one brokerage's product and starts
being a service several brokerages are on. The whole stage is about one property,
and everything below is either that property or the operations a managed service
needs in order to keep it:

> A second Brokerage Organization operates in an accompanied way without reaching
> the founding one's data, credentials, conversations, configuration, inventory or
> analytics — using the same product and the same modules.

Nothing here is proven with a real external inmobiliaria. ADR-0018 said the
brokerage comes before the platform, and the entry condition for this stage was
"Larevia demonstrably operating, plus the real needs of at least one candidate
external brokerage". The first half is local; the second is not met. What follows
is therefore a complete implementation of the isolation, provisioning and
lifecycle work, with every unvalidated assumption named in *Operating limits* at
the end rather than absorbed silently.

## The isolation threat, stated before the mechanism

The dangerous failures are not the ones that raise. They are the ones that
succeed:

| Threat | Consequence | What stops it |
|---|---|---|
| A query over an operational table forgets its join | Organization B's Inbox, Outbox or consent record answers Organization A | `organization_id` on every such table, plus a composite foreign key so the column and the parent cannot disagree (ADR-0050) |
| A webhook arrives on an unbound WhatsApp number and Product defaults to "the only Organization" | One brokerage's customer is filed, answered and attributed under another's brand | `OrganizationRouting.resolve` refuses; the webhook counts it `unroutable` and logs the identifier |
| Two Organizations mint the same business key | One of them is refused by a constraint naming the other's row, or resolves to it | Every business key is unique *per Organization*: Property Key, appointment reference, `wamid`, Outbox idempotency key, Telegram `update_id`, analytics event key |
| A Hermes session binding resolves across the boundary | The model answers one brokerage's Contact with another's conversation history | `agent_sessions.organization_id`, and every binding lookup filters on it |
| An Organization with no credential silently uses the platform's | Messages go out on the wrong number, into the wrong Meta account, billed to the wrong customer | `IntegrationCredentials.resolve` refuses; the process environment answers for exactly one named founding Organization (ADR-0052) |
| Internal support reads a customer's records invisibly | The customer cannot know it happened; the audit trail cannot tell support from the customer's own administrator | No superadmin exists. Support gets an ordinary read-only member row from an expiring, explained, counted grant (ADR-0054) |
| An export leaks a pseudonymisation salt or a live token digest | Every analytics reference becomes reversible; a capability is handed over | Withheld columns are declared in the scoping table and *named* in the export manifest |
| A deletion partially complies with a live retention hold | Neither the request nor the obligation is satisfied | Deletion refuses outright, quoting the hold's authority (ADR-0055) |
| A provisioning run fails halfway | An Organization exists, looks operable, and cannot receive a message | Named steps, committed individually, `Provisioning` until the last one; resume or roll back |

## The scoping table

`realestate.domain.platform.scoping` classifies **every** table in the metadata.
It is not documentation — three mechanisms read it, and a test fails if a table is
missing from it:

* **`OrganizationRoot`** — `organizations`, scoped by its own `id`.
* **`Organization`** — rows belong to one Organization, named by
  `organization_id`. Since Stage 9 that column is present even where a join could
  have reached it: a query that forgets the join is a leak, and a query that
  forgets a `WHERE organization_id` at least fails a test.
* **`Platform`** — deliberately not one Organization's data, with a written
  reason. There are four, and each reason has to survive being read by somebody
  looking for a hole: the shared measurement rulebook (per-Organization
  thresholds would make two customers' numbers incomparable while looking
  identical), the analytics projection-run bookkeeping (one monotonic sequence
  across Organizations), and the provisioning run and step tables (a run exists
  before its Organization does — that is what makes a partial creation
  resumable).

Two further per-table facts live there because they are properties of the table
rather than of a caller: `withheld`, the columns an export must never carry, and
`content`, whether a row is conversation content rather than commercial record —
which is what makes "delete our conversations" and "delete our company" different
requests.

Deletion order is *derived* from the metadata's own dependency sort, not written
down. A hand-maintained order is wrong the first time somebody adds a table, and
the symptom is a deletion that fails halfway with a foreign-key error and a
customer waiting.

## Provisioning

`OrganizationProvisioning.provision(command)` runs seven named steps, each
committed on success:

1. **Organization** — the row, created `Provisioning`.
2. **Configuration** — version 1 of the document.
3. **Entitlements** — the base package, one seat tier, the named add-ons, and
   every unsold add-on recorded `Disabled` rather than omitted.
4. **Team** — the founding Administrators and Advisors, through the same
   reconciliation the founding Organization uses. A login another Organization
   already holds is refused *by name* before anything is written.
5. **Channels** — the WhatsApp number, WABA, Telegram bot and public hostname.
   An identifier another Organization holds is refused with the conflict named.
6. **Credentials** — secret *references*, and whether each name resolves today.
7. **Activation** — `Active`, with a date. Only now can a login authenticate or a
   webhook be accepted.

Re-running the same command key resumes from the first incomplete step. Each step
is independently idempotent, so "skip" and "do it again" produce the same state —
which is what makes the resume safe even when a step completed but its row did
not.

`rollback` walks completed steps backwards: bindings retired, references revoked,
members deactivated, status returned to `Deprovisioning`. It does **not** delete
the configuration or entitlement history, because those are the evidence for every
decision taken while the Organization operated. `deprovision` is the same list
read in reverse for a live Organization; `suspend`/`resume` pause service without
undoing anything.

## Configuration

One row is the whole document, checksummed and numbered, with a required written
reason. Recording an identical document records no new version; recording the same
*command key* replays its own version. Sections are an allowlist, and any key
anywhere in the document whose name looks like a credential's home —
`token`, `secret`, `password`, `credential`, `api_key`, `private_key` — is refused
recursively. The danger is not a top-level `token`; it is
`channels.whatsapp.access_token`, added by somebody solving a real problem in the
most obvious way.

The founding Organization's version 1 is seeded by migration 0026 and says what is
true: its behaviour still comes from the process environment.
`uses_process_environment(organization_id)` is the one place that exception is
decided, and it compares an Organization *id*.

## Entitlements

Fourteen named capabilities, two of which carry a ceiling rather than a yes/no:
Advisor seats and the monthly WhatsApp conversation allowance. An Organization with
**no recorded entitlement** for a capability is refused — a permissive default
would silently grant every new capability to every existing customer and erase the
difference between "we sold this" and "nobody has decided".

Three seat tiers (`Fundadora` 3, `Equipo` 10, `Operación` 25) with a conversation
allowance each, and no prices anywhere. `evaluate` returns a decision with a
machine-readable reason and a Mexican Spanish sentence; `require` is the same
evaluation with a refusal on the end, so a surface cannot treat the absence of an
entitlement as permission by forgetting to check a boolean.

Advisor seats are counted from the member table at evaluation time. The
conversation allowance reads the usage projection, because putting an aggregate
scan in front of every outbound message would trade a management number for
latency a customer feels — so a ceiling is enforced against the last refresh,
which the surface reporting it says out loud.

**Where they are actually enforced.** An entitlement nothing checks is a report,
so five seams call `require` — each of them the module that *performs* the work
rather than a surface that could be bypassed:

| Capability | Refused at |
|---|---|
| `AdvisorSeats` | `TeamAdministration.record(AddMember)`, before the row is claimed |
| `ExternalInventory` | `ExternalInventory.synchronize` |
| `ReactivationCampaigns` | `Reactivation.discover` |
| `DevelopmentCampaigns` | `Campaigns.plan` |
| `SponsoredPlacement` | `SponsorshipQuoting.quote` |

The other nine are reported and not enforced, deliberately and with the reason
stated: `CommercialCrm`, `AuthorizedCatalog`, `ListingMedia`, `PublicSite`,
`WebsiteConversation`, `WhatsAppChannel`, `CalendarScheduling` and
`BusinessIntelligence` are what the base package *is* — an Organization without
them is not operating, so a check on every read would be a per-request query
whose only possible answer is yes. `MonthlyWhatsAppConversations` is reported
rather than enforced because the outbound eligibility gate is the single path to
a customer and adding a second reason for it to refuse needs its own decision.

## Credentials

A reference is a *name*. The module refuses anything matching a credential's
shape, and the resolver — the only object that reads a value — is the single seam a
secret-manager deployment replaces.

Resolution order is short on purpose: the Organization's own `Active` reference,
then its own `Rotating` one (a half-applied rotation must not take the integration
down), then the process environment **only** for the founding Organization, then a
refusal. There is no step that reads another Organization's row.

Rotation appends: the outgoing reference becomes `Rotating`, the new one `Active`,
both rows surviving. The fingerprint proves the value changed without disclosing
it. Rotation does not verify the credential works — only the provider knows that,
and claiming otherwise would report success for an integration that fails on first
use.

## Support access

An internal engineer gets `soporte:<login>` as an ordinary Advisor member row in
one Organization, `advises=False` so the assignment rule cannot route a real
Opportunity to Maia's support desk, read-only, expiring within eight hours, with a
written reason and a use count. Expiry is checked when the login resolves, so
access ends on the clock rather than on a worker having run; the sweep additionally
deactivates the member row, which is what the customer's own Administrator sees.

`/crm/plataforma` shows every grant anybody was ever given into that
Organization's records — who, when, until when, why, and how many times it was
used. A grant that expired unused is evidence the process is working.

## Data lifecycle

`export` walks the scoping table, writes one JSON document with per-table row
counts, and names every withheld column in the manifest with the reason. The
counts are the point: an export that silently missed a table is the failure worth
detecting, and it is only detectable against the registry that produced the list.

`delete` takes a scope. `OperationalContent` removes conversations, drafts,
sessions and saved selections; `Everything` also removes the commercial record.
Neither removes the Organization row, the lifecycle records or the audit trail —
an erasure nobody can prove happened is not a service. A live retention hold
refuses the request outright with its authority quoted back.

## Initial import

`plan` and `apply` are the same code path with a mode, which is what makes "the
dry run said 412" and "the apply created 412" comparable. `apply` requires a
completed dry run over the *identical* source checksum. Every record gets a
finding — `Accepted`, `Duplicate`, `Invalid` or `Skipped` — carrying the source's
own reference, because a summary of counts cannot answer "which twelve were
rejected", which is the only question the customer has.

What lands is one physical Property per accepted record, with `facts_review_state`
`Pending` and provenance naming the run. No Listing, no Offer, no publication, no
media, no price treated as authority: those need a human, and an import that made
them would produce an unreviewed catalog on a public site under somebody's brand.

Rollback deletes by stored identifier. A Property another record already
references is left in place and reported rather than force-deleted — the foreign
keys would refuse anyway, and cascading through a confirmed visit would be doing
damage to undo an inconvenience.

## Usage

Eight measures per Organization per calendar month, recomputed rather than
incremented: active Advisors, WhatsApp Conversations opened, inbound and outbound
messages, model turns (settled Inbox groups, not messages — a customer who writes
in fragments is one turn), integrations with a live reference, published Listings,
confirmed appointments. Usage, not billing.

## Surfaces

* `/platform/...` — JSON, authenticated by `PLATFORM_OPERATOR_TOKEN` **and** a
  mandatory `X-Platform-Operator` name header. An action attributed to "the token"
  is an audit row nobody can follow up. Every mutation requires a written reason
  of at least twelve characters.
* `/crm/plataforma` — Mexican Spanish, read-only, Administrator-only, about the
  caller's own Organization by construction: there is no identifier on the route
  to point somewhere else.

## No new Hermes tools, deliberately

Every stage since Stage 0 added typed tools the model can call. Stage 9 adds none,
and the absence is the design: provisioning an Organization, changing its
entitlements, rotating a credential, granting support access and deleting a
customer's data are not things a conversation should be able to reach, however
well it argues for them. The plugin's tool list is unchanged.

What *did* change for Hermes is invisible from the model's side and important:
`agent_sessions` now names an Organization, and every binding lookup filters on
it. A session is the model's continuity, so a binding resolved across the boundary
would let one brokerage's conversation history answer another's Contact — the
worst leak this product has available. The Sales tools already derived their
Organization from the Conversation; the Administrative ones now derive it from the
session binding rather than from "the only Organization".

## Provider limits, honestly

Not every integration can be separated per Organization by us alone:

* **Meta WhatsApp** separates cleanly: each Organization has its own phone number
  id, WABA id and access token, and the binding is what routes inbound traffic.
  What we cannot separate is Meta's own account health, quality rating and
  messaging limits — those belong to whoever owns the WABA.
* **Google Calendar** separates per Advisor calendar, but the *service account*
  is one credential per reference. An Organization that requires its own service
  account records its own reference; nothing forces it to.
* **Telegram** separates by bot token. Each active Organization resolves its own
  secret reference, verifies that the token's public bot id matches its active
  `TelegramBotId` binding, and polls with only that Organization's active
  Administrator chat ids. A missing or mismatched pair is skipped, never
  inherited from the founding Organization.
* **EasyBroker** separates by API key, and remains gated on the account access and
  written MLS clarification that ADR-0020 and PROJECT_MEMORY already require.
* **The public site** runs one process per public origin, and tells Product which
  hostname it serves. Two brands means two site processes today.

## Operating limits and open decisions

* **No external brokerage has been onboarded.** The stage's own entry condition —
  knowing a candidate inmobiliaria's real needs — is not met. Everything here is
  built from the operating model Larevia proved, and the shape of onboarding,
  support and packaging will move when a real customer disagrees with it.
* **No price, no invoice, no charging.** The packaging structure exists; the
  commercial decision does not, and building charging needs separate
  authorisation (ADR-0053).
* **Seat tiers and the conversation allowance are Product hypotheses**, not
  measurements. Three, ten and twenty-five seats and 1 000/5 000/15 000
  conversations are conservative round numbers chosen to be enforceable, not
  observed.
* **The login namespace is platform-wide.** HTTP Basic carries no Organization, so
  a username identifies one member row across the whole installation.
  Provisioning refuses a taken login *by name* rather than attaching it to the
  wrong brokerage, but the collision itself discloses that some other
  Organization holds it. A per-Organization login namespace needs a different
  authentication scheme.
* **A platform operator can grant themselves support access to any
  Organization.** Bounded, expiring and visible to the customer, but real
  (ADR-0054).
* **Only bounded local load has been measured.** The automated rehearsal accepts
  100 concurrent synthetic inquiries across two Organizations with a concurrency
  ceiling of ten and a deliberately broad 30-second regression bound. This
  catches contention and scoping regressions; it is not a production capacity or
  latency claim.
* **Analytics retention is still unresolved** (ADR-0044), and Stage 9 does not
  change it. Deletion can now remove analytics rows on request, which is not the
  same as an expiry policy.
* **Deliberately absent**: a marketplace, self-service signup, self-service
  billing, a dedicated server per customer, cross-organization model training,
  identifiable cross-organization benchmarks, and any geographic expansion.

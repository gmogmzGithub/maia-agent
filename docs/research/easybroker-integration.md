# EasyBroker integration: verified scope, constraints, and open questions

Status: research note, not an architecture decision  
Verified: 2026-08-27  
Sources: official EasyBroker product pages, developer documentation, help center,
terms, and privacy policy only

## Executive conclusion

Maia must not describe EasyBroker as containing **all properties in Mexico**.
EasyBroker calls its Bolsa Inmobiliaria the largest in Mexico, but its official API
documentation makes a narrower promise: the MLS endpoint returns published
properties that share commission from the authenticated organization's
collaborators, plus the organization's own properties, and it requires a separate
API MLS plan. Membership in a real-estate association is not documented as
automatically granting API access to every EasyBroker listing. [EasyBroker's Bolsa
description](https://ayuda.easybroker.com/article/82-que-es-la-bolsa-inmobiliaria),
[MLS list endpoint](https://dev.easybroker.com/reference/get_mls-properties),
[MLS guide](https://dev.easybroker.com/docs/propiedades-mls)

A defensible product statement is:

> Maia first searches the brokerage's authorized inventory. If the tenant has
> contracted and configured EasyBroker API MLS access, Maia may also search the
> commission-sharing inventory available through that tenant's EasyBroker
> collaborations.

EasyBroker should therefore be modeled as a replaceable, tenant-authorized catalog
provider—not as Maia's source of truth, not as a guaranteed national inventory, and
not as a dataset that Maia is automatically entitled to retain or resell.

## Two APIs with materially different purposes

EasyBroker documents two relevant integration surfaces. They should not be treated
as interchangeable.

### Account API

The ordinary account API exposes information from one EasyBroker account. The
official introduction says it can query that company's properties, create
properties, and create or update prospects. `GET /properties` specifically returns
properties from the authenticated organization. A paid EasyBroker account is
required. [Account API introduction](https://dev.easybroker.com/docs/api-de-easybroker),
[`GET /properties`](https://dev.easybroker.com/reference/get_properties)

The separate MLS endpoints extend that account-level surface to published,
commission-sharing properties from the organization's collaborators, but only for
subscribers to the API MLS plan. They do not promise access to every property in
EasyBroker, let alone every property in Mexico. [MLS list
endpoint](https://dev.easybroker.com/reference/get_mls-properties), [MLS
guide](https://dev.easybroker.com/docs/propiedades-mls)

This is the likely surface for an initial Santiago-owned deployment, subject to
confirming his plan and actual collaborator graph.

### Integration Partners API

EasyBroker separately documents a partner program for external applications that
publish customer listings to their own portals. Partner endpoints use the
`/v1/integration_partners` base path, require both `X-Authorization` and a
`Country-Code`, and only operate in countries where the integration has been
activated. The documented onboarding requirements include linking and unlinking
EasyBroker accounts, processing listing changes, reporting publication status,
sending contact requests back to EasyBroker, testing with EasyBroker, and receiving
approval before customers can connect. [Integration Partners
introduction](https://dev.easybroker.com/docs/introducci%C3%B3n)

This is the stronger candidate for a future Maia platform serving multiple
independent brokerages. It is an approval path, not an entitlement Maia already
has, and the documented use case is portal syndication rather than unrestricted
MLS search or data resale.

## Authentication and tenant isolation

The account API uses a unique API key per EasyBroker account, sent in the
`X-Authorization` header. Only an account administrator can obtain it. EasyBroker
warns that the key can expose or modify private account information and must never
be included in browser or mobile code. [Authentication
guide](https://dev.easybroker.com/docs/autenticaci%C3%B3n), [Account API
introduction](https://dev.easybroker.com/docs/api-de-easybroker)

EasyBroker's terms call the key secret, unique, exclusive, and non-transferable,
while also explaining that it can authorize third-party access to account data.
The account holder remains responsible for protecting it. [Terms, API key and
credentials](https://cdn.easybroker.com/mx/terms)

Implications for Maia:

- calls must be server-to-server;
- each brokerage must have an independently encrypted credential and connection
  record;
- authorization decisions, audit records, rotation, and revocation must be scoped
  by tenant;
- no tenant may inherit Santiago's credential or catalog permissions;
- an EasyBroker key must never be a Hermes tool argument, prompt value, browser
  value, log field, or analytics property.

These are architecture implications derived from EasyBroker's credential model,
not claims that EasyBroker has approved Maia's multi-tenant design.

## Query capability and its limits

### Inventory lists and pagination

`GET /properties` lists the authenticated organization's properties;
`GET /mls_properties` lists the eligible collaborator inventory when the API MLS
plan is present. Both document `page` with a default of 1 and `limit` with a default
of 20 and maximum of 50. [Own-property
guide](https://dev.easybroker.com/docs/propiedades), [MLS list
reference](https://dev.easybroker.com/reference/get_mls-properties)

The documented list filters include property type, update timestamps, operation
type, price range, minimum bedrooms, bathrooms and parking spaces, and construction
and lot-size ranges. They also support update-time sorting. Full details require a
second request to `/properties/{property_id}` or
`/mls_properties/{property_id}`. [Own-property
guide](https://dev.easybroker.com/docs/propiedades), [MLS
guide](https://dev.easybroker.com/docs/propiedades-mls), [MLS detail
reference](https://dev.easybroker.com/reference/get_mls-properties-property-id)

### Location is a material gap

The currently documented `/properties` and `/mls_properties` search schemas do
**not** include a location filter. EasyBroker has a `/locations` endpoint for
retrieving its location hierarchy, but the property-list documentation does not
show a corresponding location predicate. [Property search
filters](https://dev.easybroker.com/docs/propiedades), [MLS search
filters](https://dev.easybroker.com/docs/propiedades-mls), [Locations
endpoint](https://dev.easybroker.com/reference/get_locations)

That creates an engineering constraint for requests such as “three bedrooms in
Querétaro”: either EasyBroker must confirm an undocumented search capability, or
Maia needs an authorized local search index synchronized from the accessible
catalog. The latter must not be implemented until the caching, redistribution, and
deletion rights are confirmed in writing.

### Property detail and commercial provenance

The MLS list/detail schemas expose a stable EasyBroker public ID, property facts,
prices, images, source agent/agency information, public URL, collaboration notes,
exclusivity, and shared-commission fields. Exact location may be hidden or
approximated when the listing owner has disabled it. [MLS list
reference](https://dev.easybroker.com/reference/get_mls-properties), [MLS detail
reference](https://dev.easybroker.com/reference/get_mls-properties-property-id)

Maia should preserve the listing's provenance and commercial constraints rather
than flattening an EasyBroker listing into a property that appears to be owned by
the tenant. At minimum, a synchronized record would need source, EasyBroker public
ID, source organization and agent, public URL, commission-sharing state,
collaboration notes, exact-location visibility, upstream status, and last observed
update time. This is a proposed Maia data contract inferred from the fields and
obligations, not an EasyBroker requirement stated in that form.

## Publication, attribution, and collaboration authority

EasyBroker's terms distinguish visibility in the Bolsa from authority to publish a
third party's listing elsewhere. An accepted collaboration gives the requesting
agent authority to edit, offer, manage, and publish that collaborator's listings on
third-party sites. If the collaboration is withdrawn, the former collaborator must
cease using the listings and remove external publications within 24 hours. [Terms,
Bolsa Inmobiliaria](https://cdn.easybroker.com/mx/terms)

The same terms state that EasyBroker may suspend a listing or account when the
publisher lacks the owner's authorization or omits the corresponding EasyBroker
code on the external site. Listing owners are responsible for the truth and rights
in prices, photos, descriptions, and other listing content; EasyBroker does not
guarantee that content. [Terms, listings and
properties](https://cdn.easybroker.com/mx/terms)

EasyBroker's help center says commission-sharing properties from an active
collaborator can be displayed on an EasyBroker website and that the displayed
listing uses the receiving collaborator's contact information. This supports the
general collaboration model, but it does not by itself define permission for a
custom Maia website or autonomous WhatsApp outreach. [Collaborations help
article](https://ayuda.easybroker.com/article/95-que-son-las-colaboraciones)

Therefore:

- `share_commission = true` should not be treated as universal permission to copy,
  rebrand, or permanently retain a listing;
- public display must preserve the EasyBroker identifier and any agreed
  attribution;
- Maia needs rapid depublication and cache invalidation when upstream authority or
  status changes;
- an outbound message proposing another agency's property should record which
  authorized listing version and collaboration supported that proposal;
- the commercial commission is an inter-agent matter; EasyBroker says it does not
  intermediate or monitor those relationships. [Terms, Bolsa
  Inmobiliaria](https://cdn.easybroker.com/mx/terms)

## Synchronization, webhooks, and failure handling

No webhook appears in the current public developer-documentation index. That is an
absence in the reviewed public documentation, not proof that EasyBroker offers no
private webhook under a commercial agreement. EasyBroker's documented partner
flow instead uses polling: check listing statuses every 15–30 minutes, process
published and unpublished changes, and run a daily full reconciliation as a safety
net. [`llms.txt` documentation index](https://dev.easybroker.com/llms.txt),
[Integration Partners introduction](https://dev.easybroker.com/docs/introducci%C3%B3n),
[Listing Statuses guide](https://dev.easybroker.com/docs/listing-statuses)

For the account API, `listing_statuses` can include collaborator changes under an
API MLS plan. The reference says published collaborator properties are included,
while unpublished collaborator properties remain visible in this change feed only
for the previous month. [Listing Statuses
reference](https://dev.easybroker.com/reference/get_listing-statuses)

The documented API limit is 20 requests per second, and exceeding it can produce
HTTP 429. A production connector therefore needs bounded concurrency, retry with
backoff, durable cursors/checkpoints, idempotent upserts, tombstones, and a full
reconciliation path. [Account API introduction](https://dev.easybroker.com/docs/api-de-easybroker),
[API errors](https://dev.easybroker.com/docs/errores-de-la-api)

EasyBroker's partner flow also requires reporting each external publication as
`pending`, `successful` with its direct listing URL, or `failed` with errors, and
requires sending property-originated contact requests back through its API. [Property
Integration](https://dev.easybroker.com/docs/property-integration-1), [Contact
Request](https://dev.easybroker.com/docs/contact-request)

## Sandbox and production readiness

EasyBroker provides a public staging environment with fictitious data at
`https://api.stagingeb.com/v1`; production keys do not work there. Production uses
`https://api.easybroker.com/v1`. The official documentation publishes a shared
staging credential, which should be loaded from the documentation or local test
configuration rather than copied into Maia's public repository. [Account API
introduction](https://dev.easybroker.com/docs/api-de-easybroker)

The create-property endpoint is currently marked beta. The retrieve endpoints are
not marked beta in the reference. Maia should avoid making beta write behavior an
irreversible dependency of its own property system of record. [Create-property
reference](https://dev.easybroker.com/reference/post_properties), [Retrieve-property
reference](https://dev.easybroker.com/reference/get_properties-property-id)

The sandbox can validate schemas, pagination, authentication failures, and retry
behavior. It cannot validate Santiago's plan, collaborator coverage, real data
quality, permission changes, commission terms, or production performance. Those
require a tenant-authorized production pilot and commercial confirmation.

## Storage, website display, BI, and redistribution

EasyBroker expressly supports building a custom website connected to one's own
account. Its partner documentation also describes synchronizing customer listings
onto an approved external portal. These sources support an operational replica for
an authorized integration, but neither grants an explicit general right to create
a permanent cross-tenant data lake, resell listing data, train models on it, or keep
third-party listing history after authority is withdrawn. [Account API
introduction](https://dev.easybroker.com/docs/api-de-easybroker), [Integration
Partners introduction](https://dev.easybroker.com/docs/introducci%C3%B3n)

The terms grant users a limited, revocable, non-transferable, non-sublicensable
license to the EasyBroker service. They prohibit reproducing, selling, reselling,
distributing, or exploiting the service or using it for a third party without
EasyBroker's express written consent. [Terms, license and prohibited
uses](https://cdn.easybroker.com/mx/terms)

Consequently, Maia may design an internal operational cache with deletion and
provenance controls, but the following uses remain **unresolved pending written
permission**:

- retaining descriptions, images, files, or exact historical prices after a
  listing is unpublished or a collaboration ends;
- aggregating listing data across independent Maia tenants;
- using EasyBroker content for machine-learning training or enrichment;
- selling analytics derived from EasyBroker listing content;
- exposing the MLS catalog through Maia's own API;
- allowing one tenant's EasyBroker entitlement to benefit another tenant.

Business intelligence about Maia's own funnel—such as lead response time,
follow-up completion, appointment conversion, consent, and attributed outcomes—is
conceptually different from copying EasyBroker's catalog. Even there, personally
identifiable lead data requires a lawful purpose, retention controls, and tenant
isolation.

## Lead data and privacy

EasyBroker's privacy policy says the agent is responsible for third-party personal
data and databases uploaded or managed through the service. It requires compliance
with applicable data-protection rules, including consent where required, adequate
security, mechanisms for access/rectification/cancellation/opposition, and deletion
when rights or processing purposes end. [EasyBroker Mexico privacy
policy](https://www.easybroker.com/mx/privacy)

The same policy warns that EasyBroker may delete account information after service
termination or nonpayment and makes the agent responsible for independent backups.
It also states that sharing an API key gives its recipient access to the associated
information. [EasyBroker Mexico privacy
policy](https://www.easybroker.com/mx/privacy)

These terms support keeping Maia's CRM—not EasyBroker—as the authoritative record
for identity, channel consent, contact preferences, follow-up state, opt-outs,
outcomes, and audit events. EasyBroker can receive contact requests when required
by an integration agreement, but it should not be the only custodian of Maia's
operational truth.

## Multi-tenant business risk

A single-brokerage pilot can use Santiago's account-specific credential and only
the inventory authorized to that account. A commercial Maia SaaS must not reuse
that credential or entitlement for other brokerages.

The terms' restrictions on resale, third-party use, credential transfer, and
sublicensing make “renting EasyBroker access through Maia” a contractual red flag.
The documented Integration Partners program is evidence that EasyBroker has a
supported multi-customer integration route, but Maia would still need approval,
country activation, and written commercial/data terms. [Terms, API key and
prohibited uses](https://cdn.easybroker.com/mx/terms), [Integration Partners
introduction](https://dev.easybroker.com/docs/introducci%C3%B3n)

The lowest-risk product boundary is:

1. Maia licenses its own CRM, lead-follow-up engine, agent, audit trail, and
   analytics to each brokerage.
2. EasyBroker is an optional connector configured and authorized separately for
   each tenant.
3. Every property result carries its source, current authority, freshness, and
   attribution.
4. Maia's business still works with tenant-owned inventory when EasyBroker is
   unavailable, revoked, commercially unsuitable, or replaced.

This is an engineering recommendation based on the verified constraints, not a
statement of EasyBroker's approval.

## Questions EasyBroker must answer in writing

Before designing the production connector or promising nationwide coverage, ask
EasyBroker:

1. Does Santiago's current account include API access and the API MLS plan?
2. Which organizations and group/association listings would his account actually
   receive through `/mls_properties`?
3. Does association membership create an EasyBroker collaboration group, or are
   bilateral collaborations still required?
4. May Maia recommend an MLS property privately over WhatsApp without a separate
   accepted collaboration? What changes for public website display?
5. What EasyBroker ID, agency, agent, branding, link, and disclaimer must Maia show
   in private messages and on public pages?
6. May Maia cache listing facts, descriptions, images, attached files, and contact
   details? For how long, and must images be hot-linked or copied?
7. What deletion deadline applies to API caches and analytics after unpublication,
   collaboration withdrawal, or account disconnection?
8. May Maia retain historical prices and availability for internal BI? May it
   compute tenant-level or cross-tenant aggregates?
9. May any EasyBroker-derived data be used for model training, evaluation, search
   embeddings, or recommendation features?
10. Is the Integration Partners program the required route for a multi-tenant Maia
    SaaS? What approval, certification, fees, and revenue terms apply?
11. Are there private webhooks, service-level commitments, per-account quotas,
    concurrency limits, or bulk-export mechanisms beyond the public documentation?
12. Is location search supported by an undocumented property API parameter, or is
    an authorized local index the expected implementation?
13. How should commissions and lead attribution be evidenced when Maia introduces a
    buyer to a collaborator's property?

Until those answers exist, the contract-safe scope is a tenant-isolated,
server-side proof of concept against EasyBroker staging and, with Santiago's
explicit authorization, a read-only inventory pilot that does not promise all of
Mexico, publish collaborators' listings publicly, or retain their data
indefinitely.

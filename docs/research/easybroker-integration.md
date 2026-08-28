# EasyBroker read-only integration: Stage 6 revalidation

Status: research note, not an architecture decision  
Verified: 2026-08-28
Method: public, unauthenticated review of official EasyBroker developer
documentation, API references, help center, terms, and privacy policy. No API key
was used and no staging or production request was made.

## Conclusion

EasyBroker can be an optional, organization-authorized source of the
authenticated organization's properties and, only with an API MLS plan, published
commission-sharing properties from its collaborators. The public API does not
promise all EasyBroker properties or all properties in Mexico. [Account API
introduction](https://dev.easybroker.com/docs/api-de-easybroker), [MLS list
reference](https://dev.easybroker.com/reference/get_mls-properties), [MLS
guide](https://dev.easybroker.com/docs/propiedades-mls)

The defensible Stage 6 boundary is therefore:

> Maia searches Product's authoritative Organization Listings first. An enabled
> EasyBroker connection may add currently authorized candidates from that
> organization's own account and API MLS collaborator scope. Every external
> candidate remains provenance-bearing, approximate when necessary, and pending
> until its action-specific facts can be revalidated.

The public documentation is sufficient to build a fake-backed port and a
read-only HTTP adapter contract. It is not sufficient to activate collaborator
inventory, publication, durable retention, or production access without the
account holder's authorization and written commercial confirmation.

## Verified versus unverified

| Topic | Evidence status | What the public official material establishes | Stage 6 consequence |
| --- | --- | --- | --- |
| Account access | **Verified** | The account API requires a paid EasyBroker account and a per-account API key in `X-Authorization`; only an administrator can obtain or regenerate the key. [API introduction](https://dev.easybroker.com/docs/api-de-easybroker), [authentication](https://dev.easybroker.com/docs/autenticaci%C3%B3n) | Credential configuration must be organization-scoped and server-only. |
| Read-only credential | **Unverified** | The public authentication guide describes one key that can access and modify private account information; no read-only key scope or OAuth scope is documented. [Authentication](https://dev.easybroker.com/docs/autenticaci%C3%B3n), [API index](https://dev.easybroker.com/llms.txt) | Enforce read-only behavior in Maia by exposing only `GET` operations and by testing method/path allowlists. Do not call the credential itself read-only. |
| Own inventory | **Verified** | `GET /properties` returns properties from the authenticated organization; `GET /properties/{property_id}` returns one account property by public or internal ID. [`GET /properties`](https://dev.easybroker.com/reference/get_properties), [`GET /properties/{property_id}`](https://dev.easybroker.com/reference/get_properties-property-id) | This is the only publicly documented account-level inventory entitlement that does not require API MLS. |
| MLS inventory | **Verified, plan-dependent** | `GET /mls_properties` returns published properties with shared commissions from the organization's collaborators and its own organization; list and detail endpoints require the API MLS plan and may return `403` when the plan is absent. [MLS list](https://dev.easybroker.com/reference/get_mls-properties), [MLS detail](https://dev.easybroker.com/reference/get_mls-properties-property-id) | Keep MLS disabled until the actual organization plan and access are confirmed. A paid account alone is insufficient. |
| Universal inventory | **Not supported** | The help center markets the Bolsa Inmobiliaria as the largest in Mexico, while the API reference limits the MLS result to the authenticated organization's collaboration scope. [Bolsa help](https://ayuda.easybroker.com/article/82-que-es-la-bolsa-inmobiliaria), [MLS list](https://dev.easybroker.com/reference/get_mls-properties) | Never claim “all properties in Mexico,” and never use association membership as proof of API-wide access. |
| Collaborations and associations | **Partially verified** | `GET /collaborations` returns organization collaborations with agency ID/name and a flag identifying a group or association. Help documentation says active collaborators and collaboration groups can share eligible inventory. [`GET /collaborations`](https://dev.easybroker.com/reference/get_collaborations), [collaborations help](https://ayuda.easybroker.com/article/95-que-son-las-colaboraciones) | The current account's actual collaborators, group coverage, and whether each relationship is active remain provider/account facts to verify. |
| Property location search | **Not available in the published search schema** | The own and MLS property-list schemas expose filters for type, timestamps, operation, price, minimum rooms/parking, sizes, statuses, and update-time sorting, but no location predicate. `/locations` is a separate hierarchy lookup. [Own-property guide](https://dev.easybroker.com/docs/propiedades), [MLS guide](https://dev.easybroker.com/docs/propiedades-mls), [`GET /locations`](https://dev.easybroker.com/reference/get_locations) | Guadalajara, Zapopan, and Tlaquepaque filtering must be performed by Maia over authorized results; ambiguous or hidden location must fail closed. |
| Pagination | **Verified as page-based, not cursor-based** | Property lists use `page` plus `limit` (default 20, maximum 50) and return `pagination.limit`, `page`, `total`, and nullable `next_page`. [Own list](https://dev.easybroker.com/reference/get_properties), [MLS list](https://dev.easybroker.com/reference/get_mls-properties) | The stable port may call its continuation a cursor, but the EasyBroker adapter must translate it to page/`next_page` semantics; no provider cursor exists in the public contract. |
| Snapshot consistency | **Unverified** | The public list references do not document snapshot isolation, cursor stability, duplicate prevention, or behavior when inventory changes between pages. [Own list](https://dev.easybroker.com/reference/get_properties), [MLS list](https://dev.easybroker.com/reference/get_mls-properties) | Make upserts idempotent, preserve source IDs, tolerate repeated items, and reconcile rather than treating one traversal as an immutable snapshot. |
| Current listing state | **Partially verified** | `GET /listing_statuses` returns `public_id`, status, and `updated_at`; with API MLS it can include all published collaborator properties and collaborator properties unpublished in the previous month. [`GET /listing_statuses`](https://dev.easybroker.com/reference/get_listing-statuses) | A missed removal older than one month cannot be recovered from the collaborator change feed alone; periodic comparison with the current MLS list is required. |
| Webhooks | **Unverified/not publicly documented** | No webhook guide or endpoint appears in the current official developer-documentation index. [Documentation index](https://dev.easybroker.com/llms.txt) | Stage 6 must not depend on a webhook. This is an absence in public docs, not proof that EasyBroker has no private offering. |
| Rate limit | **Verified** | EasyBroker documents a limit of 20 requests per second and HTTP `429` when it is exceeded; the error guide says to wait before retrying. [API introduction](https://dev.easybroker.com/docs/api-de-easybroker), [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Bound concurrency below the published ceiling and classify `429` as retryable. |
| Retry contract | **Unverified** | The public docs do not specify the rate-limit scope/window, `Retry-After`, retry headers, backoff formula, timeout, request ID, or `5xx` semantics. [API introduction](https://dev.easybroker.com/docs/api-de-easybroker), [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Backoff, jitter, timeout, attempt caps, and circuit behavior are Maia policy, not provider guarantees; preserve a provider `Retry-After` header if one is observed later. |
| Commission | **Partially verified** | MLS detail exposes nullable `shared_commission_percentage` (currently documented as `50` or `null`) and nullable free-text `collaboration_notes`; MLS operations do not expose the account property's operation-level `commission` object. [MLS detail](https://dev.easybroker.com/reference/get_mls-properties-property-id), [own detail](https://dev.easybroker.com/reference/get_properties-property-id) | `null`, missing, or ambiguous notes mean commission is unknown. Do not calculate or promise a commission from MLS data alone. |
| External publication authority | **Partially verified** | The terms say an accepted collaboration authorizes the collaborator to edit, offer, manage, and publish the other agent's listings on third-party sites; such publication must include the EasyBroker code. On withdrawal, use must cease and external publications must be removed within 24 hours. [Terms, sections 5 and 7](https://cdn.easybroker.com/mx/terms) | Treat public publication as a separate authorization decision. A candidate being visible through MLS is not by itself a Maia publication decision. |
| Private recommendation and scheduling authority | **Unverified** | Public terms describe offering and external publication through collaborations, but do not define autonomous WhatsApp recommendations, appointment scheduling, or the evidence Maia must retain for those actions. [Terms](https://cdn.easybroker.com/mx/terms) | Require business/provider confirmation; return `Pending` when action-specific authority cannot be established. |
| Retention and redistribution | **Unverified except for the 24-hour depublication duty** | The terms prohibit copying, resale, distribution, third-party use, or exploitation of the service without express written consent and impose the 24-hour withdrawal rule, but publish no general cache, tombstone, or historical-listing retention schedule. [Terms, sections 7 and 20](https://cdn.easybroker.com/mx/terms) | Written permission is required for durable collaborator caches, history, analytics, model training, cross-organization aggregation, or re-exposure through Maia's API. |
| Staging | **Verified, not exercised here** | EasyBroker publishes a fictitious-data staging environment separate from production; production keys do not work there. [API introduction](https://dev.easybroker.com/docs/api-de-easybroker) | Fixtures remain the public-CI contract. Any provider-backed staging check must be separate and opt-in; this research did not use the published staging credential. |

## Stage 6 HTTP contract

The relevant Account API base URL is `https://api.easybroker.com/v1`. The
`/v1/integration_partners` API is a separate approved-portal integration program,
not the account/MLS API required by this stage. [Account API
introduction](https://dev.easybroker.com/docs/api-de-easybroker), [Integration
Partners introduction](https://dev.easybroker.com/docs/introducci%C3%B3n)

| Purpose | Method and path | Publicly documented result |
| --- | --- | --- |
| Search own organization inventory | `GET /properties` | Paginated account properties, with optional filters and update-time sort. [`GET /properties`](https://dev.easybroker.com/reference/get_properties) |
| Refresh one own property | `GET /properties/{property_id}` | Detailed account property by public or internal ID; `404` when the property is not found. [`GET /properties/{property_id}`](https://dev.easybroker.com/reference/get_properties-property-id) |
| Search eligible own plus collaborator inventory | `GET /mls_properties` | Paginated published, commission-sharing properties; requires API MLS. [`GET /mls_properties`](https://dev.easybroker.com/reference/get_mls-properties) |
| Refresh one MLS property | `GET /mls_properties/{property_id}` | Detailed MLS property by EasyBroker public ID; requires API MLS; documents `403` and `404`. [`GET /mls_properties/{property_id}`](https://dev.easybroker.com/reference/get_mls-properties-property-id) |
| Read lifecycle changes | `GET /listing_statuses` | Paginated source IDs, statuses, and update timestamps; optional collaborator inclusion requires API MLS. [`GET /listing_statuses`](https://dev.easybroker.com/reference/get_listing-statuses) |
| Read organization collaborations | `GET /collaborations` | Paginated agency IDs/names and group-or-association flags. [`GET /collaborations`](https://dev.easybroker.com/reference/get_collaborations) |
| Resolve EasyBroker location hierarchy | `GET /locations?query=...` | A matching location with parent-qualified `full_name` and child localities. [`GET /locations`](https://dev.easybroker.com/reference/get_locations) |
| Resolve stable property-type symbols | `GET /property_types` | Current property-type symbols and localized names for the account country. [`GET /property_types`](https://dev.easybroker.com/reference/get_property-types) |

The Stage 6 provider path uses only `GET` routes. EasyBroker's ordinary account
API also documents write operations, which is why a general account key must never
be described as provider-enforced read-only. [API introduction](https://dev.easybroker.com/docs/api-de-easybroker),
[authentication](https://dev.easybroker.com/docs/autenticaci%C3%B3n)

## Search, pagination, and service-area enforcement

Both property-list endpoints document these search inputs: property-type symbols;
`updated_after`/`updated_before`; operation type (`sale`, `rental`, or
`temporary_rental`); minimum/maximum price; minimum bedrooms, bathrooms, and
parking spaces; minimum/maximum construction and lot size; statuses; and
`updated_at-asc`/`updated_at-desc` sorting. Price filters require an operation
type. [Own list reference](https://dev.easybroker.com/reference/get_properties),
[MLS list reference](https://dev.easybroker.com/reference/get_mls-properties)

With no filters, `/properties` returns all of the organization's properties,
including non-lead-facing statuses; a customer search must request allowed statuses
explicitly rather than treating the unfiltered result as available inventory.
[Own-property guide](https://dev.easybroker.com/docs/propiedades), [own list
reference](https://dev.easybroker.com/reference/get_properties)

Property-type symbols should come from `/property_types`; the reference says names
remain accepted only for backward compatibility and may change or be translated.
[Own list reference](https://dev.easybroker.com/reference/get_properties)

Neither property list has a documented location, title, keyword, feature, or free-
text filter. List records contain a location string, and detail records contain a
location object with `name`, nullable coordinates/street/postal code, and
`show_exact_location`. For MLS responses, coordinates can be hidden or approximate
when exact location is disabled. [Own list
reference](https://dev.easybroker.com/reference/get_properties), [MLS list
reference](https://dev.easybroker.com/reference/get_mls-properties), [MLS detail
reference](https://dev.easybroker.com/reference/get_mls-properties-property-id)

The own-account detail endpoint can expose stored coordinates even when
`show_exact_location` is false. Maia must enforce the disclosure flag and must not
pass a raw detail payload to Hermes or a lead. [Own detail
reference](https://dev.easybroker.com/reference/get_properties-property-id)

Therefore, `/locations` can help normalize the EasyBroker hierarchy but cannot
restrict `/properties` or `/mls_properties` at the provider. The adapter must map
the returned location without inventing precision, and Product must reject or mark
pending any candidate that cannot be proven to fall in Guadalajara, Zapopan, or
Tlaquepaque. [`GET /locations`](https://dev.easybroker.com/reference/get_locations),
[MLS guide](https://dev.easybroker.com/docs/propiedades-mls)

The property-list continuation is page-based. The request uses integer `page` and
`limit`; the response returns `limit`, `page`, `total`, and nullable `next_page`.
The public schema does not define an opaque cursor. [Own list
reference](https://dev.easybroker.com/reference/get_properties), [MLS list
reference](https://dev.easybroker.com/reference/get_mls-properties)

One documentation inconsistency must be covered by fixtures: the
`/listing_statuses` parameter allows up to 100 items, but its reused pagination
schema still declares a maximum of 50. The returned value, not the reused schema's
maximum, should remain authoritative at runtime, and the adapter should not request
more than the endpoint parameter permits. [`GET /listing_statuses`](https://dev.easybroker.com/reference/get_listing-statuses)

## Fields and mapping limits

The list schemas are smaller than the detail schemas. Stage 6 must not infer a
missing detail field from a list record.

| Surface | Important documented fields | Mapping caution |
| --- | --- | --- |
| Own-property list | `public_id`, title and title images, nullable room/size facts, location string, property type, `updated_at`, agent name, `show_prices`, `share_commission`, and operations including commission. [`GET /properties`](https://dev.easybroker.com/reference/get_properties) | `public_id` is the provider ID; `internal_id` is not present in the list. Nullable facts remain unknown. |
| Own-property detail | Base facts, images, description, `internal_id`, maintenance, dates, features, `public_url`, files/media, collaboration notes, exclusivity, shared-commission percentage, private description, full location, tags, price visibility, sharing flag, and operations with commission. [`GET /properties/{property_id}`](https://dev.easybroker.com/reference/get_properties-property-id) | `private_description`, exact address/coordinates, source agent contact, and account-only metadata must not become customer facts. A write-capable account representation is still only an external candidate in Maia. |
| MLS list | `public_id`, source agent and agency, title/title images, nullable room/size facts, location string, property type, `updated_at`, `public_url`, and operations. [`GET /mls_properties`](https://dev.easybroker.com/reference/get_mls-properties) | It does **not** expose collaboration notes, exclusivity, or shared-commission percentage; detail is required before action. |
| MLS detail | Base facts/media, source agent, dates, `public_url`, nullable collaboration notes, exclusivity, nullable shared-commission percentage, operations, and a location that may hide or approximate exact coordinates. [`GET /mls_properties/{property_id}`](https://dev.easybroker.com/reference/get_mls-properties-property-id) | It does **not** expose a listing `status` or an operation-level commission object. Use lifecycle evidence separately and keep commission unknown when evidence is incomplete. |
| Listing status | `public_id`, `status`, and `updated_at`. Response statuses are documented as `published`, `sold`, `rented`, `reserved`, `suspended`, and `not_published`. [`GET /listing_statuses`](https://dev.easybroker.com/reference/get_listing-statuses) | The search filter also accepts `flagged` and `disapproved`, although the response enum omits them. Preserve unknown provider values and fail closed rather than coercing them to `published`. |
| Collaboration | `agency_id`, `agency_name`, and `group`. [`GET /collaborations`](https://dev.easybroker.com/reference/get_collaborations) | No per-listing publication grant, commission terms, expiry, or retention right is documented in this response. |

Image URLs include a version query parameter that changes when an image changes;
EasyBroker says to retain the complete URL and refresh it during synchronization.
[Own detail reference](https://dev.easybroker.com/reference/get_properties-property-id)

At minimum, the external candidate should preserve the source, EasyBroker
`public_id`, source agency/agent identifiers, source URL, upstream timestamps,
location precision, current lifecycle evidence, price operation/currency/unit,
collaboration evidence, commission evidence, attribution, and the time each fact
was observed. This is a proposed Maia mapping derived from the official schemas,
not a provider-mandated data model.

## Revalidation semantics

The strongest public evidence available for an action-time revalidation is a
fresh MLS detail response plus current lifecycle/collaboration evidence. The detail
response refreshes price, facts, attribution, notes, and exact-location visibility;
`/listing_statuses` carries the explicit lifecycle state. [MLS detail](https://dev.easybroker.com/reference/get_mls-properties-property-id),
[listing statuses](https://dev.easybroker.com/reference/get_listing-statuses)

The MLS detail endpoint documents `403` when API MLS is unavailable and `404` when
the property cannot be found, but it does not document distinct error reasons for
withdrawn collaboration, unpublished inventory, deleted inventory, or an unknown
ID. [MLS detail](https://dev.easybroker.com/reference/get_mls-properties-property-id)

Consequently, a `404` is evidence that Maia cannot currently revalidate the
candidate, not proof of a specific business reason. `403`, `404`, stale lifecycle
evidence, missing collaboration evidence, hidden/ambiguous service area, changed
price, and incomplete commission evidence must not silently pass the Stage 6
action gate.

The status feed includes collaborator listings unpublished only during the
previous month. A complete reconciliation against the current MLS list is therefore
necessary to detect long-missed removals. [`GET /listing_statuses`](https://dev.easybroker.com/reference/get_listing-statuses),
[`GET /mls_properties`](https://dev.easybroker.com/reference/get_mls-properties)

The official 15–30 minute polling and daily safety-net advice belongs to the
separate Integration Partners portal API. EasyBroker does not publish the same
cadence as a contract for the ordinary account/MLS API, so Stage 6 freshness and
staleness thresholds remain a Maia policy awaiting provider/business confirmation.
[Integration Partners introduction](https://dev.easybroker.com/docs/introducci%C3%B3n),
[Account API introduction](https://dev.easybroker.com/docs/api-de-easybroker)

## Errors, rate limiting, and retries

EasyBroker's current error guide documents:

| HTTP status | Official meaning | Adapter classification |
| --- | --- | --- |
| `400` | Invalid filter or format. [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Permanent request/contract failure. |
| `401` | Missing/invalid key or account cannot use the API. [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Connection/authentication failure; no blind retry. |
| `403` | Plan does not allow the resource, including API MLS. [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Permission/plan denial; no blind retry. |
| `404` | Resource does not exist or does not belong to the account. [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Unrevalidatable candidate outcome, with exact reason unknown. |
| `422` | Submitted data violates resource rules. [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Not expected on the Stage 6 `GET` allowlist; treat as contract failure. |
| `429` | Request limit exceeded; wait before trying again. [API errors](https://dev.easybroker.com/docs/errores-de-la-api) | Retryable with bounded backoff. |

The guide warns clients not to compare exact error-message text because it can
vary by language; use HTTP status and field names. [API errors](https://dev.easybroker.com/docs/errores-de-la-api)

The documented ceiling is 20 requests per second. No public document reviewed
specifies a `Retry-After` contract, attempt count, exponential-backoff formula,
timeout, or server-error response body. [API introduction](https://dev.easybroker.com/docs/api-de-easybroker),
[API errors](https://dev.easybroker.com/docs/errores-de-la-api)

Therefore, bounded exponential backoff with jitter, timeout budgets, partial-page
checkpoints, idempotent upserts, and a circuit/health state are Maia engineering
policy. Tests should distinguish the documented provider facts (`429` and the
20/second ceiling) from simulated but necessary transport failures (`timeout` and
`5xx`).

## Permissions, attribution, commission, and retention

An accepted collaboration is the clearest public authorization described by
EasyBroker: its terms say it authorizes the collaborator to edit, offer, manage,
and publish the other agent's listings outside EasyBroker. If that collaboration
is withdrawn, authorization ends and the former collaborator must cease use and
remove external publications within 24 hours. [Terms, section 7](https://cdn.easybroker.com/mx/terms)

For an externally published collaborator listing, the terms require inclusion of
the EasyBroker identification code and permit suspension when authorization is
missing or the code is omitted. [Terms, section 5](https://cdn.easybroker.com/mx/terms)

EasyBroker does not mediate or monitor the commercial relationship or guarantee
that a listing owner will share commission. The listing owners remain responsible
for their listing content and authorization. [Terms, sections 5 and
7](https://cdn.easybroker.com/mx/terms)

The API MLS result already selects published, commission-sharing properties, but
the detail contract still allows `shared_commission_percentage: null` and free-text
collaboration notes. These are not enough to infer a payable amount or all
conditions. [MLS list](https://dev.easybroker.com/reference/get_mls-properties),
[MLS detail](https://dev.easybroker.com/reference/get_mls-properties-property-id)

EasyBroker's publishing help identifies commission percentages and collaboration
conditions as information for advisers, not final customers. [Property publishing
help](https://ayuda.easybroker.com/article/482-agrega-y-publica-tus-propiedades)

The help center says active collaborator properties with shared commission may be
shown on an EasyBroker website and appear with the receiving collaborator's contact
details. That product behavior does not itself establish a general license for a
custom Maia site, API redistribution, autonomous outreach, or indefinite storage.
[Collaborations help](https://ayuda.easybroker.com/article/95-que-son-las-colaboraciones)

The terms provide a limited, revocable, non-transferable, non-sublicensable service
license and prohibit copying, resale, distribution, third-party access/use, or
exploitation without written consent. They do not publish a general retention
schedule for cached collaborator listing content. [Terms, license and prohibited
uses](https://cdn.easybroker.com/mx/terms)

The privacy policy makes the account holder responsible for lawful handling of
third-party personal data, security, data-subject rights, and deletion when rights
or processing purposes end. It also says EasyBroker may delete account information
after cancellation or nonpayment and places backup responsibility on the account
holder. [Mexico privacy policy](https://www.easybroker.com/mx/privacy)

The following remain written-permission gates:

- production API and API MLS entitlement for the actual organization;
- the organization's current collaborator/group scope;
- custom-site or WhatsApp attribution requirements beyond the EasyBroker code;
- recommendation and appointment authority for collaborator listings;
- commission interpretation when percentage or notes are missing or ambiguous;
- cache duration, tombstones, and deletion beyond the 24-hour external-publication
  rule;
- retention of descriptions, images, files, prices, or commercial history after
  unpublication or collaboration withdrawal;
- analytics, model training, cross-organization aggregation, resale, or exposure
  through Maia's own API.

## Provider readiness gates

The following evidence cannot be obtained from public documentation and must not
be represented as verified:

1. A real EasyBroker account or API key has been issued to Maia.
2. The target organization has a paid account and an active API MLS plan.
3. Any real collaborator, group, or association inventory is visible to that key.
4. EasyBroker has approved Maia's caching, attribution, retention, WhatsApp,
   scheduling, analytics, or multi-organization design.
5. Production schemas, latency, error headers, data quality, and permission-change
   behavior match public examples.
6. A listing's legal facts, owner authorization, visit availability, price,
   collaboration, or commission are true merely because its record is returned.

Until those gates close, Stage 6 can truthfully claim only fake/fixture-backed
behavior and a contract shaped by the current public documentation. Provider
staging and production checks must remain separate, explicit, and opt-in.

## Official source set reviewed

- [Developer documentation index](https://dev.easybroker.com/llms.txt)
- [Account API introduction](https://dev.easybroker.com/docs/api-de-easybroker)
- [Authentication](https://dev.easybroker.com/docs/autenticaci%C3%B3n)
- [Own-property guide](https://dev.easybroker.com/docs/propiedades)
- [MLS guide](https://dev.easybroker.com/docs/propiedades-mls)
- [API errors](https://dev.easybroker.com/docs/errores-de-la-api)
- [Own-property list reference](https://dev.easybroker.com/reference/get_properties)
- [Own-property detail reference](https://dev.easybroker.com/reference/get_properties-property-id)
- [MLS list reference](https://dev.easybroker.com/reference/get_mls-properties)
- [MLS detail reference](https://dev.easybroker.com/reference/get_mls-properties-property-id)
- [Listing-status reference](https://dev.easybroker.com/reference/get_listing-statuses)
- [Collaborations reference](https://dev.easybroker.com/reference/get_collaborations)
- [Locations reference](https://dev.easybroker.com/reference/get_locations)
- [Property-types reference](https://dev.easybroker.com/reference/get_property-types)
- [Integration Partners introduction](https://dev.easybroker.com/docs/introducci%C3%B3n)
- [Bolsa Inmobiliaria help](https://ayuda.easybroker.com/article/82-que-es-la-bolsa-inmobiliaria)
- [Collaborations help](https://ayuda.easybroker.com/article/95-que-son-las-colaboraciones)
- [Property publishing help](https://ayuda.easybroker.com/article/482-agrega-y-publica-tus-propiedades)
- [Mexico terms](https://cdn.easybroker.com/mx/terms)
- [Mexico privacy policy](https://www.easybroker.com/mx/privacy)

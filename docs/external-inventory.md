# Stage 6: read-only external inventory

Stage 6 adds a replaceable external-inventory module and an EasyBroker HTTP
adapter. It does not activate a real EasyBroker account and it does not turn an
external record into Product catalog truth.

## Authority boundary

An EasyBroker property is stored as an **External Listing Candidate**. It has a
stable source ID, observed/source timestamps, raw sanitized-provider provenance,
an explicit Listing/Offer candidate mapping, service-area classification, and
separate authority and commercial-review states. It has no foreign key to a
Product Property or Catalog Listing, so synchronization cannot auto-merge a
look-alike record or replace the authoritative catalog.

Product exposes four stable seams:

| Interface | Responsibility |
| --- | --- |
| `ExternalInventory.search(criteria)` | Search only fresh, authorized candidates in the local index. |
| `ExternalInventory.refresh(source_listing_id)` | Re-read one source record and atomically update its candidate mapping. |
| `ListingRevalidation.evaluate(listing_id, intended_action, at)` | Refresh and decide `Eligible`, `Pending`, or `Denied` for `Recommend`, `Share`, or `Appointment`. |
| `InventorySourceHealth.read(source)` | Read sanitized operational status, counts, timestamps, and error class. |

The true-external port is narrower than those Product interfaces: list one page
and retrieve one source record. The EasyBroker adapter contains page/continuation
translation, a 20-request/second pace, bounded retry/backoff, timeout handling,
`429` handling, and an allowlist consisting only of `GET /properties`,
`GET /properties/{id}`, `GET /mls_properties`, and
`GET /mls_properties/{id}`.

## Mapping and evidence

| Source fact | Candidate field | Missing/unknown behavior |
| --- | --- | --- |
| `public_id` | immutable `source_listing_id` | record rejected; no identity is invented |
| `updated_at` and observation time | freshness evidence | mapping issue; never treated as permanent freshness |
| `location.municipality` | Guadalajara, Zapopan, or Tlaquepaque | outside/ambiguous is denied, never broadened to the metro area |
| `status` | candidate availability only for an explicit availability value | publication-like or unknown values remain `Unknown` |
| `operations[]` | separate Offer candidates | unknown operation, price, or currency stays null/unknown |
| agent/agency | attribution | missing attribution remains pending |
| shared commission field | preserved commission source value | null/missing remains unknown |
| complete source response | `raw_payload` plus SHA-256 checksum | retained only while permitted and active |

Source presence never establishes collaboration authority. An Organization
Administrator must record the current authority evidence, attribution,
collaboration confirmation, known commission, and availability. A source change
to the Offer returns the candidate to `Pending`/`NeedsReview`; a withdrawal,
out-of-area location, or revoked collaboration is `Denied`.

Every use-time decision refreshes under the candidate row lock. That serializes a
concurrent sync/refresh with recommendation or appointment evaluation and binds
the audit record to the exact source checksum it evaluated.

## Search behavior

`AuthorizedInventorySearch` asks the authoritative Product catalog first. A
matching Organization Listing ends the search; EasyBroker candidates are a
fallback, never a replacement. Optional criteria with missing source values are
reported as `Approximate`; a known mismatch is excluded. Municipality is never
approximate.

Hermes reaches the feature only through the thin plugin calls
`search_inventory` and `revalidate_external_listing`. It receives the public
source reference, exact/approximate label, attribution, bounded Offer facts, and
whether revalidation is required. It receives no provider key, raw payload,
database access, or authority override.

## Withdrawal and cache cleanup

A provider `404` or explicit withdrawn status immediately denies the candidate
and records a deletion deadline 23 hours and 45 minutes later. A paced Product
worker runs every five minutes so cleanup finishes before the provider's
24-hour maximum instead of only becoming due at that boundary. The cleanup removes
the cached source payload, description, facts, parties, URL, commission and Offer
candidates while retaining only the minimum source identity and audit evidence.
The Administrator surface at `/crm/inventario-externo` shows health, last sync,
sanitized errors, candidates, evidence state, refresh and due-cleanup controls.
It never renders the API key.

Product defaults both the API MLS confirmation and the external-payload
retention confirmation to false. `EASYBROKER_MLS_ACCESS_CONFIRMED` and
`EASYBROKER_RETENTION_PERMISSION_CONFIRMED` are explicit deployment gates, not
credentials; neither appears in the secret template. Until both are confirmed,
the real collaborator sync is fail-closed and makes no provider request.

## What has and has not been exercised

- **Certified fake/fixtures:** adapter contract, pagination, timeout/retry/rate
  limit, partial sync, lossless unknown mapping, strict service area, duplicate
  non-merging, all revalidation outcomes, refresh/use serialization, cache
  deletion, Admin authorization/redaction, and Product/Hermes boundaries.
- **EasyBroker staging:** an opt-in read-only smoke test exists under
  `live_external_inventory`; it is skipped unless the operator supplies a
  separate staging key and explicitly enables it. It is not a public CI gate.
- **Real provider/account:** not exercised and not claimed. The broad account
  key, API MLS plan, actual collaborator graph, action-specific authority,
  commission evidence, cache/retention permission, and production activation
  remain open gates in `docs/SANTIAGO_REAL_ESTATE_REVIEW.md`.

Current official-source findings and links are retained in
[`docs/research/easybroker-integration.md`](research/easybroker-integration.md).

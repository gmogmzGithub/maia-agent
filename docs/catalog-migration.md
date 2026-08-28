# Authoritative catalog migration

Migration `0020_authoritative_catalog` is the one-way runtime cut from the Stage 0
Property Document model to Product-owned catalog authority.

## Authority after the cut

- `properties` identifies physical real estate and holds reviewed physical facts.
- `catalog_listings` identifies one Organization or Collaborator publication and
  owns provenance, attribution, freshness, Availability, Publication State and
  Authority.
- `listing_offers` owns operation, authoritative price, currency, public price
  visibility, terms and offer availability.
- `listing_media` owns approved JPG/PNG/WebP references and cleanup state.
- `developments` and `unit_models` describe possible inventory without asserting
  that a physical unit exists.

Every customer-facing catalog use goes through `ListingEligibility` and
`CatalogProjection`. The legacy document artifact may contribute attributed
narrative, but its price and operation never bypass the current Offer.

## Upgrade and compatibility

On upgrade, each accepted legacy document creates at most one Draft Organization
Listing and one Offer. The migration preserves its checksum/version as provenance.
The pre-existing administrative acceptance is sufficient only for the same private
Maia/visit use that existed before the cut; public publication still requires
deterministic readiness. A Property without an accepted document remains Pending
and receives no invented Offer.

The legacy `/admin/properties` surface remains temporarily as an ingestion adapter.
Its accepted replacement updates physical facts and narrative provenance, but does
not rewrite an existing Offer's price or operation. Its Active/Inactive control is
a write-through compatibility projection implemented by
`SyncLegacyPropertyStatus`; the authoritative Listing and Offers change in the same
transaction. A disagreement fails closed at customer disclosure.

## Downgrade and removal

Downgrade removes only the new projections and columns. It keeps every legacy
Property Document/version and restores the earlier normalized-name constraint
without merging or deleting duplicate physical records; a deterministic key suffix
is used only when the old schema cannot represent two normalized names.

The compatibility path is scheduled for removal before a public site or
EasyBroker synchronization is introduced:

1. prove every catalog consumer reads `CatalogProjection`;
2. replace legacy status controls with Listing/Offer controls;
3. stop accepting commercial operation/price fields from Property Documents;
4. migrate any remaining narrative into an explicitly attributed source record;
5. remove `/admin/properties`, the mutable current-copy folder and legacy
   operation/price fields in a later reviewed migration.

Until those steps finish, there are not two editable commercial truths: new catalog
interfaces own commercial writes and the legacy adapter may only create the first
cut or update physical/narrative provenance.

## External gates

EasyBroker access, MLS scope, caching/retention/attribution, public-site launch,
presentation thresholds, media policy and any facts still marked Pending in the
Santiago Answers Needed register remain external decisions. The implementation
fails closed; it does not turn those unknowns into defaults.

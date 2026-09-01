---
status: accepted
---

# Store Listing Media behind private S3-compatible object storage

PostgreSQL remains authoritative for every Listing Media object's Organization,
Listing, checksum, provenance, publication authority and revocation state, while
the image bytes live in private S3-compatible object storage behind the small
`MediaStorage` interface. Sandbox runs the same S3 Adapter against a persistent
MinIO container and cloud environments point it at AWS S3; the public Site gets
neither credentials nor bucket access and Product streams an object only after
the normal publication and authority checks pass.
Sandbox uses a separate MinIO root identity only for bucket initialization and a
least-privilege Product identity limited to the originals and renditions buckets.

Repository photographs may exist only as explicit, public-safe Sandbox bootstrap
inputs and are imported through `MediaAdministration`; they are never runtime
storage or an alternate catalog. The filesystem Adapter is retained solely for
the one-time, read-only migration of the retired Compose volume. Direct public
buckets, presigned URLs and CDN access are deferred until they can preserve the
same immediate unpublication, revocation and cache-purge contract rather than
bypassing Product authority.

---
status: accepted
---

# Separate the Property Catalog from runtime truth

`src/properties` is Product's public-safe, source-controlled Property Catalog, while
PostgreSQL and accepted immutable artifacts remain runtime truth. Property Documents
from the catalog or a manual administrative submission must pass through the same
Product-owned validation and acceptance boundary; Hermes continues to request facts
through typed Product tools and never reads the catalog directly. Consequently, a
deployed administrative action may update durable runtime state but does not pretend
to modify source files inside an immutable application image. Crawling or synchronizing
with EasyBroker is outside the current scope.

For the local Compose stage only, Product may receive a writable bind mount of the
host Property Catalog. An accepted submission writes the current document to
`src/properties/{property_id}.md`; a later fact edit replaces that catalog copy while
accepted artifact versions remain immutable. Deployment correctness never depends on
the catalog mount being writable or present.

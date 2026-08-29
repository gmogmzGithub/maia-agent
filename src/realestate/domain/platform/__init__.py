"""The managed platform: several Brokerage Organizations, one product.

Everything in :mod:`realestate.domain` above this package answers a question
*inside* one Organization. This package answers the questions that only exist
because there is more than one:

* :mod:`~realestate.domain.platform.scoping` — which tables belong to an
  Organization, which deliberately do not, and which columns must never leave;
* :mod:`~realestate.domain.platform.provisioning` — bringing an Organization
  into existence, and taking it out, one resumable and reversible step at a
  time;
* :mod:`~realestate.domain.platform.configuration` — the versioned document
  that says how one Organization operates;
* :mod:`~realestate.domain.platform.credentials` — resolving one Organization's
  provider access from a reference, never from a shared default;
* :mod:`~realestate.domain.platform.entitlements` — what an Organization is
  entitled to do, and the refusal when it is not;
* :mod:`~realestate.domain.platform.support` — temporary, explained, expiring
  internal access, and nothing wider;
* :mod:`~realestate.domain.platform.routing` — which Organization an inbound
  message, request or hostname belongs to;
* :mod:`~realestate.domain.platform.usage` — what the platform counts;
* :mod:`~realestate.domain.platform.imports` — a new Organization's existing
  records, dry-run first;
* :mod:`~realestate.domain.platform.lifecycle` — export and deletion, bounded
  by retention.

The one rule the whole package exists to protect: **no operation reaches across
Organizations.** Not for support convenience, not for a shared cache, not for a
worker's batch query, and not for an aggregate report.
"""

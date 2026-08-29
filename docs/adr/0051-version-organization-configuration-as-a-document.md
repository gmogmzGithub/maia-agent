---
status: accepted
---

# Version Organization configuration as a document

How each Brokerage Organization operates — brand, service area, bookable hours,
default Advisor, channel identifiers, expected integrations and permitted
operational limits — will be recorded as immutable, checksummed, numbered
document versions with a required written reason, not as editable settings rows or
process environment variables. Recording an identical document is a no-op, so a
restarted provisioning run is idempotent, and a rollback records the previous
document again. The process environment remains authoritative for exactly one
named founding Organization as a bounded bootstrap; every other Organization reads
its document or is refused, because an Organization silently inheriting settings
written for a different brokerage is indistinguishable from correct behaviour until
it is not.

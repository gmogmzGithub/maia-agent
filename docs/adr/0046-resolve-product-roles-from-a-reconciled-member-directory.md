---
status: accepted
---

# Resolve product roles from a reconciled member directory

Authentication for the operational web surface stays what it was: HTTP Basic
against the credentials in the local environment. Authorization stops being
implied by it. Every commercial entry point takes an Actor resolved from an
`organization_members` row that names one Brokerage Organization and one role,
and a credential that authenticates but has no active member row is refused with
an explanation rather than granted whatever the surface exposes.

PostgreSQL is the system of record for membership, because Opportunities,
assignments and Next Actions reference those rows. Configuration only solves the
bootstrap: somebody must be an Organization Administrator before anybody can
create one, and the alternative — treating the first credential that
authenticates as privileged — is exactly the ambiguity this cut removes. Three
explicit non-secret values name the initial team, and Product reconciles them
into the table at startup, idempotently and with an audit event. A login that
disappears from configuration is deactivated, never deleted, so history stays
readable and a `RESTRICT` foreign key is never violated.

Authority follows the role; eligibility to own an Opportunity is a separate
`advises` flag. That is how "Santiago initially has both roles" is expressed
without inventing a third role whose meaning nobody could state. Product's own
deterministic work — intake, assignment, dormancy, retention — acts as an
organization-scoped Actor that is deliberately not an administrator, so it can
reach work nobody owns yet and still cannot mark an Opportunity Won (ADR-0032).

Self-service team management, per-organization credentials, and Advisor Absences
are deferred. So is any mapping from a WhatsApp phone number to an Organization:
the single-Organization MVP resolves it by slug in one place, which is where a
real mapping will go.

# Runbook: a suspected cross-organization incident

Treat "Organization A may have seen Organization B's data" as the highest-severity
class of incident this product has. It is the one promise the managed platform is
sold on.

## 1. Stop the bleeding before diagnosing

If the suspected path is inbound (a message, a callback, a website request):

```
POST /platform/organizations/{id}/suspend
{"reason": "Incidente de aislamiento en investigación, 12 de marzo 14:20.",
 "command_key": "suspend-acme-incident-2026-03-12"}
```

Suspending stops logins and every background pass for that Organization while
leaving channels bound, credentials registered and members listed — so resuming is
one status change, not a re-provisioning.

If the suspected path is a *channel binding* pointed at the wrong Organization,
retire the binding rather than suspending: a suspended Organization still owns the
number.

## 2. Establish what actually crossed

The audit trail is organization-scoped since Stage 9, which is what makes this
answerable:

```sql
SELECT occurred_at, organization_id, actor_type, actor_id, action,
       subject_type, subject_id
FROM audit_events
WHERE occurred_at > :since
ORDER BY occurred_at;
```

Then, for each suspect table, whether any row names the wrong Organization:

```sql
SELECT c.organization_id AS conversation_org, i.organization_id AS inbox_org,
       count(*)
FROM inbox_messages i JOIN conversations c ON c.id = i.conversation_id
GROUP BY 1, 2 HAVING c.organization_id <> i.organization_id;
```

A non-empty result on a query like that is the incident. An empty one across every
parent/child pair means the columns and the composite foreign keys agree, and the
exposure — if there was one — was a *read* rather than a write.

Also check the support grants: `GET /platform/support-access`. A grant nobody
remembers requesting is its own incident.

## 3. Decide whether it was a read or a write

They need different responses:

- **a write** (a row naming the wrong Organization) is a data-integrity incident.
  Do not "fix" the column. Export both Organizations first —
  `POST /platform/organizations/{id}/export` — so the state before your repair is
  preserved with a checksum;
- **a read** (a query that returned another Organization's rows to a surface) left
  no trace in the data. The evidence is in the logs and in whatever the user saw.
  Reconstruct from the request log and say so plainly rather than implying you
  know less than you do.

## 4. Notify

Both Organizations, not just the one that complained. The Organization whose data
may have been seen has the stronger claim to know, and they are the one who will
not have called.

Say what crossed, when, to whom, whether it was read or written, and what stops
it now. Mexican Spanish, in writing, from a named person.

## 5. Close the hole in the product, not in the incident

Every cross-organization defect should end with a failing test that would have
caught it, added to `tests/test_platform_isolation.py`. The isolation matrix in
that file is the artefact; a fix without a row added to it will be reintroduced.

If the defect was a table missing from the scoping registry, that is also a bug in
the registry test, and both get fixed.

## 6. Resume

```
POST /platform/organizations/{id}/resume
{"reason": "Incidente cerrado; se corrigió la asignación del canal y se añadió la prueba.",
 "command_key": "resume-acme-incident-2026-03-12"}
```

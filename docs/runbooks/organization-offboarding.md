# Runbook: offboarding a Brokerage Organization

Three separate decisions that are easy to conflate and expensive to conflate:

1. **stop serving them** — `deprovision`;
2. **give them their data** — `export`;
3. **remove their data** — `delete`.

Do them in that order, and get the second one confirmed received before the third.

## 0. Before anything

Get, in writing:

- who is asking, and whether they can bind the brokerage;
- the effective date service stops;
- whether they want an export, and where it should go;
- whether they are asking for deletion, and of what — their conversations, or
  everything;
- whether anything obliges us to keep data anyway: an open dispute, a contractual
  term, a legal request.

That last one becomes a retention hold *before* you touch deletion:

```
POST /platform/organizations/{id}/retention-holds
{"basis": "Contract",
 "authority": "Cláusula 9 del contrato firmado el 3 de marzo de 2026",
 "description": "Conservar el registro comercial 12 meses tras la terminación.",
 "expires_at": "2027-03-03T00:00:00Z"}
```

A hold with an expiry releases itself. One without needs a human, which is the
right default for an obligation nobody has dated.

## 1. Stop serving them

```
POST /platform/organizations/{id}/deprovision
{"reason": "Terminación acordada con Acme, efectiva el 31 de marzo de 2026.",
 "command_key": "deprovision-acme-2026-03-31"}
```

This retires the channel bindings, revokes the secret references, deactivates the
members and leaves the Organization `Deprovisioned`. **Their data is still
there** — the response says so explicitly, because that is the sentence people
misread.

Note what this means operationally: their WhatsApp number stops resolving, so
messages to it are refused and logged rather than answered. Tell them, so they can
redirect their number before the date rather than after.

## 2. Export

```
POST /platform/organizations/{id}/export
{"reason": "Entrega de información a Acme por terminación de servicio.",
 "command_key": "export-acme-2026-03-31"}
```

You get an artifact path, a sha256, a byte size, per-table row counts, and the
withheld columns *by name*. Send them the checksum with the file and keep the
counts: they are how anybody later answers "was the export complete".

Read the withheld list before you send it and be ready to explain it: the
pseudonymisation salt, live token digests, credential fingerprints and Hermes
session handles are withheld because including them would make the
pseudonymisation reversible or hand over a live capability. This is not us
holding something back from them; it is us not shipping a key.

**Get written confirmation of receipt before step 3.** Deletion is not reversible
and "we thought they had it" is not a position you want to be in.

## 3. Delete

```
POST /platform/organizations/{id}/delete
{"scope": "Everything",
 "reason": "Solicitud de eliminación de Acme, confirmada por escrito el 2 de abril.",
 "command_key": "delete-acme-2026-04-02"}
```

`OperationalContent` removes conversations, drafts, sessions and saved selections
and keeps the commercial record. `Everything` removes the commercial record too.

If a retention hold is live, the request is **refused** and the response quotes
the hold's authority. There is no partial deletion — a half-deleted Organization
satisfies neither the request nor the obligation. Release the hold, with a reason,
or tell the customer why you cannot comply yet.

What survives whatever the scope: the Organization row, the export and deletion
records, the retention holds, and the audit trail. An erasure nobody can prove
happened is not a service.

Read the response's `deleted_tables` and `retained_rows`. A table you expected in
one list appearing in the other is worth understanding before you close the
ticket.

## 4. Close

- confirm to the customer, in writing, what was exported, what was deleted, and
  what was retained and why;
- if the number was ours, retire it from the account after the redirect period;
- if a hold remains, diary its expiry. A hold nobody revisits is a data-retention
  problem wearing a compliance costume.

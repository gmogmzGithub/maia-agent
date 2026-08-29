# Runbook: rotating a Brokerage Organization's credential

Product never holds a credential's value. It holds a **reference** — the name of
the place the value lives — and a fingerprint of what that name last resolved to.
Rotation therefore has two halves in two systems, and the order matters.

## The order

1. **Write the new value into the secret store, under a new name.**
   `ACME_META_ACCESS_TOKEN_2` next to `ACME_META_ACCESS_TOKEN`. Do not overwrite
   the old name yet: if the new value is wrong you want the old one still
   reachable.

2. **Point Product at the new name.**

   ```
   PUT /platform/organizations/{id}/credentials
   X-Platform-Operator: <your login>
   X-Reason: Rotación programada del token de Meta de Acme, 12 de marzo.
   {"provider": "MetaWhatsApp", "reference": "ACME_META_ACCESS_TOKEN_2"}
   ```

   The outgoing reference becomes `Rotating` and is kept; the new one becomes
   `Active`. Both rows survive, so the change is provable. The response's
   `resolves` tells you whether the new *name* resolves — not whether Meta accepts
   the value.

3. **Prove the provider accepts it.** Send one real message, read one calendar,
   run one search. Product cannot do this for you and does not pretend to.

4. **Remove the old value from the secret store** once the new one has been in
   use long enough that you would have noticed. The `Rotating` row remains as
   history; its name no longer resolving is exactly the state you want.

## If the new credential is rejected

Point the reference back at the old name with a second `PUT`. The old row is
reused and becomes `Active` again — the module recognises a reference it has seen
before rather than accumulating duplicates.

Do **not** delete the reference and leave the Organization with none: an
Organization with no reference is refused with "no hay credencial registrada",
which is correct behaviour and reads to a customer as an outage.

## What rotation does not do

- it does not fall back to another Organization's credential, ever. A reference
  that resolves to nothing is a named refusal
  (`UnresolvableCredential`), deliberately distinct from "nobody configured it";
- it does not verify the credential. See step 3;
- it does not touch the founding Organization's process-environment path. If the
  founding Organization is still resolving `MetaWhatsApp` from
  `META_ACCESS_TOKEN` via the bootstrap, rotating means changing that variable
  and restarting — or, better, giving it a real reference so it stops being
  special.

## Verifying afterwards

`/crm/plataforma` shows the customer their own references and the date of the last
rotation. Check it reads the way you would want it to read if you were them.

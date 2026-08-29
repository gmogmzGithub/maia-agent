# Runbook: supporting a Brokerage Organization

## The rule

You cannot read a customer's records with the platform credential. It provisions,
configures, entitles and counts; it returns no Contact, Opportunity or message.

To read their records you need a support grant, which creates an ordinary
read-only member row inside one Organization, expires within eight hours, and
appears on the customer's own `/crm/plataforma` page with your reason on it.

Assume the customer will read that page. Write the reason for them, not for us.

## Getting access

```
POST /platform/organizations/{id}/support-access
X-Platform-Operator: <your login>
```

```json
{
  "engineer_login": "gerardo",
  "reason": "Acme reporta que una cita confirmada no aparece en la agenda de Ana.",
  "request_reference": "Llamada del 12 de marzo, 10:15",
  "hours": 2,
  "command_key": "support-acme-2026-03-12-a"
}
```

You get `soporte:gerardo` as a login in that Organization. Authenticate to the CRM
with it exactly as an Advisor would.

Ask for the shortest window that will do. Two hours is the default because the
common case is looking at one thing. A longer investigation asks again, which
leaves a second dated row — that is the intended cost, not an obstacle.

## What you can and cannot do

You are an Advisor with `advises=False`. You can read; you cannot mark an
Opportunity Won, publish a Listing, change an entitlement or send a message. If
the fix requires a mutation, the customer's Administrator performs it — with you
on the call if necessary. There is no write scope and adding one is an ADR, not a
patch.

## Finishing

Revoke as soon as you are done rather than letting it lapse:

```
POST /platform/support-access/{grant_id}/revoke
{"reason": "Diagnóstico terminado; el problema era la ausencia registrada.",
 "command_key": "revoke-acme-2026-03-12-a"}
```

Then write what you found where the customer can see it. A grant with a use count
of zero is evidence the access was not needed; a grant used forty times with no
follow-up note is a question somebody will ask.

## Common diagnoses that do *not* need a grant

Check these first — most of them are visible from the platform surface alone:

| Symptom | Look at |
|---|---|
| "Messages stopped arriving" | The webhook's `unroutable` count in the logs, and `GET /platform/organizations` for the Organization's status. An unbound or retired channel binding refuses by design |
| "Nobody can log in" | Organization status. `Suspended` refuses every login with a Spanish sentence |
| "We cannot send campaigns" | `GET /platform/organizations/{id}/entitlements`. `NotRecorded` and `Disabled` are different answers |
| "It says we reached a limit" | The same call, plus `GET .../usage`. A ceiling is enforced against the last hourly refresh, so a customer just over the line may be reading a stale number |
| "The integration broke" | The reference's `resolves` flag. `false` means the secret is gone from the store; `true` means the provider is rejecting it and the problem is on their side of the boundary |
| "Our website shows nothing" | The `PublicSiteHost` binding. An unbound hostname answers 503 rather than an empty catalog, on purpose |

## What to say about isolation

If a customer asks whether Maia's team can read their data: yes, with a grant that
they can see, that expires, and that names a reason. No, not otherwise — there is
no account that reads every Organization. Do not soften either half.

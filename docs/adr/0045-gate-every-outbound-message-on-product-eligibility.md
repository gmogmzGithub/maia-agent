---
status: accepted
---

# Gate every outbound message on Product eligibility

Product decides whether a message **to a Contact** may be sent before it can
exist as an Outbox row. The decision belongs to one module with one entry point:

```text
OutboundMessaging.request(intent) -> Queued | Denied
```

Outbox keeps the responsibility it already had — durable persistence, claiming,
retries, delivery reconciliation — and gains none of this policy. The gate sits
above it and is the only caller of the staging path, so no product code can
create an outbound message without a decision recorded against it.

The scope is customer-facing WhatsApp. Telegram notices to the Broker and
Administrator are internal operational traffic on a private channel, not
outreach to a Contact, and they do not pass through the gate. Consent,
suppression and the customer-service window are all Contact-facing concepts;
applying them to a notification the operation sends itself would be meaningless.

## The intent carries initiation, not a kind

Proactivity is a property of *why a message is being sent*, and it cannot be
recovered by inspecting the row that results. An `OutboxKind` describes what was
delivered; two messages of the same kind can be an answer to something the
Contact just wrote or the operation reaching out on a schedule. Classifying by
kind would silently mis-authorise whichever case the enumeration did not
anticipate.

An `OutboundIntent` therefore states:

- `initiation`: `Reactive` or `BusinessInitiated`;
- `trigger_inbox_ids`: the concrete inbound messages a reactive send answers;
- `purpose`: the business reason, which selects the WhatsApp consent category;
- `requested_at`: when the caller asked, so the decision is reproducible;
- `template_id` and `template_category` when a template is being used.

Neither `initiation` nor `trigger_inbox_ids` is trusted on its own. A Reactive
intent must carry at least one trigger, every trigger must belong to the same
Conversation, and the gate computes the customer-service window from persisted
inbound messages.

Be precise about what this does and does not guarantee. A proven Reactive intent
skips the outreach rules — suppression, consent, stop-on-reply — because answering
the concrete messages somebody just wrote is not outreach. The window check
still applies: a Contact who has not written in twenty-four hours cannot receive
free-form text, and the declaration cannot manufacture a window.

## Every existing outbound path is classified

| Purpose | Initiation | Category | Call site |
|---|---|---|---|
| `AgentReply` | Reactive | Service | `worker/whatsapp.py` settlement |
| `AppointmentConfirmation` | Reactive | Utility | `worker/whatsapp.py` settlement |
| `AppointmentNeedsReview` | Reactive | Utility | `worker/whatsapp.py` settlement |
| `ProcessingFailureNotice` | Reactive | Service | `worker/whatsapp.py` failure |
| `AppointmentCancellation` | Reactive | Utility | `domain/appointments.py` |
| `AppointmentResolution` | BusinessInitiated | Utility | `domain/admin_work.py` |
| `AppointmentNeedsReview` | BusinessInitiated | Utility | `domain/admin_work.py` recovery |
| `LeadFollowUp` | BusinessInitiated | Marketing | `domain/followups.py` |

A deterministic appointment notice replaces the Model's draft during settlement,
so one call site legitimately produces three different purposes; which one is
decided where the body is chosen, not inferred afterwards from the Outbox kind.

`AppointmentNeedsReview` previously reached the Outbox as a bare string that was
not even a member of `OutboxKind`. `AppointmentResolution` carried its own
private copy of the 24-hour window check. Both now go through the gate, and the
duplicated window rule is deleted rather than kept in parallel.

## Allowed and denied

A message is queued only when all of the following hold. Anything else is
denied, including anything the gate cannot positively establish.

For every message: the Conversation resolves to a Lead, and any supplied trigger
messages belong to that Conversation.

For business-initiated messages, in this order: no active Suppression Record;
for purposes that stop on reply, the Contact has not written since Product last
wrote; and for the Marketing category, the most recent Consent Record is
`Granted`.

For every message: either the 24-hour customer-service window is open, or an
approved template is supplied whose category matches the purpose. A supplied
template is validated whether or not the window is open.

Denial reasons are stable codes — including `MissingReactiveTrigger`,
`UntrustedTrigger`, `Suppressed`, `ContactReplied`, `FollowUpPolicyInactive`,
`MarketingConsentMissing`, `ServiceWindowClosed`,
`TemplateMetadataIncomplete`, `TemplateNotApproved`,
`TemplateCategoryMismatch`, and `EligibilityEvidenceMissing` — because they are
persisted or audited and will be reported on.

## Fail closed

The gate never guesses in the permissive direction.

The approved-template registry is empty and Product has no path that adds to
it: templates are approved by Meta against a named WhatsApp Business Account,
and inventing an entry would authorise a send the platform will reject. There is
likewise no path that records a `Granted` marketing consent, because capturing
it needs a real form, a privacy notice, and Mexican legal review that has not
happened.

The consequence is deliberate: **every proactive follow-up is currently denied.**
The follow-up policy has an additional explicit inactive gate because the
Opportunity, Next Action, appointment/rejection awareness and day-28 Dormant
transition accepted in ADR-0021 do not exist yet. Consent or template
configuration cannot accidentally turn the partial cadence on.

Templates are structural for that policy rather than a fallback. The window is
measured from the Contact's last message and the cadence's earliest day is a day
later, so no follow-up can ever be free-form. The policy names the template each
day would use, and Product can dispatch a registered template through Meta's
template payload. Real template approval, consent capture, the missing
commercial states, explicit policy activation and live provider verification
are all still required.

Product does have a production path for the opposite direction. A Contact whose
whole message is an unambiguous opt-out gets a Suppression Record and a
`Revoked` marketing Consent Record, written in the same transaction that
persists their message, with an audit event. Matching is deterministic Product
policy on the exact normalised message, never model judgement, and it stops the
operation from reaching out without gagging Product while the Contact is
actively writing.

## Atomicity

`request` does not commit. The eligibility decision, the Outbox row, and the
caller's own record of the attempt land in one transaction or none of them do.

This closes a real hole: the follow-up path used to commit the Outbox row and
then write its own tracking row, so an interruption between the two could leave
a message queued that nothing recorded, or — with the tracking row absent — a
day that looked unhandled. A queued message no decision authorised, and an
attempt recorded as sent that was never staged, are both lies about what
happened.

Concurrency uses both serialization and constraints. Request, delivery, and
authenticated Inbox acceptance lock the same Lead row, so a reply or opt-out and
an outbound send acquire a causal order. Unique constraints still provide the
final idempotency guarantee: one `Queued` decision per intent key, one Outbox row
per key, one follow-up per cycle/day, and one active suppression per Lead/channel.

Request-time approval is not a promise to send later. Immediately before Meta,
the worker re-loads the Queued decision, locks the Lead, and rechecks suppression,
reply state, consent, template registration/category and the current service
window. A failure marks the row `Failed` with a
`WithholdOutboundAtDelivery` audit event; no provider call occurs. The lock is
held through Meta's answer when delivery is allowed.

Revision 0011 quarantines pre-gate Pending rows as `Failed`, ambiguous legacy
Sending rows as `DeliveryUnknown`, and records one audit event per row. It also
converts the legacy follow-up opt-out flag into an active Suppression Record and
a revoked Marketing Consent Record. Downgrade intentionally never reactivates
those rows.

## Not in scope

Organisation scoping (ADR-0019) is not addressed here. Adding an `organizations`
table that only these three tables referenced would be decoration: Leads,
Conversations, Appointments, and Properties would still be implicitly global,
and the claim to have scoped business data would be false. Scoping belongs to
the commercial-identity cut that introduces Contact, Advisor, and Opportunity,
where it can be applied coherently.

Also deferred: revoking a suppression, capturing marketing consent, registering
real approved templates, activating the state-driven follow-up policy, live
template delivery verification, and surfacing denied decisions to an operator.
Denied decisions are queryable but no CRM surface reads them yet.

## Sequencing this constrains

Public catalog search must not be built on the current `properties` table. A
Property, its Listings, and each Listing's Offers — with Availability,
Publication State and Authority as independent facts (ADR-0025, ADR-0030) — come
first. Projecting today's single-Property columns into a search index would
create a catalog that has to be dismantled when those distinctions arrive.

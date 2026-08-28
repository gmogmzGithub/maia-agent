---
status: accepted
---

# Separate internal operational alerts from customer messaging

ADR-0045 put every message **to a Contact** behind one eligibility gate and drew
a line the other way too: Telegram notices to the Broker and Administrator are
internal operational traffic, not outreach, and do not pass through it. Consent,
suppression and the customer-service window are Contact-facing concepts, and
applying them to a notification the operation sends itself would be meaningless.

Stage 3 needs that internal channel to become durable rather than a direct call
at each site, because two of its promises are about time. A human-handoff
request alerts the responsible Advisor immediately and the Organization
Administrator after fifteen minutes — and "after fifteen minutes, once" has to
survive a restart.

So an `internal_alerts` row is written in the transaction that caused it, and
delivery is a separate claimable step with a lease. The escalation stamp and the
alert row commit together: a process that dies before the commit re-derives the
same due request, and one that dies after it finds nothing due. No timer, no
scheduler, no in-memory state.

## Three properties differ deliberately from the Outbox

**At-least-once, not at-most-once.** `dedupe_key` makes creation idempotent, and
a crash between the Telegram send and the stamp can repeat one internal notice.
For an operator's alert a duplicate beats a miss. P-036 makes the opposite trade
for a Contact, where a duplicate message is worse than silence — and that
asymmetry is the reason these are two mechanisms rather than one with a flag.

**Undeliverable is not lost.** A recipient with no configured chat produces an
`Undeliverable` alert that stays visible in the CRM, and the Administrators are
told the immediate notice could not be delivered. A missing configuration value
must not make a customer's request for help disappear.

**Addressing is a role, not a list.** An alert names one member or every
Organization Administrator. The Stage 0 `TELEGRAM_ADMIN_IDS` remain as the
fallback for an "every Administrator" alert whose members have no per-person
chat configured, so an existing local setup keeps receiving escalations.

## What still goes through the gate

Everything a Contact reads. The warm handoff acknowledgement is the case worth
naming: it is Contact-facing, so it is staged through
`OutboundMessaging.request` as a Reactive service message answering what they
just wrote. Product sends it rather than the Model for two reasons — the wording
must not become a service-level commitment because one run phrased it
confidently, and the request has just paused Maia, so the draft that turn
produces is withheld. Without Product owning the send, the Contact would hear
nothing at the exact moment they asked for help.

## Not in scope

Alert preferences, digests, quiet hours, per-kind routing and any second
internal transport. There is one channel, one recipient rule, and an
acknowledgement an operator can press.

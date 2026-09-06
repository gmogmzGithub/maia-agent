---
status: accepted
---

# Require a phone claim before saving a Listing

Product requires a Phone Claim before the first Listing enters a Saved
Collection. The claim is stored with the Organization-scoped collection so the
Brokerage can retain the selection history, while the opaque HttpOnly browser
cookie remains the only authority to read or change that collection. Entering a
phone does not create an account, resolve a Contact, prove ownership, or permit
recovery by phone alone; only the existing verified WhatsApp handoff may link the
collection to a Contact and make it recoverable across devices. This supersedes
ADR-0040's anonymous-first rule because unattributed hearts did not meet the
product's lead-history requirement.

Existing anonymous collections may still be read and their items removed so a
visitor never loses deletion control, but they require a Phone Claim before
another Listing can be added or a selection shared. A rejected mutation is a
final state, not an offline operation: only transport and server availability
failures may enter the browser retry queue, and each new toggle receives a new
idempotency key.

## Considered options

Creating or resolving a Contact from a typed phone was rejected because the
public form has not authenticated that identity and could join one person's
commercial history to another's. Requiring a completed WhatsApp handoff before
the first heart was rejected as unnecessary friction for same-browser history.
Restoring collections from a phone alone was rejected for the same disclosure
reason; cross-device recovery remains a verified-channel operation.

## Consequences

The stored Phone Claim is personal data but remains explicitly unverified. It is
never returned to the browser, placed in a cookie or URL, copied into analytics,
or used as a Contact lookup key. Deleting a collection clears the claim, and an
eventual verified WhatsApp protection replaces it with the Contact relationship.

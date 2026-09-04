---
status: accepted
---

# Unify customer messages behind channel-specific Meta edges

WhatsApp, Facebook Messenger and Instagram Messaging enter Product through
separate signed webhook adapters and leave through separate provider clients,
then share one durable Inbox, commercial intake, Hermes session, authorization,
Outbound Eligibility and Outbox pipeline. A channel adapter projects provider
payloads into a customer message carrying the channel, receiving account,
provider message id and provider user id. Product persists those facts before it
acknowledges Meta. An unbound WhatsApp number, Facebook Page or Instagram
professional account is refused rather than assigned to a default Brokerage
Organization.

A Channel Identity is scoped by `(Organization, channel, receiving account,
provider user id)`. Messenger PSIDs and Instagram-scoped user ids are not global
person identifiers, and Product never merges Contacts merely because values or
profile details resemble each other across channels. A future cross-channel
link requires explicit verified evidence and its own decision. The historical
database column names `wa_id`, `phone_number_id`, `wamid`, `from_wa_id` and
`to_wa_id` remain physical migration compatibility details; domain code uses
provider-neutral names.

Each Organization records a separate active binding and credential reference
for `MetaMessenger` and `MetaInstagram`. Secret material remains outside
PostgreSQL. The founding Organization may bootstrap those references and account
ids from its process environment, under the same bounded exception used by
WhatsApp; no other Organization inherits them. Each webhook can use its own
configured Meta app secret, with the existing shared app secret as an explicit
fallback, and the three paths share the configured webhook verify token.

Delivery resolves the credential only after matching the Conversation's exact
receiving account to an active Organization binding. Replacing an active Page
or Instagram account therefore cannot redirect an older Conversation through a
new account whose provider-scoped user identifiers mean something different.

Reactive free-form replies use the existing 24-hour Customer Service Window and
the same fail-closed delivery revalidation. WhatsApp templates remain WhatsApp
only. Messenger or Instagram business-initiated delivery outside the open window
is withheld until Product represents and verifies the provider-specific tag or
permission that authorizes it. Provider delivery edges retain the existing
three-way outcome: conclusive success, conclusive failure, or ambiguous delivery
that is quarantined rather than replayed.

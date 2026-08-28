---
status: accepted
---

# Use progressive server-backed Saved Collections

Visitors may save Listings immediately without an account. Product holds the
Saved Collection authoritatively on the server and identifies an anonymous browser
with an opaque, first-party Secure, HttpOnly, SameSite cookie containing no
personal data. A local cache provides immediate rendering and offline queuing but
is not treated as durable truth.

The interface shows `Guardada` only after server confirmation and
`Pendiente de guardar` while an operation is offline or retrying. Mutations are
idempotent, retried, deduplicated, and reconciled after reconnection. An unavailable
Listing remains visibly marked in the collection instead of disappearing silently.

Customers may explicitly protect and synchronize the collection through their
verified WhatsApp Contact without creating a password-based account. Starting a
conversation does not itself authorize linking the anonymous collection or
sharing its contents with Maia.

The save action combines a heart with `Guardar`, and the collection is named `Mis
propiedades guardadas`. After the first confirmed save, Product may non-blockingly
offer `Proteger con WhatsApp`; verification through the official channel permits
recovery across devices. Product states plainly that clearing an unprotected
browser loses access and never uses fingerprinting as a substitute. Anonymous
collections expire after 12 months without activity.

Unavailable Listings remain marked `Ya no disponible` with removal and authorized
alternative actions. A customer may create and revoke an opaque read-only Shared
Selection containing no identity or conversations. Sharing saved Listings with
Maia requires the separate explicit `Hablar con Maia sobre mis propiedades
guardadas` action.

Protection merges and deduplicates the anonymous browser collection with any
existing Protected Saved Collection for the verified Contact. Shared Selections
are fixed snapshots rather than live views; recipients may copy Listings into
their own collections but cannot modify the sender's snapshot. Sharing with Maia
is likewise point-in-time access, never permanent visibility into future saves.

The MVP provides one collection without folders. Unavailable items may offer
deterministic `Ver propiedades similares` and explicit `Preguntarle a Maia`
actions without authorizing outreach. Emptying a collection does not delete or
change Contact, Conversation, Opportunity, consent, or other independently
retained business records.

---
status: accepted
---

# Store secret references, never secret material

Each Brokerage Organization's provider access will be stored as a *reference* —
the name of an environment variable or a secret-manager path — with a salted
fingerprint of what that name last resolved to, and never as the credential
itself. Resolution consults only the asking Organization's own Active reference,
then its Rotating one; it never falls back to another Organization's value, to a
platform default, or to an empty string a client library would send anonymously.
Rotation appends rather than edits, so a change is provable without the value
being readable, and the fingerprint is withheld from exports because a digest is a
confirmation oracle. The consequence accepted here is that Product cannot verify a
credential works — only the provider can — so provisioning reports whether a
reference resolves, never whether the integration will succeed.

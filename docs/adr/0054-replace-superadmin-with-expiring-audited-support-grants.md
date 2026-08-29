---
status: accepted
---

# Replace the superadmin with expiring, audited support grants

Internal support will reach a customer's records only through a grant that creates
an ordinary read-only member row inside one Brokerage Organization, with a written
reason, an optional request reference, a maximum eight-hour expiry checked at login
resolution rather than by a sweep, and a recorded use count. There is no account
that can read every Organization: platform administration authenticates with its
own credential, writes history as `Platform`, and is refused by every commercial,
catalog, conversation and analytics surface. The exposure this accepts and states
plainly is that an internal engineer holding the platform credential can grant
themselves access to any Organization; what they cannot do is read it without
leaving a dated row the customer can see on their own surface, which is the
property a customer can actually be promised.

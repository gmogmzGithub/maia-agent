---
status: accepted
---

# Propagate direct SQL market corrections from PostgreSQL

Market Sale Records and Purchase Profiles will have no correction interface;
authorized operators correct their current values directly with SQL. PostgreSQL
triggers therefore preserve the prior and replacement values with the database
role and time, then enqueue a new idempotent Market Contribution in the same
transaction. The central projector reads that contribution and replaces the
current shared analytical version while retaining its earlier version. This
keeps the Organization record and Shared Market Dataset consistent even when the
Product application did not execute the write, and avoids the unsafe operating
procedure of editing both copies manually.

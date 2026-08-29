---
status: accepted
---

# Onboard and offboard Organizations as resumable, reversible runs

Provisioning, initial data import, export and deletion will each be recorded as a
run of individually idempotent, individually reversible named steps rather than as
one procedure. An Organization is created `Provisioning` and becomes usable only
in the final step, so a half-built one cannot answer a customer; re-running a
command key resumes from the first incomplete step; rollback walks the steps
backwards without deleting the configuration, entitlement or audit history that
explains what happened. An import must dry-run the identical source checksum
first, records a per-record finding with the source's own reference, creates only
unreviewed physical Properties, and rolls back by stored identifier rather than by
time window. Deletion refuses outright when a retention hold is live instead of
partially complying, and never removes the evidence that it ran.

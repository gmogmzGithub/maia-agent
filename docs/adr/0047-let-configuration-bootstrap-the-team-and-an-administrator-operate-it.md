---
status: accepted
---

# Let configuration bootstrap the team and an Administrator operate it

ADR-0046 resolved authority to an `organization_members` row and solved the
bootstrap with three explicit non-secret configuration values reconciled at
startup. It also deferred self-service team management, which is the capability
Larevia now needs: an Organization Administrator adds Advisors, gives each one
an authoritative calendar and an alert channel, names the assignment fallback,
and takes somebody's access away.

Those two mechanisms conflict in one specific way, and the conflict is not
theoretical. Reconciliation deactivates a login that has left the configuration
— deliberately, so that removing somebody from `.env` actually removes their
access. Applied to *every* row, that rule deletes the team an Administrator just
built on the next restart.

So a member row records who provisioned it, and reconciliation governs only its
own. `provisioned_by` is `Configuration` or `Administrator`. A login that
appears in configuration becomes configuration-owned from then on, whoever
created the row first; a login that never appears there is the Administrator's
and survives every restart.

Two narrower rules follow from the same principle.

**Configuration supplies, it does not clear.** An Advisor's calendar and alert
channel can be set from either side. Reconciliation writes them when the
configuration names them and leaves them alone when it does not, because the
absence of an environment variable is not an instruction to erase a value
somebody typed into the CRM. The alternative — treating an unset variable as
"clear this" — would silently make an Advisor unbookable every time the
operator trimmed their `.env`.

**The default Advisor stays singular.** It is named in one place and a partial
unique index permits one per Organization, so both paths clear the outgoing
fallback before setting the new one. Deactivating the default Advisor clears the
flag as well: leaving it would let the assignment rule choose somebody who can
no longer log in, and the Assignment Queue would report a reason that was not
the real one.

## What an Administrator may not do

Two refusals are invariants rather than policy that a later stage will relax.

The last active Administrator cannot be deactivated. An Organization with no
administrator has no path back: absences, assignments, Property acceptance and
team management are all Administrator-only, and the remedy would be editing
configuration and restarting.

An Advisor cannot be made ineligible to own Opportunities while remaining an
Advisor. `ck_organization_members_advisor_advises` already forbids storing it;
refusing it here turns a constraint violation into a sentence that says to
change the role or deactivate the person.

## Not in scope

Product still does not mint credentials. Authentication remains HTTP Basic
against the configured operational accounts, so adding a member grants authority
to a login that somebody else has to make able to authenticate. Creating the row
first is legitimate and the ordering is the operator's, which is why
`AddMember` records rather than validates.

Per-organization credentials, invitations, password management and any notion of
a session remain deferred, as does role-granular permission beyond the two
product roles.

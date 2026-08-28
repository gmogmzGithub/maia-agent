---
status: accepted
---

# Keep human and Maia replies on the official channel

Human Advisors will handle customer WhatsApp conversations through the CRM using
the Brokerage Organization's official channel rather than moving the primary
relationship to personal numbers. An explicit Conversation Handling Mode pauses
Maia while a human is handling the Contact and prevents concurrent replies; this
preserves identity, consent, continuity, auditability, and operational metrics.
Only the Advisor or Admin explicitly returns the conversation to Maia; a timeout
may alert the Admin but never transfers conversational authority silently.

When a Contact requests a human, Maia uses a warm handoff rather than presenting
a formal response-time SLA. Maia says that it will notify the Advisor, discloses
that it cannot confirm the Advisor's exact availability, and says it will do what
it can to have the Advisor respond within the next few minutes. Product alerts
the Advisor immediately and tracks the unhandled request internally. If no human
has taken handling authority after 15 minutes, Product alerts the Organization
Administrator without automatically reassigning the Opportunity.

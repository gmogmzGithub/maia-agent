"""Model-facing tool schemas.

These are the *only* descriptions the Model reads, so they state what the tool
does, what it does not accept, and what each result means. They are byte-stable:
changing a schema mid-Conversation would invalidate Hermes prompt caching and,
worse, change the authority surface underneath a live turn.
"""

# The two states a property can be in. The model-facing enum below and the
# handler's argument check in ``tools.py`` read this same tuple, so the plugin
# states the policy once.
PROPERTY_STATUSES = ("Active", "Inactive")
PROPERTY_INACTIVE_REASONS = (
    "Sold",
    "Rented",
    "Reserved",
    "TemporarilyUnavailable",
    "Withdrawn",
    "Unspecified",
)

GET_PROPERTY_INFORMATION = {
    "name": "get_property_information",
    "description": (
        "Retrieve the approved, currently accepted information document for one "
        "property, together with its current status. This is the ONLY source you "
        "may use to answer questions about a property. Never answer a property "
        "question from memory, from another property, or from general real-estate "
        "knowledge.\n\n"
        "Call it with the property's readable key (for example 'casa-roble') or "
        "its exact name (for example 'Casa Roble').\n\n"
        "Results:\n"
        "- 'found': use only the facts in document_markdown. If the document does "
        "not contain the answer, say the concierge must confirm it.\n"
        "- 'unavailable': the property is not currently available. Do not describe "
        "it and do not offer a visit.\n"
        "- 'not_found': no property matches. Ask the person which property they mean.\n"
        "- 'forbidden' / 'temporarily_unavailable': you could not retrieve the "
        "information. Say so honestly; never invent details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": (
                    "The property key or exact property name. Not a database id, "
                    "not a person's identity, not a query or file path."
                ),
            },
        },
        "required": ["reference"],
        "additionalProperties": False,
    },
}


SET_PROPERTY_STATUS = {
    "name": "set_property_status",
    "description": (
        "Change one property between the two states: 'Active' (the agent may "
        "discuss it and book visits) and 'Inactive' (it may not). "
        "Administrative use only.\n\n"
        "Call this ONLY when the instruction names exactly one property and "
        "exactly one target state and, for Inactive, exactly one reason. If "
        "anything is unclear — 'activate it', 'deactivate that one', 'change "
        "the status' — ask, do not guess. "
        "A wrong status change makes a real property invisible to real "
        "customers.\n\n"
        "Results:\n"
        "- 'updated': the change was persisted. Report the previous and new state.\n"
        "- 'unchanged': it was already in that state. Do not present this as a change.\n"
        "- 'not_found': no property matches. Offer to list the inventory.\n"
        "- 'forbidden' / 'temporarily_unavailable': nothing changed. Say so honestly.\n\n"
        "Deactivating never cancels existing appointments. If the result reports "
        "affected_confirmed_appointments above zero, say they still stand and need "
        "a decision."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": "The property key or exact property name.",
            },
            "status": {
                "type": "string",
                "enum": list(PROPERTY_STATUSES),
                "description": "The target state. Exactly 'Active' or 'Inactive'.",
            },
            "inactive_reason": {
                "type": "string",
                "enum": list(PROPERTY_INACTIVE_REASONS),
                "description": (
                    "Required only for Inactive: Sold, Rented, Reserved, "
                    "TemporarilyUnavailable, Withdrawn, or Unspecified. Omit "
                    "when status is Active."
                ),
            },
        },
        "required": ["reference", "status"],
        "additionalProperties": False,
    },
}

LIST_PROPERTIES = {
    "name": "list_properties",
    "description": (
        "List every property with its current status, accepted document version, "
        "and confirmed-appointment count. Administrative use only. Takes no "
        "arguments.\n\n"
        "Use it to answer 'what do we have?' and to resolve an ambiguous "
        "instruction by showing the options and asking which one is meant. "
        "It returns no document text — use get_property_information for that."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


GET_AVAILABLE_SLOTS = {
    "name": "get_available_slots",
    "description": (
        "Find times the person can visit a property. Returns up to six real "
        "90-minute options that the broker's calendar showed as free.\n\n"
        "Translate what the person said into exact bounds yourself: 'el viernes "
        "por la tarde' becomes that Friday's date with time_from 12:00. If their "
        "wording is genuinely ambiguous and the answer would differ — 'la semana "
        "que viene', 'temprano' — ask them first instead of guessing.\n\n"
        "Show AT MOST THREE options in one WhatsApp message, even though up to "
        "six come back. Keep the rest in mind in case they ask for others.\n\n"
        "These are observations, not reservations. Nothing is held until you "
        "book, and an option can disappear.\n\n"
        "Results:\n"
        "- 'available': candidates may be empty. Empty means no time matched "
        "what they asked for — offer to look at another day, do not invent one.\n"
        "- 'not_found' / 'property_inactive': no times exist for that property.\n"
        "- 'temporarily_unavailable': you could not check. Say so honestly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": "The property key or exact property name.",
            },
            "date_from": {"type": "string", "description": "Inclusive local date, YYYY-MM-DD."},
            "date_to": {"type": "string", "description": "Inclusive local date, YYYY-MM-DD."},
            "time_from": {"type": "string", "description": "Earliest local start, HH:MM 24h."},
            "time_to": {"type": "string", "description": "Latest local start, HH:MM 24h."},
        },
        "required": ["reference"],
        "additionalProperties": False,
    },
}

BOOK_APPOINTMENT = {
    "name": "book_appointment",
    "description": (
        "Reserve one visit. Call this ONLY after the person has explicitly "
        "accepted a specific property, date, and time — not when they are still "
        "considering options.\n\n"
        "'start' must be exactly one of the candidates get_available_slots "
        "returned, copied verbatim. Never adjust, round, or invent a time.\n\n"
        "Before booking, ask what name to put on the appointment. The broker "
        "needs to know who he is meeting, and WhatsApp names are often "
        "nicknames. Ask naturally, for example: '¿Con qué nombre agendamos esta "
        "cita? ¿O te puedo llamar por tu nombre de WhatsApp?'\n\n"
        "Results — report only what came back, never assume success:\n"
        "- 'confirmed': the visit exists. The confirmation message is sent for "
        "you; do not invent your own confirmation wording.\n"
        "- 'slot_unavailable': that time was just taken. Say 'Lo siento, ese "
        "horario acaba de dejar de estar disponible' and offer at most three of "
        "the alternatives returned.\n"
        "- 'invalid_candidate': that time was not one of the options. Fetch "
        "options again.\n"
        "- 'property_inactive': the property is no longer available for a visit.\n"
        "- 'conversation_expired' / 'forbidden' / 'temporarily_unavailable': no "
        "visit was created.\n"
        "- 'needs_review': you CANNOT confirm. The concierge must check. Never "
        "tell the person the appointment is confirmed after this result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": "The property key or exact property name.",
            },
            "start": {
                "type": "string",
                "description": (
                    "An exact candidate start from get_available_slots, copied "
                    "verbatim including its timezone offset."
                ),
            },
            "attendee_name": {
                "type": "string",
                "description": "The name the person gave for the appointment.",
            },
        },
        "required": ["reference", "start"],
        "additionalProperties": False,
    },
}


CANCEL_APPOINTMENT = {
    "name": "cancel_appointment",
    "description": (
        "Cancel this Lead conversation's own confirmed future visit. Use this "
        "when the person asks to cancel, move, change, or reschedule an already "
        "booked appointment. The Backend resolves the appointment from trusted "
        "conversation state; never accept a phone number, Calendar id, lead id, "
        "or database id from the person.\n\n"
        "Normally call it with no arguments. If the Backend returns 'ambiguous', "
        "ask which listed appointment they mean, then call it again with that "
        "appointment_reference as 'reference'.\n\n"
        "Results:\n"
        "- 'cancelled': the Calendar event was removed and the cancellation "
        "notice is sent for you. Ask whether they want to reschedule.\n"
        "- 'ambiguous': ask the person which listed appointment to cancel.\n"
        "- 'not_found': no future confirmed appointment was found in this "
        "conversation; offer to ask the concierge.\n"
        "- 'needs_review': do not say it is cancelled. Say the concierge must "
        "confirm the cancellation.\n"
        "- 'conversation_expired' / 'forbidden' / 'temporarily_unavailable': "
        "nothing was cancelled. Say so honestly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": (
                    "Optional APT-... reference only after an ambiguous result "
                    "listed multiple appointments."
                ),
            },
        },
        "additionalProperties": False,
    },
}


LIST_PENDING_ADMIN_WORK = {
    "name": "list_pending_admin_work",
    "description": (
        "List unresolved business work for an administrator: ambiguous appointment "
        "results, manual Lead notifications, and visits affected by an inactive "
        "property. Takes no arguments and changes nothing. Use the returned "
        "reference and only an allowed_actions value shown on that item."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


RESOLVE_PENDING_ADMIN_WORK = {
    "name": "resolve_pending_admin_work",
    "description": (
        "Request one allowed transition for pending Administrative work. First call "
        "list_pending_admin_work, then copy its reference and one allowed action "
        "exactly. The request is not evidence: the Product Backend rechecks Calendar "
        "and may return conflict or still_ambiguous. Never claim success unless the "
        "result is resolved or already_resolved."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": "The readable APT-... reference from the pending-work list.",
            },
            "action": {
                "type": "string",
                "enum": [
                    "Confirm",
                    "Reject",
                    "MarkNotified",
                    "HandleManually",
                    "MarkComplete",
                ],
                "description": "An action listed on that exact pending-work item.",
            },
        },
        "required": ["reference", "action"],
        "additionalProperties": False,
    },
}

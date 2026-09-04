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

PROPERTY_NEED_CRITERIA = (
    "transaction_intent",
    "service_area",
    "economic_range",
    "horizon",
    "essential_requirements",
)

GET_TRANSACTION_JOURNEY = {
    "name": "get_transaction_journey",
    "description": (
        "Read the current Contact's Product-confirmed purchase Transaction Journey. "
        "Takes no identifiers and resolves the Opportunity only from the trusted "
        "Sales session. Use it after the customer asks about their formal purchase "
        "process, a pending item, a recorded delay, or what Product still needs.\n\n"
        "This tool is READ ONLY. It cannot start a Journey, advance a milestone, "
        "invent evidence, approve financing, interpret a document, or declare the "
        "sale complete. Say only what the returned confirmed state supports. "
        "If result is no_active_journey, do not imply that formal processing began."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

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
        "List properties for the current role. In Sales, returns only Active "
        "properties with customer-safe summaries. In Administrative, returns "
        "every property with its current status, accepted document version, and "
        "confirmed-appointment count. Takes no arguments.\n\n"
        "Use it in Sales when the person explicitly asks what options are "
        "available, and use get_property_information for the full facts of a "
        "named property. Use it in Administrative to answer 'what do we have?' "
        "or resolve an ambiguous instruction. It returns no document prose."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


RECORD_PROPERTY_NEED = {
    "name": "record_property_need",
    "description": (
        "Keep the current Contact's property need synchronized with what this "
        "conversation establishes. Call after the Contact states, corrects, or "
        "confirms any of: transaction intent, acceptable area, economic range, "
        "approximate horizon, or essential requirements. Also call when you form "
        "a useful interpretation that the Contact has not confirmed yet.\n\n"
        "For each value, use source 'ContactStated' only when the Contact said it "
        "explicitly and copy the exact supporting excerpt into evidence. Use "
        "'ModelInferred' for every interpretation or normalization that still "
        "needs confirmation. Never use placeholders such as unknown, flexible, "
        "or not provided. Product resolves the Contact, Opportunity and "
        "Organization from the trusted Sales session; never ask for or supply "
        "their identifiers.\n\n"
        "This records qualification facts only. It does not qualify the lead, "
        "change the funnel stage, assign an advisor, or send a message. If "
        "evidence for a ContactStated value cannot be found in retained inbound "
        "messages, Product safely records it as Pending and lists it in "
        "evidence_downgraded. Use missing_required and pending_required to choose "
        "one useful next question."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": list(PROPERTY_NEED_CRITERIA),
                        },
                        "value": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 300,
                            "description": (
                                "The concise criterion value. When name is "
                                "transaction_intent, use exactly Buy, Rent, Sell, "
                                "or LeaseOut; Maia renders the customer-facing "
                                "Spanish label separately."
                            ),
                        },
                        "source": {
                            "type": "string",
                            "enum": ["ContactStated", "ModelInferred"],
                        },
                        "evidence": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 500,
                            "description": (
                                "An exact excerpt from the Contact's message that "
                                "supports the value or inference."
                            ),
                        },
                    },
                    "required": ["name", "value", "source", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["criteria"],
        "additionalProperties": False,
    },
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
        "Show AT MOST THREE options in one customer message, even though up to "
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
            "date_from": {
                "type": "string",
                "description": "Inclusive local date, YYYY-MM-DD.",
            },
            "date_to": {
                "type": "string",
                "description": "Inclusive local date, YYYY-MM-DD.",
            },
            "time_from": {
                "type": "string",
                "description": "Earliest local start, HH:MM 24h.",
            },
            "time_to": {
                "type": "string",
                "description": "Latest local start, HH:MM 24h.",
            },
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
        "needs to know who he is meeting, and channel profile names are often "
        "nicknames. Ask naturally, for example: '¿Con qué nombre agendamos esta "
        "cita? ¿O te puedo llamar por tu nombre de perfil?'\n\n"
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


# --- Stage 3: bounded Appointment Logistics and the human handoff ------------
#
# Two names added to the frozen surface by the human-operation stage. Both exist
# because a rule the product must enforce cannot be expressed with the Stage 0
# tools: an atomic reschedule (ADR-0037) is not a cancel followed by a booking,
# and a warm handoff to a person (ADR-0029) is not something the Model can do by
# writing a sentence.


RESCHEDULE_APPOINTMENT = {
    "name": "reschedule_appointment",
    "description": (
        "Move this Lead conversation's own confirmed future visit to a new "
        "time. Prefer this over cancelling when the person names a new time: it "
        "secures the new slot before releasing the old one, so a failure leaves "
        "the original appointment in place.\n\n"
        "Call get_available_slots first and use one of the exact starts it "
        "returned. The Backend resolves the appointment from trusted "
        "conversation state; never accept a phone number, Calendar id, lead id, "
        "or database id from the person.\n\n"
        "Results:\n"
        "- 'rescheduled': confirm the new date and time you are given, and say "
        "the previous one was released.\n"
        "- 'slot_unavailable': the new time was taken. Offer the returned "
        "candidates.\n"
        "- 'ambiguous': ask which listed appointment they mean, then call again "
        "with that appointment_reference as 'reference'.\n"
        "- 'needs_review': say clearly that the ORIGINAL appointment is still "
        "in place and the concierge will confirm the change. Never say it was "
        "moved.\n"
        "- 'not_found': no future confirmed appointment in this conversation.\n"
        "- 'conversation_expired' / 'forbidden' / 'temporarily_unavailable' / "
        "'property_inactive': nothing changed. Say so honestly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "start": {
                "type": "string",
                "description": (
                    "The new start, exactly as get_available_slots returned it. "
                    "Never invent or round a time."
                ),
            },
            "reference": {
                "type": "string",
                "description": (
                    "Optional APT-... reference only after an ambiguous result "
                    "listed multiple appointments."
                ),
            },
        },
        "required": ["start"],
        "additionalProperties": False,
    },
}


REQUEST_HUMAN_HANDOFF = {
    "name": "request_human_handoff",
    "description": (
        "Ask the operation to have a human advisor take over this conversation. "
        "Call it when the person asks to speak to a person, an advisor, or a "
        "human, when they say they do not want to talk to a bot, or when they "
        "need something you are not allowed to decide.\n\n"
        "After calling it, tell them plainly: you will let the advisor know, you "
        "cannot confirm the advisor's availability right now, and you will do "
        "what you can so the advisor gets in touch in the next few minutes. "
        "Never promise a response time, a deadline, or a specific person.\n\n"
        "Once a handoff is requested you stop leading the conversation. Do not "
        "keep qualifying, recommending properties, or negotiating. Answer only "
        "if they ask something factual you already know.\n\n"
        "Results:\n"
        "- 'requested': a person has been alerted. Acknowledge warmly, as "
        "above.\n"
        "- 'already_requested': somebody was already alerted and has not taken "
        "it yet. Say the advisor has been notified; do not alert again.\n"
        "- 'forbidden' / 'temporarily_unavailable': nobody was alerted. Say you "
        "could not reach the team right now and do not claim otherwise."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "One short internal sentence about what they need. Never "
                    "shown to the person."
                ),
            },
        },
        "additionalProperties": False,
    },
}


# --- Stage 6: Product-owned, read-only inventory discovery ------------------

SEARCH_INVENTORY = {
    "name": "search_inventory",
    "description": (
        "Search Product's authorized inventory for one municipality in the "
        "service area. Product checks Organization Listings first and uses "
        "authorized collaborator candidates only as fallback. Preserve "
        "match_quality exactly: say when a result is approximate. External "
        "results require revalidate_external_listing before recommending, "
        "sharing, or discussing an appointment. Never imply that EasyBroker "
        "contains all properties in Mexico."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "municipality": {
                "type": "string",
                "enum": ["Guadalajara", "Zapopan", "Tlaquepaque"],
            },
            "operation": {
                "type": "string",
                "enum": ["Sale", "Rental", "Presale"],
            },
            "property_type": {"type": "string"},
            "min_price": {"type": "number", "exclusiveMinimum": 0},
            "max_price": {"type": "number", "exclusiveMinimum": 0},
            "min_bedrooms": {"type": "integer", "minimum": 0},
        },
        "required": ["municipality"],
        "additionalProperties": False,
    },
}


REVALIDATE_EXTERNAL_LISTING = {
    "name": "revalidate_external_listing",
    "description": (
        "Revalidate one external EasyBroker candidate immediately before a "
        "specific use. Call only for a reference returned by search_inventory. "
        "Only 'eligible' permits that named action. 'pending' means a human "
        "must confirm missing or changed evidence; 'denied' means do not use it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference": {"type": "string"},
            "intended_action": {
                "type": "string",
                "enum": ["Recommend", "Share", "Appointment"],
            },
        },
        "required": ["reference", "intended_action"],
        "additionalProperties": False,
    },
}

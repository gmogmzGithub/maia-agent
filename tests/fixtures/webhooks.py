"""Builders for realistic Meta WhatsApp Cloud API webhook bodies.

Shapes follow the Cloud API's documented payloads. The referral block is the
one V-001 must confirm against a real Click-to-WhatsApp message; it is included
here only so the parser and the Inbox can be shown to retain it untouched.
"""

from __future__ import annotations

import json
import time
from typing import Any

PHONE_NUMBER_ID = "1257310757465762"
DISPLAY_NUMBER = "+1 555-671-0559"
LEAD_WA_ID = "523318923936"
WABA_ID = "2102414207379718"


def text_message(
    *,
    wamid: str,
    body: str,
    from_wa_id: str = LEAD_WA_ID,
    profile_name: str = "Cliente Demo",
    timestamp: int | None = None,
    referral: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "from": from_wa_id,
        "id": wamid,
        "timestamp": str(timestamp or int(time.time())),
        "type": "text",
        "text": {"body": body},
    }
    if referral is not None:
        message["referral"] = referral
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": DISPLAY_NUMBER,
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": profile_name},
                                    "wa_id": from_wa_id,
                                }
                            ],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def status_update(
    *,
    provider_message_id: str,
    status: str = "delivered",
    recipient: str = LEAD_WA_ID,
    timestamp: int | None = None,
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": DISPLAY_NUMBER,
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "statuses": [
                                {
                                    "id": provider_message_id,
                                    "status": status,
                                    "timestamp": str(timestamp or int(time.time())),
                                    "recipient_id": recipient,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


# A plausible Click-to-WhatsApp referral block. Field names are NOT accepted as
# a contract until V-001 captures a real one (P-049, TC-009).
SAMPLE_REFERRAL = {
    "source_url": "https://fb.me/example",
    "source_id": "120210000000000000",
    "source_type": "ad",
    "headline": "Casa Roble en Zapopan",
    "body": "4 recámaras en coto privado",
    "ctwa_clid": "ARAa1example",
}


def encode(body: dict[str, Any]) -> bytes:
    """Serialise exactly as it will be signed and sent."""
    return json.dumps(body, separators=(",", ":")).encode("utf-8")

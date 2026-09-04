"""Synthetic Instagram Messaging webhook bodies."""

from __future__ import annotations

import time

ACCOUNT_ID = "ig-17841400000000000"
SENDER_IGSID = "ig-user-987654321"


def text_message(
    *,
    message_id: str,
    body: str,
    sender_id: str = SENDER_IGSID,
    account_id: str = ACCOUNT_ID,
    timestamp: int | None = None,
) -> dict[str, object]:
    moment = timestamp or int(time.time() * 1000)
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account_id,
                "time": moment,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": account_id},
                        "timestamp": moment,
                        "message": {"mid": message_id, "text": body},
                    }
                ],
            }
        ],
    }

"""Synthetic Facebook Page Messenger webhook bodies."""

from __future__ import annotations

import time

PAGE_ID = "page-123456789"
SENDER_PSID = "psid-987654321"


def text_message(
    *,
    message_id: str,
    body: str,
    sender_id: str = SENDER_PSID,
    page_id: str = PAGE_ID,
    timestamp: int | None = None,
) -> dict[str, object]:
    moment = timestamp or int(time.time() * 1000)
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "time": moment,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": page_id},
                        "timestamp": moment,
                        "message": {"mid": message_id, "text": body},
                    }
                ],
            }
        ],
    }

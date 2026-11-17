"""Remove short-lived OAuth authorization codes from HTTP access logs."""

import logging
import re


class CalendarCallbackFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if "/api/calendar/callback?" in message or "/api/whatsapp/webhook?" in message:
            record.msg = re.sub(
                r"(/api/(?:calendar/callback|whatsapp/webhook))\?[^\s\"]+",
                r"\1?<redacted>",
                message,
            )
            record.args = ()
        return True

"""Validation failures whose code and field survive transport and translation."""


class CaptureError(ValueError):
    def __init__(self, message, *, code, field=None):
        super().__init__(message)
        self.code = code
        self.field = field

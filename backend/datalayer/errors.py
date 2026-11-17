"""Concurrency signal shared by turn and booking operations."""


class Superseded(Exception):
    """The input revision or human control invalidated an in-flight turn."""

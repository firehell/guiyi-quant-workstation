"""Observe provider buffering for the Feed's drain and readiness checks."""


def buffered_message_count(provider) -> int:
    count = getattr(provider, "buffered_message_count", None)
    return count() if callable(count) else len(getattr(provider, "_messages", ()))

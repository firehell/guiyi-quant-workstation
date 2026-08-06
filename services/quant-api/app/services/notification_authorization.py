"""Neutral one-event authorization contract for observation notifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class ObservationNotificationAuthorization:
    event_id: int
    signal_id: int
    event_sha256: str
    dedupe_key: str
    max_attempts: int
    retry_deadline: datetime
    rendered_message_sha256: str


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

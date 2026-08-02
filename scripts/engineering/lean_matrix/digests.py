"""Canonical JSON and SHA-256 digests for semantic Lean Matrix contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import TaskCharterV1


def canonical_json(value: Any) -> str:
    """Return stable UTF-8 JSON text without presentation-only whitespace."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def semantic_digest(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def charter_digest(charter: TaskCharterV1) -> str:
    """Digest only the normalized semantic Charter fields, never Markdown."""
    return semantic_digest(charter.to_dict())

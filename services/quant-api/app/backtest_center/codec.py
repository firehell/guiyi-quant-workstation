"""Canonical serialization shared across the workstation and Plus interpreters."""

from hashlib import sha256
import json


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def digest(value) -> str:
    return sha256(encode(value).encode()).hexdigest()

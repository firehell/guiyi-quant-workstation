"""Strict JSON contract loading and immutable-shape helpers for research policies."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any


def matches_exact_json(value: object, expected: object) -> bool:
    """Match JSON recursively without accepting Python's bool/int equivalence."""

    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            isinstance(value, dict)
            and value.keys() == expected.keys()
            and all(
                matches_exact_json(value[key], item)
                for key, item in expected.items()
            )
        )
    if isinstance(expected, list):
        return isinstance(value, list) and len(value) == len(expected) and all(
            matches_exact_json(actual, item)
            for actual, item in zip(value, expected, strict=True)
        )
    return value == expected


def load_exact_json(
    path: Path,
    expected: dict[str, Any],
    error_type: type[ValueError],
) -> dict[str, Any]:
    """Load one exact JSON object and expose only its stable domain error."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise error_type() from None
    if not matches_exact_json(payload, expected):
        raise error_type()
    assert isinstance(payload, dict)
    return payload


def freeze_json(value: Any) -> Any:
    """Freeze JSON dictionaries/lists while retaining scalar types."""

    if isinstance(value, dict):
        return MappingProxyType(
            {key: freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    return value


def matches_exact_frozen(value: object, expected: object) -> bool:
    """Match a value produced by ``freeze_json`` against its JSON shape."""

    if isinstance(expected, dict):
        return (
            isinstance(value, MappingProxyType)
            and value.keys() == expected.keys()
            and all(
                matches_exact_frozen(value[key], item)
                for key, item in expected.items()
            )
        )
    if isinstance(expected, list):
        return isinstance(value, tuple) and len(value) == len(expected) and all(
            matches_exact_frozen(actual, item)
            for actual, item in zip(value, expected, strict=True)
        )
    return (
        not isinstance(value, MappingABC)
        and type(value) is type(expected)
        and value == expected
    )

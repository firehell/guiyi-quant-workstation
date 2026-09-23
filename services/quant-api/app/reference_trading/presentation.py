"""Versioned, bounded display facts emitted by historical reference kernels.

These facts are never market prices or trade actions.  They are committed in
the same batch as the reducer output and included in its payload hash.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json


MAX_PRESENTATION_BYTES = 1_048_576
MAX_PRESENTATION_ITEMS = 2_000


class PresentationUnavailable(ValueError):
    """A published legacy batch cannot satisfy the persisted display contract."""


def _wire(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _wire(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _wire(item) for key, item in value.items()}
    raise TypeError("PRESENTATION_VALUE_INVALID")


def presentation_point(
    *, kind: str, value: object, trading_day: date, formula_versions: tuple[str, ...],
) -> dict[str, object]:
    if kind not in {"signal", "indicator", "hint", "diagnostic", "boundary", "trade_identity", "action", "availability"}:
        raise ValueError("PRESENTATION_KIND_INVALID")
    if type(trading_day) is not date or not formula_versions:
        raise ValueError("PRESENTATION_IDENTITY_INVALID")
    return {
        "kind": kind,
        "trading_day": trading_day.isoformat(),
        "formula_versions": list(formula_versions),
        "value": _wire(value),
    }


def envelope(points: list[dict[str, object]]) -> dict[str, object]:
    if len(points) > MAX_PRESENTATION_ITEMS:
        raise ValueError("PRESENTATION_BATCH_LIMIT")
    if len(json.dumps(points, sort_keys=True, separators=(",", ":")).encode()) > MAX_PRESENTATION_BYTES:
        raise ValueError("PRESENTATION_BATCH_LIMIT")
    days = [point.get("trading_day") for point in points]
    if any(not isinstance(day, str) or len(day) != 10 for day in days):
        raise ValueError("PRESENTATION_IDENTITY_INVALID")
    result: dict[str, object] = {
        "version": "presentation_v1", "points": points,
        "first_day": min(days) if days else None,
        "last_day": max(days) if days else None,
    }
    size = len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
    if size > MAX_PRESENTATION_BYTES:
        raise ValueError("PRESENTATION_BATCH_LIMIT")
    return result


def require_envelope(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, dict) or value.get("version") != "presentation_v1":
        raise PresentationUnavailable("PRESENTATION_NOT_MATERIALIZED")
    points = value.get("points")
    if not isinstance(points, list) or len(points) > MAX_PRESENTATION_ITEMS:
        raise PresentationUnavailable("PRESENTATION_CORRUPT")
    if len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()) > MAX_PRESENTATION_BYTES:
        raise PresentationUnavailable("PRESENTATION_CORRUPT")
    if not all(isinstance(item, dict) for item in points):
        raise PresentationUnavailable("PRESENTATION_CORRUPT")
    return tuple(points)

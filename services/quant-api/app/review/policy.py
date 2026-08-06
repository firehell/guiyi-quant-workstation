from __future__ import annotations

from typing import Any


SUPPORTED_REVIEW_SOURCE_TYPES = frozenset(
    {
        "strategy_signal",
        "signal_event",
        "signal_decision",
        "manual_trade",
    }
)


def is_supported_review_source_type(source_type: str) -> bool:
    return source_type in SUPPORTED_REVIEW_SOURCE_TYPES


def supported_review_source_clause(source_type_column: Any) -> Any:
    return source_type_column.in_(SUPPORTED_REVIEW_SOURCE_TYPES)

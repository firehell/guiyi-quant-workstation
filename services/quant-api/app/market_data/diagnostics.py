"""Bounded public data diagnostics; never serialize adapter exception text."""

from collections.abc import Mapping
from datetime import date, datetime
import re


MISSING_REASONS = frozenset(
    {
        "REPLAY_PREFIX_MISSING",
        "REPLAY_ENDPOINTS_MISSING",
        "TRADING_CALENDAR_MISSING",
        "TRADING_SESSION_MISSING",
        "HISTORICAL_SESSION_FACT_MISSING",
        "CONTRACT_METADATA_MISSING",
        "MAIN_CONTRACT_MAP_MISSING",
        "DATASET_OR_PARTITION_MISSING",
        "COMPLETE_PERIOD_MISSING",
        "CONTRACT_ACTIVE_WINDOW_MISSING",
        "PRODUCT_WINDOW_START_MISSING",
    }
)
INTEGRITY_REASONS = frozenset(
    {
        "REPLAY_ORDER_INVALID",
        "REPLAY_ENDPOINTS_EXTRA",
        "REPLAY_CUTOFF_MISMATCH",
        "METADATA_IDENTITY_INVALID",
        "DATA_INTEGRITY_INVALID",
    }
)
DATA_REASONS = MISSING_REASONS | INTEGRITY_REASONS | {"SOURCE_NONPOSITIVE_PRICE"}

_SOURCE_REASONS = {
    **{reason: reason for reason in MISSING_REASONS},
    "CONTRACT_NOT_FOUND": "CONTRACT_METADATA_MISSING",
    "INSTRUMENT_EXCHANGE_MISSING": "CONTRACT_METADATA_MISSING",
    "CONTRACT_IDENTITY_MISMATCH": "METADATA_IDENTITY_INVALID",
    "CONTRACT_SYMBOL_MISMATCH": "METADATA_IDENTITY_INVALID",
    "CONTRACT_PROVIDER_UNSUPPORTED": "METADATA_IDENTITY_INVALID",
    "PRODUCT_WINDOW_STARTS_INVALID": "METADATA_IDENTITY_INVALID",
    "MAPPED_CONTRACT_DATASET_MISSING": "DATASET_OR_PARTITION_MISSING",
    "QUERY_WINDOW_EMPTY": "DATASET_OR_PARTITION_MISSING",
    "ACTUAL_DOMINANT_WEEKLY_DATASET_ABSENT": "DATASET_OR_PARTITION_MISSING",
    "DOMINANT_CONTEXT_MISSING": "MAIN_CONTRACT_MAP_MISSING",
    "COMPLETE_WEEK_MISSING": "COMPLETE_PERIOD_MISSING",
    "COMPLETE_TRADING_DAY_MISSING": "COMPLETE_PERIOD_MISSING",
    "CONTRACT_REPLAY_CUTOFF_INVALID": "REPLAY_CUTOFF_MISMATCH",
    "PARTITION_INTEGRITY_INVALID": "DATA_INTEGRITY_INVALID",
}


def data_reason(code: str) -> str | None:
    return _SOURCE_REASONS.get(code)


def safe_context(values: Mapping[str, object] | None) -> dict[str, str | int]:
    """Copy only validated locations/counts, excluding all other supplied fields."""
    result: dict[str, str | int] = {}
    for key, value in (values or {}).items():
        if (
            key == "symbol"
            and isinstance(value, str)
            and re.fullmatch(r"[a-z]{1,8}", value)
        ):
            result[key] = value
        elif (
            key == "contract"
            and isinstance(value, str)
            and re.fullmatch(r"[A-Za-z]{1,8}[0-9]{3,4}", value)
        ):
            result[key] = value
        elif (
            key == "frequency"
            and isinstance(value, str)
            and value in {"1m", "5m", "15m", "30m", "60m", "1d", "1w"}
        ):
            result[key] = value
        elif (
            key in {"expected_count", "actual_count", "missing_count"}
            and type(value) is int
            and 0 <= value <= 1_000_000_000
        ):
            result[key] = value
        elif key in {"trading_day", "first_missing_day"}:
            try:
                parsed = (
                    value
                    if type(value) is date
                    else date.fromisoformat(value)
                    if isinstance(value, str)
                    else None
                )
                if parsed is not None:
                    result[key] = parsed.isoformat()
            except ValueError:
                pass
        elif key in {"cutoff", "first_missing_at"}:
            try:
                instant = (
                    value
                    if isinstance(value, datetime)
                    else datetime.fromisoformat(value)
                    if isinstance(value, str)
                    else None
                )
                if instant is not None and instant.utcoffset() is not None:
                    result[key] = instant.isoformat()
            except ValueError:
                pass
    return result

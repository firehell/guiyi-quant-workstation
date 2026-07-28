"""Schema-v5 observer ledger records for one DCE trading day."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Mapping


def build_ledger_sample(
    *,
    trading_day: date,
    sampled_at: datetime,
    evaluated_bucket_ends: list[str],
    partial_rejections: int,
    event_counts: Mapping[str, int],
    notification_counts: Mapping[str, int],
    health: Mapping[str, bool],
    eod_status: str,
) -> dict[str, Any]:
    if sampled_at.tzinfo is None:
        raise ValueError("S610_LEDGER_TIMEZONE_REQUIRED")
    unique_ends = sorted(set(evaluated_bucket_ends))
    if (
        len(unique_ends) != len(evaluated_bucket_ends)
        or len(unique_ends) > 23
        or partial_rejections < 0
        or any(type(value) is not int or value < 0 for value in event_counts.values())
        or any(
            type(value) is not int or value < 0
            for value in notification_counts.values()
        )
        or set(health) != {"runtime", "redis", "database", "after_market"}
        or any(type(value) is not bool for value in health.values())
        or eod_status not in {"pending", "passed", "failed"}
    ):
        raise ValueError("S610_LEDGER_SAMPLE_INVALID")
    return {
        "schema_version": 5,
        "sample_type": "htdy_s6_10_one_day_ledger",
        "trading_day": trading_day.isoformat(),
        "sampled_at": sampled_at.astimezone(UTC).isoformat(),
        "expected_confirmed_15m_closes": 23,
        "evaluated_confirmed_15m_closes": len(unique_ends),
        "evaluated_bucket_ends": unique_ends,
        "partial_evaluations": 0,
        "partial_rejections": partial_rejections,
        "event_counts": dict(event_counts),
        "notification_counts": dict(notification_counts),
        "health": dict(health),
        "eod_status": eod_status,
        "disaster_recovery_ready": False,
        "auto_order": False,
    }

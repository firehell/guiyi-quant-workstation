"""Schema-v5 observer ledger records for one DCE trading day."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
import json
from pathlib import Path
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


def build_remaining_window_ledger_sample(
    *,
    trading_day: date,
    sampled_at: datetime,
    expected_bucket_ends: list[str],
    evaluated_bucket_ends: list[str],
    partial_rejections: int,
    event_counts: Mapping[str, int],
    notification_counts: Mapping[str, int],
    health: Mapping[str, bool],
    eod_status: str,
    activation_receipt_hash: str,
) -> dict[str, Any]:
    expected = sorted(set(expected_bucket_ends))
    evaluated = sorted(set(evaluated_bucket_ends))
    if (
        not expected
        or len(expected) > 23
        or len(expected) != len(expected_bucket_ends)
        or any(value not in expected for value in evaluated)
        or len(activation_receipt_hash) != 64
    ):
        raise ValueError("S610_REMAINING_LEDGER_SAMPLE_INVALID")
    base = build_ledger_sample(
        trading_day=trading_day,
        sampled_at=sampled_at,
        evaluated_bucket_ends=evaluated,
        partial_rejections=partial_rejections,
        event_counts=event_counts,
        notification_counts=notification_counts,
        health=health,
        eod_status=eod_status,
    )
    return {
        **base,
        "schema_version": 6,
        "sample_type": "htdy_s6_10_remaining_window_ledger",
        "expected_confirmed_15m_closes": len(expected),
        "expected_bucket_ends": expected,
        "activation_receipt_hash": activation_receipt_hash,
        "complete_trading_day_passed": False,
    }


def parse_confirmed_close_evaluations(
    log_path: Path,
    *,
    trading_day: date,
    allowed_bucket_ends: set[str] | None = None,
) -> list[str]:
    """Read only explicit v1.1 confirmed-close summaries from the Runtime log."""

    if not log_path.is_file():
        return []
    marker = "htdy_close_evaluation_summary "
    bucket_ends: set[str] = set()
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if marker not in line:
            continue
        try:
            payload = json.loads(line.split(marker, 1)[1])
        except (json.JSONDecodeError, IndexError):
            continue
        if (
            payload.get("trading_day") == trading_day.isoformat()
            and payload.get("bucket_status") == "confirmed"
            and payload.get("partial_allowed") is False
            and payload.get("signal_changed") == 0
            and isinstance(payload.get("bucket_end"), str)
        ):
            bucket_end = payload["bucket_end"]
            if (
                allowed_bucket_ends is None
                or bucket_end in allowed_bucket_ends
            ):
                bucket_ends.add(bucket_end)
    return sorted(bucket_ends)


def collect_one_day_ledger_sample(
    *,
    session: Any,
    redis: Any,
    trading_day: date,
    runtime_log: Path,
    sampled_at: datetime,
    expected_bucket_ends: list[str] | None = None,
    activation_receipt_hash: str | None = None,
) -> dict[str, Any]:
    """Collect bounded DB/Redis/runtime facts without sending or mutating business rows."""

    from sqlalchemy import select

    from app.after_market_scheduler import HEARTBEAT_KEY as EOD_HEARTBEAT_KEY
    from app.models.signal import SignalEvent, SignalNotification
    from app.runtime_scheduler import SCHEDULER_HEARTBEAT_KEY

    events = list(
        session.scalars(
            select(SignalEvent).where(
                SignalEvent.product == "jm",
                SignalEvent.period == "15m",
                SignalEvent.strategy_name
                == "htdy_original_realtime_first_seen",
                SignalEvent.strategy_version == "v1.1",
                SignalEvent.dominant_mapping_date == trading_day,
            )
        )
    )
    if expected_bucket_ends is not None:
        allowed_datetimes = {
            datetime.fromisoformat(value) for value in expected_bucket_ends
        }
        events = [
            event
            for event in events
            if event.bar_end in allowed_datetimes
        ]
    event_ids = [event.id for event in events]
    notifications = (
        list(
            session.scalars(
                select(SignalNotification).where(
                    SignalNotification.channel == "enterprise_wechat",
                    SignalNotification.event_id.in_(event_ids),
                )
            )
        )
        if event_ids
        else []
    )
    event_counts = Counter(event.event_type for event in events)
    event_counts.setdefault("signal_created", 0)
    event_counts.setdefault("signal_changed", 0)
    notification_counts = Counter(item.status for item in notifications)
    for status in ("pending", "retry_pending", "sent", "failed", "skipped"):
        notification_counts.setdefault(status, 0)
    notification_counts["duplicate_dedupe_keys"] = len(notifications) - len(
        {item.dedupe_key for item in notifications}
    )
    notification_counts["attempts_over_limit"] = sum(
        item.attempt_count > 3 or item.max_attempts > 3
        for item in notifications
    )
    notification_counts["capped"] = sum(
        ((item.payload or {}).get("s6_10_bounded") or {}).get("status")
        == "capped"
        for item in notifications
    )

    redis_ready = bool(redis.ping())
    runtime_heartbeat = _heartbeat(redis, SCHEDULER_HEARTBEAT_KEY)
    eod_heartbeat = _heartbeat(redis, EOD_HEARTBEAT_KEY)
    eod_state = str(eod_heartbeat.get("status") or "")
    eod_status = (
        "passed"
        if eod_state == "success"
        else "failed"
        if eod_state == "failed"
        else "pending"
    )
    common = {
        "trading_day": trading_day,
        "sampled_at": sampled_at,
        "evaluated_bucket_ends": parse_confirmed_close_evaluations(
            runtime_log,
            trading_day=trading_day,
            allowed_bucket_ends=(
                set(expected_bucket_ends)
                if expected_bucket_ends is not None
                else None
            ),
        ),
        "partial_rejections": 0,
        "event_counts": event_counts,
        "notification_counts": notification_counts,
        "health": {
            "runtime": _heartbeat_fresh(runtime_heartbeat, sampled_at),
            "redis": redis_ready,
            "database": True,
            "after_market": _heartbeat_fresh(eod_heartbeat, sampled_at),
        },
        "eod_status": eod_status,
    }
    if expected_bucket_ends is None:
        return build_ledger_sample(**common)
    return build_remaining_window_ledger_sample(
        **common,
        expected_bucket_ends=expected_bucket_ends,
        activation_receipt_hash=str(activation_receipt_hash or ""),
    )


def _heartbeat(redis: Any, key: str) -> dict[str, Any]:
    raw = redis.get(key)
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _heartbeat_fresh(payload: Mapping[str, Any], now: datetime) -> bool:
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]))
    except (KeyError, ValueError):
        return False
    if generated_at.tzinfo is None:
        return False
    return (
        payload.get("status") != "failed"
        and -5 <= (now.astimezone(UTC) - generated_at.astimezone(UTC)).total_seconds() <= 180
    )

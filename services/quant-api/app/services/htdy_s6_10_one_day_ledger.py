"""Bounded one-day observer ledger and schema-v7 terminal evidence."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.htdy_s6_10_one_day_notifications import (
    event_decision_bucket_end,
)


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
        "schema_version": 7,
        "sample_type": "htdy_s6_10_remaining_window_ledger",
        "expected_confirmed_15m_closes": len(expected),
        "expected_bucket_ends": expected,
        "activation_receipt_hash": activation_receipt_hash,
        "complete_trading_day_passed": (
            len(expected) == 23
            and evaluated == expected
            and partial_rejections == 0
            and int(event_counts.get("signal_changed") or 0) == 0
            and int(notification_counts.get("failed") or 0) == 0
            and int(
                notification_counts.get("duplicate_dedupe_keys") or 0
            )
            == 0
            and int(notification_counts.get("attempts_over_limit") or 0) == 0
            and int(notification_counts.get("sent") or 0)
            == int(event_counts.get("signal_created") or 0)
            and all(health.values())
            and eod_status == "passed"
        ),
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


def filter_events_by_decision_bucket_ends(
    events: list[Any],
    allowed_bucket_ends: set[datetime],
) -> list[Any]:
    """Keep only schema-v7 events first detected at an authorized close."""

    return [
        event
        for event in events
        if event_decision_bucket_end(event) in allowed_bucket_ends
    ]


def collect_one_day_ledger_sample(
    *,
    session: Any,
    redis: Any,
    trading_day: date,
    runtime_log: Path,
    sampled_at: datetime,
    expected_bucket_ends: list[str] | None = None,
    activation_receipt_hash: str | None = None,
    parent_packet_hash: str | None = None,
    terminal_seal_path: Path | None = None,
    expected_eod_authorization_hash: str | None = None,
) -> dict[str, Any]:
    """Collect bounded DB/Redis/runtime facts without sending or mutating business rows."""

    from sqlalchemy import select

    from app.after_market_scheduler import HEARTBEAT_KEY as EOD_HEARTBEAT_KEY
    from app.models.data_center import AfterMarketSchedulerCheckpoint
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
        events = filter_events_by_decision_bucket_ends(
            events,
            allowed_datetimes,
        )
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

    evaluated_bucket_ends = parse_confirmed_close_evaluations(
        runtime_log,
        trading_day=trading_day,
        allowed_bucket_ends=(
            set(expected_bucket_ends)
            if expected_bucket_ends is not None
            else None
        ),
    )
    redis_ready = bool(redis.ping())
    runtime_heartbeat = _heartbeat(redis, SCHEDULER_HEARTBEAT_KEY)
    eod_heartbeat = _heartbeat(redis, EOD_HEARTBEAT_KEY)
    checkpoint = session.scalar(
        select(AfterMarketSchedulerCheckpoint).where(
            AfterMarketSchedulerCheckpoint.product == "jm"
        )
    )
    eod_exact = _eod_exact(
        checkpoint=checkpoint,
        heartbeat=eod_heartbeat,
        trading_day=trading_day,
            sampled_at=sampled_at,
            expected_authorization_hash=expected_eod_authorization_hash,
    )
    eod_status = (
        "passed"
        if eod_exact
        else "failed"
        if eod_heartbeat.get("status") == "failed"
        else "pending"
    )
    common = {
        "trading_day": trading_day,
        "sampled_at": sampled_at,
        "evaluated_bucket_ends": evaluated_bucket_ends,
        "partial_rejections": 0,
        "event_counts": event_counts,
        "notification_counts": notification_counts,
        "health": {
            "runtime": _runtime_health_exact(
                payload=runtime_heartbeat,
                sampled_at=sampled_at,
                parent_packet_hash=parent_packet_hash,
                trading_day=trading_day,
                last_expected_bucket_end=(
                    expected_bucket_ends[-1]
                    if expected_bucket_ends
                    and evaluated_bucket_ends == expected_bucket_ends
                    else None
                ),
            ),
            "redis": redis_ready,
            "database": True,
            "after_market": eod_exact,
        },
        "eod_status": eod_status,
    }
    if expected_bucket_ends is None:
        return build_ledger_sample(**common)
    _seal_or_restore_terminal_health(
        common=common,
        redis=redis,
        trading_day=trading_day,
        sampled_at=sampled_at,
        expected_bucket_ends=expected_bucket_ends,
        parent_packet_hash=str(parent_packet_hash or ""),
        terminal_seal_path=terminal_seal_path,
    )
    sample = build_remaining_window_ledger_sample(
        **common,
        expected_bucket_ends=expected_bucket_ends,
        activation_receipt_hash=str(activation_receipt_hash or ""),
    )
    if (
        not isinstance(expected_eod_authorization_hash, str)
        or len(expected_eod_authorization_hash) != 64
    ):
        raise ValueError("S610_EOD_AUTHORIZATION_BINDING_INVALID")
    sample["eod_authorization_hash"] = (
        expected_eod_authorization_hash
    )
    return sample


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


def _runtime_health_exact(
    *,
    payload: Mapping[str, Any],
    sampled_at: datetime,
    parent_packet_hash: str | None,
    trading_day: date,
    last_expected_bucket_end: str | None,
) -> bool:
    return bool(
        parent_packet_hash
        and _heartbeat_fresh(payload, sampled_at)
        and payload.get("signal_event_gate_schema") == "s6_10_schema_v7"
        and payload.get("signal_event_authorization_hash")
        == parent_packet_hash
        and payload.get("signal_event_target_trading_day")
        == trading_day.isoformat()
        and (
            last_expected_bucket_end is None
            or payload.get("signal_event_last_decision_bucket_end")
            == last_expected_bucket_end
        )
    )


def _service_heartbeat_exact(
    payload: Mapping[str, Any],
    *,
    service: str,
    parent_packet_hash: str,
    terminal_seal_path: Path | None,
    trading_day: date,
    sampled_at: datetime,
) -> bool:
    return bool(
        _heartbeat_fresh(payload, sampled_at)
        and payload.get("service") == service
        and payload.get("authorization_hash") == parent_packet_hash
        and payload.get("target_trading_day") == trading_day.isoformat()
    )


def _eod_exact(
    *,
    checkpoint: Any,
    heartbeat: Mapping[str, Any],
    trading_day: date,
    sampled_at: datetime,
    expected_authorization_hash: str | None = None,
) -> bool:
    return bool(
        checkpoint is not None
        and checkpoint.product == "jm"
        and checkpoint.last_successful_trading_day == trading_day
        and expected_authorization_hash is not None
        and checkpoint.authorization_hash == expected_authorization_hash
        and checkpoint.status in {"idle", "success", "waiting"}
        and _heartbeat_fresh(heartbeat, sampled_at)
        and heartbeat.get("status") != "failed"
    )


def _seal_or_restore_terminal_health(
    *,
    common: dict[str, Any],
    redis: Any,
    trading_day: date,
    sampled_at: datetime,
    expected_bucket_ends: list[str],
    parent_packet_hash: str,
    terminal_seal_path: Path | None,
) -> None:
    from app.services.htdy_s6_10_remaining_window import canonical_hash
    from app.services.htdy_s6_10_service_heartbeat import (
        DISPATCHER_HEARTBEAT_KEY,
        OBSERVER_HEARTBEAT_KEY,
        load_s610_terminal_seal,
        publish_s610_terminal_seal,
        terminal_seal_key,
    )

    if (
        len(expected_bucket_ends) != 23
        or common["evaluated_bucket_ends"] != expected_bucket_ends
    ):
        return
    observer = _heartbeat(redis, OBSERVER_HEARTBEAT_KEY)
    dispatcher = _heartbeat(redis, DISPATCHER_HEARTBEAT_KEY)
    live_services_ok = all(
        (
            _service_heartbeat_exact(
                observer,
                service="observer",
                parent_packet_hash=parent_packet_hash,
                trading_day=trading_day,
                sampled_at=sampled_at,
            ),
            _service_heartbeat_exact(
                dispatcher,
                service="dispatcher",
                parent_packet_hash=parent_packet_hash,
                trading_day=trading_day,
                sampled_at=sampled_at,
            ),
        )
    )
    if live_services_ok and common["health"]["runtime"]:
        publish_s610_terminal_seal(
            redis,
            authorization_hash=parent_packet_hash,
            target_trading_day=trading_day,
            last_decision_bucket_end=expected_bucket_ends[-1],
            observer_heartbeat=observer,
            dispatcher_heartbeat=dispatcher,
            sealed_at=sampled_at,
            seal_path=terminal_seal_path,
        )
    seal = _heartbeat(
        redis,
        terminal_seal_key(
            authorization_hash=parent_packet_hash,
            target_trading_day=trading_day,
        ),
    )
    if not seal and terminal_seal_path is not None:
        seal = load_s610_terminal_seal(terminal_seal_path)
    seal_hash = seal.get("seal_hash")
    seal_valid = bool(
        seal.get("schema_version") == 1
        and seal.get("authorization_hash") == parent_packet_hash
        and seal.get("target_trading_day") == trading_day.isoformat()
        and seal.get("last_decision_bucket_end") == expected_bucket_ends[-1]
        and isinstance(seal_hash, str)
        and canonical_hash(
            {key: value for key, value in seal.items() if key != "seal_hash"}
        )
        == seal_hash
    )
    common["health"]["runtime"] = bool(
        common["health"]["runtime"] and seal_valid
    )

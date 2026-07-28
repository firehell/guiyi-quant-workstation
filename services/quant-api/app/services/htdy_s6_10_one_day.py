"""Pure schema-v5 contract for one complete DCE trading-day observation."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
import hashlib
import json
from typing import Any, Mapping
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 5
TASK_ID = "JM-LIVE-STABILITY-S6-10"
PACKET_TYPE = "htdy_s6_10_one_day_parent"
SHANGHAI = ZoneInfo("Asia/Shanghai")


class HtDyS610OneDayError(RuntimeError):
    """Fail-closed schema-v5 contract violation."""


def canonical_hash(payload: Mapping[str, Any]) -> str:
    normalized = {
        str(key): deepcopy(value)
        for key, value in payload.items()
        if key not in {"packet_hash", "receipt_hash", "seal_hash"}
    }
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=lambda value: value.isoformat(),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_one_day_parent_packet(
    *,
    trading_day: date,
    night_session_date: date,
    generated_at: datetime,
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        generated_at.tzinfo is None
        or night_session_date >= trading_day
        or "backup_receipt_sha256" in bindings
        or "restore_receipt_sha256" in bindings
    ):
        raise HtDyS610OneDayError("one_day_window_invalid")
    frozen_bindings = deepcopy(dict(bindings))
    _validate_bindings(frozen_bindings)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "packet_type": PACKET_TYPE,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "trading_days": [trading_day.isoformat()],
        "night_session_date": night_session_date.isoformat(),
        "window_start": datetime(
            night_session_date.year,
            night_session_date.month,
            night_session_date.day,
            21,
            tzinfo=SHANGHAI,
        ).isoformat(),
        "window_end_trading_day": trading_day.isoformat(),
        "expected_confirmed_15m_closes": 23,
        "max_wecom_notifications": 23,
        "max_notification_attempts": 3,
        "backup_required": False,
        "disaster_recovery_ready": False,
        "strategy_identity": {
            "product": "jm",
            "period": "15m",
            "strategy_code": "htdy_original_realtime_first_seen",
            "strategy_version": "v1.1",
            "indicator_code": "huotian_dayou_original_v0",
            "indicator_version": "original-v0",
            "signal_policy": "htdy_original_xma_15m_close_first_seen_v1",
            "source_mode": "live_realtime_repainting",
            "decision_trigger": "confirmed_15m_close",
            "partial_allowed": False,
            "purpose": "observation_only",
            "future_looking": True,
            "repainting_accepted": True,
            "first_seen_no_retraction": True,
            "historical_backtest_allowed": False,
            "auto_order": False,
        },
        "bindings": frozen_bindings,
        "approval_required": "Approval C2",
        "authorization_consumed": False,
        "global_wechat_autosend_required": False,
        "bounded_delivery_only": True,
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def verify_one_day_parent_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_bindings: Mapping[str, Any],
    now: datetime,
    allow_started: bool = False,
) -> None:
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise HtDyS610OneDayError("schema_version_invalid")
    if packet.get("packet_type") != PACKET_TYPE:
        raise HtDyS610OneDayError("packet_type_invalid")
    if (
        packet.get("packet_hash") != approval_hash
        or canonical_hash(packet) != approval_hash
        or not _sha256(approval_hash)
    ):
        raise HtDyS610OneDayError("approval_hash_invalid")
    if now.tzinfo is None:
        raise HtDyS610OneDayError("now_timezone_required")
    window_start = datetime.fromisoformat(str(packet.get("window_start") or ""))
    if (
        not allow_started
        and now.astimezone(UTC) >= window_start.astimezone(UTC)
    ):
        raise HtDyS610OneDayError("window_already_started")
    _validate_bindings(current_bindings)
    if deepcopy(dict(current_bindings)) != packet.get("bindings"):
        raise HtDyS610OneDayError("parent_bindings_drift")
    if packet.get("authorization_consumed") is not False:
        raise HtDyS610OneDayError("authorization_consumed")


def finalize_one_day(
    *,
    expected_confirmed_closes: int,
    evaluated_confirmed_closes: int,
    partial_evaluations: int,
    signal_changed: int,
    duplicate_events: int,
    natural_events: int,
    sent_notifications: int,
    failed_notifications: int,
    eod_passed: bool,
) -> dict[str, Any]:
    stability = (
        expected_confirmed_closes == 23
        and evaluated_confirmed_closes == expected_confirmed_closes
        and partial_evaluations == 0
        and signal_changed == 0
        and duplicate_events == 0
        and failed_notifications == 0
        and eod_passed
    )
    natural_passed = (
        stability
        and natural_events > 0
        and sent_notifications == natural_events
    )
    if natural_passed:
        gate = "ONE_DAY_SIGNAL_AND_WECOM_PASSED"
    elif stability and natural_events == 0 and sent_notifications == 0:
        gate = "ONE_DAY_STABILITY_PASSED_NATURAL_SIGNAL_PENDING"
    else:
        gate = "ONE_DAY_STABILITY_FAILED"
    return {
        "gate": gate,
        "stability_passed": stability,
        "wecom_natural_event_passed": natural_passed,
        "disaster_recovery_ready": False,
    }


def _validate_bindings(bindings: Mapping[str, Any]) -> None:
    flags = bindings.get("feature_flags")
    if not isinstance(flags, Mapping):
        raise HtDyS610OneDayError("feature_flags_invalid")
    if flags.get("wechat_autosend") is not False:
        raise HtDyS610OneDayError("wechat_autosend_must_remain_false")
    if any(
        key in bindings
        for key in ("backup_receipt_sha256", "restore_receipt_sha256")
    ):
        raise HtDyS610OneDayError("backup_binding_forbidden")


def _sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()

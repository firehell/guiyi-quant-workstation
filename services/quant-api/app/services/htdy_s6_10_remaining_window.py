"""Schema-v7 contract for a bounded remainder of one DCE trading day."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from app.services.htdy_s6_10_one_day import _validate_bindings


SCHEMA_VERSION = 7
SUPPORTED_SCHEMA_VERSIONS = frozenset({6, 7})
TASK_ID = "JM-LIVE-STABILITY-S6-10"
PACKET_TYPE = "htdy_s6_10_remaining_trading_day_parent"
ACTIVATION_RECEIPT_TYPE = "htdy_s6_10_remaining_window_activation"
ACTIVATION_START_MARGIN_SECONDS = 180
SHANGHAI = ZoneInfo("Asia/Shanghai")


class HtDyS610RemainingWindowError(RuntimeError):
    """Fail-closed schema-v7 contract violation."""


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


def build_remaining_window_parent_packet(
    *,
    trading_day: date,
    night_session_date: date,
    generated_at: datetime,
    activation_deadline: datetime,
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        generated_at.tzinfo is None
        or activation_deadline.tzinfo is None
        or night_session_date >= trading_day
    ):
        raise HtDyS610RemainingWindowError("remaining_window_invalid")
    window_end = datetime.combine(
        trading_day,
        time(16),
        tzinfo=SHANGHAI,
    )
    if not generated_at < activation_deadline < window_end:
        raise HtDyS610RemainingWindowError("activation_deadline_invalid")
    frozen = deepcopy(dict(bindings))
    _validate_bindings(frozen)
    frozen_paths = frozen.get("artifact_paths")
    if (
        not isinstance(frozen_paths, Mapping)
        or not Path(
            str(
                frozen_paths.get(
                    "pre_activation_s6_07_enable_packet"
                )
                or ""
            )
        ).is_absolute()
        or not _sha256(
            frozen.get(
                "pre_activation_s6_07_enable_packet_sha256"
            )
        )
        or not _sha256(
            frozen.get("pre_activation_s6_07_enable_hash")
        )
        or not _commit(frozen.get("rollback_runtime_commit"))
        or not _sha256(frozen.get("rollback_runtime_tree"))
    ):
        raise HtDyS610RemainingWindowError(
            "pre_activation_s607_binding_invalid"
        )
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "packet_type": PACKET_TYPE,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "trading_days": [trading_day.isoformat()],
        "night_session_date": night_session_date.isoformat(),
        "window_mode": "remaining_trading_day",
        "activation_policy": "next_full_15m_bucket",
        "activation_start_margin_seconds": (
            ACTIVATION_START_MARGIN_SECONDS
        ),
        "activation_deadline": activation_deadline.isoformat(),
        "window_end": window_end.isoformat(),
        "maximum_confirmed_15m_closes": 23,
        "max_wecom_notifications": 23,
        "max_notification_attempts": 3,
        "backup_required": False,
        "disaster_recovery_ready": False,
        "complete_trading_day_claim_allowed": False,
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
        "bindings": frozen,
        "approval_required": "Approval C2",
        "authorization_consumed": False,
        "global_wechat_autosend_required": False,
        "bounded_delivery_only": True,
        "event_time_contract": {
            "signal_bar_field": "bar_end",
            "decision_close_field": (
                "formal_lineage.live_detection_snapshot."
                "decision_bucket_end"
            ),
            "delivery_window_field": "decision_bucket_end",
            "missing_decision_close_policy": "fail_closed",
        },
        "activation_state_contract": [
            "armed_signal_events_disabled",
            "activation_receipt_created",
            "activated_exact_gate_verified",
        ],
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def build_complete_day_parent_packet(
    *,
    trading_day: date,
    night_session_date: date,
    generated_at: datetime,
    activation_deadline: datetime,
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the clean 23-close acceptance parent used before Approval D."""

    night_start = datetime.combine(
        night_session_date,
        time(21),
        tzinfo=SHANGHAI,
    )
    if (
        generated_at.tzinfo is None
        or activation_deadline.tzinfo is None
        or generated_at.astimezone(SHANGHAI) >= night_start
        or activation_deadline.astimezone(SHANGHAI)
        > night_start - timedelta(minutes=15)
    ):
        raise HtDyS610RemainingWindowError(
            "complete_day_activation_window_invalid"
        )
    packet = build_remaining_window_parent_packet(
        trading_day=trading_day,
        night_session_date=night_session_date,
        generated_at=generated_at,
        activation_deadline=activation_deadline,
        bindings=bindings,
    )
    packet.pop("packet_hash", None)
    packet.update(
        {
            "window_mode": "complete_trading_day",
            "activation_policy": "before_first_full_15m_bucket",
            "complete_trading_day_claim_allowed": True,
        }
    )
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def verify_remaining_window_parent_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_bindings: Mapping[str, Any],
) -> None:
    if (
        packet.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS
        or packet.get("packet_type") != PACKET_TYPE
    ):
        raise HtDyS610RemainingWindowError("schema_or_packet_type_invalid")
    if (
        packet.get("packet_hash") != approval_hash
        or canonical_hash(packet) != approval_hash
    ):
        raise HtDyS610RemainingWindowError("approval_hash_invalid")
    verify_remaining_window_bindings(
        expected=packet.get("bindings"),
        observed=current_bindings,
        phase="post_activation",
    )
    if packet.get("authorization_consumed") is not False:
        raise HtDyS610RemainingWindowError("authorization_consumed")


def verify_remaining_window_bindings(
    *,
    expected: Any,
    observed: Any,
    phase: str,
) -> None:
    """Compare immutable bindings while making the activation phase explicit."""

    if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
        raise HtDyS610RemainingWindowError("parent_bindings_invalid")
    _validate_bindings(expected)
    _validate_bindings(observed)
    expected_copy = deepcopy(dict(expected))
    observed_copy = deepcopy(dict(observed))
    if phase == "pre_activation":
        observed_flags = observed_copy.pop("feature_flags", None)
        expected_copy.pop("feature_flags", None)
        if (
            not isinstance(observed_flags, Mapping)
            or observed_flags.get("live_runtime") is not True
            or observed_flags.get("signal_events") is not False
            or observed_flags.get("wechat_autosend") is not False
            or observed_flags.get("bounded_wecom_delivery") is not False
            or observed_flags.get("after_market_automation")
            not in {True, False}
            or set(observed_flags)
            != {
                "live_runtime",
                "signal_events",
                "wechat_autosend",
                "after_market_automation",
                "bounded_wecom_delivery",
            }
        ):
            raise HtDyS610RemainingWindowError(
                "pre_activation_flags_unsafe"
            )
        for key in ("runtime_commit", "runtime_tree"):
            pre_key = f"pre_activation_{key}"
            if pre_key in expected_copy:
                expected_copy[key] = expected_copy[pre_key]
            expected_copy.pop(pre_key, None)
            observed_copy.pop(pre_key, None)
    elif phase == "activation_ready":
        observed_flags = observed_copy.pop("feature_flags", None)
        expected_copy.pop("feature_flags", None)
        for key in (
            "pre_activation_runtime_commit",
            "pre_activation_runtime_tree",
        ):
            expected_copy.pop(key, None)
            observed_copy.pop(key, None)
        if observed_flags != {
            "live_runtime": True,
            "signal_events": False,
            "wechat_autosend": False,
            "after_market_automation": True,
            "bounded_wecom_delivery": False,
        }:
            raise HtDyS610RemainingWindowError(
                "activation_ready_flags_unsafe"
            )
    elif phase == "runtime_switched":
        observed_flags = observed_copy.pop("feature_flags", None)
        expected_copy.pop("feature_flags", None)
        for key in (
            "pre_activation_runtime_commit",
            "pre_activation_runtime_tree",
        ):
            expected_copy.pop(key, None)
            observed_copy.pop(key, None)
        if observed_flags != {
            "live_runtime": True,
            "signal_events": False,
            "wechat_autosend": False,
            "after_market_automation": False,
            "bounded_wecom_delivery": False,
        }:
            raise HtDyS610RemainingWindowError(
                "runtime_switched_flags_unsafe"
            )
    elif phase == "post_activation":
        for key in (
            "pre_activation_runtime_commit",
            "pre_activation_runtime_tree",
        ):
            expected_copy.pop(key, None)
            observed_copy.pop(key, None)
    else:
        raise HtDyS610RemainingWindowError("binding_phase_invalid")
    if observed_copy != expected_copy:
        differing = sorted(
            {
                *expected_copy.keys(),
                *observed_copy.keys(),
            }
            - {
                key
                for key in expected_copy
                if expected_copy.get(key) == observed_copy.get(key)
            }
        )
        raise HtDyS610RemainingWindowError(
            "parent_bindings_drift:" + ",".join(differing)
        )


def build_activation_receipt(
    *,
    parent_packet: Mapping[str, Any],
    activated_at: datetime,
) -> dict[str, Any]:
    if activated_at.tzinfo is None:
        raise HtDyS610RemainingWindowError("activation_timezone_required")
    deadline = datetime.fromisoformat(
        str(parent_packet.get("activation_deadline") or "")
    )
    if activated_at.astimezone(UTC) > deadline.astimezone(UTC):
        raise HtDyS610RemainingWindowError("activation_deadline_exceeded")
    trading_day = date.fromisoformat(str(parent_packet["trading_days"][0]))
    night_date = date.fromisoformat(str(parent_packet["night_session_date"]))
    start_margin_seconds = int(
        parent_packet.get("activation_start_margin_seconds", -1)
    )
    if not 0 <= start_margin_seconds <= 300:
        raise HtDyS610RemainingWindowError(
            "activation_start_margin_invalid"
        )
    expected = [
        bucket_end
        for bucket_end in _jm_15m_bucket_ends(night_date, trading_day)
        if bucket_end
        - timedelta(
            minutes=15,
            seconds=start_margin_seconds,
        )
        >= activated_at.astimezone(SHANGHAI)
    ]
    if not expected:
        raise HtDyS610RemainingWindowError("no_full_bucket_remaining")
    if (
        parent_packet.get("complete_trading_day_claim_allowed") is True
        and len(expected) != 23
    ):
        raise HtDyS610RemainingWindowError(
            "complete_day_bucket_coverage_invalid"
        )
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_type": ACTIVATION_RECEIPT_TYPE,
        "parent_packet_hash": parent_packet.get("packet_hash"),
        "activated_at": activated_at.astimezone(UTC).isoformat(),
        "activation_start_margin_seconds": start_margin_seconds,
        "first_expected_bucket_end": expected[0].isoformat(),
        "expected_bucket_ends": [value.isoformat() for value in expected],
        "expected_confirmed_15m_closes": len(expected),
        "complete_trading_day_passed": False,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    return receipt


def verify_activation_receipt(
    *,
    parent_packet: Mapping[str, Any],
    activation_receipt: Mapping[str, Any],
) -> None:
    if (
        activation_receipt.get("schema_version") != 1
        or activation_receipt.get("receipt_type") != ACTIVATION_RECEIPT_TYPE
        or activation_receipt.get("parent_packet_hash")
        != parent_packet.get("packet_hash")
        or activation_receipt.get("receipt_hash")
        != canonical_hash(activation_receipt)
    ):
        raise HtDyS610RemainingWindowError("activation_receipt_invalid")
    rebuilt = build_activation_receipt(
        parent_packet=parent_packet,
        activated_at=datetime.fromisoformat(
            str(activation_receipt.get("activated_at") or "")
        ),
    )
    if rebuilt != dict(activation_receipt):
        raise HtDyS610RemainingWindowError("activation_receipt_drift")


def verify_remaining_window_approval_times(
    *,
    parent_packet: Mapping[str, Any],
    activation_receipt: Mapping[str, Any],
    approved_at: datetime,
) -> None:
    if approved_at.tzinfo is None:
        raise HtDyS610RemainingWindowError("approval_timezone_required")
    activated_at = datetime.fromisoformat(
        str(activation_receipt.get("activated_at") or "")
    )
    if approved_at.astimezone(UTC) >= activated_at.astimezone(UTC):
        raise HtDyS610RemainingWindowError(
            "approval_not_before_activation"
        )
    deadline = datetime.fromisoformat(
        str(parent_packet.get("activation_deadline") or "")
    )
    if activated_at.astimezone(UTC) > deadline.astimezone(UTC):
        raise HtDyS610RemainingWindowError("activation_deadline_exceeded")


def verify_activation_start_margin(
    *,
    activation_receipt: Mapping[str, Any],
    now: datetime,
    minimum_seconds: int = 180,
) -> None:
    if now.tzinfo is None or not 0 <= minimum_seconds <= 300:
        raise HtDyS610RemainingWindowError(
            "activation_start_margin_invalid"
        )
    first_end = datetime.fromisoformat(
        str(activation_receipt.get("first_expected_bucket_end") or "")
    )
    first_start = first_end - timedelta(minutes=15)
    if now.astimezone(UTC) >= (
        first_start.astimezone(UTC)
        - timedelta(seconds=minimum_seconds)
    ):
        raise HtDyS610RemainingWindowError(
            "activation_start_margin_exhausted"
        )


def finalize_remaining_window(
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
        0 < expected_confirmed_closes <= 23
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
        gate = "REMAINING_TRADING_DAY_SIGNAL_AND_WECOM_PASSED"
    elif stability and natural_events == 0 and sent_notifications == 0:
        gate = (
            "REMAINING_TRADING_DAY_STABILITY_PASSED_"
            "NATURAL_SIGNAL_PENDING"
        )
    else:
        gate = "REMAINING_TRADING_DAY_STABILITY_FAILED"
    return {
        "gate": gate,
        "stability_passed": stability,
        "wecom_natural_event_passed": natural_passed,
        "complete_trading_day_passed": False,
        "disaster_recovery_ready": False,
    }


def _jm_15m_bucket_ends(
    night_session_date: date,
    trading_day: date,
) -> list[datetime]:
    session_ranges = (
        (
            datetime.combine(night_session_date, time(21), tzinfo=SHANGHAI),
            datetime.combine(night_session_date, time(23), tzinfo=SHANGHAI),
        ),
        (
            datetime.combine(trading_day, time(9), tzinfo=SHANGHAI),
            datetime.combine(trading_day, time(10, 15), tzinfo=SHANGHAI),
        ),
        (
            datetime.combine(trading_day, time(10, 30), tzinfo=SHANGHAI),
            datetime.combine(trading_day, time(11, 30), tzinfo=SHANGHAI),
        ),
        (
            datetime.combine(trading_day, time(13, 30), tzinfo=SHANGHAI),
            datetime.combine(trading_day, time(15), tzinfo=SHANGHAI),
        ),
    )
    ends: list[datetime] = []
    for start, end in session_ranges:
        cursor = start + timedelta(minutes=15)
        while cursor <= end:
            ends.append(cursor)
            cursor += timedelta(minutes=15)
    return ends


def _sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _commit(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 40:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()

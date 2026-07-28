from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime

import pytest


SHA = "a" * 64
DAY = date(2026, 7, 29)


def _bindings() -> dict[str, object]:
    return {
        "runtime_commit": "b" * 40,
        "runtime_tree": SHA,
        "runtime_tracked_clean": True,
        "source_commit": "c" * 40,
        "source_tree": SHA,
        "database_revision": "20260721_0025",
        "profile_sha256": SHA,
        "indicator_source_sha256": SHA,
        "policy_sha256": SHA,
        "s6_07_receipt_sha256": SHA,
        "s6_08_receipt_sha256": SHA,
        "s6_09_receipt_sha256": SHA,
        "calendar_sha256": SHA,
        "launchd_sha256": SHA,
        "observer_launchd_sha256": SHA,
        "delivery_launchd_sha256": SHA,
        "deployment_packet_sha256": SHA,
        "approval_c2_approved_signers_sha256": SHA,
        "feature_flags": {
            "live_runtime": True,
            "signal_events": False,
            "wechat_autosend": False,
            "after_market_automation": False,
            "bounded_wecom_delivery": False,
        },
        "baseline_counts": {
            "signal_events": 4,
            "signal_notifications": 2,
            "review_notes": 0,
            "orders": 0,
            "trades": 0,
        },
        "baseline_hashes": {
            "profile_bindings": SHA,
            "canonical_assets": SHA,
            "forbidden_tables": SHA,
        },
        "baseline_max_ids": {
            "signal_events": 4,
            "signal_notifications": 2,
            "review_notes": 0,
            "orders": 0,
            "trades": 0,
        },
    }


def _parent() -> dict[str, object]:
    from app.services.htdy_s6_10_one_day import build_one_day_parent_packet

    return build_one_day_parent_packet(
        trading_day=DAY,
        night_session_date=date(2026, 7, 28),
        generated_at=datetime(2026, 7, 28, 2, tzinfo=UTC),
        bindings=_bindings(),
    )


def test_schema_v5_parent_is_one_day_and_does_not_bind_backup() -> None:
    """Break caught: reusing the old five-day/backup contract."""

    from app.services.htdy_s6_10_one_day import (
        canonical_hash,
        verify_one_day_parent_packet,
    )

    parent = _parent()
    assert parent["schema_version"] == 5
    assert parent["packet_type"] == "htdy_s6_10_one_day_parent"
    assert parent["trading_days"] == ["2026-07-29"]
    assert parent["expected_confirmed_15m_closes"] == 23
    assert parent["max_wecom_notifications"] == 23
    assert parent["backup_required"] is False
    assert parent["disaster_recovery_ready"] is False
    assert "backup_receipt_sha256" not in parent["bindings"]
    assert parent["strategy_identity"] == {
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
    }
    assert parent["packet_hash"] == canonical_hash(parent)
    verify_one_day_parent_packet(
        parent,
        approval_hash=str(parent["packet_hash"]),
        current_bindings=_bindings(),
        now=datetime(2026, 7, 28, 3, tzinfo=UTC),
    )


def test_schema_v5_parent_rejects_old_approval_and_binding_drift() -> None:
    """Break caught: accepting schema-v4 authorization or autosend drift."""

    from app.services.htdy_s6_10_one_day import (
        HtDyS610OneDayError,
        canonical_hash,
        verify_one_day_parent_packet,
    )

    parent = _parent()
    old = deepcopy(parent)
    old["schema_version"] = 4
    old["packet_hash"] = canonical_hash(old)
    with pytest.raises(HtDyS610OneDayError, match="schema_version_invalid"):
        verify_one_day_parent_packet(
            old,
            approval_hash=str(old["packet_hash"]),
            current_bindings=_bindings(),
            now=datetime(2026, 7, 28, 3, tzinfo=UTC),
        )

    drift = _bindings()
    drift["feature_flags"] = {
        **dict(drift["feature_flags"]),
        "wechat_autosend": True,
    }
    with pytest.raises(HtDyS610OneDayError, match="wechat_autosend"):
        verify_one_day_parent_packet(
            parent,
            approval_hash=str(parent["packet_hash"]),
            current_bindings=drift,
            now=datetime(2026, 7, 28, 3, tzinfo=UTC),
        )


def test_one_day_finalize_distinguishes_missing_natural_signal() -> None:
    """Break caught: claiming live WeCom passed when no natural event exists."""

    from app.services.htdy_s6_10_one_day import finalize_one_day

    pending = finalize_one_day(
        expected_confirmed_closes=23,
        evaluated_confirmed_closes=23,
        partial_evaluations=0,
        signal_changed=0,
        duplicate_events=0,
        natural_events=0,
        sent_notifications=0,
        failed_notifications=0,
        eod_passed=True,
    )
    passed = finalize_one_day(
        expected_confirmed_closes=23,
        evaluated_confirmed_closes=23,
        partial_evaluations=0,
        signal_changed=0,
        duplicate_events=0,
        natural_events=1,
        sent_notifications=1,
        failed_notifications=0,
        eod_passed=True,
    )

    assert pending["gate"] == (
        "ONE_DAY_STABILITY_PASSED_NATURAL_SIGNAL_PENDING"
    )
    assert pending["wecom_natural_event_passed"] is False
    assert passed["gate"] == "ONE_DAY_SIGNAL_AND_WECOM_PASSED"
    assert passed["wecom_natural_event_passed"] is True


def test_one_day_ledger_counts_unique_closes_and_freezes_no_partial() -> None:
    from app.services.htdy_s6_10_one_day_ledger import build_ledger_sample

    sample = build_ledger_sample(
        trading_day=DAY,
        sampled_at=datetime(2026, 7, 29, 8, tzinfo=UTC),
        evaluated_bucket_ends=[
            "2026-07-28T21:15:00+08:00",
            "2026-07-28T21:30:00+08:00",
        ],
        partial_rejections=8,
        event_counts={"created": 0, "unchanged": 0, "signal_changed": 0},
        notification_counts={"sent": 0, "duplicate": 0, "capped": 0},
        health={
            "runtime": True,
            "redis": True,
            "database": True,
            "after_market": True,
        },
        eod_status="pending",
    )

    assert sample["expected_confirmed_15m_closes"] == 23
    assert sample["evaluated_confirmed_15m_closes"] == 2
    assert sample["partial_evaluations"] == 0
    assert sample["partial_rejections"] == 8
    assert sample["disaster_recovery_ready"] is False

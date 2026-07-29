from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
import json

import pytest


DAY = date(2026, 7, 29)
SHA = "a" * 64


def _bindings() -> dict[str, object]:
    return {
        "runtime_commit": "b" * 40,
        "runtime_tree": SHA,
        "runtime_tracked_clean": True,
        "source_commit": "c" * 40,
        "source_tree": SHA,
        "parent_packet_path": "/tmp/parent_packet.json",
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
        "s6_07_rebind_packet_sha256": SHA,
        "s6_07_enable_packet_sha256": SHA,
        "approval_c2_approved_signers_sha256": SHA,
        "pre_activation_s6_07_enable_packet_sha256": SHA,
        "pre_activation_s6_07_enable_hash": SHA,
        "rollback_runtime_commit": "d" * 40,
        "rollback_runtime_tree": SHA,
        "artifact_paths": {
            "s6_07_rebind_packet": "/tmp/s6_07_rebind_packet.json",
            "s6_07_enable_packet": "/tmp/s6_07_enable_packet.json",
            "pre_activation_s6_07_enable_packet": (
                "/tmp/pre_activation_s6_07_enable_packet.json"
            ),
        },
        "feature_flags": {
            "live_runtime": True,
            "signal_events": True,
            "wechat_autosend": False,
            "after_market_automation": True,
            "bounded_wecom_delivery": True,
        },
        "baseline_counts": {},
        "baseline_hashes": {},
        "baseline_max_ids": {},
    }


def _parent() -> dict[str, object]:
    from app.services.htdy_s6_10_remaining_window import (
        build_remaining_window_parent_packet,
    )

    return build_remaining_window_parent_packet(
        trading_day=DAY,
        night_session_date=date(2026, 7, 28),
        generated_at=datetime(2026, 7, 28, 14, 5, tzinfo=UTC),
        activation_deadline=datetime(2026, 7, 29, 6, 30, tzinfo=UTC),
        bindings=_bindings(),
    )


def test_schema_v6_activation_skips_in_progress_bucket_and_lists_remaining() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        build_activation_receipt,
        canonical_hash,
    )

    parent = _parent()
    activation = build_activation_receipt(
        parent_packet=parent,
        activated_at=datetime(2026, 7, 28, 14, 6, tzinfo=UTC),
    )

    assert parent["schema_version"] == 6
    assert parent["window_mode"] == "remaining_trading_day"
    assert parent["activation_policy"] == "next_full_15m_bucket"
    assert activation["first_expected_bucket_end"] == (
        "2026-07-28T22:30:00+08:00"
    )
    assert "2026-07-28T22:15:00+08:00" not in activation[
        "expected_bucket_ends"
    ]
    assert activation["expected_bucket_ends"][-1] == (
        "2026-07-29T15:00:00+08:00"
    )
    assert activation["expected_confirmed_15m_closes"] == 18
    assert activation["receipt_hash"] == canonical_hash(activation)


def test_schema_v6_activation_skips_bucket_without_startup_margin() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        build_activation_receipt,
        verify_activation_start_margin,
    )

    activation = build_activation_receipt(
        parent_packet=_parent(),
        activated_at=datetime(
            2026,
            7,
            29,
            3,
            12,
            39,
            tzinfo=UTC,
        ),
    )

    assert activation["activation_start_margin_seconds"] == 180
    assert activation["first_expected_bucket_end"] == (
        "2026-07-29T13:45:00+08:00"
    )
    assert "2026-07-29T11:30:00+08:00" not in activation[
        "expected_bucket_ends"
    ]
    verify_activation_start_margin(
        activation_receipt=activation,
        now=datetime(2026, 7, 29, 3, 12, 39, tzinfo=UTC),
    )


def test_schema_v6_rejects_activation_after_deadline() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        HtDyS610RemainingWindowError,
        build_activation_receipt,
    )

    with pytest.raises(
        HtDyS610RemainingWindowError,
        match="activation_deadline_exceeded",
    ):
        build_activation_receipt(
            parent_packet=_parent(),
            activated_at=datetime(2026, 7, 29, 6, 31, tzinfo=UTC),
        )


def test_schema_v6_approval_may_follow_2100_but_must_precede_activation() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        HtDyS610RemainingWindowError,
        verify_remaining_window_approval_times,
    )

    activation = {
        "activated_at": "2026-07-28T14:06:00+00:00",
    }
    verify_remaining_window_approval_times(
        parent_packet=_parent(),
        activation_receipt=activation,
        approved_at=datetime(2026, 7, 28, 14, 5, tzinfo=UTC),
    )
    with pytest.raises(
        HtDyS610RemainingWindowError,
        match="approval_not_before_activation",
    ):
        verify_remaining_window_approval_times(
            parent_packet=_parent(),
            activation_receipt=activation,
            approved_at=datetime(2026, 7, 28, 14, 7, tzinfo=UTC),
        )


def test_schema_v6_finalization_never_claims_complete_one_day() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        finalize_remaining_window,
    )

    result = finalize_remaining_window(
        expected_confirmed_closes=18,
        evaluated_confirmed_closes=18,
        partial_evaluations=0,
        signal_changed=0,
        duplicate_events=0,
        natural_events=0,
        sent_notifications=0,
        failed_notifications=0,
        eod_passed=True,
    )

    assert result["gate"] == (
        "REMAINING_TRADING_DAY_STABILITY_PASSED_NATURAL_SIGNAL_PENDING"
    )
    assert result["complete_trading_day_passed"] is False


def test_schema_v6_runtime_gate_uses_activation_bucket_allowlist(
    tmp_path,
) -> None:
    from app.services.htdy_s6_10_remaining_window_runtime_gate import (
        HtDyS610RemainingWindowRuntimeGate,
    )

    parent = _parent()
    parent_path = tmp_path / "parent.json"
    activation_path = tmp_path / "activation.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    from app.services.htdy_s6_10_remaining_window import (
        build_activation_receipt,
    )

    activation = build_activation_receipt(
        parent_packet=parent,
        activated_at=datetime(2026, 7, 28, 14, 6, tzinfo=UTC),
    )
    activation_path.write_text(json.dumps(activation), encoding="utf-8")
    captured: dict[str, object] = {}

    def handler_factory(_session, *, allowed_bucket_ends):
        captured["allowed"] = allowed_bucket_ends
        return object()

    gate = HtDyS610RemainingWindowRuntimeGate(
        parent_packet_path=parent_path,
        approval_hash=str(parent["packet_hash"]),
        activation_receipt_path=activation_path,
        current_bindings=lambda _session, phase: _bindings(),
        handler_factory=handler_factory,
        trading_day_resolver=lambda *_args: DAY,
        approval_c2_verifier=lambda _activation: None,
        now=lambda: datetime(2026, 7, 28, 14, 31, tzinfo=UTC),
    )

    result = gate(object(), phase="pre_write")

    assert result["gate_status"] == "authorized"
    assert captured["allowed"] == {
        datetime.fromisoformat(value)
        for value in activation["expected_bucket_ends"]
    }


def test_schema_v6_post_write_accepts_idle_cycle_without_signal_result() -> None:
    from app.services.htdy_s6_10_remaining_window_runtime_gate import (
        HtDyS610RemainingWindowRuntimeGate,
    )

    gate = object.__new__(HtDyS610RemainingWindowRuntimeGate)
    gate.approval_hash = SHA
    gate.activation_receipt = {"receipt_hash": "b" * 64}
    gate.parent_packet = {"trading_days": [DAY.isoformat()]}

    result = gate(
        object(),
        phase="post_write",
        result={"signal_events": None},
    )

    assert result["gate_status"] == "authorized"


def test_schema_v6_post_write_rejects_signal_changed_result() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        HtDyS610RemainingWindowError,
    )
    from app.services.htdy_s6_10_remaining_window_runtime_gate import (
        HtDyS610RemainingWindowRuntimeGate,
    )

    gate = object.__new__(HtDyS610RemainingWindowRuntimeGate)
    gate.approval_hash = SHA
    gate.activation_receipt = {"receipt_hash": "b" * 64}
    gate.parent_packet = {"trading_days": [DAY.isoformat()]}

    with pytest.raises(
        HtDyS610RemainingWindowError,
        match="signal_changed_forbidden",
    ):
        gate(
            object(),
            phase="post_write",
            result={"signal_events": {"changed": 1}},
        )


def test_binding_phases_distinguish_safe_pre_activation_from_enabled_runtime() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        HtDyS610RemainingWindowError,
        verify_remaining_window_bindings,
    )

    expected = _bindings()
    pre_activation = deepcopy(expected)
    pre_activation["feature_flags"] = {
        "live_runtime": True,
        "signal_events": False,
        "wechat_autosend": False,
        "after_market_automation": False,
        "bounded_wecom_delivery": False,
    }
    verify_remaining_window_bindings(
        expected=expected,
        observed=pre_activation,
        phase="pre_activation",
    )
    verify_remaining_window_bindings(
        expected=expected,
        observed=expected,
        phase="post_activation",
    )

    unsafe = deepcopy(pre_activation)
    unsafe["feature_flags"]["signal_events"] = True
    with pytest.raises(
        HtDyS610RemainingWindowError,
        match="pre_activation_flags_unsafe",
    ):
        verify_remaining_window_bindings(
            expected=expected,
            observed=unsafe,
            phase="pre_activation",
        )


def test_activation_margin_prevents_backfill_if_startup_crosses_bucket_open() -> None:
    from app.services.htdy_s6_10_remaining_window import (
        HtDyS610RemainingWindowError,
        verify_activation_start_margin,
    )

    activation = {
        "first_expected_bucket_end": "2026-07-29T09:15:00+08:00",
    }
    verify_activation_start_margin(
        activation_receipt=activation,
        now=datetime(2026, 7, 29, 0, 56, tzinfo=UTC),
    )
    with pytest.raises(
        HtDyS610RemainingWindowError,
        match="activation_start_margin_exhausted",
    ):
        verify_activation_start_margin(
            activation_receipt=activation,
            now=datetime(2026, 7, 29, 0, 59, 31, tzinfo=UTC),
        )

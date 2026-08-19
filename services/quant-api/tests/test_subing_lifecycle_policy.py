from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.subing_lifecycle_policy import (
    SubingLifecyclePolicyError,
    load_subing_lifecycle_policy,
)


def _valid_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_id": "subing_lifecycle_v2_research_v1",
        "formula_version": "subing_lifecycle_v2",
        "research_only": True,
        "supported_timeframes": ["5m", "15m"],
        "clock_timeframe": "5m",
        "trend_anchor_timeframe": "15m",
        "setup": {
            "requires_both_timeframes": True,
            "calibration_id": "subing_intraday_v1",
        },
        "pivot": {
            "source_timeframe": "5m",
            "left_span": 2,
            "right_span": 2,
            "tie_policy": "reject",
            "same_trading_day_only": True,
            "breakout_basis": "close_cross",
        },
        "entry_confirmation": {
            "hold_required_bars": 3,
            "hold_count_includes_trigger_bar": True,
            "retest_rebreak_max_bars": 3,
            "unavailable_boundary_policy": "pause",
            "trigger_priority": ["formal_v1", "pivot_break", "macd_cross"],
        },
        "risk": {
            "lower_tf_consecutive_bars": 2,
            "anchor_soft_risk_immediate": True,
            "recovery_requires_completed_15m": True,
        },
        "trading_day": {
            "unconfirmed_setup_cross_trading_day": False,
            "confirmed_opportunity_cross_trading_day": True,
        },
    }


def _write_payload(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _set_path(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    target: dict[str, Any] = payload
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value


def test_load_exact_lifecycle_policy() -> None:
    policy = load_subing_lifecycle_policy()

    assert policy.policy_id == "subing_lifecycle_v2_research_v1"
    assert policy.formula_version == "subing_lifecycle_v2"
    assert policy.research_only is True
    assert policy.supported_timeframes == (BarFrequency.M5, BarFrequency.M15)
    assert policy.clock_timeframe is BarFrequency.M5
    assert policy.trend_anchor_timeframe is BarFrequency.M15
    assert policy.hold_required_bars == 3
    assert policy.retest_rebreak_max_bars == 3
    assert policy.lower_tf_risk_consecutive_bars == 2
    assert (policy.pivot_left_span, policy.pivot_right_span) == (2, 2)
    assert policy.pivot_tie_policy == "reject"


def test_lifecycle_policy_is_immutable() -> None:
    policy = load_subing_lifecycle_policy()

    with pytest.raises(FrozenInstanceError):
        policy.hold_required_bars = 4  # type: ignore[misc]


def test_missing_lifecycle_policy_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SubingLifecyclePolicyError, match="SUBING_LIFECYCLE_POLICY_INVALID"):
        load_subing_lifecycle_policy(tmp_path / "missing.json")


def test_malformed_lifecycle_policy_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(SubingLifecyclePolicyError, match="SUBING_LIFECYCLE_POLICY_INVALID"):
        load_subing_lifecycle_policy(path)


@pytest.mark.parametrize(
    ("container_path", "key"),
    (
        ((), "formula_version"),
        (("setup",), "calibration_id"),
        (("pivot",), "breakout_basis"),
        (("entry_confirmation",), "hold_required_bars"),
        (("risk",), "anchor_soft_risk_immediate"),
        (("trading_day",), "confirmed_opportunity_cross_trading_day"),
    ),
)
def test_missing_policy_key_fails_closed(
    tmp_path: Path,
    container_path: tuple[str, ...],
    key: str,
) -> None:
    payload = _valid_payload()
    target: dict[str, Any] = payload
    for part in container_path:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    del target[key]
    path = tmp_path / "policy.json"
    _write_payload(path, payload)

    with pytest.raises(SubingLifecyclePolicyError, match="SUBING_LIFECYCLE_POLICY_INVALID"):
        load_subing_lifecycle_policy(path)


@pytest.mark.parametrize(
    "container_path",
    ((), ("setup",), ("pivot",), ("entry_confirmation",), ("risk",), ("trading_day",)),
)
def test_extra_policy_key_fails_closed(
    tmp_path: Path,
    container_path: tuple[str, ...],
) -> None:
    payload = _valid_payload()
    target: dict[str, Any] = payload
    for part in container_path:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target["unexpected"] = True
    path = tmp_path / "policy.json"
    _write_payload(path, payload)

    with pytest.raises(SubingLifecyclePolicyError, match="SUBING_LIFECYCLE_POLICY_INVALID"):
        load_subing_lifecycle_policy(path)


@pytest.mark.parametrize(
    ("field_path", "invalid"),
    (
        (("schema_version",), 2),
        (("schema_version",), True),
        (("policy_id",), "subing_lifecycle_v2_research_v2"),
        (("formula_version",), "subing_lifecycle_v3"),
        (("research_only",), False),
        (("supported_timeframes",), ["15m", "5m"]),
        (("supported_timeframes",), ["5m", "30m"]),
        (("clock_timeframe",), "15m"),
        (("trend_anchor_timeframe",), "5m"),
        (("setup", "requires_both_timeframes"), False),
        (("setup", "calibration_id"), "subing_intraday_v2"),
        (("pivot", "source_timeframe"), "15m"),
        (("pivot", "left_span"), 3),
        (("pivot", "left_span"), 2.0),
        (("pivot", "right_span"), 3),
        (("pivot", "tie_policy"), "first"),
        (("pivot", "same_trading_day_only"), False),
        (("pivot", "breakout_basis"), "intrabar"),
        (("entry_confirmation", "hold_required_bars"), 2),
        (("entry_confirmation", "hold_required_bars"), 3.0),
        (("entry_confirmation", "hold_count_includes_trigger_bar"), False),
        (("entry_confirmation", "retest_rebreak_max_bars"), 4),
        (("entry_confirmation", "unavailable_boundary_policy"), "reset"),
        (("entry_confirmation", "trigger_priority"), ["pivot_break", "formal_v1", "macd_cross"]),
        (("risk", "lower_tf_consecutive_bars"), 3),
        (("risk", "anchor_soft_risk_immediate"), False),
        (("risk", "recovery_requires_completed_15m"), False),
        (("trading_day", "unconfirmed_setup_cross_trading_day"), True),
        (("trading_day", "confirmed_opportunity_cross_trading_day"), False),
    ),
)
def test_same_id_policy_semantic_drift_fails_closed(
    tmp_path: Path,
    field_path: tuple[str, ...],
    invalid: object,
) -> None:
    payload = _valid_payload()
    _set_path(payload, field_path, invalid)
    path = tmp_path / "policy.json"
    _write_payload(path, payload)

    with pytest.raises(SubingLifecyclePolicyError, match="SUBING_LIFECYCLE_POLICY_INVALID"):
        load_subing_lifecycle_policy(path)

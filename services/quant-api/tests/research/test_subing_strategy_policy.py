from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.market_data.subing_strategy.policy import (
    SubingStrategyPolicy,
    SubingStrategyPolicyError,
    load_subing_strategy_policy,
)


EXACT_POLICY_PAYLOAD = {
    "schema_version": 1,
    "strategy_id": "subing_strategy_v1",
    "formula_version": "subing_strategy_15m_v1",
    "research_only": True,
    "series_kind": "actual_dominant",
    "decision_frequency": "15m",
    "direction_context": {
        "projection_version": "subing_daily_watch_v2",
        "formula_version": "subing_ema21_rank1_stitched_raw_v2",
        "history_mode": "rank1_stitched_raw",
        "require_d1_h1_alignment": True,
        "allow_context_late_retroactive_entry": False,
        "context_change_exits_position": False,
    },
    "entry": {
        "lifecycle_policy_id": "subing_lifecycle_v2_research_v1",
        "allowed_confirmation_sources": [
            "formal_v1",
            "momentum_hold",
            "pivot_break_hold",
            "pivot_retest_rebreak",
        ],
        "window_projection": (
            "first_confirmation_after_previous_15m_through_current_15m"
        ),
        "cancel_when_window_ends_exit_risk_or_closed": True,
        "one_entry_per_opportunity_key": True,
    },
    "execution": {
        "decision_basis": "completed_15m_close",
        "effective_fill_basis": "next_existing_same_segment_15m_open",
        "marker_anchor": "effective_bar_end",
        "allow_session_gap": True,
        "allow_overnight": True,
        "allow_reverse": False,
        "allow_same_effective_bar_reentry": False,
    },
    "exit": {
        "logic": "any",
        "ema21": "close_beyond_ema21",
        "previous_bar": "close_beyond_previous_15m_extreme",
        "structure": "close_beyond_bound_lifecycle_pivot_when_available",
        "macd": "high_dead_cross_for_long_low_golden_cross_for_short",
        "preserve_all_same_bar_reason_codes": True,
    },
    "segment": {
        "carry_position_across_segment": False,
        "terminal_position_fill_basis": "last_15m_close",
        "terminal_reason": "CONTRACT_SEGMENT_END",
    },
}


def test_loads_exact_subing_strategy_v1_policy() -> None:
    policy = load_subing_strategy_policy()

    assert policy.strategy_id == "subing_strategy_v1"
    assert policy.formula_version == "subing_strategy_15m_v1"
    assert policy.research_only is True
    assert policy.series_kind.value == "actual_dominant"
    assert policy.decision_frequency.value == "15m"
    assert policy.lifecycle_policy_id == "subing_lifecycle_v2_research_v1"
    assert tuple(source.value for source in policy.allowed_confirmation_sources) == (
        "formal_v1",
        "momentum_hold",
        "pivot_break_hold",
        "pivot_retest_rebreak",
    )


def test_policy_rejects_one_changed_field(tmp_path: Path) -> None:
    payload = deepcopy(EXACT_POLICY_PAYLOAD)
    payload["execution"]["allow_reverse"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SubingStrategyPolicyError) as exc:
        load_subing_strategy_policy(path)

    assert exc.value.code == "SUBING_STRATEGY_POLICY_INVALID"


def test_policy_dataclass_rejects_non_v1_values() -> None:
    policy = load_subing_strategy_policy()

    with pytest.raises(SubingStrategyPolicyError):
        SubingStrategyPolicy(
            strategy_id=policy.strategy_id,
            formula_version="subing_strategy_15m_v2",
            research_only=policy.research_only,
            series_kind=policy.series_kind,
            decision_frequency=policy.decision_frequency,
            lifecycle_policy_id=policy.lifecycle_policy_id,
            allowed_confirmation_sources=policy.allowed_confirmation_sources,
        )

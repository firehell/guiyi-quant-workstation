"""Exact immutable policy contract for SuBing Strategy V1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.env import PROJECT_ROOT
from app.core.exact_json_contract import load_exact_json

from ..domain import BarFrequency, SeriesKind
from ..subing_lifecycle import ConfirmationSource


_POLICY_PATH = PROJECT_ROOT / "data/research_policies/subing_strategy_v1.json"
_STRATEGY_ID = "subing_strategy_v1"
_FORMULA_VERSION = "subing_strategy_15m_v1"
_LIFECYCLE_POLICY_ID = "subing_lifecycle_v2_research_v1"
_CONFIRMATION_SOURCES = (
    ConfirmationSource.FORMAL_V1,
    ConfirmationSource.MOMENTUM_HOLD,
    ConfirmationSource.PIVOT_BREAK_HOLD,
    ConfirmationSource.PIVOT_RETEST_REBREAK,
)
_EXPECTED_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "strategy_id": _STRATEGY_ID,
    "formula_version": _FORMULA_VERSION,
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
        "lifecycle_policy_id": _LIFECYCLE_POLICY_ID,
        "allowed_confirmation_sources": [source.value for source in _CONFIRMATION_SOURCES],
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


class SubingStrategyPolicyError(ValueError):
    code = "SUBING_STRATEGY_POLICY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyPolicy:
    strategy_id: str
    formula_version: str
    research_only: bool
    series_kind: SeriesKind
    decision_frequency: BarFrequency
    lifecycle_policy_id: str
    allowed_confirmation_sources: tuple[ConfirmationSource, ...]

    def __post_init__(self) -> None:
        if (
            self.strategy_id != _STRATEGY_ID
            or self.formula_version != _FORMULA_VERSION
            or self.research_only is not True
            or self.series_kind is not SeriesKind.ACTUAL_DOMINANT
            or self.decision_frequency is not BarFrequency.M15
            or self.lifecycle_policy_id != _LIFECYCLE_POLICY_ID
            or self.allowed_confirmation_sources != _CONFIRMATION_SOURCES
        ):
            raise SubingStrategyPolicyError()


def load_subing_strategy_policy(path: Path | None = None) -> SubingStrategyPolicy:
    payload = load_exact_json(
        path or _POLICY_PATH,
        _EXPECTED_PAYLOAD,
        SubingStrategyPolicyError,
    )
    return SubingStrategyPolicy(
        strategy_id=payload["strategy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
        series_kind=SeriesKind(payload["series_kind"]),
        decision_frequency=BarFrequency(payload["decision_frequency"]),
        lifecycle_policy_id=payload["entry"]["lifecycle_policy_id"],
        allowed_confirmation_sources=tuple(
            ConfirmationSource(value)
            for value in payload["entry"]["allowed_confirmation_sources"]
        ),
    )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.env import PROJECT_ROOT

from .domain import BarFrequency
from app.core.exact_json_contract import load_exact_json


_SUBING_LIFECYCLE_POLICY_PATH = (
    PROJECT_ROOT / "data/research_policies/subing_lifecycle_v2_research_v1.json"
)
_POLICY_ID = "subing_lifecycle_v2_research_v1"
_FORMULA_VERSION = "subing_lifecycle_v2_structure_binding_v1"
_SUPPORTED_TIMEFRAMES = (BarFrequency.M5, BarFrequency.M15)
_EXPECTED_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "policy_id": _POLICY_ID,
    "formula_version": _FORMULA_VERSION,
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


class SubingLifecyclePolicyError(ValueError):
    code = "SUBING_LIFECYCLE_POLICY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingLifecyclePolicy:
    policy_id: str
    formula_version: str
    research_only: bool
    supported_timeframes: tuple[BarFrequency, BarFrequency]
    clock_timeframe: BarFrequency
    trend_anchor_timeframe: BarFrequency
    hold_required_bars: int
    retest_rebreak_max_bars: int
    lower_tf_risk_consecutive_bars: int
    pivot_left_span: int
    pivot_right_span: int
    pivot_tie_policy: str

    def __post_init__(self) -> None:
        if (
            self.policy_id != _POLICY_ID
            or self.formula_version != _FORMULA_VERSION
            or self.research_only is not True
            or self.supported_timeframes != _SUPPORTED_TIMEFRAMES
            or self.clock_timeframe is not BarFrequency.M5
            or self.trend_anchor_timeframe is not BarFrequency.M15
            or type(self.hold_required_bars) is not int
            or self.hold_required_bars != 3
            or type(self.retest_rebreak_max_bars) is not int
            or self.retest_rebreak_max_bars != 3
            or type(self.lower_tf_risk_consecutive_bars) is not int
            or self.lower_tf_risk_consecutive_bars != 2
            or type(self.pivot_left_span) is not int
            or self.pivot_left_span != 2
            or type(self.pivot_right_span) is not int
            or self.pivot_right_span != 2
            or self.pivot_tie_policy != "reject"
        ):
            raise SubingLifecyclePolicyError()


def load_subing_lifecycle_policy(path: Path | None = None) -> SubingLifecyclePolicy:
    source = path if path is not None else _SUBING_LIFECYCLE_POLICY_PATH
    payload = load_exact_json(source, _EXPECTED_PAYLOAD, SubingLifecyclePolicyError)

    return SubingLifecyclePolicy(
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
        supported_timeframes=_SUPPORTED_TIMEFRAMES,
        clock_timeframe=BarFrequency(payload["clock_timeframe"]),
        trend_anchor_timeframe=BarFrequency(payload["trend_anchor_timeframe"]),
        hold_required_bars=payload["entry_confirmation"]["hold_required_bars"],
        retest_rebreak_max_bars=payload["entry_confirmation"][
            "retest_rebreak_max_bars"
        ],
        lower_tf_risk_consecutive_bars=payload["risk"][
            "lower_tf_consecutive_bars"
        ],
        pivot_left_span=payload["pivot"]["left_span"],
        pivot_right_span=payload["pivot"]["right_span"],
        pivot_tie_policy=payload["pivot"]["tie_policy"],
    )

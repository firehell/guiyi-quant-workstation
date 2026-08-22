from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.core.env import PROJECT_ROOT

from app.market_data.domain import BarFrequency
from app.market_data.exact_json_contract import (
    freeze_json,
    load_exact_json,
    matches_exact_frozen,
)


_JDJ_POLICY_PATH = PROJECT_ROOT / "data/research_policies/jdj_1m_policy_v1.json"
_EXPECTED_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "policy_id": "jdj_1m_policy_v1",
    "formula_version": "jdj_1m_v1",
    "research_only": True,
    "source_timeframe": "1m",
    "trend_context_timeframe": "5m",
    "trend_context": {
        "policy_id": "n_structure_5m_v1",
        "formula_version": "n_structure_v1",
        "strict_before": True,
        "same_epoch_key_level": True,
    },
    "ema": {
        "kind": "ema",
        "period": 20,
        "seed_policy": "sma_window",
        "round_digits": 6,
        "input_field": "close",
    },
    "previous_bar_trigger": {
        "dynamic_reference": True,
        "equal_is_breach": False,
        "fill_model": False,
    },
    "state_boundary": {
        "same_trading_day": True,
        "same_physical_contract": True,
        "same_rank1_segment": True,
    },
    "trend_follow": {
        "reaction": "ema_touch_and_close_on_trend_side",
        "armed_invalidation": "ema_close_failure_or_trend_lost",
        "same_bar_trigger_invalidation": "ambiguous_no_event",
    },
    "trend_reentry_6": {
        "trend_side_prerequisite": True,
        "excursion_reference": "opposite_ema_side_extreme",
        "reclaim": "first_close_back_on_trend_side",
        "reclaim_bar_can_react": False,
        "first_post_reclaim_reaction_only": True,
        "failed_first_reaction_terminal": True,
        "armed_invalidation": "ema_close_failure_or_trend_lost",
    },
    "key_level_breakout": {
        "pivot_source": "latest_same_epoch_confirmed_n_swing",
        "post_confirmation_origin_side_required": True,
        "first_break_basis": "close_cross",
        "first_break_creates_entry": False,
        "first_break_bar_can_retest": False,
        "volume_rule": "all_first_break_do_not_chase",
        "retest": "touch_level_and_close_on_breakout_side",
        "failed_retest": "close_not_on_breakout_side",
        "same_pivot_single_episode": True,
        "armed_invalidation": (
            "close_back_through_frozen_level_or_trend_lost"
        ),
    },
    "outcome": {
        "reference_price": "trigger_bar_close",
        "horizons_bars": [3, 5, 8, 20],
        "trigger_bar_in_future_window": False,
        "same_trading_day": True,
        "same_physical_contract": True,
        "same_rank1_segment": True,
    },
    "parameter_sweep": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


class JdjPolicyError(ValueError):
    code = "JDJ_POLICY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjPolicy:
    schema_version: int
    policy_id: str
    formula_version: str
    research_only: bool
    source_timeframe: BarFrequency
    trend_context_timeframe: BarFrequency
    ema_period: int
    ema_seed_policy: str
    ema_round_digits: int
    strict_previous_bar_trigger: bool
    same_epoch_key_level: bool
    raw: Mapping[str, object]


def load_jdj_policy(path: Path | None = None) -> JdjPolicy:
    source = path if path is not None else _JDJ_POLICY_PATH
    payload = load_exact_json(source, _EXPECTED_PAYLOAD, JdjPolicyError)

    return JdjPolicy(
        schema_version=payload["schema_version"],
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
        source_timeframe=BarFrequency(payload["source_timeframe"]),
        trend_context_timeframe=BarFrequency(payload["trend_context_timeframe"]),
        ema_period=payload["ema"]["period"],
        ema_seed_policy=payload["ema"]["seed_policy"],
        ema_round_digits=payload["ema"]["round_digits"],
        strict_previous_bar_trigger=(
            payload["previous_bar_trigger"]["dynamic_reference"] is True
            and payload["previous_bar_trigger"]["equal_is_breach"] is False
        ),
        same_epoch_key_level=payload["trend_context"]["same_epoch_key_level"],
        raw=freeze_json(payload),
    )


def is_exact_jdj_policy(policy: object) -> bool:
    """Return whether ``policy`` is the exact immutable JDJ 1m V1 contract."""

    return (
        isinstance(policy, JdjPolicy)
        and type(policy.schema_version) is int
        and policy.schema_version == _EXPECTED_PAYLOAD["schema_version"]
        and type(policy.policy_id) is str
        and policy.policy_id == _EXPECTED_PAYLOAD["policy_id"]
        and type(policy.formula_version) is str
        and policy.formula_version == _EXPECTED_PAYLOAD["formula_version"]
        and type(policy.research_only) is bool
        and policy.research_only is _EXPECTED_PAYLOAD["research_only"]
        and policy.source_timeframe
        is BarFrequency(_EXPECTED_PAYLOAD["source_timeframe"])
        and policy.trend_context_timeframe
        is BarFrequency(_EXPECTED_PAYLOAD["trend_context_timeframe"])
        and type(policy.ema_period) is int
        and policy.ema_period == _EXPECTED_PAYLOAD["ema"]["period"]
        and type(policy.ema_seed_policy) is str
        and policy.ema_seed_policy == _EXPECTED_PAYLOAD["ema"]["seed_policy"]
        and type(policy.ema_round_digits) is int
        and policy.ema_round_digits == _EXPECTED_PAYLOAD["ema"]["round_digits"]
        and type(policy.strict_previous_bar_trigger) is bool
        and policy.strict_previous_bar_trigger is True
        and type(policy.same_epoch_key_level) is bool
        and policy.same_epoch_key_level
        is _EXPECTED_PAYLOAD["trend_context"]["same_epoch_key_level"]
        and matches_exact_frozen(policy.raw, _EXPECTED_PAYLOAD)
    )

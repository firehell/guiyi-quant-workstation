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


_N_STRUCTURE_POLICY_PATH = (
    PROJECT_ROOT / "data/research_policies/n_structure_5m_v1.json"
)
_EXPECTED_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "policy_id": "n_structure_5m_v1",
    "formula_version": "n_structure_v1",
    "research_only": True,
    "source_timeframe": "5m",
    "swing": {
        "breach_basis": "previous_bar_high_low",
        "equal_is_breach": False,
        "outside_bar": "reset_unresolved_epoch",
        "inside_bar": "continue_current_or_stay_unresolved",
        "extreme_tie": "keep_first",
    },
    "n_pattern": {
        "base_origin_equal_allowed": True,
        "completion": "first_strict_n1_extreme_breach",
        "same_boundary_completion_break": (
            "record_both_without_intrabar_order_claim"
        ),
        "completed_identity_immutable": True,
        "n2_break_is_reversal": False,
        "origin_break_is_stronger_direction_break": True,
    },
    "range_band": {
        "definition": "n1_n2_price_span_v1",
        "reentry_starts": "after_completion_boundary",
        "strong_medium_weak_labels": False,
    },
    "structure": {
        "minimum_completed_n": 2,
        "kinds": ["bull", "bear", "range"],
        "outside_bar_preserves_active_direction_unless_defense_breaks": True,
        "defense_break": "strict",
        "break_to": "range",
    },
    "outcome": {
        "entry_price": "completion_bar_close",
        "horizons_bars": [3, 5, 8],
        "may_cross_trading_day": True,
        "may_cross_rank1_segment": False,
    },
}


class NStructurePolicyError(ValueError):
    code = "N_STRUCTURE_POLICY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class NStructurePolicy:
    schema_version: int
    policy_id: str
    formula_version: str
    research_only: bool
    source_timeframe: BarFrequency
    raw: Mapping[str, object]


def load_n_structure_policy(path: Path | None = None) -> NStructurePolicy:
    source = path if path is not None else _N_STRUCTURE_POLICY_PATH
    payload = load_exact_json(source, _EXPECTED_PAYLOAD, NStructurePolicyError)

    return NStructurePolicy(
        schema_version=payload["schema_version"],
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
        source_timeframe=BarFrequency(payload["source_timeframe"]),
        raw=freeze_json(payload),
    )


def is_exact_n_structure_policy(policy: object) -> bool:
    """Return whether ``policy`` is the exact immutable N Structure V1 contract."""

    return (
        isinstance(policy, NStructurePolicy)
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
        and matches_exact_frozen(policy.raw, _EXPECTED_PAYLOAD)
    )

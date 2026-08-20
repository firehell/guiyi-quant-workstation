"""Single-pass causal N Structure evaluation for one exact rank-1 segment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .domain import CanonicalBar
from .n_structure_pattern import (
    NPatternTrace,
    _evaluate_n_patterns_from_exact_swings,
)
from .n_structure_policy import NStructurePolicy, is_exact_n_structure_policy
from .n_structure_state import (
    NStructureTrace,
    _evaluate_n_market_structure_from_exact_facts,
)
from .n_structure_swing import (
    NStructureContractError,
    NSwingTrace,
    reduce_n_swings,
)


@dataclass(frozen=True, slots=True)
class NStructureSegmentTrace:
    swings: NSwingTrace
    patterns: NPatternTrace
    structures: NStructureTrace


def evaluate_n_structure_segment(
    bars: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
    policy: NStructurePolicy,
) -> NStructureSegmentTrace:
    """Run Swing, Pattern, and Structure exactly once for one segment."""

    if not is_exact_n_structure_policy(policy):
        raise NStructureContractError()
    segment_bars = tuple(bars)
    swings = reduce_n_swings(
        segment_bars,
        source_timeframe=policy.source_timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        segment_end_trading_day=segment_end_trading_day,
    )
    patterns = _evaluate_n_patterns_from_exact_swings(
        segment_bars,
        swings,
        policy=policy,
        inputs_validated=True,
    )
    structures = _evaluate_n_market_structure_from_exact_facts(
        segment_bars,
        swings=swings,
        patterns=patterns,
    )
    return NStructureSegmentTrace(
        swings=swings,
        patterns=patterns,
        structures=structures,
    )

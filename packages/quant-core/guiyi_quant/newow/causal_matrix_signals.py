"""Pure completed-Bar target signals for the JM seven-strategy research matrix.

The page formulas decide *whether* a completed Bar changes the target. Their
Low/High/stop reference prices are never fill prices here. Execution remains a
separate next-executable-Bar concern. A fresh formula state is used for every
physical segment; contract-prefix Bars warm indicators but emit no intents.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import cast

from .models import NewowDailyBar
from .oscillation_experiments import ExperimentKind, ExperimentState, step_experiment
from .research_backtest import (
    BacktestAction,
    BacktestIntent,
    NewowStrategyReplaySegment,
    ResearchStrategy,
    build_strategy_intents_from_replay_segments,
)


class CausalMatrixStrategy(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    DUAL_FUSION = "dual_fusion"
    TEST1 = "osc-test"
    TEST2 = "osc-test2"
    TEST3 = "osc-test3"
    TEST4 = "osc-test4"


CAUSAL_MATRIX_SIGNAL_VERSIONS = {
    CausalMatrixStrategy.TREND: "newow_trend_causal_target_v1",
    CausalMatrixStrategy.OSCILLATION: "newow_oscillation_causal_target_v1",
    CausalMatrixStrategy.DUAL_FUSION: "newow_dual_fusion_causal_target_v1",
    CausalMatrixStrategy.TEST1: "newow_osc_test_causal_target_v1",
    CausalMatrixStrategy.TEST2: "newow_osc_test2_causal_target_v1",
    CausalMatrixStrategy.TEST3: "newow_osc_test3_causal_target_v1",
    CausalMatrixStrategy.TEST4: "newow_osc_test4_causal_target_v1",
}

_MATRIX_FREQUENCIES = frozenset({"5m", "15m", "30m", "60m", "1d", "1w"})
_BASE_STRATEGY = {
    CausalMatrixStrategy.TREND: ResearchStrategy.TREND,
    CausalMatrixStrategy.OSCILLATION: ResearchStrategy.OSCILLATION,
    CausalMatrixStrategy.DUAL_FUSION: ResearchStrategy.DUAL_FUSION,
}


def _validate_segments(segments: tuple[NewowStrategyReplaySegment, ...]) -> None:
    if not segments:
        raise ValueError("NEWOW_CAUSAL_MATRIX_SEGMENTS_EMPTY")
    seen_eligible_ends = set()
    frequency = (
        segments[0].bars[0].frequency
        if isinstance(segments[0], NewowStrategyReplaySegment)
        else None
    )
    for segment in segments:
        if not isinstance(segment, NewowStrategyReplaySegment):
            raise ValueError("NEWOW_CAUSAL_MATRIX_SEGMENT_INVALID")
        eligible_started = False
        for bar in segment.bars:
            if (
                bar.product != "jm"
                or bar.frequency not in _MATRIX_FREQUENCIES
                or bar.frequency != frequency
            ):
                raise ValueError("NEWOW_CAUSAL_MATRIX_SCOPE_INVALID")
            if bar.observation_eligible:
                eligible_started = True
                if bar.bar_end in seen_eligible_ends:
                    raise ValueError("NEWOW_CAUSAL_MATRIX_IDENTITY_CONFLICT")
                seen_eligible_ends.add(bar.bar_end)
            elif eligible_started:
                raise ValueError("NEWOW_CAUSAL_MATRIX_PREFIX_INVALID")


def _fold_final_targets(
    segment: NewowStrategyReplaySegment,
    raw: tuple[BacktestIntent, ...],
    version: str,
) -> tuple[BacktestIntent, ...]:
    """Apply source action order, emitting at most one changed target per Bar."""
    by_end: dict[datetime, list[BacktestIntent]] = {}
    for intent in raw:
        by_end.setdefault(intent.signal_bar_end, []).append(intent)
    holding = False
    result: list[BacktestIntent] = []
    for bar in segment.bars:
        if not bar.observation_eligible:
            continue
        before = holding
        for intent in by_end.get(bar.bar_end, ()):
            holding = intent.action is BacktestAction.BUILD
        if holding != before:
            result.append(
                BacktestIntent(
                    BacktestAction.BUILD if holding else BacktestAction.CLEAR,
                    bar.bar_end,
                    version,
                )
            )
    return tuple(result)


def build_causal_matrix_intents(
    segments: tuple[NewowStrategyReplaySegment, ...],
    strategy: CausalMatrixStrategy,
) -> tuple[tuple[BacktestIntent, ...], tuple[str, ...]]:
    """Return final LONG/FLAT changes with adapter and source formula lineage.

    Every signal becomes known only after its completed signal Bar. The caller
    must schedule any fill strictly later on the actual physical contract.
    """
    if not isinstance(strategy, CausalMatrixStrategy):
        raise ValueError("NEWOW_CAUSAL_MATRIX_STRATEGY_INVALID")
    _validate_segments(segments)
    version = CAUSAL_MATRIX_SIGNAL_VERSIONS[strategy]

    if strategy is CausalMatrixStrategy.DUAL_FUSION:
        # This source is already folded with CLEAR/oscillation priority and has
        # an established identity. Preserve it exactly.
        return build_strategy_intents_from_replay_segments(
            segments, ResearchStrategy.DUAL_FUSION
        )

    output: list[BacktestIntent] = []
    if strategy in _BASE_STRATEGY:
        versions: tuple[str, ...] | None = None
        for segment in segments:
            raw, source_versions = build_strategy_intents_from_replay_segments(
                (segment,), _BASE_STRATEGY[strategy]
            )
            if versions is None:
                versions = source_versions
            output.extend(_fold_final_targets(segment, raw, version))
        assert versions is not None
        output.sort(key=lambda intent: intent.signal_bar_end)
        return tuple(output), (version, *versions)

    kind = ExperimentKind(strategy.value)
    for segment in segments:
        state = ExperimentState()
        for bar in segment.bars:
            before = state.holding
            # Research bars carry the same formula-facing fields as page bars;
            # their research identity also permits six formal frequencies.
            result = step_experiment(
                state, cast(NewowDailyBar, bar), kind, path="ordinary"
            )
            state = result.state
            if not bar.observation_eligible:
                continue
            after = result.state.holding
            if before != after:
                output.append(
                    BacktestIntent(
                        BacktestAction.BUILD if after else BacktestAction.CLEAR,
                        bar.bar_end,
                        version,
                    )
                )
    output.sort(key=lambda intent: intent.signal_bar_end)
    return tuple(output), (version, kind.formula_version)

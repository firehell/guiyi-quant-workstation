"""Causal target adapter checks using completed, physical-contract replay bars."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.causal_matrix_signals import (
    CausalMatrixStrategy,
    build_causal_matrix_intents,
)
from guiyi_quant.newow.oscillation_experiments import (
    ExperimentKind,
    ExperimentState,
    restore_experiment_state,
    step_experiment,
)
from guiyi_quant.newow.research_backtest import (
    BacktestAction,
    NewowResearchBar,
    NewowStrategyReplaySegment,
    ResearchStrategy,
    build_strategy_intents_from_replay_segments,
)


FREQUENCIES = ("5m", "15m", "30m", "60m", "1d", "1w")
EXPERIMENTS = (
    CausalMatrixStrategy.TEST1,
    CausalMatrixStrategy.TEST2,
    CausalMatrixStrategy.TEST3,
    CausalMatrixStrategy.TEST4,
)


def _bar(
    index: int,
    *,
    frequency: str = "5m",
    contract: str = "JM2701",
    segment: str = "jm-2701",
    eligible: bool = True,
    high: str = "110",
    low: str = "100",
    close: str = "105",
) -> NewowResearchBar:
    end = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=60 * index)
    return NewowResearchBar(
        product="jm",
        physical_contract=contract,
        segment_id=segment,
        trading_day=date(2026, 1, 1),
        bar_end=end,
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=100,
        open_interest=1000,
        source_identity=f"{frequency}-{contract}-{segment}-{index}",
        observation_eligible=eligible,
        completed=True,
        series_kind="actual_dominant" if eligible else "contract",
        frequency=frequency,
    )


def _replay(
    bars: tuple[NewowResearchBar, ...],
) -> tuple[NewowStrategyReplaySegment, ...]:
    return (NewowStrategyReplaySegment(bars),)


@pytest.mark.parametrize("frequency", FREQUENCIES)
@pytest.mark.parametrize("strategy", EXPERIMENTS)
def test_experiment_prefix_invariance_and_warmup_isolation(
    frequency: str, strategy: CausalMatrixStrategy
) -> None:
    bars = tuple(
        _bar(i, frequency=frequency, eligible=False, close=str(101 + i))
        for i in range(10)
    ) + (
        _bar(10, frequency=frequency, low="90", close="110"),
        _bar(11, frequency=frequency, high="105", low="95", close="100"),
        _bar(12, frequency=frequency, high="110", low="95", close="100"),
    )
    full, versions = build_causal_matrix_intents(_replay(bars), strategy)
    assert versions[0].endswith("_causal_target_v1")
    assert versions[1] == ExperimentKind(strategy.value).formula_version
    assert full[0].action is BacktestAction.BUILD
    assert full[0].signal_bar_end == bars[10].bar_end
    assert all(intent.signal_bar_end >= bars[10].bar_end for intent in full)
    for end in range(11, len(bars) + 1):
        prefix, _ = build_causal_matrix_intents(_replay(bars[:end]), strategy)
        assert prefix == tuple(
            x for x in full if x.signal_bar_end <= bars[end - 1].bar_end
        )


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_same_bar_clear_then_build_keeps_final_long_target(frequency: str) -> None:
    bars = tuple(
        _bar(i, frequency=frequency, close=str(101 + i), eligible=False)
        for i in range(10)
    ) + (
        _bar(10, frequency=frequency, low="90", close="110"),
        _bar(11, frequency=frequency, low="90", close="100"),
    )
    for strategy in (CausalMatrixStrategy.OSCILLATION, *EXPERIMENTS[:3]):
        intents, _ = build_causal_matrix_intents(_replay(bars), strategy)
        assert len([x for x in intents if x.signal_bar_end == bars[11].bar_end]) <= 1
        assert [x.action for x in intents] == [BacktestAction.BUILD]
        if strategy in EXPERIMENTS:
            kind = ExperimentKind(strategy.value)
            state = ExperimentState()
            for bar in bars[:11]:
                state = step_experiment(state, bar, kind, path="ordinary").state
            source = step_experiment(state, bars[11], kind, path="ordinary")
            assert [signal.action.value for signal in source.signals] == [
                "CLEAR",
                "BUILD",
            ]


def test_test2_stop_uses_page_signal_anchor_at_completed_close() -> None:
    bars = tuple(_bar(i, eligible=False) for i in range(10)) + (
        _bar(10, low="90"),  # page entry anchor 90; 7% threshold is 83.7
        _bar(11, high="105", low="84", close="100"),
        _bar(12, high="105", low="83", close="100"),
    )
    intents, _ = build_causal_matrix_intents(_replay(bars), CausalMatrixStrategy.TEST2)
    assert [(x.action, x.signal_bar_end) for x in intents] == [
        (BacktestAction.BUILD, bars[10].bar_end),
        (BacktestAction.CLEAR, bars[12].bar_end),
    ]


@pytest.mark.parametrize("strategy", EXPERIMENTS)
def test_experiment_replay_restart_and_physical_reset(
    strategy: CausalMatrixStrategy,
) -> None:
    first = tuple(_bar(i, close=str(101 + i), eligible=False) for i in range(10)) + (
        _bar(10, low="90", close="110"),
    )
    second = tuple(
        _bar(
            i + 20,
            contract="JM2705",
            segment="jm-2705",
            close=str(101 + i),
            eligible=False,
        )
        for i in range(10)
    ) + (_bar(30, contract="JM2705", segment="jm-2705", low="90", close="110"),)
    segments = (*_replay(first), *_replay(second))
    batch, _ = build_causal_matrix_intents(segments, strategy)
    restarted, _ = build_causal_matrix_intents(segments, strategy)
    assert batch == restarted
    assert [x.action for x in batch] == [BacktestAction.BUILD, BacktestAction.BUILD]
    assert [x.signal_bar_end for x in batch] == [first[-1].bar_end, second[-1].bar_end]

    kind = ExperimentKind(strategy.value)
    state = ExperimentState()
    for bar in first[:10]:
        state = step_experiment(state, bar, kind, path="ordinary").state
    restored = restore_experiment_state(asdict(state))
    assert step_experiment(state, first[10], kind, path="ordinary") == step_experiment(
        restored, first[10], kind, path="ordinary"
    )


@pytest.mark.parametrize(
    ("strategy", "source"),
    [
        (CausalMatrixStrategy.TREND, ResearchStrategy.TREND),
        (CausalMatrixStrategy.OSCILLATION, ResearchStrategy.OSCILLATION),
        (CausalMatrixStrategy.DUAL_FUSION, ResearchStrategy.DUAL_FUSION),
    ],
)
@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_existing_formula_paths_preserved_with_target_adapter(
    strategy: CausalMatrixStrategy, source: ResearchStrategy, frequency: str
) -> None:
    bars = tuple(
        _bar(i, frequency=frequency, low="95", close="100") for i in range(10)
    ) + (
        _bar(10, frequency=frequency, low="90", close="100"),
        _bar(11, frequency=frequency, low="90", close="100"),
    )
    raw, raw_versions = build_strategy_intents_from_replay_segments(
        _replay(bars), source
    )
    intents, versions = build_causal_matrix_intents(_replay(bars), strategy)
    assert versions[-len(raw_versions) :] == raw_versions
    assert all(x.signal_bar_end in {bar.bar_end for bar in bars} for x in intents)
    assert len({x.signal_bar_end for x in intents}) == len(intents)
    if strategy is CausalMatrixStrategy.DUAL_FUSION:
        assert intents == raw
        assert versions == raw_versions
    for end in (10, 11, 12):
        prefix, _ = build_causal_matrix_intents(_replay(bars[:end]), strategy)
        assert prefix == tuple(
            x for x in intents if x.signal_bar_end <= bars[end - 1].bar_end
        )


def test_test4_confirm_exit_waits_for_later_completed_bar() -> None:
    bars = tuple(_bar(i, eligible=False) for i in range(10)) + (
        _bar(10, low="90", close="100"),
        _bar(11, high="110", low="95", close="100"),
        _bar(12, high="105", low="99", close="100"),
    )
    intents, _ = build_causal_matrix_intents(_replay(bars), CausalMatrixStrategy.TEST4)
    assert [(x.action, x.signal_bar_end) for x in intents] == [
        (BacktestAction.BUILD, bars[10].bar_end),
        (BacktestAction.CLEAR, bars[12].bar_end),
    ]


def test_rejects_duplicate_observation_identity_across_segments() -> None:
    bars = tuple(_bar(i) for i in range(10)) + (_bar(10, low="90"),)
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        build_causal_matrix_intents(
            (_replay(bars)[0], _replay(bars)[0]), CausalMatrixStrategy.TEST1
        )


def test_rejects_mixed_frequencies_and_nonprefix_warmup() -> None:
    first = tuple(_bar(i, eligible=False) for i in range(10)) + (_bar(10, low="90"),)
    second = tuple(
        _bar(
            i + 20,
            contract="JM2705",
            segment="jm-2705",
            frequency="15m",
            eligible=False,
        )
        for i in range(10)
    ) + (_bar(30, contract="JM2705", segment="jm-2705", frequency="15m"),)
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        build_causal_matrix_intents(
            (*_replay(first), *_replay(second)), CausalMatrixStrategy.TEST1
        )
    bad = (*first, _bar(11, eligible=False))
    with pytest.raises(ValueError, match="PREFIX_INVALID"):
        build_causal_matrix_intents(_replay(bad), CausalMatrixStrategy.TEST1)

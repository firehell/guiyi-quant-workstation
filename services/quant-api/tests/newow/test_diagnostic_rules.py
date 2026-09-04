from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow import (
    AI_SIX_COMBO_PAGE_V3250,
    DIAGNOSTIC_FACTS_CLEANROOM_V1,
    MAIN_FORCE_CONTROL_FORMULA_VERSION,
    OSCILLATION_FORMULA_VERSION,
    TARGET_ABSORB_DISPLAY_PAGE_V1,
    DisplayPeriod,
    DisplayPriceSelection,
    DiagnosticInputs,
    MainForceControlResult,
    MainForceStatus,
    MainRiseState,
    NewowDailyBar,
    NewowTrendBandPoint,
    OscillationState,
    PageAiCombination,
    PageAiPeriod,
    PageAiRanking,
    PageAiStrategy,
    PageSignalState,
    TrendBandState,
    WalkForwardValidationResult,
    assess_oos_candidate,
    build_diagnostic_facts,
    diagnostic_tokens,
    rank_page_ai_combinations,
)
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.research_backtest import ResearchStrategy
from guiyi_quant.newow.subplots import ZhaoyaoMirrorResult


def _bars(count: int = 25, *, split_at: int | None = None) -> tuple[NewowDailyBar, ...]:
    start = date(2026, 1, 1)
    result: list[NewowDailyBar] = []
    for index in range(count):
        second = split_at is not None and index >= split_at
        close = Decimal(100 + index)
        result.append(
            NewowDailyBar(
                product="rb",
                physical_contract="RB2605" if second else "RB2601",
                segment_id="seg-b" if second else "seg-a",
                trading_day=start + timedelta(days=index),
                bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1000 + index,
                open_interest=2000 + index,
                source_identity=f"bar-{index}",
                observation_eligible=True,
                completed=True,
            )
        )
    return tuple(result)


def _inputs(*, split_at: int | None = None) -> DiagnosticInputs:
    bars = _bars(split_at=split_at)
    trend_points = tuple(
        NewowTrendBandPoint(
            bar.bar_end,
            1.0,
            1.0,
            TrendBandState.YELLOW,
            TrendBandState.YELLOW,
        )
        for bar in bars
    )
    return DiagnosticInputs(
        bars=bars,
        display_prices=DisplayPriceSelection(
            target=Decimal("140"),
            absorb=Decimal("110"),
            raw_target=Decimal("140"),
            raw_absorb=Decimal("110"),
            target_period=DisplayPeriod.DAY,
            absorb_period=DisplayPeriod.DAY,
            target_branch_token="DAILY_POSITIVE",
            absorb_branch_token="DAILY_POSITIVE",
        ),
        trend_points=trend_points,
        trend_formula_version=NEWOW_TREND_D1_PAGE_V2.trend_band_formula,
        oscillation_state=OscillationState(
            highs=tuple(bar.high for bar in bars[-10:]),
            lows=tuple(bar.low for bar in bars[-10:]),
            volumes=tuple(bar.volume for bar in bars[-10:]),
            history_count=10,
            holding=True,
            physical_contract=bars[-1].physical_contract,
            segment_id=bars[-1].segment_id,
        ),
        main_force=MainForceControlResult(
            kongpan=(1.0,),
            status=(MainForceStatus.CONTROLLED,),
            current_status=MainForceStatus.CONTROLLED,
        ),
        main_rise_state=MainRiseState(
            band_state=TrendBandState.YELLOW,
            physical_contract=bars[-1].physical_contract,
            segment_id=bars[-1].segment_id,
        ),
        cup_overlay=None,
        weekly_signal=PageSignalState.HOLD,
        daily_signal=PageSignalState.BUY,
    )


def test_diagnostic_copy_cannot_change_quant_facts() -> None:
    facts = build_diagnostic_facts(_inputs())
    tokens = diagnostic_tokens(facts)

    assert facts.formula_versions
    assert DIAGNOSTIC_FACTS_CLEANROOM_V1 in facts.formula_versions
    assert all(token.code.startswith("NEWOW_DIAG_") for token in tokens)
    assert not hasattr(facts, "advice")
    assert not hasattr(tokens[0], "position")


def test_diagnostic_facts_are_decimal_strict_before_and_segment_bounded() -> None:
    facts = build_diagnostic_facts(_inputs())
    prior_closes = [bar.close for bar in _bars()[:-1]]
    alpha = Decimal(2) / Decimal(21)
    expected_ema = prior_closes[0]
    for close in prior_closes[1:]:
        expected_ema = close * alpha + expected_ema * (Decimal(1) - alpha)

    assert facts.ema20 == expected_ema
    assert facts.close_vs_ema20 == "above"
    assert facts.target_distance_pct == Decimal("12.9032")
    assert facts.absorb_distance_pct == Decimal("-11.2903")
    assert facts.trend_duration_bars == 25
    assert facts.oscillation_holding is True
    assert facts.main_rise_active is True
    assert facts.main_force_status is MainForceStatus.CONTROLLED


def test_rollover_resets_trend_duration_and_ema_warmup() -> None:
    facts = build_diagnostic_facts(_inputs(split_at=20))
    assert facts.trend_duration_bars == 5
    assert facts.ema20 is None
    assert facts.close_vs_ema20 == "unavailable"


def test_diagnostic_missing_facts_stay_unavailable() -> None:
    inputs = _inputs()
    facts = build_diagnostic_facts(
        replace(
            inputs,
            bars=inputs.bars[-1:],
            trend_points=inputs.trend_points[-1:],
            display_prices=replace(inputs.display_prices, target=None, absorb=None),
            oscillation_state=None,
            main_force=None,
            main_rise_state=None,
            weekly_signal=None,
            daily_signal=None,
        )
    )

    assert facts.ema20 is None
    assert facts.close_vs_ema20 == "unavailable"
    assert facts.target_distance_pct is None
    assert facts.absorb_distance_pct is None
    assert facts.oscillation_holding is None
    codes = {token.code for token in diagnostic_tokens(facts)}
    assert "NEWOW_DIAG_DATA_INSUFFICIENT" in codes
    assert not any(code.startswith("NEWOW_DIAG_AI_MATRIX_") for code in codes)


def test_repainting_subplot_is_rejected_from_formal_diagnostic_input() -> None:
    repainting = ZhaoyaoMirrorResult(
        entry=(0.0,),
        wash=(0.0,),
        distribution=(0.0,),
        markup=(0.0,),
        exit=(0.0,),
        inducement=(0.0,),
        peaks=(),
        caution=(),
    )
    with pytest.raises(ValueError, match="NEWOW_DIAGNOSTIC_REPAINTING_INPUT"):
        build_diagnostic_facts(replace(_inputs(), repainting_inputs=(repainting,)))


@pytest.mark.parametrize(
    ("weekly", "daily"),
    tuple((weekly, daily) for weekly in PageSignalState for daily in PageSignalState),
)
def test_all_16_current_week_day_page_branches_are_tokens(
    weekly: PageSignalState, daily: PageSignalState
) -> None:
    facts = build_diagnostic_facts(
        replace(_inputs(), weekly_signal=weekly, daily_signal=daily)
    )
    token = next(
        item
        for item in diagnostic_tokens(facts)
        if item.code.startswith("NEWOW_DIAG_AI_MATRIX_")
    )
    assert token.fact_keys == ("weekly_signal", "daily_signal")
    assert token.formula_identities == (AI_SIX_COMBO_PAGE_V3250,)
    assert token.code == f"NEWOW_DIAG_AI_MATRIX_{weekly.value.upper()}_{daily.value.upper()}"


def _six_combinations() -> tuple[PageAiCombination, ...]:
    values = (
        (PageAiPeriod.WEEK, PageAiStrategy.OSCILLATION, "8", "8", "60", 10),
        (PageAiPeriod.WEEK, PageAiStrategy.TREND, "12", "6", "70", 8),
        (PageAiPeriod.DAY, PageAiStrategy.OSCILLATION, "4", "0", "50", 2),
        (PageAiPeriod.DAY, PageAiStrategy.TREND, "20", "5", "80", 12),
        (PageAiPeriod.SIXTY_MINUTE, PageAiStrategy.OSCILLATION, "3", "6", "55", 5),
        (PageAiPeriod.SIXTY_MINUTE, PageAiStrategy.TREND, "6", "4", "65", 5),
    )
    return tuple(
        PageAiCombination(
            period=period,
            strategy=strategy,
            cumulative_return_pct=Decimal(ret),
            max_drawdown_pct=Decimal(calmar),
            accuracy_pct=Decimal(accuracy),
            trade_count=trades,
            formula_version=(
                OSCILLATION_FORMULA_VERSION
                if strategy is PageAiStrategy.OSCILLATION
                else NEWOW_TREND_D1_PAGE_V2.trend_band_formula
            ),
        )
        for period, strategy, ret, calmar, accuracy, trades in values
    )


def test_page_ai_ranking_discards_sparse_results_and_is_not_oos() -> None:
    ranking = rank_page_ai_combinations(_six_combinations())

    assert isinstance(ranking, PageAiRanking)
    assert ranking.trustworthy_for_research is False
    assert len(ranking.ranked) == 5
    assert ranking.ranked[0].combination.strategy is PageAiStrategy.TREND
    assert ranking.ranked[0].combination.period is PageAiPeriod.DAY
    assert all(item.score.as_tuple().exponent >= -4 for item in ranking.ranked)
    scores = {
        (item.combination.period, item.combination.strategy): item.score
        for item in ranking.ranked
    }
    assert scores == {
        (PageAiPeriod.WEEK, PageAiStrategy.OSCILLATION): Decimal("0.2513"),
        (PageAiPeriod.WEEK, PageAiStrategy.TREND): Decimal("0.4788"),
        (PageAiPeriod.DAY, PageAiStrategy.TREND): Decimal("1.0000"),
        (PageAiPeriod.SIXTY_MINUTE, PageAiStrategy.OSCILLATION): Decimal("0.0000"),
        (PageAiPeriod.SIXTY_MINUTE, PageAiStrategy.TREND): Decimal("0.2712"),
    }
    with pytest.raises(ValueError, match="NEWOW_PAGE_OPTIMIZER_UNTRUSTED_RESULT"):
        assess_oos_candidate(ranking)


def test_page_ai_ranking_tie_breaks_by_trade_count_then_input_order() -> None:
    base = _six_combinations()[0]
    combinations = (
        replace(base, period=PageAiPeriod.WEEK, trade_count=5),
        replace(base, period=PageAiPeriod.DAY, trade_count=8),
        replace(base, period=PageAiPeriod.SIXTY_MINUTE, trade_count=8),
    )
    ranking = rank_page_ai_combinations(combinations, require_six=False)
    assert [item.combination.period for item in ranking.ranked] == [
        PageAiPeriod.DAY,
        PageAiPeriod.SIXTY_MINUTE,
        PageAiPeriod.WEEK,
    ]


def test_page_ai_formula_identity_mismatch_fails_closed() -> None:
    combinations = _six_combinations()
    with pytest.raises(ValueError, match="NEWOW_FORMULA_IDENTITY_MISMATCH"):
        rank_page_ai_combinations(
            (replace(combinations[0], formula_version="wrong"), *combinations[1:])
        )


def test_walk_forward_result_has_a_distinct_trusted_assessment_type() -> None:
    result = WalkForwardValidationResult(
        strategy=ResearchStrategy.TREND,
        signal_formula_versions=(NEWOW_TREND_D1_PAGE_V2.trend_band_formula,),
        folds=(),
        closed_trade_count=7,
        compounded_net_return_pct=Decimal("8.25"),
    )
    assessment = assess_oos_candidate(result)
    assert assessment.trustworthy_for_research is True
    assert assessment.compounded_net_return_pct == Decimal("8.25")
    assert not isinstance(assessment, PageAiRanking)


def test_formula_lineage_contains_only_explicit_primitive_identities() -> None:
    facts = build_diagnostic_facts(_inputs())
    assert TARGET_ABSORB_DISPLAY_PAGE_V1 in facts.formula_versions
    assert MAIN_FORCE_CONTROL_FORMULA_VERSION in facts.formula_versions
    assert OSCILLATION_FORMULA_VERSION in facts.formula_versions
    assert NEWOW_TREND_D1_PAGE_V2.trend_band_formula in facts.formula_versions


def test_diagnostic_trend_formula_identity_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="NEWOW_FORMULA_IDENTITY_MISMATCH"):
        build_diagnostic_facts(
            replace(_inputs(), trend_formula_version="unversioned-trend")
        )

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.newow.research_backtest import (
    CAUSAL_BACKTEST_FORMULA_VERSION,
    BacktestAction,
    BacktestCosts,
    BacktestIntent,
    NewowResearchBar,
    ResearchStrategy,
    backtest_newow_strategy,
    evaluate_newow_timeframes,
    run_causal_long_only_backtest,
)


UTC = timezone.utc


def _bar(
    offset: int,
    *,
    value: str,
    frequency: str = "1d",
    contract: str = "RB2610",
    segment: str = "rb-2610",
    eligible: bool = True,
) -> NewowResearchBar:
    day = date(2026, 1, 1) + timedelta(days=offset)
    price = Decimal(value)
    return NewowResearchBar(
        product="rb",
        physical_contract=contract,
        segment_id=segment,
        trading_day=day,
        bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=offset),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=100,
        open_interest=1000,
        source_identity=f"fixture-{frequency}-{offset}",
        observation_eligible=eligible,
        completed=True,
        frequency=frequency,
    )


def test_research_bar_accepts_only_formal_completed_actual_dominant_periods() -> None:
    assert _bar(0, value="100", frequency="60m").frequency == "60m"
    with pytest.raises(ValueError, match="NEWOW_RESEARCH_BAR_INVALID_FREQUENCY"):
        _bar(0, value="100", frequency="120m")
    with pytest.raises(ValueError, match="NEWOW_RESEARCH_BAR_NOT_COMPLETED"):
        NewowResearchBar(
            **{
                **_bar(0, value="100").as_kwargs(),
                "completed": False,
            }
        )


def test_causal_executor_fills_only_at_next_bar_open_with_costs() -> None:
    bars = tuple(
        _bar(index, value=str(value))
        for index, value in enumerate((100, 110, 120, 130))
    )
    intents = (
        BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, "fixture_v1"),
        BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, "fixture_v1"),
    )
    costs = BacktestCosts(
        commission_rate=Decimal("0.001"),
        slippage_bps=Decimal("10"),
    )

    result = run_causal_long_only_backtest(bars, intents, costs=costs)

    assert result.formula_version == CAUSAL_BACKTEST_FORMULA_VERSION
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry.signal_bar_end == bars[0].bar_end
    assert trade.entry.fill_bar_end == bars[1].bar_end
    assert trade.entry.raw_open == Decimal("110")
    assert trade.entry.fill_price == Decimal("110.110")
    assert trade.exit.signal_bar_end == bars[2].bar_end
    assert trade.exit.fill_bar_end == bars[3].bar_end
    assert trade.exit.fill_price == Decimal("129.870")
    assert trade.entry.fee == Decimal("0.110110")
    assert trade.exit.fee == Decimal("0.129870")
    assert trade.net_pnl_per_contract == Decimal("19.520020")
    assert trade.net_return_pct == Decimal("17.71003494734309374214923211")


def test_futures_costs_apply_multiplier_fixed_fee_and_tick_slippage() -> None:
    bars = tuple(
        _bar(index, value=str(value)) for index, value in enumerate((90, 100, 105, 110))
    )
    intents = (
        BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, "fixture_v1"),
        BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, "fixture_v1"),
    )
    costs = BacktestCosts(
        contract_multiplier=Decimal("10"),
        commission_per_contract=Decimal("2"),
        price_tick=Decimal("1"),
        slippage_ticks=1,
    )

    result = run_causal_long_only_backtest(bars, intents, costs=costs)

    trade = result.trades[0]
    assert trade.entry.fill_price == Decimal("101")
    assert trade.exit.fill_price == Decimal("109")
    assert trade.entry.fee == Decimal("2")
    assert trade.exit.fee == Decimal("2")
    assert trade.gross_pnl_per_contract == Decimal("80")
    assert trade.net_pnl_per_contract == Decimal("76")
    assert trade.gross_return_pct == Decimal("7.920792079207920792079207921")
    assert trade.net_return_pct == Decimal("7.509881422924901185770750988")


def test_bps_slippage_is_rounded_against_the_futures_price_tick() -> None:
    bars = tuple(
        _bar(index, value=str(value)) for index, value in enumerate((90, 100, 105, 110))
    )
    result = run_causal_long_only_backtest(
        bars,
        (
            BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, "fixture_v1"),
            BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, "fixture_v1"),
        ),
        costs=BacktestCosts(
            slippage_bps=Decimal("5"),
            price_tick=Decimal("0.2"),
        ),
    )

    assert result.trades[0].entry.fill_price == Decimal("100.2")
    assert result.trades[0].exit.fill_price == Decimal("109.8")


def test_rollover_cancels_pending_intent_and_never_carries_position() -> None:
    old = (_bar(0, value="100"), _bar(1, value="101"))
    new = _bar(2, value="200", contract="RB2701", segment="rb-2701")

    pending = run_causal_long_only_backtest(
        old + (new,),
        (BacktestIntent(BacktestAction.BUILD, old[-1].bar_end, "fixture_v1"),),
    )
    assert pending.fills == ()
    assert pending.cancelled_intent_count == 1

    opened = run_causal_long_only_backtest(
        old + (new,),
        (BacktestIntent(BacktestAction.BUILD, old[0].bar_end, "fixture_v1"),),
    )
    assert len(opened.fills) == 1
    assert len(opened.incomplete_positions) == 1
    assert opened.incomplete_positions[0].reason == "DOMINANT_ROLL_EXCLUDED"
    assert opened.trades == ()


def test_input_identity_is_fail_closed() -> None:
    bars = (_bar(1, value="101"), _bar(0, value="100"))
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_BARS_NOT_STRICTLY_ORDERED"):
        run_causal_long_only_backtest(bars, ())

    mixed = (_bar(0, value="100", frequency="1d"), _bar(1, value="101", frequency="1w"))
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_MIXED_FREQUENCY"):
        run_causal_long_only_backtest(mixed, ())


def test_trend_wrapper_runs_60m_independently_with_next_bar_fills() -> None:
    values = (100, 80, 120, 80, 90)
    bars = tuple(
        _bar(index, value=str(value), frequency="60m")
        for index, value in enumerate(values)
    )

    result = backtest_newow_strategy(bars, strategy=ResearchStrategy.TREND)

    assert result.frequency == "60m"
    assert result.strategy is ResearchStrategy.TREND
    assert len(result.trades) == 1
    assert result.trades[0].entry.signal_bar_end == bars[2].bar_end
    assert result.trades[0].entry.fill_bar_end == bars[3].bar_end
    assert result.trades[0].exit.signal_bar_end == bars[3].bar_end
    assert result.trades[0].exit.fill_bar_end == bars[4].bar_end


def test_timeframes_are_evaluated_as_separate_series_without_fallback() -> None:
    values = (100, 80, 120, 80, 90)
    day = tuple(
        _bar(index, value=str(value), frequency="1d")
        for index, value in enumerate(values)
    )
    hour = tuple(
        _bar(index, value=str(value), frequency="60m")
        for index, value in enumerate(values)
    )

    results = evaluate_newow_timeframes(
        {"1d": day, "60m": hour},
        strategy=ResearchStrategy.TREND,
    )

    assert tuple(results) == ("1d", "60m")
    assert results["1d"].frequency == "1d"
    assert results["60m"].frequency == "60m"
    assert results["1d"].trades[0].entry.fill_bar_end == day[3].bar_end
    assert results["60m"].trades[0].entry.fill_bar_end == hour[3].bar_end


def test_repainting_mirror_is_rejected_from_formal_backtest() -> None:
    bars = tuple(
        _bar(index, value=str(value)) for index, value in enumerate((100, 80, 120))
    )
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_STRATEGY_NOT_CAUSAL"):
        backtest_newow_strategy(bars, strategy="zhaoyao_mirror")  # type: ignore[arg-type]

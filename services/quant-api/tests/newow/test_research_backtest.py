from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.newow.research_backtest import (
    CAUSAL_BACKTEST_FORMULA_VERSION,
    BacktestAction,
    BacktestCostSnapshot,
    BacktestCosts,
    BacktestExecutionConstraint,
    BacktestIntent,
    NewowResearchBar,
    ResearchStrategy,
    backtest_newow_strategy,
    build_strategy_intents,
    evaluate_newow_timeframes,
    run_causal_long_only_backtest,
)
from guiyi_quant.newow.oscillation_channel import OSCILLATION_FORMULA_VERSION
from guiyi_quant.newow.subplots import ZHAOYAO_MIRROR_FORMULA_VERSION


UTC = timezone.utc
TREND_FORMULA = "newow_trend_band_page_v2"


def _bar(
    offset: int,
    *,
    value: str,
    frequency: str = "1d",
    contract: str = "RB2610",
    segment: str = "rb-2610",
    eligible: bool = True,
    volume: int = 100,
    spread: str = "1",
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
        high=price + Decimal(spread),
        low=price - Decimal(spread),
        close=price,
        volume=volume,
        open_interest=1000,
        source_identity=f"fixture-{frequency}-{offset}",
        observation_eligible=eligible,
        completed=True,
        frequency=frequency,
    )


def _cost_snapshot(
    *,
    contract: str = "RB2610",
    effective_from: date = date(2026, 1, 1),
    effective_to: date = date(2027, 1, 1),
    source: str = "fee-snapshot-rb-2026",
    multiplier: str = "10",
) -> BacktestCostSnapshot:
    return BacktestCostSnapshot(
        product="rb",
        physical_contract=contract,
        effective_from=effective_from,
        effective_to=effective_to,
        captured_at=datetime(2025, 12, 31, tzinfo=UTC),
        source_identity=source,
        costs=BacktestCosts(
            contract_multiplier=Decimal(multiplier),
            commission_per_contract=Decimal("2"),
            price_tick=Decimal("1"),
            slippage_ticks=1,
        ),
    )


def _constraint(
    bar: NewowResearchBar,
    *,
    limit_up: str = "200",
    limit_down: str = "1",
    source: str | None = None,
) -> BacktestExecutionConstraint:
    return BacktestExecutionConstraint(
        bar_source_identity=bar.source_identity,
        physical_contract=bar.physical_contract,
        limit_up=Decimal(limit_up),
        limit_down=Decimal(limit_down),
        captured_at=datetime(2025, 12, 31, tzinfo=UTC),
        source_identity=source or f"limits-{bar.source_identity}",
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


def test_research_bar_rejects_a_contract_from_another_product() -> None:
    with pytest.raises(
        ValueError,
        match="NEWOW_RESEARCH_BAR_INVALID_PHYSICAL_CONTRACT",
    ):
        NewowResearchBar(
            **{
                **_bar(0, value="100").as_kwargs(),
                "physical_contract": "JM2609",
            }
        )


def test_causal_executor_fills_only_at_next_bar_open_with_costs() -> None:
    bars = tuple(
        _bar(index, value=str(value))
        for index, value in enumerate((100, 110, 120, 130))
    )
    intents = (
        BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),
        BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, TREND_FORMULA),
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
        BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),
        BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, TREND_FORMULA),
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


def test_cost_snapshot_and_execution_constraint_validation_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_COST_SNAPSHOT_INVALID"):
        _cost_snapshot(contract="rb2610")
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_COST_SNAPSHOT_INVALID"):
        _cost_snapshot(contract="JM2609")
    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_EXECUTION_CONSTRAINT_INVALID",
    ):
        BacktestExecutionConstraint(
            bar_source_identity="bar-1",
            physical_contract="RB2610",
            limit_up=Decimal("90"),
            limit_down=Decimal("100"),
            captured_at=datetime(2025, 12, 31, tzinfo=UTC),
            source_identity="limits-1",
        )


def test_futures_facts_require_exact_nonoverlapping_cost_snapshot() -> None:
    bars = tuple(_bar(index, value=str(100 + index)) for index in range(2))
    intent = (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),)

    with pytest.raises(ValueError, match="NEWOW_BACKTEST_COST_SNAPSHOT_MISSING"):
        run_causal_long_only_backtest(
            bars,
            intent,
            cost_snapshots=(
                _cost_snapshot(
                    effective_from=date(2025, 1, 1),
                    effective_to=date(2025, 12, 31),
                ),
            ),
            execution_constraints=(_constraint(bars[1]),),
            require_execution_facts=True,
        )

    with pytest.raises(ValueError, match="NEWOW_BACKTEST_COST_SNAPSHOT_OVERLAP"):
        run_causal_long_only_backtest(
            bars,
            intent,
            cost_snapshots=(
                _cost_snapshot(source="fee-a"),
                _cost_snapshot(source="fee-b"),
            ),
            execution_constraints=(_constraint(bars[1]),),
            require_execution_facts=True,
        )


def test_strict_futures_facts_require_a_price_tick() -> None:
    bars = tuple(_bar(index, value=str(100 + index)) for index in range(2))
    snapshot = BacktestCostSnapshot(
        product="rb",
        physical_contract="RB2610",
        effective_from=date(2026, 1, 1),
        effective_to=date(2027, 1, 1),
        captured_at=datetime(2025, 12, 31, tzinfo=UTC),
        source_identity="fee-without-tick",
        costs=BacktestCosts(contract_multiplier=Decimal("10")),
    )

    with pytest.raises(ValueError, match="NEWOW_BACKTEST_PRICE_TICK_REQUIRED"):
        run_causal_long_only_backtest(
            bars,
            (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),),
            cost_snapshots=(snapshot,),
            execution_constraints=(_constraint(bars[1]),),
            require_execution_facts=True,
        )


def test_strict_futures_facts_reject_limits_off_the_price_tick() -> None:
    bars = (
        _bar(0, value="90", spread="0"),
        _bar(1, value="99", spread="0"),
    )

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_EXECUTION_CONSTRAINT_TICK_MISMATCH",
    ):
        run_causal_long_only_backtest(
            bars,
            (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),),
            cost_snapshots=(_cost_snapshot(),),
            execution_constraints=(
                _constraint(bars[1], limit_up="100.5", limit_down="1"),
            ),
            require_execution_facts=True,
        )


def test_strict_futures_facts_reject_bar_prices_off_the_price_tick() -> None:
    bars = (
        _bar(0, value="90", spread="0"),
        _bar(1, value="99.5", spread="0"),
    )

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_BAR_PRICE_TICK_MISMATCH",
    ):
        run_causal_long_only_backtest(
            bars,
            (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),),
            cost_snapshots=(_cost_snapshot(),),
            execution_constraints=(_constraint(bars[1]),),
            require_execution_facts=True,
        )


def test_strict_futures_facts_validate_warmup_bar_prices_against_the_tick() -> None:
    bars = (
        _bar(0, value="90.5", spread="0"),
        _bar(1, value="99", spread="0"),
    )

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_BAR_PRICE_TICK_MISMATCH",
    ):
        run_causal_long_only_backtest(
            bars,
            (),
            cost_snapshots=(_cost_snapshot(),),
            require_execution_facts=True,
        )


def test_strict_futures_facts_reject_multiplier_change_during_a_position() -> None:
    bars = tuple(_bar(index, value=str(100 + index), spread="0") for index in range(4))
    snapshots = (
        _cost_snapshot(effective_to=date(2026, 1, 3), source="multiplier-10-a"),
        _cost_snapshot(
            effective_from=date(2026, 1, 3),
            effective_to=date(2026, 1, 4),
            source="multiplier-20",
            multiplier="20",
        ),
        _cost_snapshot(
            effective_from=date(2026, 1, 4),
            source="multiplier-10-b",
        ),
    )

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_COST_SNAPSHOT_CONFLICT",
    ):
        run_causal_long_only_backtest(
            bars,
            (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),),
            cost_snapshots=snapshots,
            execution_constraints=(_constraint(bars[1]),),
            require_execution_facts=True,
        )


def test_futures_facts_require_one_exact_execution_constraint() -> None:
    bars = tuple(_bar(index, value=str(100 + index)) for index in range(2))
    intent = (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),)

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_EXECUTION_CONSTRAINT_MISSING",
    ):
        run_causal_long_only_backtest(
            bars,
            intent,
            cost_snapshots=(_cost_snapshot(),),
            require_execution_facts=True,
        )

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_EXECUTION_CONSTRAINT_CONFLICT",
    ):
        run_causal_long_only_backtest(
            bars,
            intent,
            cost_snapshots=(_cost_snapshot(),),
            execution_constraints=(
                _constraint(bars[1], source="limits-a"),
                _constraint(bars[1], source="limits-b"),
            ),
            require_execution_facts=True,
        )


@pytest.mark.parametrize(
    ("action", "fill_index", "constraint_kwargs", "expected_reason"),
    (
        (BacktestAction.BUILD, 1, {"limit_up": "101"}, "BUY_AT_LIMIT_UP"),
        (BacktestAction.CLEAR, 3, {"limit_down": "103"}, "SELL_AT_LIMIT_DOWN"),
    ),
)
def test_limit_locked_next_open_is_rejected_once(
    action: BacktestAction,
    fill_index: int,
    constraint_kwargs: dict[str, str],
    expected_reason: str,
) -> None:
    bars = tuple(
        _bar(index, value=str(100 + index), spread="0") for index in range(5)
    )
    intents = [BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA)]
    if action is BacktestAction.CLEAR:
        intents.append(
            BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, TREND_FORMULA)
        )
    constraints = [_constraint(bars[1])]
    if fill_index != 1:
        constraints.append(_constraint(bars[fill_index], **constraint_kwargs))
    else:
        constraints[0] = _constraint(bars[fill_index], **constraint_kwargs)

    result = run_causal_long_only_backtest(
        bars,
        tuple(intents),
        cost_snapshots=(_cost_snapshot(),),
        execution_constraints=tuple(constraints),
        require_execution_facts=True,
    )

    assert tuple(item.reason for item in result.rejected_fills) == (expected_reason,)
    assert result.rejected_fills[0].fill_bar_end == bars[fill_index].bar_end
    if action is BacktestAction.BUILD:
        assert result.fills == ()
    else:
        assert tuple(fill.action for fill in result.fills) == (BacktestAction.BUILD,)
        assert result.incomplete_positions[0].reason == "END_OF_SAMPLE_EXCLUDED"


def test_zero_volume_next_open_is_rejected_with_cost_lineage_unused() -> None:
    bars = (
        _bar(0, value="100"),
        _bar(1, value="101", volume=0),
        _bar(2, value="102"),
    )
    result = run_causal_long_only_backtest(
        bars,
        (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),),
        cost_snapshots=(_cost_snapshot(),),
        execution_constraints=(_constraint(bars[1]),),
        require_execution_facts=True,
    )

    assert tuple(item.reason for item in result.rejected_fills) == ("ZERO_VOLUME",)
    assert result.fills == ()
    assert result.cost_snapshot_identities == ()


def test_zero_volume_rejection_precedes_nonpositive_sell_slippage() -> None:
    bars = (
        _bar(0, value="10", spread="0"),
        _bar(1, value="10", spread="0"),
        _bar(2, value="10", spread="0"),
        _bar(3, value="1", spread="0", volume=0),
    )
    result = run_causal_long_only_backtest(
        bars,
        (
            BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),
            BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, TREND_FORMULA),
        ),
        costs=BacktestCosts(price_tick=Decimal("2"), slippage_ticks=1),
        execution_constraints=(_constraint(bars[1]), _constraint(bars[3])),
    )

    assert tuple(item.reason for item in result.rejected_fills) == ("ZERO_VOLUME",)
    assert len(result.incomplete_positions) == 1
    assert result.incomplete_positions[0].reason == "END_OF_SAMPLE_EXCLUDED"


def test_slippage_is_capped_at_limit_without_calling_an_unlocked_open_locked() -> None:
    bars = (
        _bar(0, value="90", spread="0"),
        _bar(1, value="99", spread="0"),
        _bar(2, value="99", spread="0"),
    )
    result = run_causal_long_only_backtest(
        bars,
        (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),),
        costs=BacktestCosts(price_tick=Decimal("1"), slippage_ticks=2),
        execution_constraints=(
            _constraint(bars[1], limit_up="100", limit_down="1"),
        ),
    )

    assert result.rejected_fills == ()
    assert result.fills[0].raw_open == Decimal("99")
    assert result.fills[0].fill_price == Decimal("100")


def test_sourced_fills_record_cost_lineage_and_multiplier() -> None:
    bars = tuple(_bar(index, value=str(value)) for index, value in enumerate((90, 100, 105, 110)))
    result = run_causal_long_only_backtest(
        bars,
        (
            BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),
            BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, TREND_FORMULA),
        ),
        cost_snapshots=(_cost_snapshot(),),
        execution_constraints=(_constraint(bars[1]), _constraint(bars[3])),
        require_execution_facts=True,
    )

    assert result.cost_snapshot_identities == ("fee-snapshot-rb-2026",)
    assert tuple(fill.cost_source_identity for fill in result.fills) == (
        "fee-snapshot-rb-2026",
        "fee-snapshot-rb-2026",
    )
    assert tuple(fill.contract_multiplier for fill in result.fills) == (
        Decimal("10"),
        Decimal("10"),
    )
    assert result.trades[0].net_pnl_per_contract == Decimal("76")


def test_bps_slippage_is_rounded_against_the_futures_price_tick() -> None:
    bars = tuple(
        _bar(index, value=str(value)) for index, value in enumerate((90, 100, 105, 110))
    )
    result = run_causal_long_only_backtest(
        bars,
        (
            BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, TREND_FORMULA),
            BacktestIntent(BacktestAction.CLEAR, bars[2].bar_end, TREND_FORMULA),
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
        (BacktestIntent(BacktestAction.BUILD, old[-1].bar_end, TREND_FORMULA),),
    )
    assert pending.fills == ()
    assert pending.cancelled_intent_count == 1

    opened = run_causal_long_only_backtest(
        old + (new,),
        (BacktestIntent(BacktestAction.BUILD, old[0].bar_end, TREND_FORMULA),),
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


def test_build_strategy_intents_preserves_primitive_rollover_reset() -> None:
    old_segment = tuple(
        _bar(index, value="1000") for index in range(20)
    )
    new_segment = tuple(
        _bar(
            20 + index,
            value=str(value),
            contract="RB2701",
            segment="rb-2701",
        )
        for index, value in enumerate((100, 80, 120, 80, 90, 130, 70, 140))
    )

    combined, versions = build_strategy_intents(
        old_segment + new_segment,
        ResearchStrategy.TREND,
    )
    fresh, fresh_versions = build_strategy_intents(
        new_segment,
        ResearchStrategy.TREND,
    )

    assert versions == (TREND_FORMULA,)
    assert fresh_versions == versions
    assert tuple(
        (intent.action, intent.signal_bar_end)
        for intent in combined
        if intent.signal_bar_end >= new_segment[0].bar_end
    ) == tuple((intent.action, intent.signal_bar_end) for intent in fresh)


def test_build_strategy_intents_rejects_an_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_STRATEGY_NOT_CAUSAL"):
        build_strategy_intents(
            (_bar(0, value="100"),),
            "unknown",  # type: ignore[arg-type]
        )


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


def test_low_level_executor_rejects_repainting_and_unknown_formula_intents() -> None:
    bars = tuple(
        _bar(index, value=str(value)) for index, value in enumerate((100, 101))
    )
    for formula in (ZHAOYAO_MIRROR_FORMULA_VERSION, "fixture_unregistered_v1"):
        with pytest.raises(ValueError, match="NEWOW_BACKTEST_SIGNAL_FORMULA_NOT_CAUSAL"):
            run_causal_long_only_backtest(
                bars,
                (BacktestIntent(BacktestAction.BUILD, bars[0].bar_end, formula),),
            )


def test_low_level_executor_rejects_strategy_and_formula_lineage_mismatch() -> None:
    bars = tuple(
        _bar(index, value=str(value)) for index, value in enumerate((100, 101))
    )

    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_STRATEGY_FORMULA_MISMATCH",
    ):
        run_causal_long_only_backtest(
            bars,
            (
                BacktestIntent(
                    BacktestAction.BUILD,
                    bars[0].bar_end,
                    OSCILLATION_FORMULA_VERSION,
                ),
            ),
            cost_snapshots=(_cost_snapshot(),),
            execution_constraints=(_constraint(bars[1]),),
            require_execution_facts=True,
            strategy=ResearchStrategy.TREND,
            signal_formula_versions=(TREND_FORMULA,),
        )

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.newow.price_channel import (
    CHANNEL_OPTIMIZER_CAUSAL_V1,
    CHANNEL_OPTIMIZER_PAGE_V1,
    CausalChannelWindowResult,
    PageChannelWindowResult,
    rank_causal_channel_windows,
    rank_page_channel_windows,
)
from guiyi_quant.newow.research_backtest import (
    CAUSAL_SIGNAL_FORMULAS,
    BacktestCostSnapshot,
    BacktestCosts,
    BacktestExecutionConstraint,
    NewowResearchBar,
    ResearchStrategy,
    build_strategy_intents,
)


UTC = timezone.utc


def _bar(
    index: int,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    contract: str = "RB2701",
    segment: str = "rb-2701-a",
    volume: int = 100,
    source: str | None = None,
) -> NewowResearchBar:
    value_date = date(2026, 1, 1) + timedelta(days=index)
    return NewowResearchBar(
        product="rb",
        physical_contract=contract,
        segment_id=segment,
        trading_day=value_date,
        bar_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
        open_interest=1000,
        source_identity=source or f"bar-{index}-{contract}",
        observation_eligible=True,
        completed=True,
        frequency="1d",
    )


def _bars() -> tuple[NewowResearchBar, ...]:
    bars = [
        _bar(index, open_="100", high="101", low="99", close="100")
        for index in range(14)
    ]
    bars[9] = _bar(9, open_="90", high="91", low="80", close="90")
    bars[10] = _bar(10, open_="92", high="95", low="90", close="93")
    bars[11] = _bar(11, open_="110", high="120", low="100", close="110")
    bars[12] = _bar(12, open_="108", high="110", low="105", close="108")
    bars[13] = _bar(13, open_="107", high="109", low="106", close="107")
    return tuple(bars)


def _cost_snapshot(
    *, contract: str = "RB2701", source: str = "fees-rb2701"
) -> BacktestCostSnapshot:
    return BacktestCostSnapshot(
        product="rb",
        physical_contract=contract,
        effective_from=date(2025, 1, 1),
        effective_to=date(2028, 1, 1),
        captured_at=datetime(2025, 12, 31, tzinfo=UTC),
        source_identity=source,
        costs=BacktestCosts(
            commission_per_contract=Decimal("2"),
            contract_multiplier=Decimal("10"),
            price_tick=Decimal("1"),
            slippage_ticks=1,
        ),
    )


def _constraint(
    bar: NewowResearchBar,
    *,
    limit_up: str = "200",
    limit_down: str = "1",
) -> BacktestExecutionConstraint:
    return BacktestExecutionConstraint(
        bar_source_identity=bar.source_identity,
        physical_contract=bar.physical_contract,
        limit_up=Decimal(limit_up),
        limit_down=Decimal(limit_down),
        captured_at=datetime(2025, 12, 31, tzinfo=UTC),
        source_identity=f"limits-{bar.source_identity}",
    )


def _run(
    bars: tuple[NewowResearchBar, ...],
    *,
    costs: tuple[BacktestCostSnapshot, ...] | None = None,
    constraints: tuple[BacktestExecutionConstraint, ...] | None = None,
) -> tuple[CausalChannelWindowResult, ...]:
    return rank_causal_channel_windows(
        bars,
        windows=(10,),
        cost_snapshots=costs or (_cost_snapshot(),),
        execution_constraints=constraints
        or tuple(_constraint(bar) for bar in bars),
        require_execution_facts=True,
    )


def test_causal_optimizer_signals_on_completed_bar_and_fills_next_open() -> None:
    bars = _bars()

    result = _run(bars)[0]

    assert result.backtest.strategy is ResearchStrategy.PRICE_CHANNEL
    assert result.backtest.signal_formula_versions == (
        CHANNEL_OPTIMIZER_CAUSAL_V1,
    )
    assert [fill.raw_open for fill in result.backtest.fills] == [
        bars[10].open,
        bars[12].open,
    ]
    assert all(
        fill.signal_bar_end < fill.fill_bar_end
        for fill in result.backtest.fills
    )
    assert result.backtest.fills[0].fill_price == Decimal("93")
    assert result.backtest.fills[1].fill_price == Decimal("107")
    assert result.backtest.trades[0].net_pnl_per_contract == Decimal("136")
    assert result.formula_version == CHANNEL_OPTIMIZER_CAUSAL_V1
    assert result.force_closed_at_end is False
    assert result.trustworthy_for_research is True


def test_causal_optimizer_rejects_disabled_execution_fact_gate() -> None:
    with pytest.raises(
        ValueError,
        match="NEWOW_BACKTEST_EXECUTION_CONSTRAINT_INVALID",
    ):
        rank_causal_channel_windows(
            _bars(),
            windows=(10,),
            cost_snapshots=(),
            execution_constraints=(),
            require_execution_facts=False,
        )


def test_page_and_causal_results_have_disjoint_identities_and_types() -> None:
    bars = _bars()

    page = rank_page_channel_windows(bars, windows=(10,))[0]
    causal = _run(bars)[0]

    assert type(page) is PageChannelWindowResult
    assert type(causal) is CausalChannelWindowResult
    assert page.formula_version == CHANNEL_OPTIMIZER_PAGE_V1
    assert causal.formula_version == CHANNEL_OPTIMIZER_CAUSAL_V1
    assert page.formula_version != causal.formula_version
    assert CHANNEL_OPTIMIZER_PAGE_V1 not in CAUSAL_SIGNAL_FORMULAS
    assert CHANNEL_OPTIMIZER_CAUSAL_V1 in CAUSAL_SIGNAL_FORMULAS


def test_causal_optimizer_is_future_tail_and_prefix_invariant() -> None:
    bars = _bars()
    prefix = bars[:13]
    changed_tail = (*bars[:-1], replace(bars[-1], close=Decimal("108")))

    prefix_result = _run(prefix)[0].backtest
    full_result = _run(bars)[0].backtest
    changed_result = _run(changed_tail)[0].backtest

    assert prefix_result.fills == full_result.fills
    assert full_result.fills == changed_result.fills
    assert full_result.trades == changed_result.trades


def test_rollover_cancels_pending_signal_before_next_open() -> None:
    bars = list(_bars()[:11])
    bars[10] = _bar(
        10,
        open_="92",
        high="95",
        low="90",
        close="93",
        contract="RB2705",
        segment="rb-2705-b",
    )
    frozen = tuple(bars)

    result = _run(
        frozen,
        costs=(
            _cost_snapshot(),
            _cost_snapshot(contract="RB2705", source="fees-rb2705"),
        ),
    )[0].backtest

    assert result.cancelled_intent_count == 1
    assert result.fills == ()


def test_rollover_excludes_an_open_position() -> None:
    bars = list(_bars()[:12])
    bars[11] = _bar(
        11,
        open_="110",
        high="120",
        low="100",
        close="110",
        contract="RB2705",
        segment="rb-2705-b",
    )
    frozen = tuple(bars)

    result = _run(
        frozen,
        costs=(
            _cost_snapshot(),
            _cost_snapshot(contract="RB2705", source="fees-rb2705"),
        ),
    )[0].backtest

    assert len(result.fills) == 1
    assert result.trades == ()
    assert result.incomplete_positions[0].reason == "DOMINANT_ROLL_EXCLUDED"


def test_open_position_at_end_is_not_force_closed() -> None:
    result = _run(_bars()[:11])[0]

    assert len(result.backtest.fills) == 1
    assert result.backtest.trades == ()
    assert result.backtest.incomplete_positions[0].reason == (
        "END_OF_SAMPLE_EXCLUDED"
    )
    assert result.force_closed_at_end is False


@pytest.mark.parametrize(
    ("bar_update", "constraint_update", "reason"),
    (
        ({"volume": 0}, {}, "ZERO_VOLUME"),
        ({"open": Decimal("100"), "high": Decimal("100")}, {"limit_up": "100"}, "BUY_AT_LIMIT_UP"),
    ),
)
def test_causal_optimizer_preserves_executor_rejections(
    bar_update: dict[str, object],
    constraint_update: dict[str, str],
    reason: str,
) -> None:
    bars = list(_bars())
    bars[10] = replace(bars[10], **bar_update)
    frozen = tuple(bars)
    constraints = tuple(
        _constraint(bar, **(constraint_update if index == 10 else {}))
        for index, bar in enumerate(frozen)
    )

    result = _run(frozen, constraints=constraints)[0].backtest

    assert result.rejected_fills[0].reason == reason


def test_causal_optimizer_fails_closed_on_missing_execution_identity() -> None:
    bars = _bars()
    constraints = tuple(_constraint(bar) for bar in bars if bar is not bars[10])

    with pytest.raises(
        ValueError, match="NEWOW_BACKTEST_EXECUTION_CONSTRAINT_MISSING"
    ):
        _run(bars, constraints=constraints)


def test_generic_strategy_dispatcher_cannot_guess_a_channel_window() -> None:
    with pytest.raises(ValueError, match="NEWOW_PRICE_CHANNEL_INVALID_WINDOW"):
        build_strategy_intents(_bars(), ResearchStrategy.PRICE_CHANNEL)

"""Explicit performance-window statistics over immutable reference trades."""

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from guiyi_quant.newow.reference_statistics import (
    PerformanceWindow,
    ReferenceSummary,
    reference_return_pct,
    summarize_reference,
)
from guiyi_quant.newow.reference_trades import (
    ReferenceProjection,
    ReferenceTradeProjector,
)


def _window(
    since: date = date(2026, 1, 5),
    through: date = date(2026, 1, 9),
    cutoff: datetime = datetime(2026, 1, 9, 16, tzinfo=UTC),
) -> PerformanceWindow:
    return PerformanceWindow(since=since, through=through, cutoff=cutoff)


def _project(case) -> ReferenceProjection:
    return ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    )


def test_reference_return_uses_decimal_percentage_points_and_fails_closed():
    assert reference_return_pct(Decimal("100"), Decimal("110")) == Decimal("10")
    assert reference_return_pct(Decimal("100"), Decimal("90")) == Decimal("-10")

    for invalid in (
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
        100,
        "100",
    ):
        with pytest.raises(ValueError, match="NEWOW_STATISTICS_INVALID_PRICE"):
            reference_return_pct(invalid, Decimal("100"))
        with pytest.raises(ValueError, match="NEWOW_STATISTICS_INVALID_PRICE"):
            reference_return_pct(Decimal("100"), invalid)


def test_closed_returns_are_summed_as_points_not_compounded(product_cases):
    gain = _project(product_cases.closed(entry="100", exit="110")).trades[0]
    loss = replace(
        _project(product_cases.closed(entry="100", exit="90")).trades[0],
        reference_trade_id="owned:loss-trade",
        entry_signal_id="owned:loss-build",
        exit_signal_id="owned:loss-clear",
    )
    projection = ReferenceProjection(
        trades=(gain, loss),
        bar_level_hints=(),
        unassigned_hints=(),
        diagnostics=(),
        as_of=datetime(2026, 1, 9, 16, tzinfo=UTC),
    )

    summary = summarize_reference(projection, _window())

    assert summary.closed_count == 2
    assert summary.win_count == 1
    assert summary.loss_count == 1
    assert summary.flat_count == 0
    assert summary.win_rate_pct == Decimal("50")
    assert summary.mean_return_pct == Decimal("0")
    assert summary.sum_return_percentage_points == Decimal("0")
    assert [trade.reference_return_pct for trade in summary.closed_trades] == [
        Decimal("10"),
        Decimal("-10"),
    ]
    assert all(
        trade.statistics_membership == "entry_in_window_v1"
        for trade in summary.closed_trades
    )


def test_one_losing_closed_trade_has_zero_win_rate_and_negative_mean(product_cases):
    projection = _project(product_cases.closed(entry="100", exit="90"))

    summary = summarize_reference(projection, _window())

    assert summary.closed_count == 1
    assert summary.win_count == 0
    assert summary.loss_count == 1
    assert summary.flat_count == 0
    assert summary.win_rate_pct == Decimal("0")
    assert summary.mean_return_pct == Decimal("-10")
    assert summary.sum_return_percentage_points == Decimal("-10")


def test_zero_return_is_flat_and_not_a_win(product_cases):
    projection = _project(product_cases.closed(entry="100", exit="100"))

    summary = summarize_reference(projection, _window())

    assert summary.closed_count == 1
    assert summary.win_count == 0
    assert summary.loss_count == 0
    assert summary.flat_count == 1
    assert summary.win_rate_pct == Decimal("0")
    assert summary.mean_return_pct == Decimal("0")
    assert summary.sum_return_percentage_points == Decimal("0")


def test_no_closed_trade_keeps_initial_open_and_interrupted_facts_separate(
    product_cases,
):
    initial = _project(product_cases.closed()).trades[0]
    open_trade = replace(
        _project(product_cases.open()).trades[0],
        reference_trade_id="owned:open-trade",
        entry_signal_id="owned:open-build",
        entry_bar_end=datetime(2026, 1, 6, 2, tzinfo=UTC),
        entry_trading_day=date(2026, 1, 6),
        mark_bar_end=datetime(2026, 1, 6, 3, tzinfo=UTC),
    )
    interrupted = replace(
        _project(product_cases.interrupted(mark="90")).trades[0],
        reference_trade_id="owned:interrupted-trade",
        entry_signal_id="owned:interrupted-build",
        entry_bar_end=datetime(2026, 1, 7, 2, tzinfo=UTC),
        entry_trading_day=date(2026, 1, 7),
        mark_bar_end=datetime(2026, 1, 7, 3, tzinfo=UTC),
        interrupted_at=datetime(2026, 1, 8, 0, tzinfo=UTC),
    )
    projection = ReferenceProjection(
        trades=(initial, open_trade, interrupted),
        bar_level_hints=(),
        unassigned_hints=(),
        diagnostics=(),
        as_of=datetime(2026, 1, 9, 16, tzinfo=UTC),
    )

    summary = summarize_reference(
        projection,
        _window(since=date(2026, 1, 6)),
    )

    assert summary.closed_count == 0
    assert summary.open_count == 1
    assert summary.interrupted_count == 1
    assert summary.initial_count == 1
    assert summary.win_rate_pct is None
    assert summary.mean_return_pct is None
    assert summary.sum_return_percentage_points is None
    assert [trade.reference_trade_id for trade in summary.open_trades] == [
        "owned:open-trade"
    ]
    assert [trade.reference_trade_id for trade in summary.interrupted_trades] == [
        "owned:interrupted-trade"
    ]
    assert [trade.reference_trade_id for trade in summary.initial_trades] == [
        initial.reference_trade_id
    ]
    assert summary.interrupted_trades[0].mark_change_pct == Decimal("-10.0")
    assert summary.interrupted_trades[0].reference_return_pct is None
    assert summary.initial_trades[0].statistics_membership == "initial_before_window"


@pytest.mark.parametrize("entry_day", [date(2026, 1, 5), date(2026, 1, 9)])
def test_entry_trading_day_window_boundaries_are_inclusive(
    product_cases, entry_day
):
    trade = _project(product_cases.closed()).trades[0]
    shifted = replace(
        trade,
        reference_trade_id=f"owned:boundary:{entry_day.isoformat()}",
        entry_signal_id=f"owned:boundary-build:{entry_day.isoformat()}",
        exit_signal_id=f"owned:boundary-clear:{entry_day.isoformat()}",
        entry_trading_day=entry_day,
    )
    projection = ReferenceProjection(
        trades=(shifted,),
        bar_level_hints=(),
        unassigned_hints=(),
        diagnostics=(),
        as_of=datetime(2026, 1, 9, 16, tzinfo=UTC),
    )

    summary = summarize_reference(projection, _window())

    assert summary.closed_count == 1


def test_night_session_membership_uses_authoritative_trading_day(product_cases):
    trade = _project(product_cases.closed(frequency="60m")).trades[0]
    night_trade = replace(
        trade,
        reference_trade_id="owned:night-session-trade",
        entry_signal_id="owned:night-session-build",
        exit_signal_id="owned:night-session-clear",
        entry_bar_end=datetime(2026, 1, 4, 13, tzinfo=UTC),
        entry_trading_day=date(2026, 1, 5),
        exit_bar_end=datetime(2026, 1, 5, 13, tzinfo=UTC),
        exit_trading_day=date(2026, 1, 6),
    )
    projection = ReferenceProjection(
        trades=(night_trade,),
        bar_level_hints=(),
        unassigned_hints=(),
        diagnostics=(),
        as_of=datetime(2026, 1, 6, 16, tzinfo=UTC),
    )

    summary = summarize_reference(
        projection,
        _window(
            since=date(2026, 1, 5),
            through=date(2026, 1, 5),
            cutoff=datetime(2026, 1, 6, 16, tzinfo=UTC),
        ),
    )

    assert night_trade.entry_bar_end.date() == date(2026, 1, 4)
    assert summary.closed_count == 1
    assert summary.initial_count == 0


def test_later_projection_and_exit_after_projection_cutoff_fail_closed(product_cases):
    projection = _project(product_cases.closed())
    earlier_cutoff = datetime(2026, 1, 8, 16, tzinfo=UTC)

    with pytest.raises(ValueError, match="NEWOW_STATISTICS_LATER_PROJECTION"):
        summarize_reference(projection, _window(cutoff=earlier_cutoff))

    damaged_trade = replace(
        projection.trades[0],
        exit_bar_end=datetime(2026, 1, 10, 7, tzinfo=UTC),
    )
    damaged = replace(
        projection,
        trades=(damaged_trade,),
        as_of=earlier_cutoff,
    )
    with pytest.raises(ValueError, match="NEWOW_STATISTICS_INVALID_PROJECTION"):
        summarize_reference(damaged, _window(cutoff=earlier_cutoff))


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_each_strategy_frequency_identity_is_summarized_independently(
    product_cases, strategy, frequency
):
    projection = _project(product_cases.closed(strategy=strategy, frequency=frequency))

    summary = summarize_reference(projection, _window())

    assert summary.closed_count == 1
    assert summary.closed_trades[0].strategy_code == strategy
    assert summary.closed_trades[0].frequency == frequency


def test_cross_identity_or_duplicate_trade_aggregation_fails_closed(product_cases):
    trend = _project(product_cases.closed(strategy="trend"))
    main_rise = _project(product_cases.closed(strategy="main_rise"))
    mixed = replace(trend, trades=(trend.trades[0], main_rise.trades[0]))

    with pytest.raises(ValueError, match="NEWOW_STATISTICS_MIXED_IDENTITY"):
        summarize_reference(mixed, _window())

    duplicated = replace(trend, trades=(trend.trades[0], trend.trades[0]))
    with pytest.raises(ValueError, match="NEWOW_STATISTICS_DUPLICATE_TRADE"):
        summarize_reference(duplicated, _window())


def test_display_window_cannot_change_summary_trade_id_or_close_state(product_cases):
    projection = _project(product_cases.closed())
    performance_window = _window()
    narrow_display = (date(2026, 1, 6), date(2026, 1, 6))
    wide_display = (date(2025, 12, 1), date(2026, 1, 9))

    narrow_summary = summarize_reference(projection, performance_window)
    wide_summary = summarize_reference(projection, performance_window)

    assert narrow_display != wide_display
    assert narrow_summary == wide_summary
    assert narrow_summary.closed_trades[0].reference_trade_id == (
        projection.trades[0].reference_trade_id
    )
    assert narrow_summary.closed_trades[0].status == "CLOSED"


def test_statistics_contracts_are_immutable_and_exclude_account_metrics(product_cases):
    window = _window()
    summary = summarize_reference(_project(product_cases.open()), window)

    with pytest.raises(FrozenInstanceError):
        window.since = date(2026, 1, 6)
    with pytest.raises(FrozenInstanceError):
        summary.open_count = 0

    public_fields = {field.name for field in fields(ReferenceSummary)}
    assert public_fields.isdisjoint(
        {
            "annualized_return",
            "equity_curve",
            "capital_drawdown",
            "position_size",
            "margin",
            "account_pnl",
            "portfolio_return",
        }
    )


@pytest.mark.parametrize(
    ("since", "through", "cutoff"),
    [
        (date(2026, 1, 10), date(2026, 1, 9), datetime(2026, 1, 10, tzinfo=UTC)),
        (
            datetime(2026, 1, 5, tzinfo=UTC),
            date(2026, 1, 9),
            datetime(2026, 1, 9, tzinfo=UTC),
        ),
        (date(2026, 1, 5), date(2026, 1, 9), datetime(2026, 1, 9)),
    ],
)
def test_invalid_performance_window_fails_closed(since, through, cutoff):
    with pytest.raises(ValueError, match="NEWOW_STATISTICS_INVALID_WINDOW"):
        PerformanceWindow(since=since, through=through, cutoff=cutoff)

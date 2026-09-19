from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, Inexact, ROUND_DOWN, localcontext

import pytest

from guiyi_quant.subing_reference import (
    ReferenceBar,
    ReferenceSegment,
    ReferenceProjectionError,
    project_reference,
    replay_subing_step,
    seed_subing_replay_state,
)
from guiyi_quant.indicators.subing_ths import SubingThs15mKernel

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def segment(prices=None, **kwargs):
    prices = prices if prices is not None else [100] * 50 + [120, 80, 120, 80]
    bars = tuple(
        ReferenceBar(
            START + timedelta(hours=i),
            (START + timedelta(hours=i)).date(),
            Decimal(str(p)),
        )
        for i, p in enumerate(prices)
    )
    return ReferenceSegment(
        "RB2605",
        "rb-segment",
        bars,
        bars[0].trading_day,
        bars[-1].trading_day,
        **kwargs,
    )


def project(seg, **kwargs):
    return project_reference(
        "RB",
        (seg,),
        since=kwargs.get("since", date(2026, 1, 1)),
        through=kwargs.get("through", date(2026, 1, 9)),
        as_of=kwargs.get("as_of", START + timedelta(days=9)),
    )


def test_real_kernel_reversals_preserve_decimal_prices_and_explicit_links():
    seg = segment()
    result = project(seg)
    assert [s.direction for s in result.signals] == ["buy", "sell", "buy", "sell"]
    assert [s.action for s in result.signals] == [
        "OPEN_LONG",
        "REVERSE_TO_SHORT",
        "REVERSE_TO_LONG",
        "REVERSE_TO_SHORT",
    ]
    assert [t.side for t in result.trades] == ["LONG", "SHORT", "LONG", "SHORT"]
    assert [t.status for t in result.trades] == ["CLOSED"] * 3 + ["OPEN"]
    first, short = result.trades[:2]
    assert first.exit_reference_price == Decimal(80)
    assert first.reference_return_pct == (Decimal(80) - 120) / 120 * 100
    assert short.reference_return_pct == Decimal(-50)
    assert first.holding_bars == 1
    assert result.signals[1].closed_trade_id == first.reference_trade_id
    assert result.signals[1].entry_trade_id == short.reference_trade_id
    assert first.exit_signal_id == short.entry_signal_id
    assert result.summary.closed_count == 3
    assert result.summary.loss_count == 3
    assert result.summary.win_rate_pct == 0
    assert result.trades[-1].mark_reference_price == Decimal(80)


@pytest.mark.parametrize("frequency", ("15m", "30m", "60m", "1d"))
def test_public_projection_and_bounded_per_bar_state_share_one_step(frequency):
    seg = segment()
    expected = project_reference(
        "RB", (seg,), since=date(2026, 1, 1), through=date(2026, 1, 9),
        as_of=START + timedelta(days=9), frequency=frequency,
    )
    state = seed_subing_replay_state()
    signals = []
    closed = []
    indicators = []
    for bar in seg.bars:
        state, signal, trade, indicator = replay_subing_step(
            "RB", seg, frequency, False, state, bar,
            since=date(2026, 1, 1), through=date(2026, 1, 9),
        )
        if signal is not None:
            signals.append(signal)
        if trade is not None:
            closed.append(trade)
        if indicator is not None:
            indicators.append(indicator)
    assert tuple(signals) == expected.signals
    assert tuple((*closed, state.current)) == expected.trades
    assert tuple(indicators) == expected.indicators


def test_per_bar_replay_freezes_decimal_policy_like_public_projection():
    seg = segment()
    state = seed_subing_replay_state()
    with localcontext(Context(prec=6, rounding=ROUND_DOWN, traps=[Inexact])):
        for bar in seg.bars:
            state, _signal, _closed, _indicator = replay_subing_step(
                "RB", seg, "15m", False, state, bar,
                since=date(2026, 1, 1), through=date(2026, 1, 9),
            )
    assert state.current is not None
    assert state.current.mark_change_pct == Decimal(0)


def test_15m_v1_reference_identity_golden_is_unchanged():
    result = project(segment())
    assert [item.signal_id for item in result.signals] == [
        "cbc12f0caed57ef6ee4ae4053bd467df4163047512aa36d2aaf3499621d11ed4",
        "71384b116dd8d8139c9bddd6654609dcc58e14633875122f7a9e5a91f8653c5a",
        "c971031a487becf2f4ada8d6c9f6a706f888bbe4fa38cf772678aff5dd48be85",
        "d24a9c5ff37575a61d6bb5fa1111e1b68a598bb30e6ab5385161a04de20ea566",
    ]
    assert [item.reference_trade_id for item in result.trades] == [
        "c62c10d0360bc71db062bca2dc7b0f6203327263e17ef519013ba9a5451ad87c",
        "fedcff95ff82f56bf25fe17d3e7a6778fab86f226d5eb1f245e14258197187f2",
        "b79d08dc1de3c870d77bb6835a1b4db8dacd2266d655f7b7f3ea36f3df230385",
        "ae2e00b894292835f6aeff99c818810660aab74c698210b7e07d64186c49250f",
    ]


def test_periods_share_formula_values_but_keep_independent_signal_identity():
    seg = segment()
    options = dict(since=date(2026, 1, 1), through=date(2026, 1, 9), as_of=START + timedelta(days=9))
    results = {frequency: project_reference("RB", (seg,), frequency=frequency, **options)
               for frequency in ("15m", "30m", "60m", "1d")}
    assert all([s.direction for s in value.signals] == ["buy", "sell", "buy", "sell"]
               for value in results.values())
    assert len({value.signals[0].signal_id for value in results.values()}) == 4
    assert len({value.trades[0].reference_trade_id for value in results.values()}) == 4
    for value in results.values():
        first_signal = value.signals[0]
        matching = next(point for point in value.indicators if point.bar_end == first_signal.bar_end)
        assert (matching.dif, matching.dea, matching.macd, matching.ema21) == (
            first_signal.dif, first_signal.dea, first_signal.macd, first_signal.ema21)


def test_complete_short_lifecycle_reports_warming_instead_of_zero_signal_readiness():
    short = segment([100] * 10)
    result = project(short)
    assert result.readiness == "warming"
    assert result.signals == ()
    assert result.indicators
    assert all(point.ema21 is None for point in result.indicators)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (33, "WARMING"),
        (34, "INDICATOR_READY_CROSS_UNEVALUABLE"),
        (35, "CROSS_EVALUATED"),
    ],
)
def test_daily_quality_model_freezes_33_34_35_bar_states(count, expected):
    seg = replace(
        segment([100] * count),
        calculation_segment_id="daily-calculation",
    )
    result = project_reference(
        "RB", (seg,), since=date(2026, 1, 1), through=date(2026, 1, 9),
        as_of=START + timedelta(days=9), frequency="1d",
        quality_segmented=True,
    )

    assert result.readiness == expected
    assert result.indicators[-1].calculation_segment_id == "daily-calculation"


def test_daily_quality_break_interrupts_without_exit_return_or_current_mark():
    break_at = START + timedelta(days=3)
    seg = replace(
        segment(),
        calculation_segment_id="daily-before-break",
        quality_interrupted_at=break_at,
        quality_interruption_trading_day=break_at.date(),
        quality_classification="NONPOSITIVE_CLOSE",
    )
    result = project_reference(
        "RB", (seg,), since=date(2026, 1, 1), through=date(2026, 1, 9),
        as_of=break_at, frequency="1d", quality_segmented=True,
    )

    trade = result.trades[-1]
    assert trade.status == "DATA_INTERRUPTED"
    assert trade.exit_signal_id is None
    assert trade.exit_reference_price is None
    assert trade.reference_return_pct is None
    assert trade.mark_bar_end is None
    assert trade.mark_reference_price is None
    assert trade.mark_change_pct is None
    assert trade.interruption_reason == "NONPOSITIVE_CLOSE"
    assert result.summary.data_interrupted_count == 1
    assert result.summary.rollover_interrupted_count == 0


def test_daily_quality_trade_interrupted_before_window_is_not_initial_history():
    break_at = START + timedelta(days=3)
    seg = replace(
        segment(),
        calculation_segment_id="daily-before-window-break",
        quality_interrupted_at=break_at,
        quality_interruption_trading_day=break_at.date(),
        quality_classification="NONPOSITIVE_CLOSE",
    )
    result = project_reference(
        "RB", (seg,), since=break_at.date() + timedelta(days=1),
        through=date(2026, 1, 9), as_of=break_at,
        frequency="1d", quality_segmented=True,
    )

    assert result.trades == ()
    assert result.summary.initial_count == 0
    assert result.summary.data_interrupted_count == 0


def test_first_sell_opens_short_without_fabricated_long():
    result = project(segment([100] * 50 + [80]))
    assert result.signals[0].action == "OPEN_SHORT"
    assert result.trades[0].side == "SHORT"
    assert result.trades[0].exit_bar_end is None


def test_completed_prefix_and_window_do_not_change_identity_or_kernel_candidates():
    seg = segment()
    full = project(seg)
    cutoff = seg.bars[51].bar_end
    prefix = project(seg, as_of=cutoff)
    truncated = project(replace(seg, bars=seg.bars[:52]))
    assert prefix == truncated
    assert prefix.signals == full.signals[:2]
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    expected = []
    for bar in seg.bars:
        state, output = kernel.step(
            state, float(bar.close), bar_end=bar.bar_end.isoformat()
        )
        expected.extend((bar.bar_end, code) for code in output.result_codes)
    assert [(s.bar_end, s.direction) for s in full.signals] == expected
    assert full.trades[1].reference_trade_id == prefix.trades[1].reference_trade_id


def test_initial_positions_are_reconstructed_and_excluded_from_closed_statistics():
    seg = segment([100] * 46 + [120] * 2 + [80] * 2 + [120] * 2)
    result = project(seg, since=date(2026, 1, 3))
    assert result.trades[0].initial
    assert result.trades[0].entry_trading_day == date(2026, 1, 2)
    assert result.summary.initial_count == 1
    assert result.summary.closed_count == 1
    assert all(s.trading_day >= date(2026, 1, 3) for s in result.signals)


def test_rollover_interrupts_without_exit_or_return_and_does_not_leak_future():
    cutoff = START + timedelta(days=3)
    seg = segment(interrupted_at=cutoff)
    current = project(seg, as_of=cutoff - timedelta(seconds=1))
    ended = project(seg, as_of=cutoff)
    assert current.trades[-1].status == "OPEN"
    trade = ended.trades[-1]
    assert trade.status == "ROLLOVER_INTERRUPTED"
    assert trade.exit_reference_price is None
    assert trade.reference_return_pct is None
    assert trade.interrupted_at == cutoff
    assert ended.summary.interrupted_count == 1


@pytest.mark.parametrize(
    "bad", [Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity"), 100.0]
)
def test_invalid_price_fails_closed(bad):
    seg = segment()
    with pytest.raises(
        ReferenceProjectionError, match="SUBING_REFERENCE_DATA_CONFLICT"
    ):
        project(replace(seg, bars=(replace(seg.bars[0], close=bad),) + seg.bars[1:]))


@pytest.mark.parametrize("kind", ["duplicate", "reverse", "naive", "empty", "overlap"])
def test_invalid_order_identity_and_missing_input_fail_closed(kind):
    seg = segment()
    if kind == "duplicate":
        seg = replace(seg, bars=(seg.bars[0],) + seg.bars)
    elif kind == "reverse":
        seg = replace(seg, bars=seg.bars[::-1])
    elif kind == "naive":
        seg = replace(
            seg,
            bars=(replace(seg.bars[0], bar_end=START.replace(tzinfo=None)),)
            + seg.bars[1:],
        )
    elif kind == "empty":
        seg = replace(seg, bars=())
    with pytest.raises(ReferenceProjectionError):
        if kind == "overlap":
            project_reference(
                "RB",
                (seg, seg),
                since=date(2026, 1, 1),
                through=date(2026, 1, 9),
                as_of=START + timedelta(days=9),
            )
        else:
            project(seg)


def test_same_direction_signal_retains_existing_entry_without_duplicate_trade():
    tail = [
        101,
        102,
        97,
        96,
        99,
        101,
        102,
        101,
        103,
        103,
        107,
        105,
        108,
        105,
        104,
        101,
        97,
        101,
        100,
        103,
        107,
        104,
        103,
        99,
        95,
        100,
        100,
        102,
        105,
        101,
        101,
        102,
        102,
        106,
        111,
        109,
        112,
        114,
        116,
        119,
        118,
        113,
        116,
        111,
        107,
        108,
        113,
        118,
        113,
        117,
    ]
    result = project(segment([100] * 50 + tail))
    assert result.signals[-1].action == "SAME_DIRECTION"
    assert result.signals[-1].entry_trade_id == result.signals[-2].entry_trade_id
    assert result.signals[-1].closed_trade_id is None
    assert len(result.trades) == len(result.signals) - 1


def test_physical_segment_starts_fresh_and_requires_explicit_interruption():
    first = segment()
    next_start = date(2026, 1, 4)
    second_bars = tuple(
        replace(
            b,
            bar_end=b.bar_end + timedelta(days=3),
            trading_day=b.trading_day + timedelta(days=3),
        )
        for b in first.bars[:20]
    )
    second = ReferenceSegment("RB2610", "next", second_bars, next_start, next_start)
    kwargs = dict(
        since=date(2026, 1, 1),
        through=date(2026, 1, 9),
        as_of=START + timedelta(days=9),
    )
    with pytest.raises(ReferenceProjectionError):
        project_reference("RB", (first, second), **kwargs)
    first = replace(first, interrupted_at=second_bars[0].bar_end)
    result = project_reference("RB", (first, second), **kwargs)
    assert all(s.physical_contract == "RB2605" for s in result.signals)
    assert result.trades[-1].status == "ROLLOVER_INTERRUPTED"


def test_interrupted_trade_before_window_is_not_an_initial_position():
    seg = segment(interrupted_at=START + timedelta(days=3))
    result = project(seg, since=date(2026, 1, 6))
    assert result.trades == ()
    assert result.summary.initial_count == 0
    assert result.summary.interrupted_count == 0


def test_interrupted_interval_uses_owner_trading_day_not_timestamp_calendar_day():
    # The ownership transition can occur on a later calendar day; the old
    # reference ends at its final owned trading day, not the transition date.
    seg = segment(interrupted_at=START + timedelta(days=5, hours=21))
    assert (
        project(seg, since=date(2026, 1, 3)).trades[-1].status == "ROLLOVER_INTERRUPTED"
    )
    result = project(seg, since=date(2026, 1, 4))
    assert result.trades == ()
    assert result.summary.initial_count == 0


def test_decimal_results_ignore_ambient_precision_rounding_and_traps():
    from decimal import localcontext, ROUND_DOWN, Inexact

    seg = segment()
    expected = project(seg)
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        assert project(seg) == expected
        assert context.prec == 6
        assert context.rounding == ROUND_DOWN
        assert context.traps[Inexact]

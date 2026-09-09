from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.subing_reference import (
    ReferenceBar,
    ReferenceSegment,
    ReferenceProjectionError,
    project_reference,
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

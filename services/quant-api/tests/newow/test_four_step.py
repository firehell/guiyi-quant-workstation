from decimal import Decimal as D

from guiyi_quant.newow.four_step import FourStepEvent, fold_four_step, summarize_four_step


def event(index, source, kind, price, sequence=0):
    return FourStepEvent(index, source, kind, D(price), sequence)


def test_public_same_bar_and_page_baseline_follow_the_actual_source():
    replay = fold_four_step(60, D(132), [
        event(10, "trend", "BUILD", 110),
        event(10, "oscillation", "BUILD", 100),
        event(15, "trend", "BUILD", 111),
        event(20, "trend", "CLEAR", 125),
        event(20, "oscillation", "CLEAR", 120),
        event(20, "oscillation", "BUILD", 110),
        event(35, "trend", "CLEAR", 121),
        event(40, "oscillation", "BUILD", 120),
    ])
    assert [trade.reason for trade in replay.trades] == ["OSCILLATION_CLEAR", "TREND_CLEAR", "TERMINAL_VALUATION"]
    assert [trade.return_pct.quantize(D(".01")) for trade in replay.trades] == [D("14.55"), D("10.00"), D("10.00")]
    assert [trade.return_pct for trade in replay.page_baseline] == [D(20), D(10), D(10)]
    assert summarize_four_step(replay.trades).average_return_pct == D("11.52")


def test_page_scope_skips_short_input_and_keeps_exit_valuation_separate():
    events = [event(10, "oscillation", "BUILD", 100)]
    assert not fold_four_step(59, D(106), events).trades
    result = fold_four_step(60, D(106), events)
    assert summarize_four_step(result.trades).terminal_valuation_count == 1
    assert summarize_four_step(result.trades).trend_exit_count == 0


def test_causal_same_bar_clear_reopens_strictly_later_and_respects_one_lot_volume():
    from datetime import UTC, datetime, timedelta
    from guiyi_quant.paper import FeeSchedule, ObserveExecutionBar
    from app.paper.four_step_research import Target, replay_targets

    t0 = datetime(2026, 8, 1, 1, tzinfo=UTC)
    fees = FeeSchedule(D(0), D(1), D(0), D(2), D(0), D(3), "test")
    minutes = tuple(ObserveExecutionBar(
        str(i), t0 + timedelta(minutes=i), "2026-08-01", "JM2701",
        t0 + timedelta(minutes=i-1), t0 + timedelta(minutes=i), True,
        D(100), D(105), D(95), D(100), volume, True, D(120), D(80), D(1), 1, D(10),
        fees, D(100), f"bar-{i}", "commission", "limits", "margin",
    ) for i, volume in enumerate([2, 9, 1, 1, 9, 1, 2]))
    result = replay_targets(minutes, {minutes[0].bar_end: Target(2), minutes[3].bar_end: Target(2, True)})
    assert replay_targets(minutes[:2], {minutes[0].bar_end: Target(2)})["entry_lots"] == 0
    assert result["entry_lots"] == 3
    assert result["exit_lots"] == 2
    assert result["round_trips"] == 1
    assert result["end_open_lots"] == 1
    assert result["fees"] == "9"

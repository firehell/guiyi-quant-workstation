from datetime import datetime, timedelta, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_counter_m_continuation_study import first_rebuilt_envelope
from lms405_counter_m_exit_clocks import progress_clocks


def test_rebuild_price_cannot_reuse_exit_minute_or_quote_minute():
    start = datetime(2026, 10, 23, 10, tzinfo=timezone(timedelta(hours=8)))
    minute = timedelta(minutes=1)
    us = timedelta(microseconds=1)
    bars = []
    for index, value in enumerate((110, 103, 110)):
        price = Decimal(value)
        bar_start = start + index * minute
        bars.append(Bar("JM2701", bar_start + minute, price, price, price, price, start=bar_start))
    args = dict(after=start + us, target_ticks=range(220, 221), lots=2, tick=Decimal(1))
    assert first_rebuilt_envelope(bars, cutoff=bars[2].end + us, **args) is None
    assert first_rebuilt_envelope(bars, cutoff=bars[2].end + 2 * us, **args) == bars[2].end + us


def test_progress_retreat_updates_anchor_before_evaluating_reversal_and_stops_at_break():
    start = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)
    minute = timedelta(minutes=1)

    def make_bar(index, low, high, close):
        begin = start + index * minute
        return Bar("JM2701", begin + minute, Decimal(close), Decimal(high), Decimal(low),
                   Decimal(close), start=begin)

    bars = [make_bar(0, 100, 105, 101), make_bar(1, 98, 106, 106), make_bar(2, 98, 107, 106)]
    broken = progress_clocks(bars + [make_bar(4, 101, 108, 107)], "SHORT", Decimal(100))
    assert broken["far_retreat"]["at"] == bars[1].end
    assert broken["last_push_retreat"] is None
    joined = make_bar(3, 101, 108, 107)
    continuous = progress_clocks(bars + [joined], "SHORT", Decimal(100))
    assert continuous["last_push_retreat"] == {
        "at": joined.end, "close": Decimal(107), "threshold": Decimal(106), "anchor_end": bars[1].end,
    }

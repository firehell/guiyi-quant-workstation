from datetime import datetime, timedelta, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_counter_m_continuation_study import first_rebuilt_envelope


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

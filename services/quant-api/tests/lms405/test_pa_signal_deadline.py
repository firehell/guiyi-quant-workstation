from datetime import datetime, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_pa_signal_deadline import comparison, quantity_support, time_constraints
from lms405_right_side_study import ONE, US


START = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)


def one_minute(offset, low, high):
    start = START + offset * ONE
    prices = map(Decimal, (low, high, low, high))
    return Bar("SA2701", start + ONE, *prices, start=start)


def test_separate_ohlc_ranges_do_not_assume_missing_ticks():
    assert quantity_support(set(), {100, 102}, 2, range(203, 204)) == []
    assert quantity_support({100}, {102}, 2, range(202, 203)) == [1]


def test_whole_minute_strictly_after_signal_and_band_price_bounds():
    rows = [one_minute(0, 100, 100), one_minute(1, 102, 102), one_minute(2, 104, 104)]
    kwargs = dict(lots=2, totals=range(204, 205), tick=Decimal(1))
    same_bar = comparison(rows, gate_known_at=START + ONE, band=None, **kwargs)
    assert same_bar["minimum_outside_later_price_set"] == 1
    earlier = comparison(rows, gate_known_at=START + ONE - US, band=None, **kwargs)
    assert earlier["whole_leg_with_later_prices"] is True
    capped = comparison(rows, gate_known_at=START + ONE - US, band=(Decimal(100), Decimal(101)), **kwargs)
    assert capped["minimum_outside_later_price_set"] is None
    missing = comparison(rows, gate_known_at=None, band=None, **kwargs)
    assert missing["whole_leg_with_later_prices"] is None


def test_quote_minute_can_change_feasibility_without_picking_a_trade_time():
    rows = [one_minute(0, 100, 100), one_minute(1, 100, 100), one_minute(2, 110, 110)]
    quotes = rows[-1].end
    args = dict(event_clocks={"opening": rows[0].end}, quote_end=quotes,
                tick=Decimal(1), band=None, lots=2, totals=range(210, 211))
    included = time_constraints(rows, **args)
    excluded = time_constraints(rows[:-1], **args)
    assert included["latest_strict_signal_knowledge_bound_exclusive"] == rows[1].start
    assert included["by_gate"]["opening"]["minimum_outside_later_price_set"] == 1
    assert excluded["latest_strict_signal_knowledge_bound_exclusive"] is None
    assert excluded["by_gate"]["opening"]["minimum_outside_later_price_set"] is None

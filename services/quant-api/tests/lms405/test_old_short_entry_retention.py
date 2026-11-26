from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from lms405_old_short_entry_retention import attempts, strict_price
from lms405_protection_lot_timing import displayed_tick_totals

LOCAL = timezone(timedelta(hours=8))
MINUTE = timedelta(minutes=1)


def quote(end, trading_day, price):
    return SimpleNamespace(bar_end=end, trading_day=trading_day, low=Decimal(price), high=Decimal(price))


def test_price_window_excludes_entry_minute_overlap_and_after_exit_prices():
    entry = datetime(2026, 10, 20, 9, 15, 0, 5, tzinfo=LOCAL)
    rows = [quote(entry.replace(microsecond=0) + MINUTE * i, entry.date(), price)
            for i, price in ((1, 1720), (2, 1718), (3, 1720))]
    totals = displayed_tick_totals(Decimal("1720.0"), 20, Decimal(1))
    assert strict_price(rows, since=entry, through=rows[1].bar_end, lots=20, totals=totals, tick=Decimal(1)) == {
        "price_compatible": False, "tick_bounds": (1718, 1718), "minutes": 1,
        "first_single_minute_price_compatible_end": None,
    }
    found = strict_price(rows, since=entry, through=rows[-1].bar_end, lots=20, totals=totals, tick=Decimal(1))
    assert found["price_compatible"]
    assert found["first_single_minute_price_compatible_end"] == rows[-1].bar_end


def test_prior_leg_price_compatibility_can_survive_despite_not_holding_at_snapshot():
    entry = datetime(2026, 10, 19, 22, 5, 0, 5, tzinfo=LOCAL)
    snapshot = datetime(2026, 10, 22, 21, 1, tzinfo=LOCAL)
    day = (entry + timedelta(days=1)).date()
    rows = [quote(entry.replace(microsecond=0) + MINUTE * i, day, price)
            for i, price in ((0, 684), (1, 684), (2, "682.5"), (3, 681))]
    trace = [dict(action="ENTER_SHORT", at=entry), dict(action="CLEAR", at=rows[2].bar_end + timedelta(microseconds=5))]
    totals = displayed_tick_totals(Decimal("682.50"), 16, Decimal("0.5"))
    result, = attempts(trace, {day: rows}, first_quote=snapshot, last_quote=snapshot, observed_day=snapshot.date(),
                       tick=Decimal("0.5"), lots=16, totals=totals)
    assert result["trading_day"] == day
    assert result["qualifies_as_prior_trading_day"]
    assert result["price_during_open_leg"]["price_compatible"]
    assert not result["active_before_first_quote_minute"]
    assert not result["active_before_last_quote_minute"]


def test_clear_inside_quote_minute_does_not_change_before_minute_state():
    entry = datetime(2026, 10, 19, 22, 5, 0, 5, tzinfo=LOCAL)
    day = (entry + timedelta(days=1)).date()
    snapshot = datetime(2026, 10, 20, 9, 16, tzinfo=LOCAL)
    clear = snapshot - timedelta(seconds=30)
    rows = [quote(entry.replace(microsecond=0), day, 684), quote(snapshot - MINUTE, day, "682.5")]
    trace = [dict(action="ENTER_SHORT", at=entry), dict(action="CLEAR", at=clear)]
    tick = Decimal("0.5")
    totals = displayed_tick_totals(Decimal("682.50"), 16, tick)
    result, = attempts(trace, {day: rows}, first_quote=snapshot, last_quote=snapshot,
                       observed_day=day, tick=tick, lots=16, totals=totals)
    assert result["active_before_first_quote_minute"]
    assert not result["qualifies_as_prior_trading_day"]

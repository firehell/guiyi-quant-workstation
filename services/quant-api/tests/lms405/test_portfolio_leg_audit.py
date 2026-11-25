from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_portfolio_leg_audit import compare_leg, leg_changes


def test_protection_removal_and_readdition_keep_original_leg_origin():
    start = datetime(2026, 10, 27, 6, tzinfo=UTC)
    minutes = timedelta(minutes=5)

    def row(index, action, before, after):
        return dict(at=(start + index * minutes).isoformat(), action=action, before=before, after=after)

    transitions = [row(0, "ENTER_SHORT", (0, 0), (0, 1)), row(1, "LOCK", (0, 1), (1, 1)),
                   row(2, "UNLOCK_SHORT", (1, 1), (0, 1)), row(3, "LOCK", (0, 1), (1, 1))]
    _, last = leg_changes("SH2701", transitions)[-1]
    assert last["short"] == (start, "ENTER_SHORT", start + minutes)
    assert last["long"] == (start + 3 * minutes, "LOCK", None)


def test_today_and_average_require_available_window_for_active_leg():
    minute = timedelta(minutes=1)
    first = datetime(2026, 10, 27, 6, tzinfo=UTC)
    night = first + timedelta(hours=7)
    next_day = night.date() + timedelta(days=1)

    def bar(end, day, price):
        return SimpleNamespace(bar_end=end, trading_day=day, low=Decimal(price), high=Decimal(price))

    bars = [bar(first + minute, first.date(), 1480), bar(night + minute, next_day, 1492)]
    quote_end = night + 2 * minute
    observed = dict(quantity=20, today_quantity=20)
    result = compare_leg(observed, Decimal("1492.0"), next_day, quote_end, (first, "LOCK", None),
                         bars, Decimal(20), Decimal(1))
    assert result["status"] == "TRADING_DAY_DIFFERS"
    assert result["price_compatible_if_trade_day_can_be_deferred"]
    fixed = compare_leg(observed, Decimal("1492.0"), next_day, quote_end, (first, "LOCK", night),
                        bars, Decimal(20), Decimal(1))
    assert not fixed["price_compatible_if_trade_day_can_be_deferred"]

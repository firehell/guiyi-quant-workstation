from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from lms405_portfolio_origin_window import cohort_price_support


def test_prior_and_current_lots_use_trading_day_not_calendar_day_or_quote_minute():
    local = ZoneInfo("Asia/Shanghai")
    quote = datetime(2026, 10, 22, 21, 3, tzinfo=local)
    current_day, prior_day = date(2026, 10, 23), date(2026, 10, 22)

    def minute(end, day, price):
        return SimpleNamespace(bar_end=end, trading_day=day, low=Decimal(price), high=Decimal(price))

    minutes = [minute(quote.replace(hour=15, minute=0), prior_day, 100),
               minute(quote - timedelta(minutes=1), current_day, 104),
               minute(quote, current_day, 125)]
    assert cohort_price_support(dict(quantity=4, today_quantity=1), Decimal("101.0"), current_day,
                                quote, minutes, Decimal(1)) == {
        "status": "COHORT_PRICE_COMPATIBLE", "earlier_tick_bounds": (100, 100),
        "current_tick_bounds": (104, 104), "required_earlier_lots": 3,
    }
    result = cohort_price_support(dict(quantity=4, today_quantity=2), Decimal("110.0"), current_day,
                                  quote, minutes, Decimal(1))
    assert result["status"] == "COHORT_PRICE_OUTSIDE_ENVELOPE"


def test_old_lots_without_prior_minutes_stay_out_of_price_support():
    local = ZoneInfo("Asia/Shanghai")
    quote = datetime(2026, 10, 22, 21, 3, tzinfo=local)
    day = date(2026, 10, 23)
    minutes = [SimpleNamespace(bar_end=quote - timedelta(minutes=1), trading_day=day,
                               low=Decimal(105), high=Decimal(105))]
    leg = dict(quantity=20, today_quantity=0)
    assert cohort_price_support(leg, Decimal("105.0"), day, quote, minutes, Decimal(1))[
        "status"
    ] == "REQUIRED_COHORT_HAS_NO_MINUTES"
    assert cohort_price_support(leg | dict(today_quantity=None), Decimal("105.0"), day, quote,
                                minutes, Decimal(1)) == {"status": "TODAY_UNKNOWN"}


def test_one_prior_day_support_is_stricter_than_combined_envelope():
    local = ZoneInfo("Asia/Shanghai")
    quote = datetime(2026, 10, 22, 21, 3, tzinfo=local)
    minutes = [SimpleNamespace(bar_end=quote.replace(day=day, hour=15), trading_day=date(2026, 10, day),
                               low=Decimal(price), high=Decimal(price)) for day, price in ((21, 98), (22, 106))]
    result = cohort_price_support(dict(quantity=20, today_quantity=0), Decimal("102.0"), date(2026, 10, 23),
                                  quote, minutes, Decimal(1))
    assert result["status"] == "COHORT_PRICE_COMPATIBLE"
    assert result["prior_whole_leg_price_days"] == []

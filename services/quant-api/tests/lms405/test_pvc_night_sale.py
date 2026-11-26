from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE
from lms405_v_exit_study import CONTRACT, SALE_MINUTE, sale_price_cohorts


def test_lots_from_overlapping_sale_minute_are_only_a_sensitivity():
    minutes = []
    for offset, raw in ((-2, 120), (0, 110), (1, 100), (2, 110)):
        start, price = SALE_MINUTE + offset * ONE, Decimal(raw)
        minutes.append(Bar(CONTRACT, start + ONE, price, price, price, price, start=start))
    result = sale_price_cohorts(minutes, SALE_MINUTE + 4 * ONE, quantity=2, totals=range(220, 221))
    assert result["exclude_report_minute"]["minimum_earlier_lots"] == 1
    assert result["allow_report_minute_as_later"]["minimum_earlier_lots"] == 0
    assert result["exclude_report_minute"]["before_after_ticks"] == ((120, 120), (100, 100))


def test_report_and_quote_in_same_minute_do_not_create_new_lots():
    prior = Decimal(110)
    minutes = [Bar(CONTRACT, SALE_MINUTE - ONE, prior, prior, prior, prior, start=SALE_MINUTE - 2 * ONE)]
    result = sale_price_cohorts(minutes, SALE_MINUTE + ONE, quantity=2, totals=range(220, 221))
    assert result["relationship"] == "SAME_MINUTE_ORDER_UNRESOLVED"
    assert result["allow_report_minute_as_later"]["minimum_earlier_lots"] == 2

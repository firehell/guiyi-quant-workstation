from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, US, at
from lms405_sa_bd_clock import path


def test_price_path_excludes_cutoff_and_keeps_touch_separate_from_cross():
    def candle(clock, close):
        end = at(f"2026-10-20T{clock}")
        price = Decimal(close)
        return Bar("SA2701", end, price, price, price, price, start=end - ONE)

    minutes = [candle("09:31", 946), candle("09:32", 948),
               candle("09:34", 946), candle("09:36", 948)]
    series = {1: minutes, 5: [], 15: []}
    start = at("2026-10-20T09:30")
    bands = {"late": (Decimal(941), Decimal(946))}
    earlier = path(series, start, at("2026-10-20T09:32") + US, bands)
    assert earlier["price_areas"]["late"]["first_touch"] == minutes[0].end
    assert earlier["price_areas"]["late"]["first_fresh_close_cross_above"] is None
    later = path(series, start, at("2026-10-20T09:37"), bands)
    assert later["price_areas"]["late"]["first_fresh_close_cross_above"] == minutes[1].end
    across_gap = path(series, minutes[1].end, at("2026-10-20T09:37"), bands)
    assert across_gap["price_areas"]["late"]["first_fresh_close_cross_above"] is None
    assert path(series, at("2026-10-20T15:00"), start, bands)["minutes"] == 0

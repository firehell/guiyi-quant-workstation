from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_fg_exit_study import minute_context, pressure_timeline, range_recapture
from lms405_right_side_study import ONE, at


def test_software_row_minute_uses_bar_start_not_bar_end():
    row_time = "2026-10-27T14:08"
    start = at(row_time)
    prior = Bar("FG2701", start, Decimal(833), Decimal(836), Decimal(831), Decimal(834),
                start=start - ONE)
    containing = Bar("FG2701", start + ONE, Decimal(844), Decimal(847), Decimal(844), Decimal(847),
                     start=start)

    result = minute_context([prior, containing], row_time, ("831", "832"))

    assert result["last_bar_ending_at_minute"]["close"] == Decimal(834)
    assert result["containing_bar"]["low"] == Decimal(844)
    assert result["containing_bar"]["high"] == Decimal(847)
    assert result["reference_opening_averages"]["832"] == {
        "inside_bar": False, "strictly_above_all_prices": False, "strictly_below_all_prices": True,
    }


def test_two_close_recapture_requires_earlier_down_cross_in_same_segment():
    start = at("2026-09-14T09:00")
    px = [101, 99, 98, 101, 102]
    bars = [Bar("FG2701", start + i * ONE, *([Decimal(close)] * 4), start=start + (i - 1) * ONE)
            for i, close in enumerate(px, 1)]
    assert pressure_timeline(bars, Decimal(100))["up_after_down_in_same_segment"] == {
        "down_two_closes_at": bars[2].end, "recapture_two_closes_at": bars[4].end,
    }
    assert range_recapture(bars, Decimal(100), Decimal(101)) is None
    last = Bar("FG2701", start + 6 * ONE, *([Decimal(103)] * 4), start=start + 5 * ONE)
    assert range_recapture([*bars, last], Decimal(100), Decimal(101)) == {
        "down_two_closes_at": bars[2].end, "recapture_two_closes_at": last.end,
    }

    reopen = start + 10 * ONE
    renewed = [Bar("FG2701", reopen + i * ONE, *([Decimal(close)] * 4), start=reopen + (i - 1) * ONE)
               for i, close in enumerate([100, 101, 102], 1)]
    split = pressure_timeline(bars[:3] + renewed, Decimal(100))
    assert split["first_up_two_closes_at"] == renewed[-1].end
    assert split["up_after_down_in_same_segment"] is None

from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_fg_exit_study import minute_context
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

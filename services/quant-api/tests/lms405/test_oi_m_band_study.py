from decimal import Decimal
from types import SimpleNamespace

from lms405_oi_m_band_study import PRIOR_LOW, first_strict_close_below
from lms405_right_side_study import at


def test_prior_low_requires_completed_close_below_and_ignores_a_touch():
    rows = [SimpleNamespace(bar_end=at(f"2026-06-05T09:0{index}"), low=Decimal("10229"), close=Decimal(close))
            for index, close in enumerate(("10231", "10230", "10229"), start=1)]
    assert first_strict_close_below(rows[:2], PRIOR_LOW) is None
    assert first_strict_close_below(rows, PRIOR_LOW) == at("2026-06-05T09:03")

from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, at
from lms405_rubber_m_classification import close_returns


def test_band_returns_preserve_exact_boundaries_and_session_breaks():
    start = at("2026-10-28T10:12")
    bars = []
    for minute, close in ((1, 95), (2, 100), (3, 115), (19, 110), (20, 105)):
        end = start + minute * ONE
        price = Decimal(close)
        bars.append(Bar("RU2701", end, price, price, price, price, start=end - ONE))

    band = Decimal(100), Decimal(110)
    rows = close_returns(bars, band)
    assert [(row["return_at"], row["close"], row["from_side"], row["adjacent"]) for row in rows] == [
        (bars[1].end, Decimal(100), "BELOW", True),
        (bars[3].end, Decimal(110), "ABOVE", False),
    ]
    assert close_returns(bars[:3], band) == rows[:1]

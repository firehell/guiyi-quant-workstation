from decimal import Decimal

from lms405_jm_oct_recovery_clock import observed_before_quote
from lms405_right_side_study import ONE, US, at


def test_release_candidate_excludes_the_entire_quote_minute_and_equal_price():
    minute_end = at("2026-10-09T21:37")
    same_minute_start = minute_end - ONE
    signals = {"5m_to_1m": [
        {"confirmed_at": same_minute_start - 2 * US, "available_at": same_minute_start - US,
         "close": Decimal("1542.5")},
        {"confirmed_at": same_minute_start - US, "available_at": same_minute_start,
         "close": Decimal("1543")},
    ]}
    outputs = observed_before_quote(signals, [minute_end])["5m_to_1m"]
    assert [x["strict_before_candidates"] for x in outputs] == [1, 0]
    assert [x["closes_above_1542_5"] for x in outputs] == [False, True]
    quote_only = observed_before_quote(signals, [minute_end], compare_jm_target=False)["5m_to_1m"]
    assert [x["strict_before_candidates"] for x in quote_only] == [1, 0]
    assert all("closes_above_1542_5" not in row for row in quote_only)

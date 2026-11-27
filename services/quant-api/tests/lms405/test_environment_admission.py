from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_portfolio_environment_audit import context_before, known_and, opening_alternatives


def test_environment_cutoff_is_strict_before_for_both_full_and_prefix_input():
    start = datetime(2026, 10, 22, 12, tzinfo=UTC)
    step = timedelta(minutes=5)
    bars = [Bar("SH2701", start + i * step, *map(Decimal, (100 + i, 105 + i, 99 + i, 102 + i)),
                start=start + (i - 1) * step) for i in range(1, 10)]
    known = bars[5].end + timedelta(microseconds=1)
    assert context_before(bars, known) is None
    after = known + timedelta(microseconds=1)
    assert context_before(bars, after) == context_before(bars[:6], after)
    assert context_before(bars, after)["window_end"] == bars[5].end.isoformat()
    assert context_before(bars, after)["environment"] == "UP"


def test_two_consecutive_opening_labels_cannot_change_the_first_vote():
    items = [dict(author_class="DOWN", day_close={"environment": "DOWN"},
                  opening_clocks=[{"environment": value} for value in ("UP", "UP", "DOWN")])]
    scores = opening_alternatives(items)
    assert scores["ROLLING"]["first_agrees"] == 0
    assert scores["TWO_LOCAL_VOTES"]["first_agrees"] == 1
    assert scores["TWO_LOCAL_VOTES"]["cases_with_flip"] == 1
    assert scores["HOLD_DAY_CLOSE"]["all_agree"] == 1
    assert known_and(None, False) is False and known_and(False, None) is False
    assert known_and(True, None) is None

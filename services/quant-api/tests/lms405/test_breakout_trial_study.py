from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_breakout_trial_study import price_states


def test_cross_contact_and_rejection_are_distinct_and_discarded_across_a_gap():
    minute = timedelta(minutes=1)
    start = datetime(2026, 10, 27, 1, tzinfo=UTC)
    examples = (
        (0, (103, 104, 102, 103)),
        (1, (102, 103, 98, 99)),
        (2, (99, 101, 98, 100)),
        (3, (99, 99, 97, 98)),
        (5, (98, 99, 97, 98)),
    )
    bars = []
    for offset, prices in examples:
        opened = start + offset * minute
        bars.append(Bar("V2701", opened + minute, *map(Decimal, prices), start=opened))
    state = price_states(bars, "SHORT", Decimal(100), Decimal(105))
    assert state[bars[1].end]["crossing"] is True
    assert state[bars[1].end]["retest_contact_at"] is None
    assert state[bars[2].end]["outside"] is False
    assert state[bars[2].end]["retest_contact_at"] == bars[2].end
    assert state[bars[2].end]["retest_confirmed_at"] is None
    assert state[bars[3].end]["retest_confirmed_at"] == bars[3].end
    assert state[bars[4].end]["outside"] is True
    assert state[bars[4].end]["active_cross_at"] is None
    assert state[bars[4].end]["retest_confirmed_at"] is None

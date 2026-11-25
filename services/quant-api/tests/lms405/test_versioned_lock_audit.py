from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, at
from lms405_versioned_lock_audit import return_clocks


def test_divider_return_excludes_reopen_and_counts_inclusive_edges():
    bars = []
    for stamp, price in (("10:14", "1257"), ("10:30", "1258.5"), ("10:31", "1269.5"),
                         ("10:32", "1269"), ("10:33", "1258"), ("10:34", "1258.5")):
        start = at(f"2026-04-24T{stamp}")
        value = Decimal(price)
        bars.append(Bar("JM2609", start + ONE, value, value, value, value, start=start))

    report = return_clocks(bars, (Decimal("1258.5"), Decimal("1269")))
    assert report["inside_close_count"] == 3
    assert report["same_session_returns"] == {
        "FROM_ABOVE": ["2026-04-24T10:33+08:00"],
        "FROM_BELOW": ["2026-04-24T10:35+08:00"],
    }

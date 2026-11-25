from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_pvc_december_counter_m import BAND, CONTRACT, POST_CUTOFF, first_return
from lms405_right_side_study import ONE, at


def make_bar(clock, prices):
    start = at(f"2025-12-22T{clock}")
    return Bar(CONTRACT, start + ONE, *map(Decimal, prices), start=start)


def test_pvc_post_retest_excludes_spanning_minutes_and_reopens():
    rows = [make_bar("21:24", (4715, 4720, 4714, 4718)),
            make_bar("21:25", (4718, 4720, 4700, 4712)),  # Straddles publication.
            make_bar("21:27", (4713, 4720, 4702, 4715)),  # No adjacent predecessor.
            make_bar("21:28", (4715, 4720, 4704, 4717))]
    assert first_return(rows, band=BAND, after=POST_CUTOFF) == rows[-1]

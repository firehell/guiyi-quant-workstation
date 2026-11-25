from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_path_stage_audit import hypothetical_publication_cutoffs
from lms405_right_side_study import FIVE, ONE, at
from lms405_v_zone_progress import publication_windows


def test_publication_cutoffs_match_whole_bar_rule_for_touch_and_close():
    bars = []
    for clock, low, close in (("13:55", "766.5", "767"), ("14:00", "766", "766"), ("14:05", "766.5", "767")):
        end = at(f"2026-06-04T{clock}")
        bars.append(Bar("I2609", end, Decimal(768), Decimal(769), Decimal(low), Decimal(close), start=end - FIVE))

    cutoffs = hypothetical_publication_cutoffs(bars, (Decimal("766.5"), Decimal("768.5")), "SHORT")
    for name, expected in (("directional_far_reach", bars[-1]), ("strict_close_beyond_far", bars[-2])):
        cutoff = expected.start - ONE
        assert cutoffs[name]["latest_release_minute_for_any"] == cutoff.isoformat(timespec="minutes")
        assert publication_windows(bars, cutoff)[1][0] == expected
        assert expected not in publication_windows(bars, cutoff + ONE)[1]

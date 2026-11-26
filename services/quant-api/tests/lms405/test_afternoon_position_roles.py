from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_afternoon_position_roles import CONTRACT, REPORT_START, compare_paths, report_clocks
from lms405_right_side_study import ONE


def test_missing_close_rows_only_constrain_explicit_complete_account_hypothesis():
    glass = compare_paths(CONTRACT, (None, 20), (None, None))
    assert all(row["visible_close_compatible"] is None for row in glass.values())
    assert {name for name, row in glass.items() if row["complete_scope_close_compatible"]} == {
        "close_original_short", "lock_then_clear",
    }
    assert not glass["add_protective_long"]["contains_short_reduction"]
    assert glass["lock_then_clear"]["timeline"][0] == dict(action="LOCK", long=20, short=20)


def test_visible_old_short_distinguishes_withdrawing_a_hedge_from_closing_original():
    soda = compare_paths("SH2701", (20, 20), (None, 20))
    assert soda["hold"]["visible_close_compatible"]
    assert not soda["hold"]["complete_scope_close_compatible"]
    assert not soda["close_original_short"]["visible_close_compatible"]
    assert not soda["clear_both"]["visible_close_compatible"]
    assert soda["withdraw_protective_long"]["complete_scope_close_compatible"]
    assert not soda["withdraw_protective_long"]["contains_short_reduction"]


def test_minute_only_report_cannot_use_bar_ending_at_minute_end():
    start = REPORT_START - 3 * ONE
    bars = []
    for n, close in enumerate(map(Decimal, (844, 845, 846, 847)), start=1):
        begin = start + (n - 1) * ONE
        bars.append(Bar(CONTRACT, begin + ONE, close, close, close, close, start=begin))
    series = {1: bars, 5: [], 15: []}
    preceding = report_clocks(series, start, REPORT_START)
    possible = report_clocks(series, start, REPORT_START + ONE)
    assert preceding["complete_minutes"] == 2
    assert preceding["edges"]["844"]["first_up_two_closes_at"] is None
    assert possible["complete_minutes"] == 3
    assert possible["edges"]["844"]["first_up_two_closes_at"] == REPORT_START

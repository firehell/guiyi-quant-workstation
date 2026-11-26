from decimal import Decimal

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.portfolio_tasks import Book
from lms405_jm_first_lock_handoff import EARLY_SHORT, LONG_WINDOWS, NEW_SHORT, counts_from_replay, project_roles
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, US, at


def bar(start, low, high):
    low, high = Decimal(low), Decimal(high)
    return Bar("JM2701", start + ONE, low, high, low, high, start=start)


def test_replacement_respects_old_protection_cohort_and_excludes_both_quote_minutes():
    start = at("2026-10-22T21:45")
    old_quote = start + 4 * ONE
    new_quote = start + 9 * ONE
    tick, lots = Decimal(1), 2
    old = [bar(start + 2 * ONE, 99, 101)]
    old_quote_row = bar(old_quote - ONE, 120, 120)
    new = [bar(old_quote + 3 * ONE, 109, 110)]
    new_quote_row = bar(new_quote - ONE, 130, 130)
    out = counts_from_replay(
        [*old, old_quote_row, *new, new_quote_row], old_at=start + US, old_quote=old_quote,
        next_quote=new_quote, known_at=old_quote + US, tick=tick, lots=lots,
        old_total=displayed_tick_totals(Decimal("100.0"), lots, tick),
        new_total=displayed_tick_totals(Decimal("110.0"), lots, tick),
    )
    assert out["old_range_ticks"] == (99, 101)
    assert out["all_ending_lots_new_after_possible"]
    assert out["max_old_retained"] == 0


def test_fixture_has_independent_exit_and_fresh_short_with_new_episode():
    start = at("2026-10-22T21:45")
    old = Book("JM2701", "old", "SHORT", start, Decimal(20), Decimal(20), attempt=1)
    result = project_roles(old, Decimal(20), {"m_far_strict_close": start + ONE, LONG_WINDOWS[0]: start + 2 * ONE},
                           {EARLY_SHORT: start + 3 * ONE, NEW_SHORT: start + 4 * ONE}, "new-plan")
    clear, entry, exit_m, fresh = result["independent_approvals"]
    assert result["old_lock_unchanged"] == old
    assert (clear["operation"], entry["operation"], exit_m["operation"], fresh["operation"]) == (
        "CLEAR_TREND", "ENTER_COUNTER_M", "EXIT_COUNTER_M", "ENTER_TREND",
    )
    assert all(row["public"]["after"] is None for row in result["independent_approvals"])
    assert fresh["before"].episode != old.episode
    assert result["late_book"].visible.short == 20

from decimal import Decimal

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.portfolio_tasks import Book
from lms405_jm_first_lock_handoff import (
    EARLY_SHORT, LONG_WINDOWS, NEW_SHORT, close_cohort_continuity, counts_from_replay, project_roles,
)
from lms405_jm_m_leg_handoff import CLOSE, FIRST
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


def test_individually_compatible_prices_cannot_explain_two_averages_with_one_unchanged_leg():
    opened = at("2026-10-22T21:45") + US
    minutes = [bar(at("2026-10-22T21:47"), 1399, 1401), bar(at("2026-10-22T21:53"), 1410, 1410)]
    first_quote = "2026-10-22T21:50:00+08:00"
    close_quote = "2026-10-23T15:00:00+08:00"

    def snapshot(source, quote, origin, average):
        return dict(source=source, side="long", assumed_trading_day="2026-10-23",
                    visible=dict(quantity=20, today_quantity=20, opening_average=average),
                    by_variant=dict(strict_replay={quote: dict(status="PRICE_COMPATIBLE", origin_at=origin)}))

    old = snapshot(FIRST, first_quote, opened, "1400.1")
    for origin, retained in ((opened, 20), (at("2026-10-22T21:52"), 0)):
        new = snapshot(CLOSE, close_quote, origin, "1410.00")
        result = close_cohort_continuity([old, new], minutes, Decimal("0.5"))
        assert result["opening_tick_sums"][FIRST] == [56004]
        assert list(result["individually_compatible_quote_pairs"].values()) == [
            dict(projected_retained=retained, minimum_replacement=20, price_compatible=retained == 0),
        ]


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

from decimal import Decimal
from types import SimpleNamespace

from lms405_partial_leg_exposure import END, POLICIES, START, additions_by_retained, cohorts, position_view, price_allocations
from lms405_right_side_study import ONE, at


def test_replacement_paths_keep_old_and_new_cohorts_separate():
    allocation = (5, 11, 2, 2)
    expected = ([20, 5, 16, 18, 20, 20], [20] * 6, [20, 20, 31, 33, 35, 20])
    for policy, quantities in zip(POLICIES, expected, strict=True):
        states = cohorts(allocation, policy)
        assert [state["side_lots"] for state in states] == quantities
        assert [state["retained_old"] for state in states] == [5] * 6
        assert states[-1] == {"retained_old": 5, "old_yet_to_remove": 0, "new_present": 15, "side_lots": 20}


def test_unlisted_opposite_is_unknown_and_visible_short_contribution_is_signed():
    low_point = cohorts((5, 15, 0, 0), POLICIES[0])[1]
    unlisted = position_view("OI2701", "short", None, low_point)
    assert unlisted["signed_visible_side"] == -5
    assert unlisted["net_lots"] is unlisted["gross_lots"] is None
    paired = position_view("I2701", "long", 16, low_point)
    assert paired["net_lots"] == -11
    assert paired["gross_lots"] == 21


def test_only_permissive_window_can_reuse_earlier_quote_minute():
    def minute(end, price):
        return SimpleNamespace(bar_end=end, low=Decimal(price), high=Decimal(price))

    rows = [minute(START - ONE, 10), minute(START, 10), minute(at("2026-10-27T13:31"), 11),
            minute(END, 11), minute(END + ONE, 10)]
    endpoint = {"earlier_leg": {"quantity": 1}, "old_ticks": (10, 10), "retained": [0, 1],
                "old_tick_sum": (10, 10), "new_tick_sum": (10, 10)}
    permissive = price_allocations(rows, endpoint, Decimal(1), include_earlier_quote=True)
    strict = price_allocations(rows, endpoint, Decimal(1), include_earlier_quote=False)
    assert permissive["allocations"] == [(0, 1, 0, 0), (1, 0, 0, 0)]
    assert strict["allocations"] == [(1, 0, 0, 0)]
    assert additions_by_retained(permissive["allocations"]) == {
        0: {"through_14_00": [1, 1], "through_14_30": [1, 1]},
        1: {"through_14_00": [0, 0], "through_14_30": [0, 0]},
    }

from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_oi_public_lifecycle import CONTRACT, DAY_OPEN, edge_window, handoff_paths
from lms405_right_side_study import ONE, US, at


def opening_example():
    prices = ((100, 102, 93, 96), (96, 97, 91, 93), (93, 96, 92, 94), (94, 95, 89, 90))
    minutes = [Bar(CONTRACT, DAY_OPEN + i * ONE, *map(Decimal, row), start=DAY_OPEN + (i - 1) * ONE)
               for i, row in enumerate(prices, 1)]
    return {1: minutes, 5: [], 15: []}


def test_open_at_edge_has_no_adjacent_crossing_and_needs_new_shape():
    series = opening_example()
    confirmation_known = series[1][-1].end + US
    withheld = edge_window(series, Decimal(100), start=DAY_OPEN, cut=confirmation_known)
    assert withheld["groups"]["1m_to_1m"]["after_first_below"] is None
    active = edge_window(series, Decimal(100), start=DAY_OPEN, cut=confirmation_known + US)
    assert active["opening_at_edge_then_close_below_at"] == DAY_OPEN + ONE
    assert active["first_fresh_cross_known_at"] is None
    minute = active["groups"]["1m_to_1m"]
    assert minute["after_first_below"]["confirmed_at"] == series[1][-1].end
    assert minute["after_first_below"]["shape_start"] > DAY_OPEN + ONE + US
    assert minute["after_opening_at_edge_in_same_run"] == minute["after_first_below"]
    assert minute["after_fresh_cross_in_same_run"] is None


def test_late_source_cannot_confirm_morning_and_same_end_position_can_have_different_actions():
    morning = at("2026-06-05T10:27")
    path = edge_window(opening_example(), Decimal(100), start=DAY_OPEN, cut=morning)
    rows = handoff_paths(path, seed_time=at("2026-06-04T16:52"), morning_cut=morning,
                        report_known=at("2026-06-05T17:01"))
    assert rows["COUNTER_M_FROM_LOCK"]["fixture"]["requested_action"] == "UNLOCK_SHORT"
    assert rows["COUNTER_M_AFTER_CLEAR"]["fixture"]["requested_action"] == "ENTER_SHORT"
    for row in rows.values():
        assert row["fixture"]["after"] == {"long": "0", "short": "1"}
        assert row["fixture"]["confirmation_kind"] == "TEST_FIXTURE"
        assert row["fixture_same_time"]["after"] is None
        assert row["morning_public_assessment"]["sources"] == []
        assert row["morning_public_assessment"]["after"] is None
        assert row["later_public_assessment"]["status"] == "INDETERMINATE"
        assert row["later_public_assessment"]["after"] is None

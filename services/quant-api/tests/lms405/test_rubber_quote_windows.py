from decimal import Decimal
from types import SimpleNamespace

from lms405_rubber_quote_windows import compare_candidate, joint_quote_timing, price_constraints
from lms405_right_side_study import ONE, US, at


def test_rubber_price_bounds_respect_band_edges_and_exact_lot_average():
    ticks = Decimal("5")
    first = price_constraints(
        [SimpleNamespace(low=Decimal("19500"), high=Decimal("19600"))],
        tick=ticks, lots=20, average=Decimal("19505.0"), band=(Decimal("19530"), Decimal("19680")),
    )
    assert first["minimum_lots_outside_on_that_side"] == 17
    second = price_constraints(
        [SimpleNamespace(low=Decimal("19405"), high=Decimal("19495"))],
        tick=ticks, lots=20, average=Decimal("19470.0"), band=(Decimal("19360"), Decimal("19405")),
    )
    assert second["minimum_lots_outside_on_that_side"] == 15


def test_quote_minute_only_uses_bars_entirely_after_candidate():
    end = at("2026-10-22T21:25")
    bars = [
        SimpleNamespace(start=end, end=end + ONE, low=Decimal("19505"), high=Decimal("19530")),
        SimpleNamespace(start=end + ONE, end=end + 2 * ONE, low=Decimal("19515"), high=Decimal("19530")),
        SimpleNamespace(start=end + 2 * ONE, end=end + 3 * ONE, low=Decimal("19500"), high=Decimal("19530")),
    ]
    leg = dict(tick=Decimal("5"), lots=20, average=Decimal("19505.0"),
               band=(Decimal("19530"), Decimal("19680")))
    result = compare_candidate(bars, {}, end + US, [bar.end for bar in bars], leg)
    assert result["first_compatible_quote_minute"] == "2026-10-22T21:28+08:00"
    assert not result["by_quote_minute"]["2026-10-22T21:26+08:00"]["whole_leg_price_possible"]


def test_joint_quote_report_keeps_asynchronous_fit_distinct_from_same_minute():
    earlier, later = "2026-10-22T21:25+08:00", "2026-10-22T21:27+08:00"
    photo = {"per_symbol": {
        "ru": {"contains": [later], "equal_close": []},
        "sh": {"contains": [earlier], "equal_close": [earlier]},
        "oi": {"contains": [earlier, later], "equal_close": [later]},
    }}
    result = joint_quote_timing(photo)
    assert result["contains"]["best_same_minute_count"] == 2
    assert result["contains"]["minimum_bar_end_separation_minutes"] == 2
    assert result["contains"]["witnesses"] == [{
        "last_minute_end": later, "matched_per_symbol": {"ru": later, "sh": earlier, "oi": later},
    }]
    assert result["equal_close"]["minimum_bar_end_separation_minutes"] is None

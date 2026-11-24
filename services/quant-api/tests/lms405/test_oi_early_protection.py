from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from lms405_oi_june_case import DAYS, SHANGHAI, early_protection_path, observe_band


def at(minute):
    return datetime(2026, 6, 3, 10, minute, tzinfo=SHANGHAI)


def bar(minute, op, high, low, close):
    return SimpleNamespace(
        bar_end=at(minute), trading_day=DAYS[0],
        open=Decimal(op), high=Decimal(high), low=Decimal(low), close=Decimal(close),
    )


def test_band_touch_edge_equality_and_strict_break_are_separate():
    events = observe_band([
        bar(15, "10199", "10200", "10197", "10199"),
        bar(16, "10199", "10199", "10195", "10197"),
        bar(17, "10180", "10181", "10175", "10175"),
        bar(18, "10175", "10175", "10174", "10174"),
    ], Decimal("10175"), Decimal("10197"))
    assert events == {
        "intersects": at(15), "close_reaches_near_edge": at(16), "close_strictly_below_far_edge": at(18),
    }


def test_fast_close_exists_before_following_five_minute_completes():
    series = {
        "1m": [
            bar(15, "10200", "10201", "10198", "10201"),
            *[bar(minute, "10202", "10205", "10200", "10202") for minute in range(16, 21)],
            bar(21, "10202", "10203", "10197", "10197"),
            *[bar(minute, "10197", "10198", "10196", "10196") for minute in range(22, 26)],
        ],
        "5m": [
            bar(15, "10200", "10212", "10198", "10201"),
            bar(20, "10202", "10205", "10200", "10202"),
            bar(25, "10202", "10203", "10196", "10196"),
        ],
        "15m": [bar(15, "10201", "10212", "10198", "10201")],
    }
    coverage = {
        period: {item.bar_end: (item.trading_day, False) for item in items} for period, items in series.items()
    }
    us = timedelta(microseconds=1)
    early = early_protection_path(series, coverage, as_of=at(21))
    assert not early["short_keybar_geometry"]
    assert early["bar_counts"]["15m"] == 0
    immediate = early_protection_path(series, coverage, as_of=at(21) + us)
    (row,) = immediate["short_keybar_geometry"]
    fast = row["evidence"]["1M_CLOSE"]
    assert fast["bar_end"] == at(21).isoformat(timespec="minutes")
    near = fast["bands"]["NEAR_HIGH_VOLATILITY"]
    assert near["first_contact_same_end"] and near["close_in_band"]
    assert near["earlier_contact"] is None
    assert row["evidence"]["5M_CLOSE"] is None
    later = early_protection_path(series, coverage, as_of=at(25) + us)
    assert later["short_keybar_geometry"][0]["evidence"]["1M_CLOSE"] == fast
    slow_checks = later["short_keybar_geometry"][0]["evidence"]["5M_CLOSE"]["bands"]
    assert slow_checks["NEAR_HIGH_VOLATILITY"]["earlier_contact"] == at(24).isoformat(timespec="minutes")
    assert slow_checks["NEAR_HIGH_VOLATILITY"]["earlier_contact_same_contiguous_run"]
    assert slow_checks["FAR_BASELINE"]["earlier_contact"] is None
    assert (later["protection_status"], later["action"]) == ("INDETERMINATE", None)

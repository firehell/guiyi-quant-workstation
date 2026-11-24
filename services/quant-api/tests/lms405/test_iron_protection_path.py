from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from lms405_i2701_case import at, protection_path, rounded_average_ticks


def minute(end, low, high, close):
    return SimpleNamespace(
        bar_end=end, open=Decimal(low), low=Decimal(low), high=Decimal(high), close=Decimal(close),
    )


def test_displayed_average_maps_to_tick_totals_without_inventing_execution_prices():
    assert list(rounded_average_ticks(Decimal("663.34"), 16, Decimal("0.5"))) == [21227]
    assert list(rounded_average_ticks(Decimal("10.00"), 1, Decimal("0.005"))) == [1999, 2000]
    assert not rounded_average_ticks(Decimal("663.34"), 1, Decimal("0.5"))


def test_price_gate_excludes_trigger_minute_and_cannot_see_past_midday(monkeypatch):
    monkeypatch.setattr("lms405_i2701_case.keybar_windows", lambda *args, **kwargs: [])
    first_night = datetime.fromisoformat("2026-10-26T21:01:00+08:00")
    minutes = [
        minute(first_night, "669", "673.5", "670.5"),
        minute(at("09:01"), "663", "663.5", "663.5"),
        minute(at("10:14"), "663", "663.5", "663.5"),
        minute(at("10:15"), "664", "664.5", "664"),
        minute(at("11:29"), "663", "667", "666.5"),
        minute(at("11:30"), "666.5", "667.5", "666.5"),
        minute(at("13:31"), "663", "670", "670"),
    ]
    report = protection_path(minutes, [], Decimal("0.5"), 16, Decimal("663.34"))
    gates = report["area_conditions"]
    assert gates["night_close_above_671"]["first_trigger_bar_end"] is None
    after_touch = gates["morning_touch_protection_667"]
    assert after_touch["first_trigger_bar_end"] == at("11:29").isoformat(timespec="minutes")
    assert after_touch["trigger_minute"]["envelope_allows_average"]
    assert not after_touch["next_minute"]["envelope_allows_average"]
    assert not after_touch["rest_of_session_window"]["envelope_allows_average"]
    assert not gates["morning_high_above_667"]["next_minute"]["count"]
    assert gates["morning_close_above_667"]["first_trigger_bar_end"] is None
    early_post_window = report["minute_windows"]["after_early_post_minute"]
    assert early_post_window["start"] == at("10:14").isoformat(timespec="minutes")
    assert early_post_window["same_minute_envelope_count"] == 1
    assert report["unlisted_early_long"] is None

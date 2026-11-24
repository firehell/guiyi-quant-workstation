from decimal import Decimal
from types import SimpleNamespace

from guiyi_quant.lms405 import Bar
from lms405_sh_protection_case import CONTRACT, assess_source, at, path


def test_no_chase_blocks_new_short_without_deciding_protection_or_leaking_before_source():
    plan = {"published_at": "2026-10-22T09:30:00+08:00", "source_url": "https://example.test/day"}
    before = assess_source(plan, "day", at("2026-10-22T09:31"), no_chase=True)
    assert before["decisions"]["RIGHT_PARTICIPATION"]["status"] == "INDETERMINATE"
    day = assess_source(plan, "day", at("2026-10-22T09:32"), no_chase=True)
    assert day["decisions"]["RIGHT_PARTICIPATION"]["failed"] == ["RIGHT_POLICY_PERMITS"]
    assert day["decisions"]["LOCK_PROTECTION"]["status"] == "INDETERMINATE"
    assert "PROTECTION_SIGNAL" in day["decisions"]["LOCK_PROTECTION"]["unknown"]
    assert day["action"] is None
    night = assess_source(plan, "new-plan", at("2026-10-22T21:01"), no_chase=False)
    assert night["decisions"]["RIGHT_PARTICIPATION"]["status"] == "INDETERMINATE"


def test_protection_band_contact_and_shape_confirmation_have_distinct_times():
    def end(minute):
        return at(f"2026-10-22T21:{minute:02}")

    minutes = [SimpleNamespace(bar_end=end(n), low=Decimal(lo), high=Decimal(hi), close=Decimal(close))
               for n, lo, hi, close in ((11, "1598", "1612", "1611"), (12, "1611", "1620", "1619"))]
    fives = [
        Bar(CONTRACT, end(5), Decimal(1595), Decimal(1608), Decimal(1588), Decimal(1599), start=end(0)),
        Bar(CONTRACT, end(10), Decimal(1599), Decimal(1605), Decimal(1595), Decimal(1600), start=end(5)),
    ]
    report = path(minutes, fives, start=end(0), before=end(12), band=(Decimal(1610), Decimal(1632)),
                  extension=Decimal(1543), observed_average=Decimal("1618.5"))
    (confirm,) = report["geometric_confirmations"]["LONG"]
    assert confirm["close_at"] == end(11).isoformat(timespec="minutes")
    assert confirm["prior_protection_contact"] is None
    assert confirm["close_inside_protection_band"] is True
    assert report["first_contact"] == end(11).isoformat(timespec="minutes")
    assert report["first_minute_range_contains_average"] is None
    assert report["first_window_prefix_range_contains_average"] is None
    assert report["author_signal_at"] is None


def test_weighted_price_envelope_can_be_bracketed_by_separate_minutes():
    start = at("2026-10-22T21:00")
    bars = [
        SimpleNamespace(bar_end=at("2026-10-22T21:01"), low=Decimal(1614), high=Decimal(1617)),
        SimpleNamespace(bar_end=at("2026-10-22T21:02"), low=Decimal(1620), high=Decimal(1622)),
    ]
    result = path(bars, [], start=start, before=at("2026-10-22T21:03"),
                  band=(Decimal(1610), Decimal(1632)), extension=Decimal(1543),
                  observed_average=Decimal("1618.5"))
    assert result["first_minute_range_contains_average"] is None
    assert result["first_window_prefix_range_contains_average"] == "2026-10-22T21:02+08:00"

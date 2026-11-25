from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_pre_touch_protection import analyze, opening_pinbar_sensitivity
from lms405_right_side_study import ONE, US, at


def test_first_touch_cannot_reuse_a_signal_invalidated_at_the_same_close(monkeypatch):
    monkeypatch.setattr("lms405_pre_touch_protection.VARIANTS", ((1, 1),))
    start = at("2026-10-27T21:00")
    bars = [
        Bar("SH2701", start + index * ONE, *map(Decimal, prices), start=start + (index - 1) * ONE)
        for index, prices in enumerate([
            (90, 96, 86, 91), (91, 94, 89, 91), (93, 98, 92, 95), (96, 97, 93, 96), (96, 101, 90, 92),
        ], start=1)
    ]
    params = dict(start=start, band=(Decimal(100), Decimal(102)), side="LONG", leg=None)
    full = analyze({1: bars}, cut=start + 6 * ONE, **params)["variants"]["1m_to_1m"]
    (signal,) = [event for event in full if event["confirmed_at"] == bars[2].end]
    assert signal["pre_touch_arm"] is True
    assert signal["touch_known_at"] == bars[4].end + US
    assert signal["first_boundary_reset"] == bars[4].end
    assert signal["first_opposing_confirmation"] == bars[4].end
    assert signal["survives_both_diagnostics"] is False

    prefix = analyze({1: bars}, cut=bars[4].end, **params)["variants"]["1m_to_1m"]
    (pending,) = [event for event in prefix if event["confirmed_at"] == bars[2].end]
    assert pending["pre_touch_arm"] is True
    assert pending["touch_known_at"] is None
    assert pending["first_opposing_confirmation"] is None


def test_opening_pinbar_sensitivity_never_calls_a_cross_session_shape_inside_bar(monkeypatch):
    monkeypatch.setattr("lms405_pre_touch_protection.VARIANTS", ((1, 1),))
    start = at("2026-10-27T21:00")
    bars = [
        Bar("SH2701", end, *map(Decimal, prices), start=end - ONE)
        for end, prices in (
            (at("2026-10-27T15:00"), (99, 105, 88, 95)),
            (start + ONE, (95, 97, 90, 96)),
            (start + 2 * ONE, (96, 101, 96, 100)),
        )
    ]
    params = dict(start=start, cut=start + 3 * ONE, band=(Decimal(100), Decimal(102)), side="LONG", leg=None)
    assert analyze({1: bars}, **params)["variants"]["1m_to_1m"] == []
    (event,) = opening_pinbar_sensitivity({1: bars}, **params)["1m_to_1m"]
    assert event["pinbar"] == "LONG"
    assert event["ibar"] is False
    assert event["confirmed_at"] == bars[2].end

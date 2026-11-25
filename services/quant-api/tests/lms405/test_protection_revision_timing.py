from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_revision_timing import public_update_control, scoped_geometry, switch_scan
from lms405_right_side_study import ONE, US, at


def test_revision_needs_fresh_complete_contact_and_a_shape_after_its_clock():
    start = at("2026-04-22T21:00")
    prices = ((1278, 1284, 1273, 1282), (1282, 1283, 1278, 1281), (1281, 1282, 1270, 1271))
    bars = [Bar("JM2609", start + i * ONE, *map(Decimal, ohlc), start=start + (i - 1) * ONE)
            for i, ohlc in enumerate(prices, 1)]
    series = {1: bars, 5: [], 15: []}
    band = Decimal(1269), Decimal("1275.5")
    cutoff = bars[-1].end + 2 * US
    eligible, touch = scoped_geometry(series, band, known_at=start - US, cutoff=cutoff)
    assert touch == bars[0]
    assert eligible["ordinary"] == bars[-1].end + US

    after_open, touch = scoped_geometry(series, band, known_at=start, cutoff=cutoff)
    assert touch == bars[-1]
    assert "ordinary" not in after_open

    scenario = switch_scan(series, (Decimal(1262), Decimal("1265.5")), band, cutoff=cutoff)
    assert scenario["actual_revision_at"] is None
    rows = {row["change_time"]: row for row in scenario["timeline"]}
    assert rows[start - US]["after_change"] == eligible
    assert rows[start]["after_change"] == after_open


def test_display_minute_and_conservative_publication_cutoffs_are_distinct():
    start = at("2026-04-22T09:58")
    prices = ((9633, 9640, 9620, 9635), (9630, 9636, 9624, 9630), (9630, 9632, 9612, 9615),
              (9615, 9620, 9613, 9615), (9615, 9620, 9613, 9615))
    bars = [Bar("OI2609", start + i * ONE, *map(Decimal, ohlc), start=start + (i - 1) * ONE)
            for i, ohlc in enumerate(prices, 1)]
    shown = start + 3 * ONE
    review = public_update_control({1: bars, 5: [], 15: []}, published=shown)
    assert review["conservative_known_at"] == shown + ONE
    assert review["retrospective_all_day"]["ordinary"] == shown + US
    assert review["retrospective_before_display_minute"] == {}
    assert review["scoped_after_publication"] == {}

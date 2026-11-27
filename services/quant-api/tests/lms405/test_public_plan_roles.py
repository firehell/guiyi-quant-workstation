from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_public_plan_roles import cotton_protection_clocks, ordered_stand
from lms405_right_side_study import ONE, US, at


def test_cotton_same_bar_touch_cannot_precede_shape():
    end = at("2026-05-06T10:15")
    touch = Bar("CF2609", end, Decimal(16865), Decimal(16870), Decimal(16845), Decimal(16845), start=end - ONE)
    before_touch = {"shape_start": end - 10 * ONE, "confirmed_at": end, "close": Decimal(16845)}
    fresh = {"shape_start": end + 30 * ONE, "confirmed_at": end + 36 * ONE, "close": Decimal(16805)}
    signals = {"5m_to_1m": [before_touch, fresh]}

    result = cotton_protection_clocks([touch], signals, (Decimal(16755), Decimal(16855)))

    assert result["overlap_known_at"] == end + US
    assert result["clocks"]["5m_to_1m"]["in_band"] == before_touch
    assert result["clocks"]["5m_to_1m"]["fresh_after_completed_overlap"] == fresh


def test_ordered_stand_does_not_credit_boundaries_on_same_bar_or_across_gap():
    times = tuple(map(at, ("2026-07-29T09:36", "2026-07-29T09:37", "2026-07-29T09:38",
                           "2026-07-29T09:39", "2026-07-29T10:31", "2026-07-29T10:32")))
    rows = [Bar("AG2610", end, Decimal(14441), Decimal(14441), Decimal(14441), Decimal(14441),
                start=end - ONE) for end in times]
    edges = Decimal(14005), Decimal(14069)
    assert ordered_stand(rows, edges, "LONG", fresh_first=False, m_level=Decimal(14440)) == dict(
        first_band=dict(known_at=times[1] + US),
        second_band=dict(known_at=times[2] + US, first_band_known_at=times[1] + US),
        m_boundary=dict(known_at=times[3] + US, first_band_known_at=times[1] + US, second_band_known_at=times[2] + US),
    )
    assert ordered_stand(rows, edges, "LONG", fresh_first=True, m_level=Decimal(14440)) == dict.fromkeys(
        ("first_band", "second_band", "m_boundary"),
    )
    assert ordered_stand(rows[:2] + rows[-2:], edges, "LONG", fresh_first=False)["second_band"] is None


def test_ordered_stand_reports_only_current_first_band_after_reset():
    times = tuple(at(f"2026-07-29T09:{minute}") for minute in range(36, 43))
    prices = map(Decimal, (14006, 14006, 14005, 14441, 14441, 14441, 14441))
    rows = [Bar("AG2610", end, price, price, price, price, start=end - ONE)
            for end, price in zip(times, prices, strict=True)]
    result = ordered_stand(rows, (Decimal(14005), Decimal(14069)), "LONG", fresh_first=False, m_level=Decimal(14440))
    assert result["first_band"]["known_at"] == times[1] + US
    assert result["second_band"]["first_band_known_at"] == times[4] + US
    assert result["m_boundary"]["first_band_known_at"] == times[4] + US

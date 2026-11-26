from decimal import Decimal

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_right_side_study import ONE, US, at
from lms405_sh_middle_protection import CONTRACT, REREVIEW, pending_review, target_reclaim


def candle(start, prices):
    return Bar(CONTRACT, start + ONE, *map(Decimal, prices), start=start)


def test_range_touch_does_not_treat_a_minute_entirely_below_target_as_contact():
    evening = at("2026-10-26T22:00")
    morning = at("2026-10-27T09:00")
    rows = [candle(evening, (1482, 1482, 1481, 1482))]
    rows.extend(candle(morning + i * ONE, prices) for i, prices in enumerate((
        (1482, 1482, 1481, 1482), (1482, 1484, 1482, 1484),
        (1484, 1484, 1484, 1484), (1484, 1487, 1484, 1487),
    )))
    cutoff = morning + 5 * ONE
    assert target_reclaim(rows, evening - ONE, cutoff, "TOUCH_FAR") is None
    reentry = target_reclaim(rows, evening - ONE, cutoff, "CLOSE_BELOW_FAR")
    assert reentry["target_completed_at"] == evening + ONE + US
    assert reentry["near_reclaimed_at"] == morning + 2 * ONE + US
    assert reentry["far_reclaimed_at"] == morning + 4 * ONE + US
    assert target_reclaim(rows, evening - ONE, reentry["far_reclaimed_at"], "CLOSE_BELOW_FAR") is None


def test_morning_sensitivity_requires_that_exact_review_to_still_be_latest():
    updated = at("2026-10-26T21:58")
    replacement = at("2026-10-27T09:00")
    reference = "https://example.com/research-fixture"
    pending = ProtectionBandUpdate(CONTRACT, REREVIEW, "REVIEW_PENDING", updated, updated, reference, "SHORT")
    later = ProtectionBandUpdate(CONTRACT, "published-new", "PROTECTION", replacement, replacement,
                                 reference, "SHORT", Decimal(1490), Decimal(1501))
    assert not pending_review([pending, later], updated)
    assert pending_review([pending, later], replacement)
    assert not pending_review([pending, later], replacement + US)

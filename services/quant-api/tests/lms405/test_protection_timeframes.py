from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_keybar_approx import classify, classify_research_period
from lms405_protection_timeframes import geometry_events, ibar_source_prefix, warning_phase_comparison


BASE = datetime.fromisoformat("2026-10-22T21:00:00+08:00")
US = timedelta(microseconds=1)


def bar(end, period, low, high, close):
    when = BASE + timedelta(minutes=end)
    prices = (Decimal(close), Decimal(high), Decimal(low), Decimal(close))
    return Bar("SH2701", when, *prices, start=when - timedelta(minutes=period))


def test_period_comparison_reuses_frozen_five_minute_identity():
    mother, inside = bar(5, 5, 9, 15, 12), bar(10, 5, 10, 14, 11)
    assert classify(mother, inside) == classify_research_period(mother, inside, minutes=5)
    minute = classify_research_period(bar(1, 1, 9, 15, 12), bar(2, 1, 10, 14, 11), minutes=1)
    assert minute.ibar is True
    assert minute.rule_version != classify(mother, inside).rule_version
    with pytest.raises(ValueError, match="COMPLETED_RESEARCH_PERIOD_REQUIRED"):
        classify_research_period(mother, inside, minutes=15)


def test_fast_close_has_own_availability_and_never_skips_a_missing_minute():
    mother, shape, next_five = bar(5, 5, 9, 15, 12), bar(10, 5, 10, 14, 11), bar(15, 5, 9, 14, 11)
    m11, m12 = bar(11, 1, 10, 12, 10), bar(12, 1, 9, 12, 9)
    args = dict(start=BASE, side="SHORT")
    data = {1: [m11, m12], 5: [mother, shape, next_five]}
    assert geometry_events(data, 5, 1, as_of=m12.end + US, **args) == []
    (fast,) = geometry_events(data, 5, 1, as_of=m12.end + 2 * US, **args)
    assert fast["confirmed_at"] == m12.end and fast["boundary"] == Decimal(10)
    assert geometry_events(data, 5, 5, as_of=next_five.end + 2 * US, **args) == []
    assert geometry_events(data | {1: [m12]}, 5, 1, as_of=next_five.end + 2 * US, **args) == []
    with pytest.raises(ValueError, match="CONFIRMATION_BAR_IDENTITY_MISMATCH"):
        geometry_events(data | {1: [m11, replace(m12, completed=1)]}, 5, 1,
                        as_of=next_five.end + 2 * US, **args)
    assert geometry_events(data, 5, 1, as_of=m12.end + 2 * US,
                           start=shape.start + US, side="SHORT") == []


def test_ibar_source_separates_equality_strict_break_and_next_full_confirmation():
    mother, shape, following = bar(15, 15, 8, 15, 12), bar(30, 15, 10, 15, 12), bar(45, 15, 9, 14, 9)
    touch, crossed = bar(31, 1, 10, 12, 10), bar(32, 1, 9, 12, 9)
    series = {15: [mother, shape, following], 1: [touch, crossed]}
    (before,) = ibar_source_prefix(series, crossed.end + US)
    assert before["strict_range_inside"] is False
    assert before["first_1m_touch"]["end"] == touch.end
    assert before["first_1m_strict_low_below"] is None
    (after,) = ibar_source_prefix(series, following.end + 2 * US)
    assert after["first_1m_strict_close_below"]["end"] == crossed.end
    assert after["next_contiguous_15m_strict_close_below"] is True
    (before_next,) = ibar_source_prefix(series, following.end + US)
    assert before_next["next_contiguous_15m"] is None

    skipped_line = bar(31, 1, 8, 9, 9)
    (gap,) = ibar_source_prefix(series | {1: [skipped_line]}, skipped_line.end + 2 * US)
    assert gap["first_1m_touch"] is None
    assert gap["first_1m_strict_low_below"]["end"] == skipped_line.end


def test_warning_confirmation_needs_contiguous_mother_and_keeps_coincidence_separate():
    shape, warning = bar(21, 1, 102, 106, 104), bar(22, 1, 106, 108, 108)
    cutoff = warning.end + 2 * US
    for mother, has_coincidence in ((bar(1, 1, 95, 110, 100), False), (bar(20, 1, 95, 110, 100), True)):
        report = warning_phase_comparison({1: [mother, shape, warning], 5: [], 15: []}, known_after=BASE,
                                          as_of=cutoff, bands={"WARNING": (Decimal(107), Decimal(109))})
        phase = report["roles"]["WARNING"]["phases"]["strict_fresh_near"]
        assert phase["known_at"] == warning.end + US
        observation = phase["observations"]["1m_to_1m"]
        assert (observation["coincident"] is not None) is has_coincidence
        assert observation["confirmed_later"] is None

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
import lms405_extreme_m_stage_study as study


@pytest.mark.parametrize(("near", "far_hit_index", "expected_geometry", "expected_before_far"), [
    ("102", 5, True, False),
    ("102", 6, True, True),
    ("100.5", 6, False, False),
])
def test_extreme_stage_requires_separate_completed_cross_and_price_room(
    monkeypatch, near, far_hit_index, expected_geometry, expected_before_far,
):
    start = datetime(2026, 10, 23, 9, tzinfo=timezone(timedelta(hours=8)))
    minute = timedelta(minutes=1)
    us = timedelta(microseconds=1)
    closes = (99, 101, 103, 103, 103, 104, 104)
    bars = []
    for index, close in enumerate(closes):
        value = Decimal(close)
        high = Decimal(105) if index == far_hit_index else value
        bar_start = start + index * minute
        bars.append(Bar("JM2701", bar_start + minute, value, high, value, value, start=bar_start))

    confirmed = bars[5].end
    event = dict(shape_end=bars[4].end, confirmed_at=confirmed, available_at=confirmed + us)
    monkeypatch.setattr(study, "VARIANTS", ((1, 1),))
    monkeypatch.setattr(study, "signals", lambda *args, **kwargs: [event])
    result = study.compare_stages({1: bars}, side="LONG", start=start, cutoff=bars[-1].end + 2 * us,
                                  ordinary=Decimal(100), near=Decimal(near), far=Decimal(105))
    stage = result["stages"]["near"]
    assert stage["same_minute_cross"] is (near == "100.5")
    assert bool(stage["candidates"]["1m_to_1m"]) is expected_geometry
    assert bool(stage["candidates_before_next_reference"]["1m_to_1m"]) is expected_before_far
    assert result["stages"]["far"]["candidates_before_next_reference"] is None
    assert result["independent_extreme_permission"] is None and result["ordinary_trade_succeeded"] is None

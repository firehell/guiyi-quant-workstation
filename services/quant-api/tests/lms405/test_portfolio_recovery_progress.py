from dataclasses import replace
from decimal import Decimal

import pytest
from guiyi_quant.lms405 import Bar, Position
from guiyi_quant.lms405.handoff import Handoff
from lms405_portfolio_recovery_progress import position_at, simulated_confirmation, study_paths
from lms405_portfolio_recovery_shape_lifetime import BOUNDED, EARLIER, NEW, RECROSS, first_candidates
from lms405_right_side_study import ONE, US, at


def test_historical_far_reach_can_pass_near_but_not_current_far():
    start = at("2026-10-27T09:00")
    values = ((112, 113, 111, 112), (112, 113, 108, 109), (109, 109, 106, 108),
              (108, 109, 104, 107), (107, 108, 105, 106), (106, 107, 103, 104))
    minutes = [Bar("SH2701", start + i * ONE, *map(Decimal, row), start=start + (i - 1) * ONE)
               for i, row in enumerate(values, 1)]
    rows = study_paths({1: minutes, 5: [], 15: []}, start=start, cut=minutes[-1].end + 3 * US, side="SHORT",
                       band=(Decimal(100), Decimal(110)), earlier_far=at("2026-10-26T14:20") + US)["events"]
    (event,) = [row for row in rows if row["confirmed_at"] == minutes[-1].end]
    assert event["conditions"] == dict(near_geometry=True, near_after_far_reach=True, current_far_before_shape=False)

    seed = Position("SH2701", Decimal(20), Decimal(20))
    request = Handoff("RESUME_ORIGINAL", seed, "SHORT", "test-plan", "test-cycle", None, start, start)
    mode = "near_after_far_reach"
    approval = simulated_confirmation(request, mode, event)
    known = approval.known_at
    before = position_at(request, event, mode=mode, as_of=known, approval=approval)
    after = position_at(request, event, mode=mode, as_of=known + US, approval=approval)
    missing = position_at(request, event, mode=mode, as_of=known + US)
    rejected = position_at(request, event, mode=mode, as_of=known + US, approval=replace(approval, accepted=False))
    strict = position_at(request, event, mode="current_far_before_shape", as_of=known + US, approval=approval)
    assert (before["long"], after["long"], strict["long"], missing["long"], rejected["long"]) == (20, 0, 20, 20, 20)
    assert before["short"] == after["short"] == strict["short"] == 20
    with pytest.raises(ValueError, match="CONFIRMATION_SCOPE_MISMATCH"):
        position_at(request, event, mode="near_geometry", as_of=known + US, approval=approval)


def test_both_recovery_variants_share_price_gate_and_preserve_distinct_shape_order():
    start = at("2026-10-27T09:00")
    marks = [start + n * ONE for n in range(7)]
    bars = [Bar("I2701", marks[n], *([Decimal(close)] * 4), start=marks[n - 1])
            for n, close in enumerate([111, 109, 108, 107, 106, 105], 1)]
    old = dict(shape_start=marks[0], confirmed_at=marks[2], available_at=marks[2] + US, boundary=Decimal(112))
    overlapping = dict(shape_start=marks[2], confirmed_at=marks[4], available_at=marks[4] + US, boundary=Decimal(112))
    later = dict(shape_start=marks[3], confirmed_at=marks[5], available_at=marks[5] + US, boundary=Decimal(112))
    geometry = {"1m_to_1m": [old, overlapping, later]}
    result = first_candidates(bars, geometry, edge=Decimal(110), side="SHORT")
    assert result[EARLIER]["1m_to_1m"]["confirmed_at"] == marks[3]
    assert result[NEW]["1m_to_1m"]["confirmed_at"] == marks[5]
    assert result[NEW]["1m_to_1m"]["original_geometry_confirmed_at"] == marks[5]


@pytest.mark.parametrize(("first_above", "expected"), [(8, 9), (9, 10), (10, None)])
def test_bounded_shape_stops_after_next_full_shape_bar(first_above, expected):
    start = at("2026-10-27T09:00")
    marks = [start + n * ONE for n in range(13)]
    bars = [Bar("JM2701", marks[n], *([Decimal(102 if n >= first_above else 101)] * 4), start=marks[n - 1])
            for n in range(1, len(marks))]
    variant = "5m_to_1m"
    event = dict(shape_start=marks[0], shape_end=marks[5], confirmed_at=marks[6],
                 available_at=marks[6] + US, boundary=Decimal(100))
    result = first_candidates(bars, {variant: [event]}, edge=Decimal(101), side="LONG", include_bounded=True)
    assert result[EARLIER][variant]["confirmed_at"] == marks[first_above + 1]
    assert not result[NEW]
    if expected is None:
        assert not result[BOUNDED]
    else:
        assert result[BOUNDED][variant]["confirmed_at"] == marks[expected]
        assert result[BOUNDED][variant]["shape_expires_at"] == marks[10]


@pytest.mark.parametrize(("early_closes", "break_between", "recross"), [
    ([100, 102, 102, 101], False, True),
    ([100, 102, 101, 101], False, False),
    ([102, 102, 102, 101], False, False),
    ([100, 102, 102, 101], True, False),
])
def test_bounded_recross_requires_completed_earlier_cross_and_return_in_same_segment(early_closes, break_between,
                                                                                    recross):
    start = at("2026-10-27T09:00")
    late_start = start + (14 if break_between else 4) * ONE
    bars = []
    for segment_start, closes in ((start, early_closes), (late_start, [101, 101, 102, 103])):
        bars.extend(Bar("JM2701", segment_start + n * ONE, *([Decimal(close)] * 4),
                        start=segment_start + (n - 1) * ONE) for n, close in enumerate(closes, 1))
    variant = "1m_to_1m"
    event = dict(shape_start=bars[-2].start, shape_end=bars[-2].end, confirmed_at=bars[-1].end,
                 available_at=bars[-1].end + US, boundary=Decimal(102))
    result = first_candidates(bars, {variant: [event]}, edge=Decimal(101), side="LONG", include_recross=True)
    assert result[BOUNDED][variant]["confirmed_at"] == bars[-1].end
    if recross:
        assert result[RECROSS][variant]["prior_crossing_known_at"] == start + 2 * ONE + US
        assert result[RECROSS][variant]["prior_two_close_run_known_at"] == start + 3 * ONE + US
        assert result[RECROSS][variant]["return_at"] == start + 4 * ONE
    else:
        assert not result[RECROSS]

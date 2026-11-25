from dataclasses import replace
from decimal import Decimal

import pytest
from guiyi_quant.lms405 import Bar, Position
from guiyi_quant.lms405.handoff import Handoff
from lms405_portfolio_recovery_progress import position_at, simulated_confirmation, study_paths
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

from dataclasses import replace
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Zone
from guiyi_quant.lms405.public_plan_handoff import Publication
from lms405_lifecycle_tape import replay
from lms405_portfolio_lifecycle import seed
from lms405_pvc_portfolio_lifecycle import CONTRACT, recorded_order, replacement_steps
from lms405_right_side_study import ONE, at


def published_zone(known):
    zone = Zone("left", CONTRACT, Decimal(5045), Decimal(5074), known, "left")
    return Publication("left", CONTRACT, known, known, "left", zone)


@pytest.mark.parametrize("replacement,operations,interim", [
    (18, ("DIRECTIONAL_LONG_REDUCE", "DIRECTIONAL_LONG_ADD"), 22),
    (40, ("CLEAR", "REENTER_LONG"), 0),
])
def test_partial_replacement_and_flat_reentry_require_separate_authority(replacement, operations, interim):
    beginning = at("2026-10-27T09:00")
    root = seed("trial", CONTRACT, beginning, long=40)
    plan = published_zone(beginning - ONE)
    drop, add = replacement_steps(root, plan, quantity=replacement,
                                  reduce_clock=beginning + ONE, add_clock=beginning + 2 * ONE)
    assert (drop.operation, add.operation) == operations
    after_first, _ = replay((root,), (drop, add), (plan,), cutoff=add.at, allow_test_fixture=True)
    assert after_first[-1]["after"]["position"]["long"] == interim
    _, approved = replay((root,), (drop, add), (plan,), cutoff=add.at + ONE, allow_test_fixture=True)
    assert approved[root.episode].position.long == 40
    result, blocked = replay((root,), (replace(drop, approval=None), add), (plan,),
                             cutoff=add.at + ONE, allow_test_fixture=True)
    assert result[-1]["status"] == "STALE_OR_UNAVAILABLE_POSITION"
    assert blocked[root.episode] == root


def test_partial_directional_replacement_rejects_a_lock_or_full_reduction():
    beginning = at("2026-10-27T09:00")
    plan = published_zone(beginning - ONE)
    locked = seed("trial", CONTRACT, beginning, long=40, short=40, protection=40)
    with pytest.raises(ValueError, match="LIFECYCLE_DIRECTIONAL_LONG_REQUIRED"):
        replacement_steps(locked, plan, quantity=18, reduce_clock=beginning + ONE, add_clock=beginning + 2 * ONE)
    long = seed("trial", CONTRACT, beginning, long=40)
    drop, _ = replacement_steps(long, plan, quantity=18, reduce_clock=beginning + ONE, add_clock=beginning + 2 * ONE)
    with pytest.raises(ValueError, match="LIFECYCLE_REDUCE_MUST_RETAIN_DIRECTIONAL_LONG"):
        replace(drop, quantity=Decimal(40)).supported_projection()


def test_software_copies_preserve_first_observation_and_unknown_action_time():
    raw = {
        "software_row": dict(version=None, quantity=None, date=None, direction_closed="LONG", repeated_in=["a", "b"]),
        "report_images": {"a": {}, "b": {}},
        "sources": {"a": {"published_at": "2026-10-27T09:00:00+08:00"},
                    "b": {"published_at": "2026-10-26T22:06:00+08:00"}},
    }
    order, retrospective = recorded_order(raw)
    assert order["source"] == "b" and retrospective["unique_report_count"] == retrospective["other_copies"] == 1
    assert "repeated_in" not in order["order"] and "other_copies" not in order
    assert order["at"] == at("2026-10-26T22:07")
    assert order["author_trade_at"] is None

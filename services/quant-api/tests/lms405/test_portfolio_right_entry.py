from decimal import Decimal

import pytest

from guiyi_quant import lms_near405 as near
from guiyi_quant.lms405 import Bar
from lms405_breakout_trial_study import CASES
from lms405_portfolio_right_entry import Branch, assess_entry
from lms405_portfolio_task_policy import gated_replay
from lms405_right_side_study import FIVE, US, at


def controlled_entry():
    case = CASES["PVC_RIGHT_LONG"]
    available = at("2026-10-27T17:38")
    branch = Branch(case, {"source_url": "plan", "archive_sha256": "fixture"},
                    available, at(case.start), at("2026-10-28T15:01"))
    signal_at = at("2026-10-27T22:12")
    event = dict(at=signal_at + 9 * US, branch=branch, clock="1m_to_1m", setup_at=at("2026-10-27T22:09"),
                 shape_start=at("2026-10-27T22:10"), signal_at=signal_at, signal_known_at=signal_at + US,
                 close=Decimal(5205), edge=Decimal(5195), reference=Decimal(5232),
                 room=Decimal(27), reference_consumed=False)
    end = at("2026-10-27T22:10")
    bars = [Bar(case.contract, end, *map(Decimal, (5193, 5200, 5191, 5198)), start=end - FIVE)]
    return bars, event


def test_right_fixture_and_public_permission_are_independent_and_exposure_is_single_unit():
    bars, event = controlled_entry()
    state = near.initial_state(bars)
    assert assess_entry("V2701", state, event)["permit"] is False
    assert assess_entry("V2701", state, event, fixture=True)["permit"] is True
    held = state | dict(long="1", cycle_id="existing")
    assert assess_entry("V2701", held, event, fixture=True)["reason"] == "ALREADY_HELD_SINGLE_UNIT"
    consumed = event | dict(reference_consumed=True)
    assert assess_entry("V2701", state, consumed, fixture=True)["decision"]["status"] == "NOT_PERMITTED"
    late = state | dict(known_at=event["setup_at"].isoformat())
    assert assess_entry("V2701", late, event, fixture=True)["reason"] == "POSITION_CHANGED_AFTER_SETUP"


def test_author_scoped_entry_is_only_projected_strictly_after_ready_clock():
    bars, event = controlled_entry()
    opts = dict(right_branches=(event["branch"],), right_events=(event,))
    assert gated_replay(bars, event["at"], **opts) == ([], [])
    (entered,), blocked = gated_replay(bars, event["at"] + US, **opts)
    assert entered["before"] == ["0", "0"] and entered["after"] == ["1", "0"]
    assert entered["right_entry"]["public"]["permit"] is False
    assert entered["right_entry"]["fixture"]["permit"] is True
    assert blocked == []
    with pytest.raises(ValueError, match="RIGHT_SCOPE_MISMATCH"):
        gated_replay(bars, event["at"] + US, right_events=(event,))


def test_same_time_right_signals_only_project_one_transition():
    bars, event = controlled_entry()
    other = event | dict(clock="5m_to_1m")
    opts = dict(right_branches=(event["branch"],), right_events=(other, event))
    (entered,), (note,) = gated_replay(bars, event["at"] + US, **opts)
    assert entered["right_entry"]["fixture"]["clock"] == "1m_to_1m"
    assert note["reason"] == "SAME_TIME_CONFIRMATIONS" and note["duplicate_clocks"] == ["5m_to_1m"]

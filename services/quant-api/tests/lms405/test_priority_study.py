import pytest

from lms405_priority_study import GROUPS, inspect_timeline, priority


def entry(contract):
    return dict(contract=contract, action="ENTER_LONG", before=["0", "0"], after=["1", "0"],
                proposal_id=f"enter-{contract}")


def batch(*actions, time="2026-10-23T01:45:00.000002+00:00"):
    return dict(time=time, layer="FIXTURE_STATE_BATCH", payload=dict(actions=list(actions)))


def test_all_entry_candidates_pass_when_capacity_is_sufficient():
    rows = [entry("TA2701"), entry("JM2701")]
    ample = priority(rows, slots=2)
    assert ample == priority(rows, slots=None, groups=GROUPS[::-1])
    assert ample == dict(status="ENOUGH_SLOTS", proposed=["JM2701", "TA2701"], unresolved=[], deferred=[])
    assert priority(rows, slots=1)["status"] == "NO_APPLICABLE_RANK"
    assert priority(rows, slots=0, groups=GROUPS)["proposed"] == []
    assert priority(rows, slots=1, groups=GROUPS)["proposed"] == ["JM2701"]
    assert priority(rows, slots=1, groups=GROUPS[::-1])["proposed"] == ["TA2701"]


def test_tied_group_crossing_capacity_keeps_known_prefix_and_defers_lower_tier():
    rows = [entry(c) for c in ("RU2701", "TA2701", "JM2701", "I2701")]
    result = priority(rows, slots=2, groups=GROUPS)
    assert result == priority(rows[::-1], slots=2, groups=GROUPS)
    assert result == dict(status="TIER_TIE", proposed=["JM2701"], unresolved=["I2701", "RU2701"],
                          deferred=["TA2701"])


def test_competing_entries_and_same_snapshot_management_are_independent():
    lock = dict(contract="SH2701", action="LOCK", before=["0", "1"], after=["1", "1"], proposal_id="lock")
    unlock = dict(contract="SH2701", action="UNLOCK_SHORT", before=["1", "1"], after=["0", "1"],
                  proposal_id="unlock")
    timeline = [batch(entry("JM2701"), entry("TA2701"), lock),
                batch(unlock, time="2026-10-23T01:50:00+00:00")]
    result = inspect_timeline(timeline)
    first, = result["entry_snapshots"]
    assert first["independent_management"] == [lock]
    assert first["comparisons"]["no_slots"]["proposed"] == []
    assert first["comparisons"]["one_slot_2025_groups_hypothetical"]["proposed"] == ["JM2701"]
    assert first["comparisons"]["one_slot_reversed_groups_control"]["proposed"] == ["TA2701"]
    assert result["management_counts"] == {"LOCK": 1, "UNLOCK_SHORT": 1}
    assert [b["actions"] for b in result["management"]] == [[lock], [unlock]]
    assert inspect_timeline(timeline[:1])["entry_snapshots"] == result["entry_snapshots"]


def test_unknown_action_and_reordered_snapshot_do_not_get_classified():
    row = entry("JM2701") | {"action": "REENTER_LONG"}
    with pytest.raises(ValueError, match="UNCLASSIFIED_FIXTURE_ACTION"):
        inspect_timeline([batch(row)])
    with pytest.raises(ValueError, match="INVALID_SNAPSHOT_ORDER"):
        inspect_timeline([batch(entry("JM2701")), batch(entry("TA2701"))])

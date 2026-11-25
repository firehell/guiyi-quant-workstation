from datetime import datetime, timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar, Position
from lms405_carry_in_study import at_anchor, keybar_events, project
from lms405_original_leg_study import compare_afternoon


START = datetime.fromisoformat("2026-10-22T22:11:00+08:00")
CONTRACT = "I2701"
QTY = Decimal(16)
SEED_FIELDS = {
    "long": {"quantity": 16, "opening_average": "668.75"},
    "short": {"quantity": 16, "opening_average": "682.50"},
}


def event(direction, shape_offset):
    return {"direction": direction, "shape_start": START + timedelta(minutes=shape_offset)}


def after(minutes):
    return START + timedelta(minutes=minutes)


def test_completion_after_seed_does_not_admit_a_straddling_shape(monkeypatch):
    ends = [after(4), after(9)]
    bars = [Bar(CONTRACT, end, QTY, QTY, QTY, QTY, start=end - timedelta(minutes=5)) for end in ends]

    def shapes(*args, side, **kwargs):
        if side == "LONG":
            return [
                {"shape_at": end.isoformat(), "level": "16",
                 "fast_at": (end + timedelta(minutes=1)).isoformat(),
                 "slow_at": (end + timedelta(minutes=5)).isoformat()}
                for end in ends
            ]
        return []

    monkeypatch.setattr("lms405_carry_in_study.confirmed_shapes", shapes)
    result = keybar_events(bars, [], START, after(14))
    assert [row["shape_end"] for _, (row,) in result["KEYBAR_1M_CLOSE"].items()] == [ends[1].isoformat()]
    assert list(result["KEYBAR_1M_CLOSE"]) == [after(10) + timedelta(microseconds=2)]
    assert result["KEYBAR_5M_CLOSE"] == {}


def test_locked_projection_conflict_stale_shape_and_renewed_protection():
    seed = Position(CONTRACT, QTY, QTY)
    batches = {
        after(8): [event("SHORT", 1), event("LONG", 2)],
        after(10): [event("SHORT", 4)],
        after(12): [event("LONG", 9)],
        after(20): [event("LONG", 12)],
    }
    steps = project(seed, START, batches)
    assert [step["action"] for step in steps] == [None, "UNLOCK_SHORT", "LOCK"]
    assert steps[0]["reason"] == "CONFLICTING_CONFIRMATIONS"
    assert steps[1]["after"] == {"long": "0", "short": "16", "net": "-16", "gross": "16"}
    assert steps[2]["after"] == {"long": "16", "short": "16", "net": "0", "gross": "32"}
    assert not steps[2]["retained_seed_long"]
    assert project(seed, START, {at: rows for at, rows in batches.items() if at < after(20)}) == steps[:2]


def test_anchor_is_strict_and_recreated_leg_does_not_inherit_old_average():
    seed = Position(CONTRACT, QTY, QTY)
    steps = project(seed, START, {
        after(10): [event("SHORT", 1)],
        after(20): [event("LONG", 11)],
    })
    observations = {**SEED_FIELDS, "long": {"quantity": 16, "opening_average": "663.34"}}
    at_first = at_anchor(seed, steps, after(10), {"short": SEED_FIELDS["short"]}, SEED_FIELDS)
    assert at_first["legs"]["long"]["status"] == "AUTHOR_LEG_UNKNOWN"
    assert at_first["retained_seed_long"] is True
    assert at_first["prior_actions"] == 0
    at_second = at_anchor(seed, steps, after(20), observations, SEED_FIELDS)
    assert at_second["legs"]["long"]["status"] == "VISIBLE_QUANTITY_DIFFERS"
    assert at_second["prior_actions"] == 1
    later = at_anchor(seed, steps, after(21), observations, SEED_FIELDS)
    assert later["legs"]["long"]["status"] == "VISIBLE_QUANTITY_AGREES"
    assert later["retained_leg_opening_average_agrees"] == {"long": None, "short": True}
    hold = at_anchor(seed, [], after(21), observations, SEED_FIELDS)
    assert hold["retained_leg_opening_average_agrees"] == {"long": False, "short": True}


def test_original_leg_comparison_distinguishes_removing_protection_from_clearing():
    older_short = SEED_FIELDS["short"] | {"today_quantity": 0}
    snapshots = [
        {"author_visible_legs": SEED_FIELDS | {"short": older_short}},
        {"author_visible_legs": {"short": older_short}},
    ]
    signal = {"confirmed_at": after(10)}
    comparison = compare_afternoon(CONTRACT, {"short_confirmations": {
        "5m_to_1m": [signal],
        "5m_to_5m": [],
    }}, snapshots)
    assert comparison["possible_state_changes"] == {
        "retain_lock": {"long": QTY, "short": QTY},
        "remove_protection": {"long": 0, "short": QTY},
        "exit_both": {"long": 0, "short": 0},
    }
    assert comparison["visible_quantity_agrees"] == {
        "retain_lock": {"long": None, "short": True},
        "remove_protection": {"long": None, "short": True},
        "exit_both": {"long": None, "short": False},
    }
    assert comparison["geometry_only_projections"]["5m_to_1m"]["scenario"] == "remove_protection"
    assert comparison["geometry_only_projections"]["5m_to_5m"]["scenario"] == "retain_lock"

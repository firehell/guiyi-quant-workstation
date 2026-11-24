from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from lms405_sized_portfolio_replay import CONTRACTS, PTA_CASE_ENTRY, project_window


def event(at, action, before, after, side=None):
    if side is None:
        position = after if after[0] != after[1] else before
        side = "LONG" if position[0] == "1" else "SHORT"
    return dict(at=at.isoformat(), action=action, before=before, after=after, reason="TEST", side=side)


def window(rows, terminal=None):
    terminal = terminal or {}
    counts = {}
    for transitions in rows.values():
        for action in transitions:
            kind = action["action"]
            counts[kind] = counts.get(kind, 0) + 1
    return dict(
        as_of=(PTA_CASE_ENTRY + timedelta(hours=1)).isoformat(),
        action_counts={"test": counts},
        contracts={
            contract: {"input_sha256": contract, "results": {
                "test": dict(version="test", rule_hash="test", transitions=rows.get(contract, []),
                             terminal=terminal.get(contract, "FLAT")),
            }} for contract in CONTRACTS
        },
    )


def test_same_time_batch_and_unlock_restore_original_side():
    first = PTA_CASE_ENTRY
    second, third = first + timedelta(minutes=5), first + timedelta(minutes=10)
    sh = [
        event(first, "ENTER_SHORT", ["0", "0"], ["0", "1"]),
        event(second, "LOCK", ["0", "1"], ["1", "1"]),
        event(third, "UNLOCK_SHORT", ["1", "1"], ["0", "1"]),
    ]
    v = [
        event(first, "ENTER_LONG", ["0", "0"], ["1", "0"]),
        event(second, "LOCK", ["1", "0"], ["1", "1"]),
        event(third, "UNLOCK_LONG", ["1", "1"], ["1", "0"]),
    ]
    ending = {"SH2701": "OPEN_DIRECTIONAL", "V2701": "OPEN_DIRECTIONAL"}
    report = project_window(window({"SH2701": sh, "V2701": v}, ending), "test",
                            {"SH2701": Decimal(20), "V2701": Decimal(40)})
    assert len(report["timeline"]) == 3  # Two simultaneous actions share a batch.
    locked = report["timeline"][1]["portfolio"]
    assert locked["known_gross_lots_subtotal"] == "120"
    assert (locked["long_contracts"], locked["short_contracts"], locked["equal_locked_contracts"]) == (0, 0, 2)
    assert report["terminal_contracts"]["SH2701"] == {"long": "0", "short": "20", "net": "-20", "gross": "20"}
    assert report["terminal_contracts"]["V2701"] == {"long": "40", "short": "0", "net": "40", "gross": "40"}

    prefix = window({"SH2701": sh[:2], "V2701": v[:2]}, {"SH2701": "OPEN_LOCKED", "V2701": "OPEN_LOCKED"})
    prefix["as_of"] = second.isoformat()
    assert project_window(prefix, "test", {"SH2701": Decimal(20), "V2701": Decimal(40)})["timeline"] == (
        report["timeline"][:2]
    )


def test_pta_size_calibration_is_optional_and_only_one_position_cycle():
    first = PTA_CASE_ENTRY
    rows = {"TA2701": [
        event(first, "ENTER_LONG", ["0", "0"], ["1", "0"]),
        event(first + timedelta(minutes=5), "LOCK", ["1", "0"], ["1", "1"]),
        event(first + timedelta(minutes=10), "CLEAR", ["1", "1"], ["0", "0"]),
        event(first + timedelta(minutes=15), "ENTER_SHORT", ["0", "0"], ["0", "1"]),
    ]}
    fixture = window(rows, {"TA2701": "OPEN_DIRECTIONAL"})
    default = project_window(fixture, "test", {})
    example = project_window(fixture, "test", {}, pta_lots=Decimal(34))
    assert default["timeline"][1]["actions"][0]["after"] == {"long": None, "short": None, "net": "0", "gross": None}
    assert example["timeline"][1]["actions"][0]["after"] == {"long": "34", "short": "34", "net": "0", "gross": "68"}
    assert example["timeline"][2]["actions"][0]["action_quantity_lots"] == "68"
    assert example["timeline"][-1] == default["timeline"][-1]
    assert example["pta_scenario_cycles"] == [first.isoformat()]


def test_projection_rejects_semantically_invalid_frozen_transition():
    rows = {
        "RU2701": [
            event(PTA_CASE_ENTRY, "ENTER_SHORT", ["0", "0"], ["0", "1"]),
            event(PTA_CASE_ENTRY + timedelta(minutes=5), "LOCK", ["0", "1"], ["1", "0"]),
        ],
    }
    invalid = window(rows, {"RU2701": "OPEN_DIRECTIONAL"})
    with pytest.raises(ValueError, match="FROZEN_UNIT_TRANSITION_MISMATCH"):
        project_window(invalid, "test", {"RU2701": Decimal(20)})
    duplicate = deepcopy(invalid)
    duplicate["contracts"]["RU2701"]["results"]["test"]["transitions"][1]["at"] = PTA_CASE_ENTRY.isoformat()
    with pytest.raises(ValueError, match="CLOCK_TRANSITION_TIME_UNVERIFIED"):
        project_window(duplicate, "test", {"RU2701": Decimal(20)})

    reverse = window({"RU2701": [
        rows["RU2701"][0],
        event(PTA_CASE_ENTRY + timedelta(minutes=5), "LOCK", ["0", "1"], ["1", "1"]),
        event(PTA_CASE_ENTRY + timedelta(minutes=10), "UNLOCK_LONG", ["1", "1"], ["1", "0"], side="SHORT"),
    ]}, {"RU2701": "OPEN_DIRECTIONAL"})
    with pytest.raises(ValueError, match="ORIGINAL_CYCLE_DIRECTION_MISMATCH"):
        project_window(reverse, "test", {"RU2701": Decimal(20)})

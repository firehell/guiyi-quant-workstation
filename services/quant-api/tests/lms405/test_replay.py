from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import pytest
from guiyi_quant.lms405 import Action, Bar, Position, Zone, apply_action, inspect_bar

T = datetime(2026, 8, 18, 0, tzinfo=UTC)


def test_complete_unit_lifecycle_and_reentry():
    p = Position("FG2609")
    for action, expected in [
        ("ENTER_SHORT", (0, 1)),
        ("LOCK", (1, 1)),
        ("UNLOCK_SHORT", (0, 1)),
        ("CLEAR", (0, 0)),
        ("REENTER_LONG", (1, 0)),
    ]:
        p = apply_action(p, Action(action, D(1)))
        assert (p.long, p.short) == expected


@pytest.mark.parametrize(
    "action", ["LOCK", "UNLOCK_LONG", "UNLOCK_SHORT", "EXIT_LONG", "EXIT_SHORT"]
)
def test_invalid_flat_actions_fail(action):
    with pytest.raises(ValueError):
        apply_action(Position("FG2609"), Action(action, D(1)))


def test_zones_strict_before_and_contract_isolation():
    bar = Bar(
        "FG2609", T, D(871), D(880), D(868), D(875), start=T - timedelta(minutes=1)
    )
    zones = [
        Zone("a", "FG2609", D(870), D(875), T, "E43"),
        Zone("b", "FG2701", D(870), D(875), T - timedelta(days=1), "E02"),
    ]
    assert inspect_bar(bar, zones)["zones"] == []
    result = inspect_bar(
        bar, [Zone("c", "FG2609", D(870), D(875), T - timedelta(days=1), "E43")]
    )
    assert result["zones"][0]["both_endpoints_touched"] is True
    assert result["zones"][0]["sequence"] == "INTRABAR_ORDER_UNKNOWN"
    assert result["action"] == "INDETERMINATE"


def test_independent_mode_does_not_read_author_zones():
    bar = Bar(
        "FG2609", T, D(871), D(880), D(868), D(875), start=T - timedelta(minutes=1)
    )
    assert (
        inspect_bar(
            bar,
            [Zone("c", "FG2609", D(870), D(875), T - timedelta(days=1), "E43")],
            mode="independent",
        )["zones"]
        == []
    )


@pytest.mark.parametrize("quantity", [D("-1"), D("NaN"), D("Infinity"), D("0")])
def test_bad_quantities(quantity):
    with pytest.raises(ValueError):
        Action("ENTER_LONG", quantity)


def test_unbalanced_lock_and_wrong_exit_fail():
    with pytest.raises(ValueError):
        apply_action(Position("FG2609", D(2)), Action("LOCK", D(1)))
    with pytest.raises(ValueError):
        apply_action(Position("FG2609", D(1)), Action("EXIT_SHORT", D(1)))


def test_incomplete_and_bad_ohlc_fail():
    with pytest.raises(ValueError):
        Bar("FG2609", T, D(1), D(2), D(0), D(3))
    with pytest.raises(ValueError):
        Bar("FG2609", T, D(1), D(2), D(1), D(2), completed=False)


def test_prefix_batch_and_restart_parity():
    bars = [
        Bar("FG2609", T + timedelta(minutes=i), D(871), D(880), D(868), D(875))
        for i in range(4)
    ]
    zone = Zone("a", "FG2609", D(870), D(875), T - timedelta(days=1), "E43")
    batch = [inspect_bar(b, [zone]) for b in bars]
    assert batch[:2] == [inspect_bar(b, [zone]) for b in bars[:2]]
    p = apply_action(Position("FG2609"), Action("ENTER_LONG", D(1)))
    restarted = Position(p.contract, p.long, p.short)
    assert apply_action(p, Action("LOCK", D(1))) == apply_action(
        restarted, Action("LOCK", D(1))
    )


def test_disclosed_event_replay_idempotence_conflicts_and_strict_before():
    from guiyi_quant.lms405 import Event, replay_events

    event = Event(
        "a", "FG2609", T, T - timedelta(seconds=1), Action("ENTER_LONG", D(1)), "E41"
    )
    assert replay_events("FG2609", [event, event], cutoff=T) == Position("FG2609", D(1))
    late = Event("late", "FG2609", T, T, Action("LOCK", D(1)), "E41")
    assert replay_events("FG2609", [event, late], cutoff=T) == Position("FG2609", D(1))
    with pytest.raises(ValueError):
        replay_events("JM2701", [event], cutoff=T)
    conflict = Event(
        "a", "FG2609", T, T - timedelta(seconds=1), Action("ENTER_SHORT", D(1)), "E41"
    )
    with pytest.raises(ValueError):
        replay_events("FG2609", [event, conflict], cutoff=T)


def test_same_time_conflicting_events_are_ambiguous():
    from guiyi_quant.lms405 import Event, replay_events

    events = [
        Event(str(i), "FG2609", T, T - timedelta(seconds=1), Action(kind, D(1)), "E41")
        for i, kind in enumerate(["ENTER_LONG", "LOCK"])
    ]
    with pytest.raises(ValueError, match="ACTION_ORDER_UNKNOWN"):
        replay_events("FG2609", events, cutoff=T)


def test_intrabar_zone_publication_cannot_claim_earlier_touch():
    bar = Bar(
        "FG2609", T, D(871), D(880), D(868), D(875), start=T - timedelta(minutes=1)
    )
    zone = Zone("a", "FG2609", D(870), D(875), T - timedelta(seconds=30), "E43")
    assert inspect_bar(bar, [zone])["zones"] == []


def test_unknown_bar_start_blocks_zone_observation():
    bar = Bar("FG2609", T, D(871), D(880), D(868), D(875))
    zone = Zone("a", "FG2609", D(870), D(875), T - timedelta(days=1), "E43")
    assert inspect_bar(bar, [zone])["zones"] == []


@pytest.mark.parametrize("contract", ["FG0", "actual_dominant", "", "FG2701/../JM2701"])
def test_synthetic_or_invalid_contract_is_rejected(contract):
    with pytest.raises(ValueError):
        Position(contract)

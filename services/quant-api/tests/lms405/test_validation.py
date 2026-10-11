from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from guiyi_quant.lms405 import Action, Event, Position
from guiyi_quant.lms405.validation import (
    FrozenRules,
    Checkpoint,
    advance,
    decide,
    compare_labels,
    holdout_status,
    causal_preflight,
    endpoint_error,
    REQUIRED_RULES,
)

T = datetime(2026, 10, 9, tzinfo=UTC)


def rules(**changes):
    args = dict(
        version="research-v1",
        sources=("E41",),
        identified=("POSITION_SEMANTICS",),
        unknown=("VPLUS", "ZONES"),
        frozen_at=T,
        definition_digest="a" * 64,
    )
    args.update(changes)
    return FrozenRules(**args)


def event(id, minute, action, quantity=1):
    return Event(
        id,
        "JM2701",
        T + timedelta(minutes=minute),
        T,
        Action(action, D(quantity)),
        "E41",
    )


def test_freeze_identity_changes_with_rules_and_time():
    assert rules().fingerprint == rules().fingerprint
    assert rules().fingerprint != rules(unknown=("VPLUS",)).fingerprint
    assert rules().fingerprint != rules(frozen_at=T + timedelta(seconds=1)).fingerprint
    assert rules().fingerprint != rules(definition_digest="b" * 64).fingerprint
    with pytest.raises(ValueError, match="OVERLAPPING_RULES"):
        rules(unknown=("POSITION_SEMANTICS",))


def test_unknown_is_not_hold_and_false_is_not_unknown():
    p = Position("JM2701", D(1))
    result = decide(p, Action("LOCK", D(1)), {"reverse_vplus": None}, ("E48",))
    assert result["status"] == "INDETERMINATE"
    assert result["unknown"] == ["reverse_vplus"]
    assert (p.long, p.short) == (1, 0)
    assert (
        decide(p, Action("LOCK", D(1)), {"permission": False}, ("E48",))["status"]
        == "NOT_PERMITTED"
    )
    assert decide(p, Action("LOCK", D(1)), {}, ("E48",))["status"] == "INDETERMINATE"


def test_conditional_action_is_not_original_strategy_or_fill():
    result = decide(
        Position("JM2701", D(1)),
        Action("LOCK", D(1)),
        {"external_permission": True},
        ("E41",),
    )
    assert result["status"] == "CONDITIONAL_ACTION"
    assert result["after"] == {"long": "1", "short": "1"}
    assert result["executable"] is False
    assert result["original_trigger_identified"] is False
    with pytest.raises(ValueError, match="BOOLEAN_OR_UNKNOWN"):
        decide(Position("JM2701"), Action("ENTER_LONG", D(1)), {"v": "yes"}, ("E41",))


def test_checkpoint_batch_incremental_restart_and_prefix():
    f = rules()
    c = Checkpoint(f.fingerprint, Position("JM2701"), T)
    events = [
        event("a", 1, "ENTER_SHORT"),
        event("b", 2, "LOCK"),
        event("c", 3, "UNLOCK_SHORT"),
        event("d", 4, "CLEAR"),
    ]
    whole = advance(c, events, T + timedelta(minutes=4), f)
    prefix = advance(c, events, T + timedelta(minutes=2), f)
    restored = Checkpoint.from_dict(prefix.to_dict())
    suffix = advance(restored, events[2:], T + timedelta(minutes=4), f)
    assert whole == suffix
    assert (prefix.position.long, prefix.position.short) == (1, 1)
    assert advance(c, events[:2], T + timedelta(minutes=2), f) == prefix
    with pytest.raises(ValueError, match="CHECKPOINT_SUFFIX_REQUIRED"):
        advance(restored, events, T + timedelta(minutes=4), f)
    with pytest.raises(ValueError, match="FROZEN_IDENTITY_MISMATCH"):
        advance(c, [], T, rules(version="research-v2"))


def test_late_equal_disclosure_and_simultaneous_actions_fail_closed():
    f = rules()
    c = Checkpoint(f.fingerprint, Position("JM2701"), T)
    late = Event(
        "late",
        "JM2701",
        T + timedelta(minutes=1),
        T + timedelta(minutes=1),
        Action("ENTER_LONG", D(1)),
        "E41",
    )
    assert advance(c, [late], T + timedelta(minutes=2), f).position.long == 0
    with pytest.raises(ValueError, match="ACTION_ORDER_UNKNOWN"):
        advance(
            c,
            [event("a", 1, "ENTER_LONG"), event("b", 1, "LOCK")],
            T + timedelta(minutes=2),
            f,
        )


def test_metrics_do_not_treat_unpublished_as_no_action_or_unknown_as_match():
    m = compare_labels(["LONG", "NONE", "SHORT", None], ["LONG", "SHORT", None, "LONG"])
    assert m == dict(
        known_truth=3,
        evaluated=2,
        matches=1,
        mismatches=1,
        unresolved=1,
        unknown_truth=1,
        false_positive=1,
        false_negative=0,
        match_rate="0.5",
    )
    assert compare_labels(["LONG"], [None])["match_rate"] is None
    assert compare_labels(["SHORT"], ["NONE"])["false_negative"] == 1


def test_holdout_cannot_be_already_seen_or_used_for_fit():
    assert (
        holdout_status(T + timedelta(seconds=1), rules(), False)
        == "ELIGIBLE_NEW_EVIDENCE"
    )
    assert holdout_status(T, rules(), False) == "DEVELOPMENT_ALREADY_SEEN"
    assert (
        holdout_status(T + timedelta(seconds=1), rules(), True)
        == "DEVELOPMENT_USED_FOR_FIT"
    )
    assert holdout_status(None, rules(), False) == "UNKNOWN_FIRST_SEEN"


def test_causal_gate_requires_all_facts_and_behavior():
    r = causal_preflight(rules(), {})
    assert r["status"] == "BLOCKED"
    assert "FORMULA_UNKNOWN:VPLUS" in r["blockers"]
    assert "BEHAVIOR_VALIDATION_MISSING" in r["blockers"]
    assert r["performance"] is None
    facts = {name: True for name in r["required_facts"]}
    # A ready preflight permits a later study, never claims an actual fill or PnL.
    assert causal_preflight(rules(unknown=()), facts)["status"] == "BLOCKED"
    ok = causal_preflight(rules(unknown=(), identified=REQUIRED_RULES), facts)
    assert ok["status"] == "READY_FOR_CAUSAL_STUDY"
    assert ok["performance"] is None and ok["executable"] is False
    facts["two_leg_costs"] = False
    assert (
        causal_preflight(rules(unknown=(), identified=REQUIRED_RULES), facts)["status"]
        == "BLOCKED"
    )


def test_decimal_endpoint_error_is_not_behavior_or_profit():
    assert endpoint_error(D("1542.5"), D("1543"), D("0.5")) == D(1)
    with pytest.raises(ValueError):
        endpoint_error(D(1), D(2), D(0))


def test_checkpoint_contract_cursor_and_serialized_identity_boundaries():
    f = rules()
    c = Checkpoint(f.fingerprint, Position("JM2701"), T)
    other = Event(
        "x", "FG2701", T + timedelta(minutes=1), T, Action("ENTER_LONG", D(1)), "E41"
    )
    with pytest.raises(ValueError, match="CONTRACT_BOUNDARY"):
        advance(c, [other], T + timedelta(minutes=2), f)
    with pytest.raises(ValueError, match="CURSOR_REGRESSION"):
        advance(c, [], T - timedelta(seconds=1), f)
    invalid = c.to_dict() | {"short": "-1"}
    with pytest.raises(ValueError, match="INVALID_DECIMAL"):
        Checkpoint.from_dict(invalid)
    with pytest.raises(ValueError, match="ACTION_STATE_CONFLICT"):
        decide(c.position, Action("UNLOCK_LONG", D(1)), {"ready": True}, ("E41",))


def test_same_event_conflict_unknown_labels_and_invalid_fact_values():
    f = rules()
    c = Checkpoint(f.fingerprint, Position("JM2701"), T)
    with pytest.raises(ValueError, match="EVENT_ID_CONFLICT"):
        advance(
            c,
            [event("a", 1, "ENTER_LONG"), event("a", 2, "ENTER_SHORT")],
            T + timedelta(minutes=3),
            f,
        )
    assert (
        advance(
            c, [event("a", 1, "ENTER_LONG")] * 2, T + timedelta(minutes=2), f
        ).position.long
        == 1
    )
    with pytest.raises(ValueError, match="ALIGNED_SAMPLES_REQUIRED"):
        compare_labels([None], [])
    with pytest.raises(ValueError, match="BOOLEAN_OR_UNKNOWN"):
        causal_preflight(f, {"strict_before": 1})


def test_conflicting_event_id_cannot_cross_restart_checkpoint():
    f = rules()
    c = Checkpoint(f.fingerprint, Position("JM2701"), T)
    first = advance(c, [event("same", 1, "ENTER_LONG")], T + timedelta(minutes=1), f)
    restored = Checkpoint.from_dict(first.to_dict())
    with pytest.raises(ValueError, match="EVENT_ID_CONFLICT"):
        advance(restored, [event("same", 2, "LOCK")], T + timedelta(minutes=2), f)

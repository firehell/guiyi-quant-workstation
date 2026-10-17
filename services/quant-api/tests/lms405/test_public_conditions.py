from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import importlib

import pytest

from guiyi_quant.lms405 import Action, Position

T = datetime(2026, 10, 17, tzinfo=UTC)


def api():
    # Imports inside tests expose the missing feature as an assertion failure.
    module = importlib.util.find_spec("guiyi_quant.lms405.public_conditions")
    assert module is not None, "time-aware public case conditions are missing"
    return importlib.import_module("guiyi_quant.lms405.public_conditions")


def plan_and_facts():
    m = api()
    p = m.PublicCase(
        "case",
        "JM2701",
        "https://weibo.com/1885745060/RfUgudQ5d",
        T,
        True,
        ("LOCK",),
        (("context", "location", "signal"), ("context", "gap_exception")),
        (),
    )
    facts = tuple(
        m.Condition(k, "case", "JM2701", True, T, T, "source:" + k, "EVENT_TIME")
        for k in ("context", "location", "signal")
    )
    return m, p, facts


def evaluate(m, p, facts, **kw):
    return m.assess_case(
        p,
        Position("JM2701", D(1)),
        Action("LOCK", D(1)),
        facts,
        as_of=kw.get("as_of", T + timedelta(seconds=1)),
    )


def test_known_route_can_satisfy_public_subset_but_never_assert_original_or_fill():
    m, p, facts = plan_and_facts()
    r = evaluate(m, p, facts)
    assert r["status"] == "CONDITIONAL_ACTION"
    assert r["after"] == {"long": "1", "short": "1"}
    assert r["routes"][0]["value"] is True
    assert r["routes"][1]["value"] is None
    assert r["executable"] is False and r["original_trigger_identified"] is False
    assert r["fill"] is None and r["performance"] is None


def test_false_normal_signal_does_not_imply_gap_exception():
    m, p, facts = plan_and_facts()
    facts = facts[:-1] + (replace(facts[-1], value=False),)
    assert evaluate(m, p, facts)["status"] == "INDETERMINATE"
    no_gap = m.Condition(
        "gap_exception", "case", "JM2701", False, T, T, "no-gap", "EVENT_TIME"
    )
    assert evaluate(m, p, facts + (no_gap,))["status"] == "NOT_PERMITTED"
    assert (
        evaluate(m, p, facts + (replace(no_gap, value=True),))["status"]
        == "CONDITIONAL_ACTION"
    )


def test_future_and_equal_time_disclosures_do_not_change_a_prefix():
    m, p, facts = plan_and_facts()
    assert evaluate(m, p, facts, as_of=T)["status"] == "INDETERMINATE"
    future = replace(facts[-1], known_at=T + timedelta(seconds=2))
    before = evaluate(m, p, facts[:-1])
    assert before == evaluate(m, p, facts[:-1] + (future,))
    assert (
        evaluate(m, p, facts[:-1] + (future,), as_of=T + timedelta(seconds=3))["status"]
        == "CONDITIONAL_ACTION"
    )
    assert (
        evaluate(m, replace(p, available_at=T + timedelta(seconds=2)), facts)["status"]
        == "INDETERMINATE"
    )


def test_two_necessary_conditions_also_require_the_disclosed_order():
    m, p, facts = plan_and_facts()
    p = replace(
        p,
        alternatives=(("pressure", "fresh_break"),),
        precedence=(("pressure", "fresh_break"),),
    )
    a = m.Condition("pressure", "case", "JM2701", True, T, T, "pressure", "EVENT_TIME")
    b = m.Condition(
        "fresh_break",
        "case",
        "JM2701",
        True,
        T + timedelta(seconds=1),
        T + timedelta(seconds=1),
        "break",
        "EVENT_TIME",
    )
    r = evaluate(m, p, (a, b), as_of=T + timedelta(seconds=2))
    assert r["status"] == "CONDITIONAL_ACTION"
    same = replace(b, observed_at=T, known_at=T)
    assert evaluate(m, p, (a, same))["status"] == "INDETERMINATE"
    backwards = replace(
        a, observed_at=T + timedelta(seconds=1), known_at=T + timedelta(seconds=1)
    )
    assert (
        evaluate(m, p, (backwards, same), as_of=T + timedelta(seconds=2))["status"]
        == "NOT_PERMITTED"
    )


def test_missing_version_identity_is_not_a_confirmed_405_case():
    m, p, facts = plan_and_facts()
    assert evaluate(m, replace(p, version_405=None), facts)["status"] == "INDETERMINATE"
    assert (
        evaluate(m, replace(p, version_405=False), facts)["status"] == "NOT_PERMITTED"
    )


def test_scope_typos_duplicates_and_invalid_actions_are_rejected():
    m, p, facts = plan_and_facts()
    for changed in (
        replace(facts[0], contract="FG2701"),
        replace(facts[0], case_id="other"),
    ):
        with pytest.raises(ValueError, match="CONDITION_SCOPE"):
            evaluate(m, p, (changed,) + facts[1:])
    with pytest.raises(ValueError, match="DUPLICATE_CONDITION"):
        evaluate(m, p, facts + facts[:1])
    with pytest.raises(ValueError, match="UNEXPECTED_CONDITION"):
        evaluate(m, p, (replace(facts[0], name="typo"),) + facts[1:])
    with pytest.raises(ValueError, match="ACTION_NOT_IN_CASE"):
        m.assess_case(p, Position("JM2701"), Action("ENTER_LONG", D(1)), (), as_of=T)
    with pytest.raises(ValueError, match="CONTRACT_BOUNDARY"):
        m.assess_case(p, Position("FG2701", D(1)), Action("LOCK", D(1)), (), as_of=T)
    with pytest.raises(ValueError, match="ACTION_STATE_CONFLICT"):
        m.assess_case(p, Position("JM2701"), Action("LOCK", D(1)), (), as_of=T)


def test_condition_and_case_validation_fail_closed():
    m, p, facts = plan_and_facts()
    with pytest.raises(ValueError, match="BOOLEAN_OR_UNKNOWN"):
        replace(facts[0], value=1)
    with pytest.raises(ValueError, match="KNOWN_BEFORE_OBSERVED"):
        replace(facts[0], known_at=T - timedelta(seconds=1))
    with pytest.raises(ValueError, match="OBSERVATION_TIME_KIND"):
        replace(facts[0], time_kind="reading-order-as-event")
    for kw in (
        {"alternatives": ()},
        {"alternatives": ((),)},
        {"alternatives": (("x", "x"),)},
        {"precedence": (("x", "y"),)},
        {"actions": ("bad",)},
        {"version_405": 1},
    ):
        with pytest.raises(ValueError):
            replace(p, **kw)


def test_fact_order_and_serialized_restart_inputs_are_deterministic():
    m, p, facts = plan_and_facts()
    r = evaluate(m, p, facts)
    assert r == evaluate(m, p, tuple(reversed(facts)))
    restored = tuple(
        m.Condition(
            f.name,
            f.case_id,
            f.contract,
            f.value,
            datetime.fromisoformat(f.observed_at.isoformat()),
            datetime.fromisoformat(f.known_at.isoformat()),
            f.source,
            f.time_kind,
        )
        for f in facts
    )
    assert r == evaluate(m, p, restored)


def test_casebook_reading_order_cannot_prove_pressure_then_market_break(tmp_path):
    import json
    from pathlib import Path
    from lms405_public_casebook import report

    book = json.loads(
        Path("docs/research/lms405/evidence/public-casebook.json").read_text()
    )
    row = book["cases"][1]
    row["version_405"] = True  # Isolate temporal proof, not the actual unknown version.
    t = datetime.fromisoformat(book["recorded_at"])
    row["disclosed_conditions"] = [
        dict(
            name=name,
            value=True,
            observed_at=(t - timedelta(seconds=3 - i)).isoformat(),
            known_at=t.isoformat(),
            source="research-reading",
            time_kind="RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME",
        )
        for i, name in enumerate(row["alternatives"][0])
    ]
    path = tmp_path / "casebook.json"
    path.write_text(json.dumps(book))
    r = report(path)["cases"][1]["assessment"]
    assert r["routes"][0]["checks"]["ORDER:PRESSURE_9010_9043<FRESH_BREAK_8969"] is None
    assert r["status"] == "INDETERMINATE"
    assert r["after"] is None

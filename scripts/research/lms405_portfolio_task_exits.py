"""Join lot-scoped counter-M exit comparisons with the nine-contract research replay."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position
from guiyi_quant.lms405.public_conditions import Condition, PublicCase, assess_case
from lms405_counter_m_lot_roles import exit_projection, exposure
from lms405_portfolio_replay import CONTRACTS
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import US
from lms_near405_replay import encoded, sha

ROOT = Path("output/lms405-portfolio-oct-20261125")
FIXTURE_SHA = "fba8faadaffb8fc5f54bc84588ad67e2256a4b113db270ed4285e4fe518ba856"
HUMAN_SHA = "da7df6ce4d9ac2e0eaa861783f4221c3135cff8f4ae8a86829aa30b4cbdf15a0"
LOTS = Path("output/lms405-counter-m-lot-roles-20261126/reviewed-a.json")
LOTS_SHA = "bbd3718bd80bd2d94e4b89b3de2f5ed1a875955c430e4c0989a896c514fcaa80"
VERSION = "lms405-portfolio-task-exits-v1"
CONDITIONS = ("M_LOT_ROLE_CONFIRMED", "M_EXIT_TRIGGER_CONFIRMED", "M_EXIT_PERMISSION")
JOINS = {
    "JM2701": ("WRnTlEfj1t", "WRo00BFM1E", "WRo2KQ43iX"),
    "SH2701": ("WRoAkcEppg", "U03", "WRoEvasxQR"),
}


def condition_comparison(contract, hypothetical, sources, available, *, as_of):
    known = available + 2 * US
    if not known < as_of:
        return dict(public_status="INDETERMINATE", public_after=None, fixture=None)
    before = hypothetical["before"]
    position = Position(contract, Decimal(before["long"]), Decimal(before["short"]))
    quantity = Decimal(hypothetical["designated_m_longs"])
    entire = exit_projection(contract, position.long, position.short, position.long)["after"]
    if not quantity:
        return dict(public_status="INDETERMINATE", public_after=None, fixture_kind="TEST_FIXTURE",
                    fixture={"permit": dict(status="NO_M_LOTS_IN_HYPOTHESIS", after=None)},
                    hypothetical_unchanged=exposure(position), whole_long_leg_comparator=entire,
                    changes_remaining_exposure=exposure(position) != entire)
    action = Action("EXIT_LONG", quantity)
    scope = sha(encoded([VERSION, contract, hypothetical, sources, available]).encode())
    case = PublicCase(scope, contract, sources[-1], available, None, (action.kind,), (CONDITIONS,))
    public = assess_case(case, position, action, (), as_of=as_of)
    if public["after"] is not None:
        raise ValueError("LMS_TASK_EXIT_UNEXPECTED_PUBLIC_ACTION")
    # Fixture facts and version are explicit. They test only the effect of
    # accepting or rejecting an exit for this assigned quantity.
    case = PublicCase(scope, contract, sources[-1], available, True, (action.kind,), (CONDITIONS,))
    checks = {}
    for label, permission in (("permit", True), ("deny", False), ("missing", None)):
        facts = tuple(Condition(name, scope, contract, permission if name == CONDITIONS[-1] else True,
                                available + US, known, "TEST_FIXTURE", "EVENT_TIME") for name in CONDITIONS)
        boundary = assess_case(case, position, action, facts, as_of=known)
        if boundary["after"] is not None:
            raise ValueError("LMS_TASK_EXIT_USED_SAME_TIME_FACT")
        result = assess_case(case, position, action, facts, as_of=as_of)
        after = result["after"]
        checks[label] = dict(status=result["status"], after=(
            exposure(Position(contract, Decimal(after["long"]), Decimal(after["short"]))) if after else None
        ))
    expected = {key: Decimal(value) for key, value in hypothetical["after"].items()}
    if checks["permit"]["after"] != expected or any(checks[key]["after"] is not None for key in ("deny", "missing")):
        raise ValueError("LMS_TASK_EXIT_PROJECTION_MISMATCH")
    return dict(public_status=public["status"], public_after=None, fixture_kind="TEST_FIXTURE",
                fixture=checks, whole_long_leg_comparator=entire,
                changes_remaining_exposure=checks["permit"]["after"] != entire)


def hypotheses(contract, report):
    case = report["cases"][contract]
    if contract == "JM2701":
        paths = case["projected"]
        result = {f"new_m_with_{v['older_longs']}_retained_long":
                  v for v in paths["new_longs_only_are_m_original_short_still_held"]}
        return result | {key: value for key, value in paths.items() if key.startswith("all_longs_are_m")}
    return {key: case[key] for key in ("projected_new_long_is_protection", "projected_new_long_is_m")}


def role_events(timeline, report, *, as_of):
    observations = {e["payload"]["source"]: e for e in timeline
                    if e["layer"] == "HOLDINGS_DISPLAY" and datetime.fromisoformat(e["time"]) < as_of}
    events = []
    for contract, sources in JOINS.items():
        if any(sid not in observations for sid in sources):
            continue
        anchors = [observations[sid] for sid in sources]
        times = [datetime.fromisoformat(anchor["time"]) for anchor in anchors]
        if times != sorted(set(times)):
            raise ValueError("LMS_TASK_EXIT_OBSERVATION_ORDER_CHANGED")
        available = times[-1]
        # The hypothetical comparison is first emitted when even its fixture
        # conditions are strictly before the read, without dating an action.
        ready = available + 3 * US
        if not ready < as_of:
            continue
        exposures = hypotheses(contract, report)
        displayed = anchors[1 if contract == "JM2701" else -1]["payload"]["positions"][contract]
        expected = next(iter(exposures.values()))["before"]
        if displayed["long"] != Decimal(expected["long"]) or (
            displayed["short"] is not None and displayed["short"] != Decimal(expected["short"])
        ):
            raise ValueError("LMS_TASK_EXIT_DISPLAY_MISMATCH")
        events.append(dict(time=ready.isoformat(), layer="COUNTER_M_EXIT_COMPARISON", payload=dict(
            contract=contract, source_ids=sources, all_sources_available_at=available,
            snapshot_long=displayed["long"], snapshot_short=displayed["short"],
            requires_explicit_role_and_permission=True, author_action_at=None,
            scenarios={key: condition_comparison(contract, row, sources, available, as_of=as_of)
                       for key, row in exposures.items()},
        )))
    return events


def study():
    fixture = verified_json(ROOT / "fixture.json", FIXTURE_SHA)
    human = verified_json(ROOT / "human.json", HUMAN_SHA)
    lots = verified_json(LOTS, LOTS_SHA)
    if (set(fixture["contract_summaries"]) != set(CONTRACTS) or not fixture["fixture"] or human["fixture"]
            or fixture["source_book_sha256"] != human["source_book_sha256"]
            or fixture["candidate_rule_hash"] != human["candidate_rule_hash"]
            or fixture["as_of"] != human["as_of"]
            or any(fixture["contract_summaries"][c]["input_prefix_sha256"]
                   != human["contract_summaries"][c]["input_prefix_sha256"] for c in CONTRACTS)
            or any(x["layer"] == "FIXTURE_STATE_BATCH" for x in human["timeline"])):
        raise ValueError("LMS_TASK_EXIT_BASELINE_CHANGED")
    original = fixture["timeline"]
    as_of = datetime.fromisoformat(fixture["as_of"])
    additions = role_events(original, lots, as_of=as_of)
    exit_events = {row["payload"]["contract"]: row for row in additions}
    if set(exit_events) != set(JOINS):
        raise ValueError("LMS_TASK_EXIT_MISSING_TERMINAL_OBSERVATION")
    event_times = [datetime.fromisoformat(event["time"]) for event in additions]
    for cutoff in sorted({t + offset for t in event_times for offset in (-4 * US, timedelta(0), US)}):
        truncated = [row for row in original if datetime.fromisoformat(row["time"]) < cutoff]
        expected = [event for event, at in zip(additions, event_times, strict=True) if at < cutoff]
        if role_events(original, lots, as_of=cutoff) != expected or role_events(
            truncated, lots, as_of=cutoff,
        ) != expected:
            raise ValueError("LMS_TASK_EXIT_PREFIX_DIVERGED")
    whole_clears = {c: [] for c in CONTRACTS}
    for event in original:
        if event["layer"] != "FIXTURE_STATE_BATCH":
            continue
        for action in event["payload"]["actions"]:
            if action["action"] == "CLEAR" and all(Decimal(q) > 0 for q in action["before"]):
                whole_clears[action["contract"]].append(dict(time=event["time"], reason=action["reason"],
                                                              after=action["after"], author_counter_m_exit=None))
    timeline = sorted(original + additions, key=lambda e: (datetime.fromisoformat(e["time"]), e["layer"],
                                                           encoded(e["payload"])))
    if [row for row in timeline if row["layer"] != "COUNTER_M_EXIT_COMPARISON"] != original:
        raise ValueError("LMS_TASK_EXIT_BASELINE_ORDER_CHANGED")
    return dict(version=VERSION, as_of=as_of, candidate_version=fixture["candidate_version"],
                candidate_rule_hash=fixture["candidate_rule_hash"], timeline=timeline,
                references=dict(fixture=FIXTURE_SHA, human=HUMAN_SHA, lot_roles=LOTS_SHA),
                fixture_terminal_units=fixture["fixture_terminal_units"],
                contracts={c: dict(paired_baseline_clears=whole_clears[c],
                                   lot_exit_coverage=("CONDITIONAL" if c in exit_events else "UNIDENTIFIED"),
                                   comparison_event_at=exit_events[c]["time"] if c in exit_events else None)
                           for c in CONTRACTS},
                outside_window_case_ids=["JM2601"], author_match_rate=None, author_action_samples=0,
                author_actions_applied=0, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    try:
        report = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (KeyError, OSError, ValueError):
        parser.exit(2, "LMS_TASK_EXIT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

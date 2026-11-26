"""Source-scoped right-side entry candidates for the independent LMS research replay."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.participation import Participation, assess_participation
from guiyi_quant.lms405.public_conditions import Condition
from lms405_breakout_trial_study import CASES, Case, analyze
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at

VERSION = "lms405-published-right-entry-v1"
PVC = "V2701"


@dataclass(frozen=True)
class Branch:
    case: Case
    source: dict
    available: datetime
    start: datetime
    through: datetime

    def active(self, side, now):
        return self.case.direction == side and self.start <= now < self.through


def branches(index, contract):
    if contract != PVC:
        return ()
    values = []
    for name, through in (("PVC_RIGHT_SHORT", "2026-10-27T15:01"), ("PVC_RIGHT_LONG", "2026-10-28T15:01")):
        case = CASES[name]
        source = load_source(index, case.source)
        available = datetime.fromisoformat(source["published_at"]) + ONE
        values.append(Branch(case, source, available, max(at(case.start), available + US), at(through)))
    return tuple(values)


def active_branch(scoped, contract, direction, now):
    eligible = [branch for branch in scoped if branch.case.contract == contract and branch.active(direction, now)]
    if len(eligible) > 1:
        raise ValueError("RIGHT_ENTRY_SCOPE_AMBIGUOUS")
    return eligible[0] if eligible else None


def entry_events(series, scoped, cutoff):
    events = []
    for branch in scoped:
        case = branch.case
        if case.role != "ENTRY_REFERENCE" or case.prerequisite not in (
            "BREAK_THEN_SIGNAL", "BREAK_PRESSURE_THEN_SIGNAL",
        ):
            raise ValueError("RIGHT_ENTRY_SOURCE_ROLE_MISMATCH")
        cut = min(cutoff, branch.through)
        if cut <= branch.start:
            continue
        view = analyze(series, case, branch.start, cut)
        retest = case.prerequisite == "BREAK_PRESSURE_THEN_SIGNAL"
        route = "fresh_shape_after_retest" if retest else "fresh_shape_after_cross"
        setup_key = "retest_confirmed_at" if retest else "active_cross_at"
        for clock, rows in view["patterns"].items():
            for signal in rows:
                ready_at = signal["available_at"] + 8 * US
                if ready_at >= cut or not signal[route]:
                    continue
                edge, target = map(Decimal, (case.edge, case.next_reference))
                room = target - signal["close"] if case.direction == "LONG" else signal["close"] - target
                reached = view["first_reference_directional_reach"]
                consumed = reached is not None and reached <= signal["confirmed_at"]
                events.append(dict(at=ready_at, branch=branch, clock=clock, setup_at=signal[setup_key],
                                   shape_start=signal["shape_start"], signal_at=signal["confirmed_at"],
                                   signal_known_at=signal["available_at"], close=signal["close"], edge=edge,
                                   reference=target, room=room, reference_consumed=consumed))
    return sorted(events, key=lambda row: (row["at"], row["clock"]))


def assess_entry(contract, state, event, *, fixture=False):
    branch = event["branch"]
    case = branch.case
    if contract != case.contract or state["contract"] != contract:
        raise ValueError("RIGHT_ENTRY_CONTRACT_MISMATCH")
    evaluated, shape_start = event["at"], event["shape_start"]
    known_at = datetime.fromisoformat(state["known_at"])
    if not known_at < evaluated:
        raise ValueError("RIGHT_ENTRY_POSITION_NOT_YET_AVAILABLE")
    p = Position(contract, Decimal(state["long"]), Decimal(state["short"]))
    setup_known = event["setup_at"] + US
    signal_known = event["signal_known_at"]
    if not (evaluated > signal_known > event["signal_at"] >= shape_start > setup_known
            > event["setup_at"] >= branch.start > branch.available and branch.active(case.direction, evaluated)):
        raise ValueError("RIGHT_ENTRY_TIME_SCOPE_MISMATCH")
    exposure = "ALREADY_HELD_SINGLE_UNIT" if p.long or p.short else None
    fresh = known_at < event["setup_at"]
    room = event["room"] > 0 and not event["reference_consumed"]
    request = Participation(p, case.direction, case.source, state["cycle_id"] or "FLAT",
                            known_at, branch.available, branch.source["source_url"], True if fixture else None)
    # Branch text and market observations do not supply the original V+ or action authority.
    facts = [
        Condition("PRICE_SETUP", request.scope, contract, True, event["setup_at"], setup_known,
                  "COMPLETED_PRICE_PROXY", "EVENT_TIME"),
        Condition("SPACE_AVAILABLE", request.scope, contract, False if not room else True if fixture else None,
                  event["signal_at"], signal_known, "RESEARCH_REFERENCE_DISTANCE", "EVENT_TIME"),
    ]
    if fixture and fresh and exposure is None:
        facts.extend(Condition(name, request.scope, contract, True, event["signal_at"], signal_known,
                               "TEST_FIXTURE", "EVENT_TIME") for name in (
            "POSITION_CONFIRMED", "PLAN_ACTIVE", "DIRECTION_ESTABLISHED", "RIGHT_POLICY_PERMITS",
            "RIGHT_SIGNAL", "PRICE_SETUP_STILL_VALID",
        ))
    decision = assess_participation(request, tuple(facts), as_of=evaluated)["decisions"]["RIGHT_PARTICIPATION"]
    blocking = exposure or ("POSITION_CHANGED_AFTER_SETUP" if not fresh else None)
    return dict(policy=VERSION, direction=case.direction, source_id=case.source, source_url=branch.source["source_url"],
                evaluated_at=evaluated, setup_at=event["setup_at"], signal_at=event["signal_at"], clock=event["clock"],
                reference=event["reference"], hypothetical_positive_space=room, distance_to_reference=event["room"],
                decision=decision, reason=blocking, permit=blocking is None and decision["status"] == "CONDITIONS_MET",
                position_known_at=known_at, before_exposure=dict(long=p.long, short=p.short),
                original_signal_verified=False, author_permission_supplied=False)

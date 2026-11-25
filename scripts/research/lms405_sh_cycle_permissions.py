"""Replay separate recovery and reprotection permissions on the frozen SH2701 case."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation, assess_handoff
from guiyi_quant.lms405.public_conditions import Condition, PublicCase
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_layers_replay import ORDER, ROUTES, assessment, fact, measure
from lms405_protection_lot_timing import verified_json
from lms405_protection_next_night_replay import SH, SH_SHA
from lms405_right_side_study import LOCAL, ONE, US
from lms405_sh_lock_lifecycle import CLOSE, CONTRACT, LUNCH, NIGHT, OLD_PLAN, PLAN, RECAP
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA
from lms_near405_replay import encoded, sha

VERSION = "lms405-sh-cycle-permissions-v1"
NEXT_NIGHT = Path("output/lms405-protection-next-night-20261125/verified.json")
NEXT_NIGHT_SHA = "c4168e321b5a8987304b7a40198d2a2398ed4c6c59a09320615951813521c2ba"
DAY_PATHS = {"old_near_5m_to_1m": ("5m_to_1m", "old_resistance_near"),
             "old_far_1m_to_1m": ("1m_to_1m", "old_resistance_far")}


def project(request, *, recovery, lock, as_of):
    day_case = assess_handoff(request, recovery["facts"], as_of=min(as_of, recovery["cutoff"]), **recovery["policy"])
    position = measure(request.before, day_case)
    night_case = None
    if position.long:
        protection_status = "EXISTING_LOCK_NO_NEW_LOCK_APPLIED"
    elif as_of <= lock["session_start"]:
        protection_status = "NIGHT_SESSION_NOT_STARTED"
    else:
        night_case = assessment(lock["case"], position, lock["facts"], min(as_of, lock["cutoff"]))
        position = measure(position, night_case)
        protection_status = night_case["status"]
    old_long = request.before.long if day_case["after"] is None else Decimal(0)
    return dict(recovery_status=day_case["status"], protection_status=protection_status,
                removed_old_long=request.before.long - old_long, retained_old_long=old_long,
                new_protection_long=position.long - old_long, original_short=position.short,
                long=position.long, short=position.short)


def recovery_input(request, source, event, cutoff, *, fixture):
    visible = datetime.fromisoformat(source["published_at"]) + ONE
    options = dict(source=source["source_url"], source_available_at=visible, version_405=True if fixture else None)
    if not fixture:
        return dict(facts=(), policy=options, cutoff=cutoff)
    observed, known = (datetime.fromisoformat(event[field]) for field in ("confirmed_at", "available_at"))
    contract, seed = request.before.contract, request.position_known_at
    facts = tuple(Condition(name, request.scope, contract, True, observed_at, known_at, "TEST_FIXTURE", "EVENT_TIME")
                  for name, observed_at, known_at in (("POSITION_PATH_CONFIRMED", seed, seed),
                                                     ("ORIGINAL_PLAN_VALID", seed, seed), ("SIGNAL", observed, known)))
    approval = HandoffConfirmation(request.confirmation_scope(**options), f"TEST_FIXTURE:UNLOCK:{known.isoformat()}",
                                   True, known + US, known + US, "TEST_FIXTURE")
    return dict(facts=facts, policy=options | dict(approval=approval, allow_test_fixture=True), cutoff=cutoff)


def protection_input(source, row, start, cutoff, *, fixture, defer):
    visible = datetime.fromisoformat(source["published_at"]) + ONE
    case = PublicCase(f"{VERSION}:{PLAN}:{'DEFERRED' if defer else 'IMMEDIATE'}", CONTRACT, source["source_url"], visible,
                      True if fixture else None, ("LOCK",), ROUTES, ORDER)
    opening = start + ONE
    facts = [fact(case, "OPENING_CONTEXT", opening, "COMPLETED_OPENING_BAR", known_at=opening + US),
             fact(case, "PROTECTION_REFERENCE", visible, source["source_url"])]
    if fixture:
        signal = datetime.fromisoformat(row["confirmed_at"])
        known = datetime.fromisoformat(row["available_at"])
        touch = datetime.fromisoformat(row["touch_known_at"])
        if not row["pre_touch_arm"] or not row["survives_both_diagnostics"] or not start < known < touch < cutoff:
            raise ValueError("SH_CYCLE_PRE_TOUCH_SCOPE_CHANGED")
        permission = (touch if defer else known) + US
        facts += [fact(case, "EXPLICIT_ADVANCE_ROUTE", visible, "TEST_FIXTURE_ADVANCE"),
                  fact(case, "OPPOSITE_VPLUS", signal, "TEST_FIXTURE_ADOPTED_GEOMETRY", known_at=known),
                  fact(case, "LOCK_PERMISSION", permission, "TEST_FIXTURE_PROTECTION_PERMISSION")]
    return dict(case=case, facts=tuple(facts), session_start=start, cutoff=cutoff)


def prefix_trace(request, recovery, lock, clocks):
    inputs = [event.known_at for item in (recovery, lock) for event in item["facts"]]
    approval = recovery["policy"].get("approval")
    if approval:
        inputs.append(approval.known_at)
    checkpoints = set(clocks) | set(inputs) | {t + US for t in inputs}
    result = []
    for as_of in sorted(t for t in checkpoints if t > request.position_known_at):
        state = project(request, recovery=recovery, lock=lock, as_of=as_of)
        earlier_recovery = recovery | dict(facts=tuple(f for f in recovery["facts"] if f.known_at < as_of))
        if approval and approval.known_at >= as_of:
            earlier_recovery["policy"] = recovery["policy"] | dict(approval=None)
        earlier_lock = lock | dict(facts=tuple(f for f in lock["facts"] if f.known_at < as_of))
        if state != project(request, recovery=earlier_recovery, lock=earlier_lock, as_of=as_of):
            raise ValueError("SH_CYCLE_PREFIX_DIVERGED")
        result.append(dict(as_of=as_of, **state))
    return result


def verify_sources(lifecycle, replacement, next_night):
    sources = lifecycle["sources"]
    for record in sources.values():
        if sha((ARCHIVE.parent / record["archive_path"]).read_bytes()) != record["archive_sha256"]:
            raise ValueError("SH_CYCLE_ARCHIVE_SOURCE_CHANGED")
    for record in lifecycle["snapshots"].values():
        image = record["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("SH_CYCLE_PHOTO_CHANGED")
    night = next_night["cases"][CONTRACT]
    reread = replacement["with_night_today_quantity"]
    visible = night["displayed_night"]
    if (replacement["lifecycle_sha256"] != LIFECYCLE_SHA or night["plan"] != sources[PLAN]
            or reread["image_sha256"] != lifecycle["snapshots"][NIGHT]["image"]["sha256"]
            or visible["long"]["today_quantity"] != 20 or reread["today_quantity"] != 20
            or visible["long"]["quantity"] != 20 or reread["prior_displayed_long_lots_retained"] != 0
            or "long" not in night["unlisted_close_sides"] or [night["later_author_report"]["action_at"],
                                                                lifecycle["author_action_at"]] != [None, None]):
        raise ValueError("SH_CYCLE_SOURCE_SCOPE_CHANGED")
    return sources, night


def study(lifecycle, replacement, next_night):
    sources, night = verify_sources(lifecycle, replacement, next_night)
    seed_at, day_cut, start, cut = (datetime.fromisoformat(lifecycle[k])
                                    for k in ("afternoon_start", "afternoon_cut", "night_start", "night_cut"))
    seed = Position(CONTRACT, *(Decimal(lifecycle["seed"][side]) for side in ("long", "short")))
    day = day_cut.astimezone(LOCAL).date()
    next_day = date.fromisoformat(next_night["trading_day"])
    if (seed.long != Decimal(20) or seed.short != Decimal(20)
            or not seed_at < day_cut < datetime.fromisoformat(sources[RECAP]["published_at"])
            < datetime.fromisoformat(sources[PLAN]["published_at"]) < start < cut or not day < next_day):
        raise ValueError("SH_CYCLE_CASE_CLOCK_OR_SEED_CHANGED")
    request = Handoff("RESUME_ORIGINAL", seed, "SHORT", f"{CONTRACT}:{OLD_PLAN}", f"{CONTRACT}:{LUNCH}",
                      None, seed_at, seed_at)
    signal = night["geometry_candidate"]
    after_close = datetime.fromisoformat(sources[CLOSE]["published_at"]) + ONE
    clocks = (day_cut, after_close, start, cut)
    scenarios = {}
    for path, (variant, edge) in DAY_PATHS.items():
        day_signal = lifecycle["variants"][variant]["edge_comparisons"][edge]["recovery"][
            "first_shape_after_fresh_cross_and_still_beyond"]
        if not seed_at < datetime.fromisoformat(day_signal["available_at"]) < day_cut:
            raise ValueError("SH_CYCLE_DAY_SIGNAL_CLOCK_CHANGED")
        for name, unlock, protect, defer in (("public", False, False, False), ("recovery_only", True, False, False),
                                               ("night_protection_only", False, True, False),
                                               ("both_immediate", True, True, False), ("both_deferred", True, True, True)):
            recovery = recovery_input(request, sources[OLD_PLAN], day_signal, day_cut, fixture=unlock)
            lock = protection_input(sources[PLAN], signal, start, cut, fixture=protect, defer=defer)
            trace = prefix_trace(request, recovery, lock, clocks)
            final = trace[-1]
            expected = (Decimal(0 if unlock else 20), Decimal(20 if unlock and protect else 0))
            if ((final["retained_old_long"], final["new_protection_long"]) != expected
                    or any(row["original_short"] != seed.short for row in trace)):
                raise ValueError("SH_CYCLE_PERMISSION_REPLAY_DIVERGED")
            scenarios[f"{path}:{name}"] = dict(recovery_fixture=unlock, protection_fixture=protect,
                                               recovery_candidate=day_signal, protection_candidate=signal,
                                               matches_new_long_quantity_constraint=final["new_protection_long"] == seed.long,
                                               prefix_checks=len(trace), trace=trace)
    return dict(version=VERSION, contract=CONTRACT, seed=lifecycle["seed"], sources=sources, scenarios=scenarios,
                day_trading_date=day, night_trading_date=next_day,
                assumption="SAME_ACCOUNT_AND_TODAY_LOTS_RESET_ON_NEW_TRADING_DAY_FOR_ORIGIN_COMPARISON_ONLY",
                account_continuity=None, unshown_close_long=None, afternoon_version_verified=False,
                author_lock_at=None, author_unlock_at=None, author_actions_scored=0, author_match_rate=None,
                inputs=dict(lifecycle=LIFECYCLE_SHA, next_night=NEXT_NIGHT_SHA, replacement=SH_SHA),
                executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = study(verified_json(LIFECYCLE, LIFECYCLE_SHA), verified_json(SH, SH_SHA),
                       verified_json(NEXT_NIGHT, NEXT_NIGHT_SHA))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (KeyError, OSError, ValueError, TypeError):
        parser.exit(2, "SH_CYCLE_INPUT_UNVERIFIED_OR_OUTPUT_EXISTS\n")


if __name__ == "__main__":
    main()

"""Project frozen LMS405 research actions onto observed per-contract lot sizes."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action, timestamp
from lms405_portfolio_replay import CONTRACTS
from lms_near405_replay import encoded, sha

CLOCK_SHA256 = "ad3522175825e62323a2c820ccc080205268b41dcb221648956bfbed018d91b3"
SIZING_SHA256 = "ef8c8dd93f5fde25d3fb7ac7a25f90659b6122b729cae7aae7c4224fb4d30ce1"
PTA_CASE_SOURCE = "WRo2KQ43iX"
PTA_CASE_ENTRY = datetime.fromisoformat("2026-10-23T21:35:00.000002+08:00")
ZERO, ONE = Decimal(0), Decimal(1)


def lot_profile(sizing):
    if set(sizing["by_contract"]) != set(CONTRACTS):
        raise ValueError("LOT_PROFILE_CONTRACT_SET_MISMATCH")
    sizes = {}
    for contract, data in sizing["by_contract"].items():
        if data["stable_lots_across_visible_tables"] is True:
            (value,) = data["displayed_quantities"]
            if type(value) is not int or value <= 0 or data["tables"] < 2 or contract == "TA2701":
                raise ValueError("LOT_PROFILE_OBSERVATION_INVALID")
            sizes[contract] = Decimal(value)
    if sizes.keys() != set(CONTRACTS) - {"TA2701"}:
        raise ValueError("EXPECTED_EIGHT_REPEATED_LOT_OBSERVATIONS")
    return sizes


def pta_example(sizing):
    (display,) = [row for row in sizing["displays"] if row["source"] == PTA_CASE_SOURCE]
    leg = display["contracts"]["TA2701"]["long"]
    if leg["quantity"] != 34 or sizing["by_contract"]["TA2701"]["tables"] != 1:
        raise ValueError("PTA_SINGLE_OBSERVATION_MISMATCH")
    return Decimal(leg["quantity"])


def unit_position(contract, sides):
    long, short = map(Decimal, sides)
    if long not in (ZERO, ONE) or short not in (ZERO, ONE):
        raise ValueError("REPLAY_UNIT_LEGS_REQUIRED")
    return Position(contract, long, short)


def lot_fields(unit, size):
    def project(quantity):
        if quantity == ZERO:
            return "0"
        return str(quantity * size) if size is not None else None

    return dict(
        long=project(unit.long), short=project(unit.short),
        gross=project(unit.long + unit.short), net=project(unit.long - unit.short),
    )


def portfolio_counts(positions, projected):
    incomplete = sorted(c for c, legs in projected.items() if legs["gross"] is None)
    return dict(
        long_contracts=sum(p.long > p.short for p in positions.values()),
        short_contracts=sum(p.short > p.long for p in positions.values()),
        equal_locked_contracts=sum(p.long == p.short > 0 for p in positions.values()),
        active_contracts_with_unknown_size=incomplete,
        known_gross_lots_subtotal=str(sum(Decimal(v["gross"]) for v in projected.values() if v["gross"] is not None)),
    )


def projected_transition(contract, row, current, cycle, profile, pta_lots, now):
    before, after = (unit_position(contract, row[stage]) for stage in ("before", "after"))
    kind = row["action"]
    units = before.long + before.short if kind == "CLEAR" else ONE
    if current != before or apply_action(before, Action(kind, units)) != after:
        raise ValueError("FROZEN_UNIT_TRANSITION_MISMATCH")
    if before.long == before.short == ZERO:
        cycle = now, "LONG" if after.long else "SHORT"
    if cycle is None:
        raise ValueError("ACTIVE_CYCLE_ENTRY_UNKNOWN")
    cycle_entry, original_side = cycle
    if row["side"] != original_side or (kind.startswith("UNLOCK_") and kind != f"UNLOCK_{original_side}"):
        raise ValueError("ORIGINAL_CYCLE_DIRECTION_MISMATCH")

    case_applied = contract == "TA2701" and cycle_entry == PTA_CASE_ENTRY and pta_lots is not None
    size = pta_lots if case_applied else profile.get(contract)
    if size is not None:
        sized_before = Position(contract, before.long * size, before.short * size)
        sized_after = Position(contract, after.long * size, after.short * size)
        if apply_action(sized_before, Action(kind, units * size)) != sized_after:
            raise ValueError("PROJECTED_ACTION_STATE_MISMATCH")
    return after, (cycle if after.long or after.short else None), dict(
        contract=contract, action=kind, reason=row["reason"],
        original_side=original_side,
        cycle_entered_at=cycle_entry.isoformat(), scale_lots=str(size) if size is not None else None,
        action_quantity_lots=str(units * size) if size is not None else None,
        size_source=PTA_CASE_SOURCE if case_applied else ("REPEATED_405_DISPLAY" if size is not None else None),
        before=lot_fields(before, size), after=lot_fields(after, size),
    )


def project_window(window, variant, profile, *, pta_lots=None):
    if set(window["contracts"]) != set(CONTRACTS):
        raise ValueError("CLOCK_REPORT_CONTRACT_SET_MISMATCH")
    events, clocks = defaultdict(dict), {}
    as_of = datetime.fromisoformat(window["as_of"])
    timestamp(as_of)
    for contract, data in window["contracts"].items():
        clock = clocks[contract] = data["results"][variant]
        last = None
        for row in clock["transitions"]:
            at = datetime.fromisoformat(row["at"])
            timestamp(at)
            if at > as_of or (last is not None and at <= last):
                raise ValueError("CLOCK_TRANSITION_TIME_UNVERIFIED")
            events[at][contract] = row
            last = at

    positions = {c: Position(c) for c in CONTRACTS}
    active_cycles = {c: None for c in CONTRACTS}
    projected = {c: lot_fields(p, profile.get(c)) for c, p in positions.items()}
    batches, counts, pta_cycles = [], Counter(), set()
    for at, rows in sorted(events.items()):
        actions = []
        for contract, row in sorted(rows.items()):
            state, cycle, action = projected_transition(
                contract, row, positions[contract], active_cycles[contract], profile, pta_lots, at,
            )
            positions[contract], active_cycles[contract], projected[contract] = state, cycle, action["after"]
            counts[action["action"]] += 1
            if action["size_source"] == PTA_CASE_SOURCE:
                pta_cycles.add(action["cycle_entered_at"])
            actions.append(action)
        batches.append(dict(at=at.isoformat(), actions=actions, portfolio=portfolio_counts(positions, projected)))

    if counts != window["action_counts"][variant]:
        raise ValueError("CLOCK_ACTION_COUNTS_MISMATCH")
    identity = {(result["version"], result["rule_hash"]) for result in clocks.values()}
    (version, rule_hash), = identity
    for contract, unit in positions.items():
        terminal = "OPEN_LOCKED" if unit.long and unit.short else ("OPEN_DIRECTIONAL" if unit.long or unit.short else "FLAT")
        if terminal != clocks[contract]["terminal"]:
            raise ValueError("CLOCK_TERMINAL_MISMATCH")
    return dict(
        as_of=window["as_of"], clock_version=version, clock_rule_sha256=rule_hash,
        input_bars={contract: row["input_sha256"] for contract, row in window["contracts"].items()},
        action_counts=dict(counts), timeline=batches,
        pta_scenario_cycles=sorted(pta_cycles),
        terminal_contracts=projected, terminal_portfolio=portfolio_counts(positions, projected),
    )


def sized_replay(clock, sizing, *, pta_case=False):
    if clock["fixture_only"] is not True or clock["executable"] is not False:
        raise ValueError("FROZEN_FIXTURE_REQUIRED")
    profile = lot_profile(sizing)
    example = pta_example(sizing) if pta_case else None
    windows = {}
    for name in ("development", "comparative"):
        window = clock[name]
        windows[name] = {
            variant: project_window(window, variant, profile, pta_lots=example if name == "development" else None)
            for variant in window["action_counts"]
        }
    if pta_case and any(len(row["pta_scenario_cycles"]) != 1 for row in windows["development"].values()):
        raise ValueError("PTA_SCENARIO_CYCLE_NOT_IDENTIFIED")
    return dict(
        version="lms405-sized-portfolio-study-v1", fixture_only=True,
        observation_basis="RETROSPECTIVE_PROFILE_FROM_405_COVER_TABLES",
        lot_profile=profile,
        pta_case=(
            dict(source=PTA_CASE_SOURCE, lots=example, entry_at=PTA_CASE_ENTRY.isoformat())
            if pta_case else None
        ),
        windows=windows,
        author_action_matches=None, admitted_author_action_samples=0,
        fills=None, pnl=None, margin=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-clock-report", type=Path, required=True)
    parser.add_argument("--sizing-audit", type=Path, required=True)
    parser.add_argument("--pta-case", action="store_true", help="Apply the 34-lot observation to one October cycle.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        clock, sizing = args.hold_clock_report.read_bytes(), args.sizing_audit.read_bytes()
        if sha(clock) != CLOCK_SHA256 or sha(sizing) != SIZING_SHA256:
            raise ValueError("FROZEN_INPUT_HASH_MISMATCH")
        report = sized_replay(json.loads(clock), json.loads(sizing), pta_case=args.pta_case)
        report["input_sha256"] = dict(hold_clock=sha(clock), sizing=sha(sizing))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

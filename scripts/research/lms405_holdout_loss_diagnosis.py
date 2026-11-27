"""Reconcile the frozen P5 date holdout and export cycle and operation diagnostics."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_near405 import RULE_HASH, replay
from lms405_holdout_replay import BASE, COVERAGE_SHA, DAYS, FROZEN_CODE, FROZEN_RULE, US
from lms405_original_leg_study import verified_json
from lms405_replay import ohlc, read_session_series
from lms_near405_backtest import EXECUTION_VERSION, SCENARIOS, execute_reference
from lms_near405_replay import encoded, sha

REPORT_SHA = "906a443cf83bf942a9bc7d99bc394713be013b30d7e6bf9878e37258561eda8c"
METRICS = ("gross", "fees", "slippage", "cost", "net")
SIDES = ("long", "short")


def require(condition, location):
    if not condition:
        raise ValueError(f"FROZEN_DIAGNOSIS_MISMATCH: {location}")


def read_frozen_series(session_factory, contract, period, expected):
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service

    interval = timedelta(minutes=period)
    with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
        raw = read_session_series(
            session, build_market_data_service(session), contract[:-4].lower(),
            contract, f"{period}m", interval, DAYS,
        )
    payload = [(b.trading_day, b.bar_end, *ohlc(b), b.volume) for b in raw]
    require(len(payload) == expected["bars"] and sha(encoded(payload).encode()) == expected["sha256"],
            (contract, period, "bar hash"))
    return raw


def market_contract(session_factory, contract, coverage, frozen):
    require(coverage["ohlc_parity"] is True, (contract, "aggregation"))
    raw_five = read_frozen_series(session_factory, contract, 5, coverage["5m"])
    raw_minute = read_frozen_series(session_factory, contract, 1, coverage["1m"])
    bars = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - timedelta(minutes=5)) for b in raw_five]
    minutes = [
        dict(contract=contract, trading_day=b.trading_day.isoformat(), bar_end=b.bar_end.isoformat(),
             open=str(b.open), high=str(b.high), low=str(b.low), close=str(b.close), volume=str(b.volume))
        for b in raw_minute
    ]
    fixture = replay(bars, as_of=bars[-1].end + 3 * US, timely_fixture=True)
    require(json.loads(encoded(fixture["transitions"])) == frozen["fixture_transitions"],
            (contract, "fixture transitions"))
    for scenario, (fee, ticks) in SCENARIOS.items():
        result = execute_reference(
            minutes, fixture["transitions"], Decimal(frozen["multiplier"]), Decimal(frozen["tick"]), fee, ticks,
        )
        require(json.loads(encoded(result)) == frozen["reference"][scenario], (contract, scenario))
    return bars, fixture


def trace_transition(transition, proposals, evaluations, bars):
    proposal = proposals[transition["proposal_id"]]
    index = proposal["index"]
    evaluation = evaluations[index]
    signal, confirmation = bars[index - 1 : index + 1]
    require(
        transition["record_kind"] == "TEST_FIXTURE"
        and proposal["status"] == "ACCEPTED"
        and proposal["signal_bar_end"] == signal.end.isoformat()
        and evaluation["bar_end"] == confirmation.end.isoformat()
        and datetime.fromisoformat(transition["known_at"]) > confirmation.end,
        transition["decision_id"],
    )
    pattern = evaluation["pattern"]
    return dict(
        action=transition["action"], reason=transition["reason"], proposal_id=transition["proposal_id"],
        decision_id=transition["decision_id"], known_at=transition["known_at"], index=index, plan=proposal["plan"],
        bar_end=confirmation.end.isoformat(), signal_bar_end=signal.end.isoformat(),
        signal_high=signal.high, signal_low=signal.low, close=confirmation.close,
        ibar=pattern["ibar"], pinbar=pattern["pinbar"], signal_direction=evaluation["signal_direction"],
        environment=evaluation["environment"], lower=evaluation["region"]["lower"],
        upper=evaluation["region"]["upper"], context_hash=evaluation["region"]["context_hash"],
    )


def reconcile(contract, frozen, bars, fixture):
    reference = frozen["reference"]["fee3_tick1"]
    cycles = {row["cycle_id"]: row for row in reference["closed_cycles"]}
    proposals = {row["proposal_id"]: row for row in fixture["proposals"]}
    decisions, intents = defaultdict(list), {}
    for transition in fixture["transitions"]:
        before, after = transition["before"], transition["after"]
        cycle_id = before["cycle_id"] or after["cycle_id"]
        require(cycle_id in cycles and (not before["cycle_id"] or not after["cycle_id"]
                or before["cycle_id"] == after["cycle_id"]), transition["decision_id"])
        trace = trace_transition(transition, proposals, fixture["evaluations"], bars)
        decisions[cycle_id].append(trace)
        intents[cycle_id, trace["known_at"]] = (
            trace,
            Counter((side, "OPEN" if Decimal(after[side]) == 1 else "CLOSE")
                    for side in SIDES if before[side] != after[side]),
        )

    positions, operations_by_cycle = {}, defaultdict(list)
    multiplier, tick = Decimal(frozen["multiplier"]), Decimal(frozen["tick"])
    for operation_index, raw in enumerate(reference["fills"], start=1):
        cycle_id, side, offset = raw["cycle_id"], raw["side"], raw["offset"]
        trace, expected = intents[cycle_id, raw["decision_known_at"]]
        require(raw["contract"] == contract and raw["hypothetical"] is True
                and datetime.fromisoformat(raw["at"]) > datetime.fromisoformat(raw["decision_known_at"])
                and expected[side, offset] > 0, (contract, operation_index, "operation identity"))
        expected[side, offset] -= 1
        position = cycle_id, side
        price = Decimal(raw["reference_price"])
        if offset == "OPEN":
            require(position not in positions, (contract, operation_index, "duplicate leg"))
            positions[position] = price
            gross = Decimal(0)
        else:
            gross = (price - positions.pop(position)) * multiplier * (1 if side == "long" else -1)
        fee, slippage = Decimal(raw["fee"]), Decimal(raw["slippage_cost"])
        require(gross == Decimal(raw["gross_pnl"]) and fee == Decimal(3) and slippage == tick * multiplier,
                (contract, operation_index, "P&L or cost"))
        operations_by_cycle[cycle_id].append(dict(
            contract=contract, cycle_id=cycle_id, operation_index=operation_index, trading_day=raw["trading_day"],
            side=side, leg="ORIGINAL" if side == cycles[cycle_id]["side"] else "PROTECTION",
            offset=offset, units=1, reference_at=raw["at"], reference_price=price, decision_at=trace["known_at"],
            decision_id=trace["decision_id"], proposal_id=trace["proposal_id"],
            decision_bar_end=trace["bar_end"], plan_id=trace["plan"]["plan_id"],
            action=trace["action"], reason=trace["reason"], gross=gross, fees=fee, slippage=slippage,
            cost=fee + slippage, net=gross - fee - slippage,
        ))
    require(not positions and all(not any(expected.values()) for _, expected in intents.values()),
            (contract, "unpaired operations or decisions"))

    rows = []
    for cycle_id, frozen_cycle in cycles.items():
        entry, *middle, exit_trace = decisions[cycle_id]
        operations = operations_by_cycle[cycle_id]
        first, last = operations[0], operations[-1]
        total = {metric: sum(op[metric] for op in operations) for metric in METRICS}
        require(
            first["reference_at"] == frozen_cycle["entry_at"] and last["reference_at"] == frozen_cycle["exit_at"]
            and first["side"] == frozen_cycle["side"]
            and all(total[metric] == Decimal(frozen_cycle[metric]) for metric in ("gross", "cost", "net"))
            and entry["reason"] == "FRESH_PLAN_KEYBAR" and exit_trace["action"] == "CLEAR"
            and all(trace["action"] == "LOCK" for trace in middle),
            (contract, cycle_id, "cycle reconciliation"),
        )
        require(entry["plan"] == exit_trace["plan"], (contract, cycle_id, "plan identity"))
        region_lower, region_upper = Decimal(entry["lower"]), Decimal(entry["upper"])
        long = first["side"] == "long"
        entry_condition = (
            "RANGE_LOWER_HALF_CONFIRMED_INSIDE" if long else "RANGE_UPPER_HALF_CONFIRMED_INSIDE"
        ) if entry["environment"] == "RANGE" else (
            "UP_UPPER_HALF_CONFIRMED_ABOVE" if long else "DOWN_LOWER_HALF_CONFIRMED_BELOW"
        )
        lock = middle[0] if middle else None
        require(len(middle) <= 1, (contract, cycle_id, "lock count"))
        protection = [op for op in operations if op["leg"] == "PROTECTION"]
        elapsed = datetime.fromisoformat(last["reference_at"]) - datetime.fromisoformat(first["reference_at"])
        rows.append(dict(
            contract=contract, cycle_id=cycle_id, side=first["side"], entry_trading_day=first["trading_day"],
            entry_environment=entry["environment"], entry_condition=entry_condition, entry_reason=entry["reason"],
            plan_id=entry["plan"]["plan_id"], entry_ibar=entry["ibar"], entry_pinbar=entry["pinbar"],
            entry_context_hash=entry["context_hash"],
            entry_lower=region_lower, entry_upper=region_upper, entry_signal_bar_end=entry["signal_bar_end"],
            entry_signal_high=entry["signal_high"], entry_signal_low=entry["signal_low"],
            entry_confirm_bar_end=entry["bar_end"], entry_confirm_close=entry["close"],
            entry_decision_at=entry["known_at"], entry_decision_id=entry["decision_id"],
            entry_reference_at=first["reference_at"], entry_reference_price=first["reference_price"],
            lock_reason=lock["reason"] if lock else None, lock_signal_bar_end=lock["signal_bar_end"] if lock else None,
            lock_confirm_bar_end=lock["bar_end"] if lock else None, lock_close=lock["close"] if lock else None,
            lock_decision_at=lock["known_at"] if lock else None,
            exit_reason=exit_trace["reason"], exit_environment=exit_trace["environment"],
            exit_confirm_bar_end=exit_trace["bar_end"], exit_confirm_close=exit_trace["close"],
            exit_decision_at=exit_trace["known_at"], exit_decision_id=exit_trace["decision_id"],
            exit_trading_day=last["trading_day"], exit_reference_at=last["reference_at"],
            exit_reference_price=last["reference_price"], held_signal_bars=exit_trace["index"] - entry["index"],
            held_wall_minutes=elapsed // timedelta(minutes=1), operations=len(operations),
            protection_operations=len(protection),
            **{f"protection_{metric}": sum(op[metric] for op in protection) for metric in METRICS},
            **total,
        ))

    for metric, key in (("gross", "realized_gross"), ("fees", "fees"),
                        ("slippage", "slippage_cost"), ("net", "net_pnl")):
        require(sum(row[metric] for row in rows) == Decimal(reference[key]), (contract, metric, "subtotal"))
    require(not reference["open_legs"] and Decimal(reference["unrealized"]) == 0, (contract, "terminal"))
    return rows, [item for group in operations_by_cycle.values() for item in group]


def summarize(cycles):
    return dict(
        cycles=len(cycles), operations=sum(row["operations"] for row in cycles),
        locked_cycles=sum(row["protection_operations"] > 0 for row in cycles),
        net_losses=sum(row["net"] < 0 for row in cycles),
        gross_wins_removed_by_cost=sum(row["gross"] > 0 and row["net"] <= 0 for row in cycles),
        aggregate_net_losses=sum(row["net"] for row in cycles if row["net"] < 0),
        **{metric: sum(row[metric] for row in cycles) for metric in METRICS},
    )


def breakdown(cycles, field, second=None):
    grouped = defaultdict(list)
    for row in cycles:
        label = row[field] if second is None else f"{row[field]} / {row[second]}"
        grouped[label].append(row)
    return {label: summarize(rows) for label, rows in grouped.items()}


def export(path, rows):
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("env-file", "report", "coverage", "output"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists() or args.output.is_symlink():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    require(RULE_HASH == FROZEN_RULE and all(sha(Path(path).read_bytes()) == digest
            for path, digest in FROZEN_CODE.items()), "original code and rule")
    report, coverage = verified_json(args.report, REPORT_SHA), verified_json(args.coverage, COVERAGE_SHA)
    require(report["base"] == BASE and report["execution_version"] == EXECUTION_VERSION
            and report["rule_hash"] == FROZEN_RULE and report["input_coverage_sha256"] == COVERAGE_SHA
            and report["code_hashes"] == FROZEN_CODE and report["executable"] is False
            and report["trading_days"] == [day.isoformat() for day in DAYS]
            and set(report["candidate_results"]) == set(coverage["contracts"]), "report provenance")

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    cycles, operations = [], []
    for contract, frozen in report["candidate_results"].items():
        bars, fixture = market_contract(SessionLocal, contract, coverage["contracts"][contract], frozen)
        contract_cycles, contract_operations = reconcile(contract, frozen, bars, fixture)
        cycles.extend(contract_cycles)
        operations.extend(contract_operations)
    total = summarize(cycles)
    require((total["cycles"], len(operations), total["operations"], total["gross"],
             total["fees"], total["slippage"], total["net"]) == (42, 90, 90, -460, 270, 1730, -2460),
            "portfolio totals")
    require(len({row["cycle_id"] for row in cycles}) == len(cycles), "cycle uniqueness")

    summary = dict(
        source_report_sha256=REPORT_SHA, coverage_sha256=COVERAGE_SHA, rule_hash=RULE_HASH,
        code_hashes=FROZEN_CODE, execution_version=EXECUTION_VERSION,
        author_action_samples=report["author_action_samples"], trading_days=report["trading_days"],
        reference_only=True, total=total, operations_per_leg=Counter(row["leg"] for row in operations),
        protection={metric: sum(row[f"protection_{metric}"] for row in cycles) for metric in METRICS},
        by_contract={contract: summarize([row for row in cycles if row["contract"] == contract])
                     for contract in report["candidate_results"]},
        by_entry_environment=breakdown(cycles, "entry_environment"),
        by_entry_condition=breakdown(cycles, "entry_condition"),
        by_exit=breakdown(cycles, "exit_reason"),
        by_environment_and_exit=breakdown(cycles, "entry_environment", "exit_reason"),
        by_contract_and_exit=breakdown(cycles, "contract", "exit_reason"),
        by_entry_trading_day=breakdown(cycles, "entry_trading_day"),
        by_holding_bars={
            "at_most_3": summarize([row for row in cycles if row["held_signal_bars"] <= 3]),
            "more_than_3": summarize([row for row in cycles if row["held_signal_bars"] > 3]),
        },
    )
    args.output.mkdir()
    export(args.output / "cycles.csv", sorted(cycles, key=lambda row: (row["entry_reference_at"], row["contract"])))
    export(args.output / "operations.csv", sorted(operations, key=lambda row: (row["contract"], row["operation_index"])))
    with (args.output / "summary.json").open("x", encoding="utf-8") as output:
        output.write(encoded(summary))


if __name__ == "__main__":
    main()

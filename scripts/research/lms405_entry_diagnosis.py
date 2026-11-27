"""Classify A and B baseline reference cycles using only their frozen samples."""

import argparse
import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from guiyi_quant import lms_near405 as kernel
from guiyi_quant.lms405 import Bar
from lms405_holdout_loss_diagnosis import REPORT_SHA as A_SHA
from lms405_holdout_replay import FROZEN_CODE, FROZEN_RULE, US
from lms405_original_leg_study import verified_json
from lms405_regime_confirmation_study import SEAL, SEAL_SHA
from lms405_replay import ohlc, read_session_series
from lms_near405_backtest import EXECUTION_VERSION
from lms_near405_replay import encoded, sha

B_SHA = "b760158c55d8747726bfbae3dbeef0e7cbf46bb587172a1a407f7a0173016e1c"
A_CSV = Path("docs/research/lms405/evidence/p5-holdout-loss-cycles-20261116.csv")
A_CSV_SHA = "6d46c38905e738a9a3fe0af827536c3b90e33aaa87d9878006805358a3071bdc"
FIVE = timedelta(minutes=5)
SHANGHAI = ZoneInfo("Asia/Shanghai")
ZERO = Decimal(0)
METRICS = ("gross", "fee", "slippage", "net")
GROUPS = ("TREND_LONG", "TREND_SHORT", "RANGE_LONG", "RANGE_SHORT")
CLASS = {("UP", "long"): "TREND_LONG", ("DOWN", "short"): "TREND_SHORT",
         ("RANGE", "long"): "RANGE_LONG", ("RANGE", "short"): "RANGE_SHORT"}


def require(valid, location):
    if not valid:
        raise ValueError(f"ENTRY_DIAGNOSIS_MISMATCH: {location}")


def read_b_trace(session_factory, contract, days, expected):
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service

    with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
        series = read_session_series(session, build_market_data_service(session),
                                     contract[:-4].lower(), contract, "5m", FIVE, days)
    payload = [(bar.trading_day, bar.bar_end, *ohlc(bar), bar.volume) for bar in series]
    require(len(series) == expected["bars"] and sha(encoded(payload).encode()) == expected["sha256"],
            (contract, days[0], "frozen B 5m input"))
    bars = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in series]
    replay = kernel.replay(bars, as_of=bars[-1].end + 3 * US, timely_fixture=True)
    return replay["transitions"], {bar.end.isoformat(): bar.close for bar in bars}, bars[-1]


def decimal_sum(rows, field):
    return sum((Decimal(r[field]) for r in rows), ZERO)


def gross_on_close(row, opened, multiplier):
    direction = 1 if row["side"] == "long" else -1
    return (Decimal(row["reference_price"]) - Decimal(opened["reference_price"])) * multiplier * direction


def ledger(batch, window, contract, fills, transitions, multiplier, tick, closes, end_mark):
    decisions = {row["known_at"]: row for row in transitions}
    entries = {row["after"]["cycle_id"]: row for row in transitions
               if row["action"].startswith(("ENTER_", "REENTER_"))}
    cycles = defaultdict(list)
    inventory = {}
    last_at = None
    for number, row in enumerate(fills, 1):
        decision = decisions[row["decision_known_at"]]
        at, known = datetime.fromisoformat(row["at"]), datetime.fromisoformat(decision["known_at"])
        side, cycle, offset = row["side"], row["cycle_id"], row["offset"]
        require(row["contract"] == contract and row["hypothetical"] is True and known < at
                and (last_at is None or last_at <= at) and decision["record_kind"] == "TEST_FIXTURE",
                (batch, window, contract, number, "reference operation identity"))
        require(cycle in (decision["before"]["cycle_id"], decision["after"]["cycle_id"])
                and Decimal(decision["after"][side]) == (1 if offset == "OPEN" else 0),
                (batch, window, contract, number, "decision position"))
        if batch == "B":
            require(all(row[key] == decision[key] for key in ("action", "reason", "decision_id", "proposal_id")),
                    (batch, window, contract, number, "original B baseline decision"))
        if offset == "OPEN":
            require(side not in inventory, (batch, window, contract, number, "duplicate opening"))
            inventory[side] = row
            gross = ZERO
        else:
            require(offset == "CLOSE" and inventory[side]["cycle_id"] == cycle,
                    (batch, window, contract, number, "unpaired closing"))
            gross = gross_on_close(row, inventory.pop(side), multiplier)
        require(gross == Decimal(row["gross_pnl"]) and Decimal(row["fee"]) == 3
                and Decimal(row["slippage_cost"]) == tick * multiplier,
                (batch, window, contract, number, "reference operation arithmetic"))
        cycles[cycle].append(row)
        last_at = at

    closed, terminal = [], []
    for cycle, operations in cycles.items():
        decision = entries[cycle]
        plan = decision["after"]["plan"]
        side = decision["after"]["original_side"].lower()
        first = next(row for row in operations if row["offset"] == "OPEN" and row["side"] == side)
        last = operations[-1]
        still_held = {s: row for s, row in inventory.items() if row["cycle_id"] == cycle}
        gross, fee, slippage = (decimal_sum(operations, f) for f in ("gross_pnl", "fee", "slippage_cost"))
        confirm_at = (datetime.fromisoformat(decision["known_at"]) - 2 * US).isoformat()
        day_hour = datetime.fromisoformat(confirm_at).astimezone(SHANGHAI).hour
        base = dict(
            batch=batch, window=window, contract=contract, product=contract[:-4], cycle_id=cycle,
            entry_class=CLASS[plan["environment"], side], original_side=side, environment=plan["environment"],
            entry_reason=decision["reason"], entry_decision_id=decision["decision_id"],
            entry_proposal_id=decision["proposal_id"], plan_id=plan["plan_id"],
            confirm_at=confirm_at, confirm_close=closes[confirm_at], lower=plan["lower"], upper=plan["upper"],
            entry_session="NIGHT" if day_hour >= 21 or day_hour < 6 else "DAY",
            entry_at=first["at"], entry_trading_day=first["trading_day"], entry_price=first["reference_price"],
            operations=len(operations), protection_operations=sum(op["side"] != side for op in operations),
        )
        if still_held:
            require(end_mark is not None, (batch, window, contract, cycle, "terminal mark"))
            mark_at, close = end_mark
            unrealized = sum((gross_on_close(dict(side=s, reference_price=close), row, multiplier)
                              for s, row in still_held.items()), ZERO)
            terminal.append(base | dict(
                mark_at=mark_at, mark_price=close, legs=encoded(
                    {s: row["reference_price"] for s, row in still_held.items()},
                ).strip().replace("\n", ""), realized_gross=gross, mtm=unrealized, fee=fee, slippage=slippage,
                realized_net=gross - fee - slippage, total_net=gross + unrealized - fee - slippage,
            ))
            continue
        require(last["offset"] == "CLOSE", (batch, window, contract, cycle, "closed cycle"))
        end = datetime.fromisoformat(last["at"])
        start = datetime.fromisoformat(first["at"])
        final_decision = decisions[last["decision_known_at"]]
        cross_trading_day = first["trading_day"] != last["trading_day"]
        cross_calendar_day = start.astimezone(SHANGHAI).date() != end.astimezone(SHANGHAI).date()
        net = gross - fee - slippage
        closed.append(base | dict(
            exit_reason=final_decision["reason"], exit_decision_id=final_decision["decision_id"],
            exit_at=last["at"], exit_trading_day=last["trading_day"], exit_price=last["reference_price"],
            held_minutes=(end - start) // timedelta(minutes=1),
            cross_trading_day=cross_trading_day, cross_calendar_day=cross_calendar_day,
            cross_either_day=cross_trading_day or cross_calendar_day,
            gross=gross, fee=fee, slippage=slippage, cost=fee + slippage, net=net,
            gross_loss=gross < 0, gross_profit_erased=gross > 0 and net <= 0,
        ))
    return closed, terminal


def subtotal(rows):
    return {field: decimal_sum(rows, field) for field in METRICS}


def reconcile_scope(key, closed, terminal, expected):
    values = dict(
        closed_cycles=len(closed), operations=sum(r["operations"] for r in closed + terminal),
        realized_gross=decimal_sum(closed, "gross") + decimal_sum(terminal, "realized_gross"),
        unrealized=decimal_sum(terminal, "mtm"),
        fee=decimal_sum(closed + terminal, "fee"), slippage=decimal_sum(closed + terminal, "slippage"),
        net=decimal_sum(closed, "net") + decimal_sum(terminal, "total_net"),
    )
    require(all(value == Decimal(expected[field]) for field, value in values.items()), (key, values))
    return values


def batch_a(report):
    with A_CSV.open(encoding="utf-8", newline="") as source:
        primary = {r["cycle_id"]: r for r in csv.DictReader(source)}
    require(sha(A_CSV.read_bytes()) == A_CSV_SHA, "frozen A cycle detail")
    results = []
    for contract, item in report["candidate_results"].items():
        source = item["reference"]["fee3_tick1"]
        frame_closes = {r["entry_confirm_bar_end"]: Decimal(r["entry_confirm_close"])
                        for r in primary.values() if r["contract"] == contract}
        closed, terminal = ledger(
            "A", "nov16", contract, source["fills"], item["fixture_transitions"], Decimal(item["multiplier"]),
            Decimal(item["tick"]), frame_closes, None,
        )
        expected = {f: source[f] for f in ("realized_gross", "unrealized")}
        expected |= dict(closed_cycles=len(source["closed_cycles"]), operations=len(source["fills"]),
                         fee=source["fees"], slippage=source["slippage_cost"], net=source["net_pnl"])
        reconcile_scope(("A", contract), closed, terminal, expected)
        for row in closed:
            anchor = primary.pop(row["cycle_id"])
            require(row["entry_decision_id"] == anchor["entry_decision_id"] and row["environment"] == anchor["entry_environment"]
                    and row["exit_decision_id"] == anchor["exit_decision_id"]
                    and all(row[field] == Decimal(anchor[field]) for field in ("gross", "slippage", "net"))
                    and row["fee"] == Decimal(anchor["fees"]),
                    (row["cycle_id"], "frozen A cycle detail join"))
        results.extend(closed)
    require(not primary, "A cycle detail coverage")
    return results


def batch_b(report, seal, session_factory):
    days_by_window = {r["id"]: tuple(map(date.fromisoformat, r["trading_days"])) for r in seal["windows"]}
    source_scope = {(w["id"], c) for w in seal["windows"] for c in w["contracts"]}
    coverage = {(r["window"], r["contract"]): r for r in report["coverage"]}
    totals = {(r["window"], r["contract"]): r["baseline"] for r in report["path_windows"]
              if r["scenario"] == "fee3_tick1"}
    require(set(coverage) == set(totals) == source_scope, "frozen B contract windows")
    fills = defaultdict(list)
    for row in report["operation_ledger"]:
        if row["path"] == "baseline":
            fills[row["window"], row["contract"]].append(row)
    require(set(fills) <= source_scope, "frozen B operation windows")
    all_closed, all_terminal = [], []
    for (window, contract), item in coverage.items():
        require(item["status"] == "EXACT_SESSION_AND_OHLCV", (window, contract, "frozen B availability"))
        decisions, closes, mark = read_b_trace(session_factory, contract, days_by_window[window], item["inputs"]["5m"])
        spec = item["spec"]
        closed, terminal = ledger(
            "B", window, contract, fills[window, contract], decisions, Decimal(spec["multiplier"]),
            Decimal(spec["tick"]), closes, (mark.end.isoformat(), mark.close),
        )
        expected = totals[window, contract]
        reconcile_scope(("B", window, contract), closed, terminal, expected)
        marked = [row["legs"] for row in terminal]
        require(marked == ([encoded(expected["open_legs"]).strip().replace("\n", "")]
                           if expected["open_legs"] else []),
                (window, contract, "terminal leg identity"))
        all_closed.extend(closed)
        all_terminal.extend(terminal)
    return all_closed, all_terminal


def summarize(rows):
    metrics = subtotal(rows)
    cost = metrics["fee"] + metrics["slippage"]
    count = len(rows)
    return dict(count=count, **metrics, cost=cost,
                averages={key: value / count if count else None for key, value in (metrics | {"cost": cost}).items()},
                gross_loss=sum(r["gross_loss"] for r in rows),
                gross_profit_erased=sum(r["gross_profit_erased"] for r in rows),
                net_loss=sum(r["net"] < 0 for r in rows))


def group(rows, field):
    cohorts = defaultdict(list)
    for row in rows:
        cohorts[str(row[field])].append(row)
    return {key: summarize(values) for key, values in sorted(cohorts.items())}


def diagnose(rows):
    range_shorts = [r for r in rows if r["entry_class"] == "RANGE_SHORT"]
    worst = min(range_shorts, key=lambda r: (r["net"], r["cycle_id"]), default=None)
    return dict(
        total=summarize(rows),
        by_entry={name: summarize([r for r in rows if r["entry_class"] == name]) for name in GROUPS},
        range_short=dict(
            counts=summarize(range_shorts), by_product=group(range_shorts, "product"),
            by_contract=group(range_shorts, "contract"), by_window=group(range_shorts, "window"),
            by_entry_day=group(range_shorts, "entry_trading_day"), by_exit=group(range_shorts, "exit_reason"),
            by_trade_day_change=group(range_shorts, "cross_trading_day"),
            by_calendar_day_change=group(range_shorts, "cross_calendar_day"),
            by_either_day_change=group(range_shorts, "cross_either_day"),
            by_entry_session=group(range_shorts, "entry_session"),
            worst=worst, without_worst=summarize([r for r in range_shorts if r is not worst]),
        ),
    )


def save_csv(path, rows):
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("env-file", "a-report", "b-report", "output"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists() or args.output.is_symlink():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    require(kernel.RULE_HASH == FROZEN_RULE and all(sha(Path(p).read_bytes()) == digest
            for p, digest in FROZEN_CODE.items()), "frozen strategy and original reference executor")
    a, b = verified_json(args.a_report, A_SHA), verified_json(args.b_report, B_SHA)
    seal = verified_json(SEAL, SEAL_SHA)
    require(a["rule_hash"] == b["baseline_rule_sha256"] == FROZEN_RULE
            and a["execution_version"] == b["executor"] == EXECUTION_VERSION
            and a["executable"] is b["executable"] is False and b["seal_sha256"] == SEAL_SHA,
            "frozen A and B baseline identities")

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    closed_a = batch_a(a)
    closed_b, terminal = batch_b(b, seal, SessionLocal)
    require(len(closed_a) == 42 and len(closed_b) == 81 and len(terminal) == 2, "sample denominators")
    report = dict(
        source_sha256={"A": A_SHA, "A_detail": A_CSV_SHA, "B": B_SHA, "B_seal": SEAL_SHA},
        rule_sha256=FROZEN_RULE, executor=EXECUTION_VERSION, scenario="fee3_tick1",
        a=diagnose(closed_a), b=diagnose(closed_b),
        b_terminal={field: decimal_sum(terminal, field)
                    for field in ("realized_gross", "mtm", "fee", "slippage", "realized_net", "total_net")},
        b_all_net=decimal_sum(closed_b, "net") + decimal_sum(terminal, "total_net"),
    )
    require(report["a"]["total"]["net"] == -2460 and report["b_all_net"] == -1549, "published net totals")
    args.output.mkdir()
    save_csv(args.output / "closed-cycles.csv", sorted(closed_a + closed_b, key=lambda r: (r["batch"], r["entry_at"],
                                                                                       r["contract"])))
    save_csv(args.output / "b-terminal.csv", terminal)
    with (args.output / "summary.json").open("x", encoding="utf-8") as output:
        output.write(encoded(report))


if __name__ == "__main__":
    main()

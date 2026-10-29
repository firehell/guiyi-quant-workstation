"""Offline, hypothetical one-unit reference execution; not Paper/Broker facts."""

import argparse
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
import hashlib
import json
from guiyi_quant.lms405 import Bar, timestamp
from guiyi_quant.lms_near405 import replay, VERSION, RULE_HASH

EXECUTION_VERSION = "lms-near405-reference-execution-v1"
SCENARIOS = {
    "gross_reference": (D(0), 0),
    "fee3_tick1": (D(3), 1),
    "fee3_tick2": (D(3), 2),
}


def time(value):
    t = datetime.fromisoformat(value)
    timestamp(t)
    return t


def encoded(v):
    return (
        json.dumps(v, default=str, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def execute_reference(minutes, transitions, multiplier, tick, fee, slippage_ticks):
    """Track separate hypothetical legs toward confirmed research targets.

    Minute start must be strictly after decision knowledge. The latest historical
    minute available strictly before start provides a liquidity proxy only.
    Current-minute volume/shape never filters a prior opening reference. No
    terminal liquidation or synthetic cross-contract carry is created.
    """
    if not minutes:
        raise ValueError("MINUTE_DATA_REQUIRED")
    for v in (multiplier, tick, fee):
        if not isinstance(v, D) or not v.is_finite() or v < 0:
            raise ValueError("INVALID_COST")
    if (
        multiplier <= 0
        or tick <= 0
        or type(slippage_ticks) is not int
        or slippage_ticks < 0
    ):
        raise ValueError("INVALID_COST")
    contract = minutes[0]["contract"]
    last = None
    for b in minutes:
        if b["contract"] != contract:
            raise ValueError("CONTRACT_BOUNDARY")
        end = time(b["bar_end"])
        Bar(
            contract,
            end,
            *(D(b[k]) for k in ("open", "high", "low", "close")),
            start=end - timedelta(minutes=1),
        )
        if last is not None and end <= last:
            raise ValueError("MINUTE_ORDER")
        if not D(b["volume"]).is_finite() or D(b["volume"]) < 0:
            raise ValueError("INVALID_VOLUME")
        last = end
    intents = sorted(transitions, key=lambda t: time(t["known_at"]))
    if len({time(t["known_at"]) for t in intents}) != len(intents):
        raise ValueError("SAME_TIME_INTENT_CONFLICT")
    for t in intents:
        if any(D(t["after"][k]) not in (D(0), D(1)) for k in ("long", "short")):
            raise ValueError("UNIT_TARGET_REQUIRED")
        if (
            any(D(t["after"][k]) for k in ("long", "short"))
            and not t["after"]["cycle_id"]
        ):
            raise ValueError("CYCLE_REQUIRED")
    legs = {}
    target = {"long": "0", "short": "0", "cycle_id": None}
    active = None
    realized = fees = slippage = D(0)
    fills = []
    closed = []
    curve = []
    blocked = Counter()
    cursor = 0
    superseded = 0
    peak = drawdown = D(0)
    intent = None
    liquidity_cursor = -1
    for b in minutes:
        start = time(b["bar_end"]) - timedelta(minutes=1)
        while cursor < len(intents) and time(intents[cursor]["known_at"]) < start:
            if intent is not None and any(
                int(k in legs) != int(target[k]) for k in ("long", "short")
            ):
                superseded += 1
            intent = intents[cursor]
            target = intent["after"]
            cursor += 1
        while (
            liquidity_cursor + 1 < len(minutes)
            and time(minutes[liquidity_cursor + 1]["bar_end"])
            + timedelta(microseconds=1)
            < start
        ):
            liquidity_cursor += 1
        liquidity = minutes[liquidity_cursor] if liquidity_cursor >= 0 else None
        pending = any(int(k in legs) != int(target[k]) for k in ("long", "short"))
        if active and target["cycle_id"] and target["cycle_id"] != active["cycle_id"]:
            raise ValueError("NEW_CYCLE_WHILE_EXECUTION_NOT_FLAT")
        if pending:
            reason = (
                "LIQUIDITY_PREIMAGE_MISSING"
                if liquidity is None
                else "ZERO_VOLUME"
                if D(liquidity["volume"]) == 0
                else "ONE_PRICE_BAR"
                if D(liquidity["high"]) == D(liquidity["low"])
                else None
            )
            if reason:
                blocked[reason] += 1
            else:
                price = D(b["open"])
                # Close legs before opening a new leg; every unit pays its own cost.
                for side in ("long", "short"):
                    if side in legs and not int(target[side]):
                        entry = legs.pop(side)
                        gain = (
                            (price - entry) * (1 if side == "long" else -1) * multiplier
                        )
                        cost = fee + tick * slippage_ticks * multiplier
                        realized += gain
                        fees += fee
                        slippage += cost - fee
                        active["gross"] += gain
                        active["cost"] += cost
                        fills.append(
                            dict(
                                at=start.isoformat(),
                                decision_known_at=intent["known_at"],
                                cycle_id=active["cycle_id"],
                                side=side,
                                offset="CLOSE",
                                reference_price=str(price),
                                gross_pnl=str(gain),
                                fee=str(fee),
                                slippage_cost=str(cost - fee),
                                trading_day=b["trading_day"],
                                contract=contract,
                                hypothetical=True,
                            )
                        )
                if active and not legs:
                    closed.append(
                        active
                        | dict(
                            exit_at=start.isoformat(),
                            net=active["gross"] - active["cost"],
                        )
                    )
                    active = None
                for side in ("long", "short"):
                    if side not in legs and int(target[side]):
                        if active is None:
                            active = dict(
                                cycle_id=target["cycle_id"],
                                side=side,
                                entry_at=start.isoformat(),
                                gross=D(0),
                                cost=D(0),
                            )
                        cost = fee + tick * slippage_ticks * multiplier
                        legs[side] = price
                        fees += fee
                        slippage += cost - fee
                        active["cost"] += cost
                        fills.append(
                            dict(
                                at=start.isoformat(),
                                decision_known_at=intent["known_at"],
                                cycle_id=active["cycle_id"],
                                side=side,
                                offset="OPEN",
                                reference_price=str(price),
                                gross_pnl="0",
                                fee=str(fee),
                                slippage_cost=str(cost - fee),
                                trading_day=b["trading_day"],
                                contract=contract,
                                hypothetical=True,
                            )
                        )
        close = D(b["close"])
        unrealized = sum(
            (
                (close - p) * (1 if k == "long" else -1) * multiplier
                for k, p in legs.items()
            ),
            D(0),
        )
        equity = realized + unrealized - fees - slippage
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        curve.append(
            dict(
                at=b["bar_end"],
                trading_day=b["trading_day"],
                pnl=str(equity),
                realized_gross=str(realized),
                unrealized=str(unrealized),
                fees=str(fees),
                slippage=str(slippage),
            )
        )
    return dict(
        execution_version=EXECUTION_VERSION,
        realized_gross=str(realized),
        unrealized=str(unrealized),
        fees=str(fees),
        slippage_cost=str(slippage),
        net_pnl=str(equity),
        max_drawdown=str(drawdown),
        fills=fills,
        closed_cycles=closed,
        open_legs={k: str(v) for k, v in legs.items()},
        open_cycle=active,
        blocked_counts=dict(blocked),
        superseded_intents=superseded,
        unobserved_execution_intents=len(intents) - cursor,
        unexecuted_intents=intents[cursor:],
        unreached_target=any(
            int(k in legs) != int(target[k]) for k in ("long", "short")
        ),
        curve=curve,
    )


def aggregate(results):
    cycles = [c for r in results for c in r["closed_cycles"]]
    wins = [D(c["net"]) for c in cycles if D(c["net"]) > 0]
    losses = [D(c["net"]) for c in cycles if D(c["net"]) < 0]
    positive = sum(wins, D(0))
    negative = -sum(losses, D(0))
    offset = D(0)
    curve = []
    peak = dd = D(0)
    monthly = Counter()
    prior = D(0)
    for r in results:
        for p in r["curve"]:
            value = offset + D(p["pnl"])
            peak = max(peak, value)
            dd = max(dd, peak - value)
            monthly[p["trading_day"][:7]] += value - prior
            prior = value
            curve.append(dict(at=p["at"], trading_day=p["trading_day"], pnl=str(value)))
        offset += D(r["net_pnl"])
    return dict(
        net_pnl=str(offset),
        realized_gross=str(sum((D(r["realized_gross"]) for r in results), D(0))),
        unrealized=str(sum((D(r["unrealized"]) for r in results), D(0))),
        fees=str(sum((D(r["fees"]) for r in results), D(0))),
        slippage_cost=str(sum((D(r["slippage_cost"]) for r in results), D(0))),
        closed_cycles=len(cycles),
        winning_cycles=len(wins),
        losing_cycles=len(losses),
        breakeven_cycles=len(cycles) - len(wins) - len(losses),
        win_rate=str(D(len(wins)) / len(cycles)) if cycles else None,
        profit_factor=str(positive / negative) if negative else None,
        average_win_loss_ratio=str((positive / len(wins)) / (negative / len(losses)))
        if wins and losses
        else None,
        max_drawdown=str(dd),
        monthly_pnl={m: str(v) for m, v in sorted(monthly.items())},
        hypothetical_fill_units=sum(len(r["fills"]) for r in results),
        curve=curve,
    )


def run(inputs, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    provenance = json.loads((inputs / "provenance.json").read_text())
    if provenance["status"] != "EXACT_LOCAL_SESSION_COVERAGE_VERIFIED":
        raise ValueError("SOURCE_COVERAGE_UNVERIFIED")
    source = {}
    for f in ("5m", "1m"):
        raw = (inputs / f"bars-{f}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != provenance["input_hashes"][f]:
            raise ValueError("INPUT_HASH_MISMATCH")
        source[f] = json.loads(raw)
    by_scenario = {s: [] for s in SCENARIOS}
    segments = []
    traces = []
    for seg in provenance["series"]["5m"]["segments"]:
        contract = seg["contract"]

        def select(f):
            return [
                b
                for b in source[f]
                if b["contract"] == contract
                and seg["start_trading_day"]
                <= b["trading_day"]
                <= seg["end_trading_day"]
            ]

        rows = select("5m")
        minutes = select("1m")
        bars = [
            Bar(
                contract,
                time(b["bar_end"]),
                *(D(b[k]) for k in ("open", "high", "low", "close")),
                start=time(b["bar_end"]) - timedelta(minutes=5),
            )
            for b in rows
        ]
        as_of = bars[-1].end + timedelta(microseconds=3)
        baseline = replay(bars, as_of=as_of)
        fixture = replay(bars, as_of=as_of, timely_fixture=True)
        row = seg | dict(
            bars_5m=len(rows),
            bars_1m=len(minutes),
            manual_proposals=len(baseline["proposals"]),
            manual_transitions=len(baseline["transitions"]),
            fixture_proposals=len(fixture["proposals"]),
            fixture_actions=dict(Counter(t["action"] for t in fixture["transitions"])),
            research_terminal=fixture["terminal_status"],
        )
        for name, (fee, ticks) in SCENARIOS.items():
            result = execute_reference(
                minutes,
                fixture["transitions"],
                D(provenance["multipliers"][contract]),
                D(2),
                fee,
                ticks,
            )
            result["contract"] = contract
            result["terminal_status"] = (
                "ROLLOVER_INTERRUPTED"
                if result["open_legs"]
                and seg != provenance["series"]["5m"]["segments"][-1]
                else "OPEN_AT_END"
                if result["open_legs"]
                else "FLAT"
            )
            by_scenario[name].append(result)
        segments.append(row)
        traces.append(
            dict(
                contract=contract,
                mode="TIMELY_TEST_FIXTURE",
                proposals=fixture["proposals"],
                transitions=fixture["transitions"],
            )
        )
    summary = dict(
        strategy_version=VERSION,
        rule_hash=RULE_HASH,
        execution_version=EXECUTION_VERSION,
        requested_window=[provenance["since"], provenance["through"]],
        input_hashes=provenance["input_hashes"],
        provenance_sha256=hashlib.sha256(
            (inputs / "provenance.json").read_bytes()
        ).hexdigest(),
        segments=segments,
        assumptions=dict(
            multiplier=5,
            tick=2,
            fee_per_side_assumed=3,
            slippage_ticks=[0, 1, 2],
            fill_time="FIRST_1M_START_STRICTLY_AFTER_KNOWN_AT",
            fee_history_verified=False,
            limit_history_verified=False,
            account_return=None,
            executable=False,
        ),
        code_hashes={
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in [
                "packages/quant-core/guiyi_quant/lms_near405.py",
                "scripts/research/lms_near405_backtest.py",
            ]
        },
        results={},
    )
    for name, results in by_scenario.items():
        full = aggregate(results)
        summary["results"][name] = {k: v for k, v in full.items() if k != "curve"}
        summary["results"][name]["by_contract"] = [
            {
                k: r[k]
                for k in (
                    "contract",
                    "net_pnl",
                    "realized_gross",
                    "unrealized",
                    "open_legs",
                    "terminal_status",
                    "blocked_counts",
                    "unobserved_execution_intents",
                    "superseded_intents",
                )
            }
            | {"closed_cycles": len(r["closed_cycles"])}
            for r in results
        ]
    output.mkdir(parents=True, exist_ok=False)
    (output / "INCOMPLETE").write_text("reference research in progress\n")
    (output / "decision-traces.json").write_text(encoded(traces))
    for name, results in by_scenario.items():
        (output / f"{name}.json").write_text(
            encoded(dict(segments=results, aggregate=aggregate(results)))
        )
    (output / "summary.json").write_text(encoded(summary))
    (output / "COMPLETE").write_text(
        hashlib.sha256((output / "summary.json").read_bytes()).hexdigest() + "\n"
    )
    (output / "INCOMPLETE").unlink()
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        r = run(a.inputs, a.output)
    except FileExistsError:
        print("OUTPUT_ALREADY_EXISTS")
        return 2
    except (ValueError, KeyError, TypeError, OSError):
        print("REFERENCE_BACKTEST_INPUT_OR_EXECUTION_UNVERIFIED")
        return 2
    print(encoded(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

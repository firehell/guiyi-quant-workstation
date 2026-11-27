"""Run the pre-registered LMS two-bar regime-exit experiment on local MDS."""

import argparse
import csv
import operator
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import FunctionType

from guiyi_quant import lms_near405 as kernel
from guiyi_quant.lms405 import Bar
from lms405_holdout_replay import CROSS_SPECS, FROZEN_CODE, FROZEN_RULE, US
from lms405_original_leg_study import verified_json
from lms405_replay import ohlc, read_session_series
from lms405_reversal_stage_bounds import SPECS_SHA
from lms405_sizing_audit import SPECS, positive_decimal
from lms_near405_backtest import EXECUTION_VERSION, SCENARIOS, execute_reference
from lms_near405_replay import encoded, sha

SEAL = Path("docs/research/lms405/evidence/regime-confirmation-b-seal.json")
SEAL_SHA = "533b6de21e44ebff13c9020106be064808bbe94c7a6069a2846672ff537065b0"
ONE = timedelta(minutes=1)
FIVE = timedelta(minutes=5)
ZERO = Decimal(0)
FIELDS = ("gross", "fee", "slippage", "net")
SIDES = ("long", "short")


def require(condition, location):
    if not condition:
        raise ValueError(f"STUDY_RECONCILIATION_FAILED: {location}")


def scoped_function(fn, **bindings):
    """Keep the imported kernel and its identities unmodified outside the experiment."""
    scoped = FunctionType(fn.__code__, fn.__globals__ | bindings, fn.__name__, fn.__defaults__, fn.__closure__)
    scoped.__kwdefaults__ = fn.__kwdefaults__
    return scoped


def confirmed_invalidation(state, bars, index, clock, omitted=None, *, activation=0):
    """Reuse the original exit precedence, filtering only opposing context."""
    opposing = "DOWN" if state["original_side"] == "LONG" else "UP"
    first_eligible = max(state["entry_index"] + 1, activation)

    def qualified_context(visible, j):
        frame = kernel.context(visible, j)
        if j < activation or not frame or frame["environment"] != opposing:
            return frame
        if j > first_eligible:
            preceding = kernel.context(visible, j - 1)
            if preceding and preceding["environment"] == opposing:
                return frame
        return None

    return scoped_function(kernel._invalid, context=qualified_context)(state, bars, index, clock, omitted)


def delayed_replay(bars, as_of, *, activation=0):
    def invalid(state, history, index, clock, omitted=None):
        return confirmed_invalidation(state, history, index, clock, omitted, activation=activation)

    evaluate = scoped_function(kernel._evaluate, _invalid=invalid)
    replay = scoped_function(kernel.replay, _evaluate=evaluate)
    # Always replay from the frozen flat seed. Kernel identifiers identify source
    # transitions; the surrounding report supplies the sealed variant identity.
    return replay(bars, as_of=as_of, timely_fixture=True)


def load_market(session_factory, contract, days):
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service

    with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
        market = build_market_data_service(session)
        raw_minute, raw_five = [
            read_session_series(session, market, contract[:-4].lower(), contract, f"{n}m",
                                timedelta(minutes=n), days)
            for n in (1, 5)
        ]
    if len(raw_minute) != 5 * len(raw_five):
        raise ValueError("AGGREGATION_COUNT_MISMATCH")
    for i, bar in enumerate(raw_five):
        group = raw_minute[i * 5 : (i + 1) * 5]
        if (
            [b.bar_end for b in group] != [bar.bar_end - ONE * offset for offset in (4, 3, 2, 1, 0)]
            or any(b.trading_day != bar.trading_day for b in group)
            or (group[0].open, max(b.high for b in group), min(b.low for b in group), group[-1].close,
                sum(b.volume for b in group)) != (*ohlc(bar), bar.volume)
        ):
            raise ValueError("AGGREGATION_OHLCV_OR_SESSION_MISMATCH")
    fingerprints = {
        k: dict(bars=len(raw), first=raw[0].bar_end, last=raw[-1].bar_end,
                sha256=sha(encoded([(b.trading_day, b.bar_end, *ohlc(b), b.volume) for b in raw]).encode()))
        for k, raw in (("1m", raw_minute), ("5m", raw_five))
    }
    bars = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw_five]
    minutes = [
        dict(contract=contract, trading_day=b.trading_day.isoformat(), bar_end=b.bar_end.isoformat(),
             open=str(b.open), high=str(b.high), low=str(b.low), close=str(b.close), volume=str(b.volume))
        for b in raw_minute
    ]
    return fingerprints, bars, minutes


def load_instrument_specs():
    sources = {contract: (Path(path), digest) for contract, (path, digest) in CROSS_SPECS.items()}
    manifest = verified_json(SPECS, SPECS_SHA)
    for archive in manifest["archives"]:
        for contract, digest in archive["contracts"].items():
            require(contract not in sources, (contract, "duplicate instrument source"))
            sources[contract] = Path(archive["root"], archive["directory"], f"{contract}-instrument.json"), digest
    specs, missing = {}, {}
    for contract, (path, digest) in sources.items():
        try:
            instrument = verified_json(path, digest)
            require(instrument["order_book_id"] == contract, (contract, "instrument identity"))
            specs[contract] = dict(multiplier=positive_decimal(instrument["contract_multiplier"]),
                                   tick=positive_decimal(instrument["tick_size"]), source_sha256=digest)
        except (OSError, ValueError, KeyError):
            missing[contract] = "FROZEN_CONTRACT_SPEC_UNAVAILABLE"
    return specs, missing


def run_execution(minutes, transitions, spec, scenario):
    return execute_reference(minutes, transitions, Decimal(spec["multiplier"]),
                             Decimal(spec["tick"]), *SCENARIOS[scenario])


def difference(new, old):
    return {field: new[field] - old[field] for field in FIELDS}


def balance(gross, fee, slippage):
    return dict(gross=gross, fee=fee, slippage=slippage, net=gross - fee - slippage)


def execution_balance(result):
    return balance(Decimal(result["realized_gross"]) + Decimal(result["unrealized"]),
                   Decimal(result["fees"]), Decimal(result["slippage_cost"]))


def holdings_at(fills, at):
    decision_time = datetime.fromisoformat(at)
    held = {}
    for fill in fills:
        if datetime.fromisoformat(fill["at"]) >= decision_time:
            break
        if fill["offset"] == "OPEN":
            held[fill["side"]] = fill
        else:
            held.pop(fill["side"])
    return held


def cycle_transitions(transitions, cycle):
    return [t for t in transitions if cycle in (t["before"]["cycle_id"], t["after"]["cycle_id"])]


def cycle_fills(result, cycle):
    return [f for f in result["fills"] if f["cycle_id"] == cycle]


def paired_events(window, contract, bars, minutes, spec, baseline, baseline_reference):
    proposals = {p["proposal_id"]: p for p in baseline["proposals"]}
    rows, traces = [], []
    for trigger in baseline["transitions"]:
        if trigger["reason"] != "REGIME_INVALID":
            continue
        state, at = trigger["before"], trigger["known_at"]
        cycle = state["cycle_id"]
        i = proposals[trigger["proposal_id"]]["index"]
        held = holdings_at(baseline_reference["fills"], at)
        expected_sides = {side for side in SIDES if Decimal(state[side]) == 1}
        preimage_matches = set(held) == expected_sides and all(f["cycle_id"] == cycle for f in held.values())
        scenarios = {name: None for name in SCENARIOS}
        row = dict(
            window=window, contract=contract, cycle_id=cycle, at=bars[i].end.isoformat(), known_at=at,
            direction=state["original_side"], long_before=state["long"], short_before=state["short"],
            long_reference=held.get("long", {}).get("reference_price"),
            short_reference=held.get("short", {}).get("reference_price"),
            next_bar=bars[i + 1].end.isoformat() if i + 1 < len(bars) else None,
            next_environment=baseline["evaluations"][i + 1]["environment"] if i + 1 < len(bars) else None,
            baseline_exit=trigger["reason"], candidate_exit=None, candidate_known_at=None,
            baseline_exit_reference=None, candidate_exit_reference=None,
            baseline_gross=None, baseline_cost=None, baseline_net=None,
            candidate_gross=None, candidate_cost=None, candidate_net=None,
            gross_delta=None, fee_delta=None, slippage_delta=None, cost_delta=None, net_delta=None,
            status="PREIMAGE_UNAVAILABLE",
        )
        if preimage_matches:
            fork = delayed_replay(bars, bars[-1].end + 3 * US, activation=i)
            fork_prefix = [t for t in fork["transitions"] if t["known_at"] < at]
            baseline_prefix = [t for t in baseline["transitions"] if t["known_at"] < at]
            require(fork_prefix == baseline_prefix, (window, contract, at, "pre-fork decisions"))
            old_cycle = cycle_transitions(baseline["transitions"], cycle)
            new_cycle = cycle_transitions(fork["transitions"], cycle)
            candidate_clear = next((t for t in new_cycle if t["action"] == "CLEAR"), None)
            if candidate_clear:
                row.update(candidate_exit=candidate_clear["reason"], candidate_known_at=candidate_clear["known_at"])
            for name in SCENARIOS:
                old = run_execution(minutes, old_cycle, spec, name)
                new = run_execution(minutes, new_cycle, spec, name)
                if name == "fee3_tick1":
                    require(old["fills"] == cycle_fills(baseline_reference, cycle), (window, contract, at, "base fills"))
                    require([f for f in new["fills"] if f["at"] < at] == [f for f in old["fills"] if f["at"] < at],
                            (window, contract, at, "pre-fork execution"))
                closed = len(old["closed_cycles"]) == len(new["closed_cycles"]) == 1
                old_balance, new_balance = execution_balance(old), execution_balance(new)
                scenarios[name] = dict(closed=closed, baseline=old_balance, candidate=new_balance,
                                       delta=difference(new_balance, old_balance))
                if name == "fee3_tick1":
                    delta = scenarios[name]["delta"]
                    row.update(status="SCORED" if closed else "TERMINAL_MARKED_UNSCORED",
                               baseline_exit_reference=old["closed_cycles"][0]["exit_at"] if old["closed_cycles"] else None,
                               candidate_exit_reference=new["closed_cycles"][0]["exit_at"] if new["closed_cycles"] else None,
                               baseline_gross=old_balance["gross"], baseline_cost=old_balance["fee"] + old_balance["slippage"],
                               baseline_net=old_balance["net"], candidate_gross=new_balance["gross"],
                               candidate_cost=new_balance["fee"] + new_balance["slippage"], candidate_net=new_balance["net"],
                               gross_delta=delta["gross"], fee_delta=delta["fee"], slippage_delta=delta["slippage"],
                               cost_delta=delta["fee"] + delta["slippage"], net_delta=delta["net"])
                    traces.append(dict(window=window, contract=contract, cycle=cycle, trigger=trigger,
                                       baseline_transitions=old_cycle, candidate_transitions=new_cycle,
                                       baseline_fills=old["fills"], candidate_fills=new["fills"]))
        rows.append(row | dict(scenarios=scenarios))
    return rows, traces


def operation_key(fill):
    return fill["side"], fill["offset"], Decimal(fill["reference_price"])


def curve_balance(point):
    if point is None:
        return balance(ZERO, ZERO, ZERO)
    result = balance(Decimal(point["realized_gross"]) + Decimal(point["unrealized"]),
                     Decimal(point["fees"]), Decimal(point["slippage"]))
    require(result["net"] == Decimal(point["pnl"]), point["at"])
    return result


def continuous_attribution(window, contract, baseline, candidate):
    results = {"baseline": baseline, "candidate": candidate}
    fills = defaultdict(lambda: defaultdict(list))
    held = {path: set() for path in results}
    for path, result in results.items():
        for fill in result["fills"]:
            fills[datetime.fromisoformat(fill["at"]) + ONE][path].append(fill)
    require(len(baseline["curve"]) == len(candidate["curve"]), (window, contract, "curve length"))
    prior = gap = balance(ZERO, ZERO, ZERO)
    segments, ledger = [], []
    active = None
    for old, new in zip(baseline["curve"], candidate["curve"], strict=True):
        require(old["at"] == new["at"], (window, contract, "curve time"))
        groups = fills.get(datetime.fromisoformat(old["at"]), {})
        common = Counter(map(operation_key, groups.get("baseline", ()))) & Counter(
            map(operation_key, groups.get("candidate", ()))
        )
        unequal = any(len(groups.get(path, ())) != sum(common.values()) for path in results)
        gap = difference(curve_balance(new), curve_balance(old))
        step = difference(gap, prior)
        prior = gap
        if active is None and unequal:
            active = dict(window=window, contract=contract, start=(datetime.fromisoformat(old["at"]) - ONE).isoformat(),
                          end=None, segment=len(segments) + 1, baseline_only=0, candidate_only=0, common=0,
                          baseline_only_open=0, candidate_only_open=0, **balance(ZERO, ZERO, ZERO))
        if active is None:
            require(not any(step.values()), (window, contract, old["at"], "unattributed P&L"))
        else:
            for field in FIELDS:
                active[field] += step[field]
            active["common"] += sum(common.values())
        for path in results:
            matched = common.copy()
            for fill in groups.get(path, ()):
                key = operation_key(fill)
                shared = matched[key] > 0
                if shared:
                    matched[key] -= 1
                else:
                    active[f"{path}_only"] += 1
                    active[f"{path}_only_open"] += fill["offset"] == "OPEN"
                if fill["offset"] == "OPEN":
                    require(fill["side"] not in held[path], (window, contract, path, "duplicate open"))
                    held[path].add(fill["side"])
                else:
                    held[path].remove(fill["side"])
                ledger.append(dict(window=window, path=path, shared=shared,
                                   segment=active["segment"] if active else None, **fill))
        if active and not any(held.values()):
            segments.append(active | dict(end=old["at"], status="COMMON_FLAT"))
            active = None
    if active:
        segments.append(active | dict(end=baseline["curve"][-1]["at"], status="TERMINAL_MARKED"))
    require(len(ledger) == sum(len(r["fills"]) for r in results.values()), (window, contract, "operation ledger"))
    require({f: sum((row[f] for row in segments), ZERO) for f in FIELDS} == gap,
            (window, contract, "segment attribution"))
    require(gap == difference(execution_balance(candidate), execution_balance(baseline)), (window, contract, "net"))
    return segments, ledger


def summarize_delta(rows, net_field, order):
    values = [row[net_field] for row in rows]
    largest = min((row for row in rows if row[net_field] > 0),
                  key=lambda row: (-row[net_field], *order(row)), default=None)
    smallest = min(rows, key=lambda row: (row[net_field], *order(row)), default=None)
    return dict(count=len(rows), improved=sum(v > 0 for v in values), worsened=sum(v < 0 for v in values),
                tied=sum(v == 0 for v in values), net=sum(values, ZERO),
                net_without_largest=sum(values, ZERO) - (largest[net_field] if largest else ZERO),
                largest_positive=largest, smallest=smallest)


def breakdown(rows, dimension, fields):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[dimension]].append(row)
    return {key: dict(count=len(items), **{field: sum((r[field] for r in items), ZERO) for field in fields})
            for key, items in sorted(grouped.items())}


def compact_execution(result):
    return dict(**execution_balance(result), realized_gross=Decimal(result["realized_gross"]),
                unrealized=Decimal(result["unrealized"]), operations=len(result["fills"]),
                closed_cycles=len(result["closed_cycles"]), open_legs=result["open_legs"],
                blocked_counts=result["blocked_counts"], unobserved_intents=result["unobserved_execution_intents"],
                unreached_target=result["unreached_target"])


def label_operations(ledger, segments, baseline, candidate):
    decisions = {
        path: {row["known_at"]: row for row in replay["transitions"]}
        for path, replay in (("baseline", baseline), ("candidate", candidate))
    }
    exclusive_entries = Counter()
    for operation in ledger:
        path = operation["path"]
        decision = decisions[path][operation["decision_known_at"]]
        action = decision["action"]
        operation.update(action=action, reason=decision["reason"],
                         decision_id=decision["decision_id"], proposal_id=decision["proposal_id"])
        if not operation["shared"] and operation["offset"] == "OPEN":
            require(action.startswith(("ENTER_", "REENTER_")) or action == "LOCK",
                    (operation["window"], operation["contract"], decision["decision_id"], "open action"))
            original = operation["side"].upper() == decision["after"]["original_side"]
            leg = "original" if original else "protection"
            exclusive_entries[operation["segment"], path, leg] += 1
    for segment in segments:
        for path in decisions:
            for leg in ("original", "protection"):
                segment[f"{path}_only_{leg}_open"] = exclusive_entries[segment["segment"], path, leg]
            require(sum(segment[f"{path}_only_{leg}_open"] for leg in ("original", "protection"))
                    == segment[f"{path}_only_open"], (segment["window"], segment["contract"], segment["segment"]))


def study(session_factory, seal, specs, missing_specs):
    from app.market_data.market_data_service import MarketDataError

    coverage, pairs, pair_traces, segments, operation_ledger, continuous = [], [], [], [], [], []
    for window in seal["windows"]:
        days = tuple(map(date.fromisoformat, window["trading_days"]))
        for contract in window["contracts"]:
            key = dict(window=window["id"], contract=contract)
            if contract not in specs:
                reason = missing_specs.get(contract, "FROZEN_CONTRACT_SPEC_UNAVAILABLE")
                coverage.append(key | dict(status="DATA_INSUFFICIENT", reason=reason))
                continue
            try:
                inputs, bars, minutes = load_market(session_factory, contract, days)
            except MarketDataError as error:
                coverage.append(key | dict(status="DATA_INSUFFICIENT", reason=error.code))
                continue
            except ValueError as error:
                coverage.append(key | dict(status="DATA_INSUFFICIENT", reason=str(error)))
                continue
            spec = specs[contract]
            as_of = bars[-1].end + 3 * US
            base_replay = kernel.replay(bars, as_of=as_of, timely_fixture=True)
            experiment = delayed_replay(bars, as_of)
            try:
                execution = {
                    name: {path: run_execution(minutes, run["transitions"], spec, name)
                           for path, run in (("baseline", base_replay), ("candidate", experiment))}
                    for name in SCENARIOS
                }
            except ValueError as error:
                if str(error) != "NEW_CYCLE_WHILE_EXECUTION_NOT_FLAT":
                    raise
                coverage.append(key | dict(status="EXECUTION_INTERRUPTED", reason=str(error), inputs=inputs, spec=spec))
                continue
            coverage.append(key | dict(status="EXACT_SESSION_AND_OHLCV", inputs=inputs, spec=spec))
            primary = execution["fee3_tick1"]
            case_rows, case_traces = paired_events(**key, bars=bars, minutes=minutes, spec=spec,
                                                   baseline=base_replay, baseline_reference=primary["baseline"])
            case_segments, case_ledger = continuous_attribution(**key, **primary)
            label_operations(case_ledger, case_segments, base_replay, experiment)
            pairs.extend(case_rows)
            pair_traces.extend(case_traces)
            segments.extend(case_segments)
            operation_ledger.extend(case_ledger)
            for name, paths in execution.items():
                old, new = (compact_execution(paths[path]) for path in ("baseline", "candidate"))
                row = key | dict(scenario=name, baseline=old, candidate=new)
                row.update(difference(new, old))
                row["realized_net_delta"] = row["net"] - (new["unrealized"] - old["unrealized"])
                continuous.append(row)

    for row in pairs + continuous:
        row["product"] = row["contract"][:-4]
    eligible = [row for row in pairs if row["status"] == "SCORED"]
    paired = summarize_delta(eligible, "net_delta", operator.itemgetter("window", "contract", "at"))
    episodes = summarize_delta(segments, "net", operator.itemgetter("window", "contract", "start"))
    paired_fields = ("gross_delta", "fee_delta", "slippage_delta", "cost_delta", "net_delta")
    primary_rows = [r for r in continuous if r["scenario"] == "fee3_tick1"]
    require(sum((r["net"] for r in primary_rows), ZERO) == episodes["net"], "portfolio attribution")
    sample_products, sample_windows = {r["product"] for r in eligible}, {r["window"] for r in eligible}
    return dict(
        research_identity=seal["research_identity"], seal_sha256=SEAL_SHA,
        baseline_rule_sha256=FROZEN_RULE, executor=EXECUTION_VERSION, coverage=coverage, executable=False,
        paired=paired | dict(status=Counter(row["status"] for row in pairs),
                             products=sorted(sample_products), windows=sorted(sample_windows),
                             by_contract=breakdown(eligible, "contract", paired_fields),
                             by_product=breakdown(eligible, "product", paired_fields),
                             by_window=breakdown(eligible, "window", paired_fields),
                             sensitivity={name: sum((r["scenarios"][name]["delta"]["net"] for r in eligible), ZERO)
                                          for name in SCENARIOS}),
        continuous=episodes | dict(totals=breakdown(continuous, "scenario", (*FIELDS, "realized_net_delta")),
                                   by_contract=breakdown(primary_rows, "contract", (*FIELDS, "realized_net_delta")),
                                   by_product=breakdown(primary_rows, "product", (*FIELDS, "realized_net_delta")),
                                   by_window=breakdown(primary_rows, "window", (*FIELDS, "realized_net_delta"))),
        supported=len(eligible) >= 20 and len(sample_products) >= 3 and len(sample_windows) >= 2
                  and min(paired["net_without_largest"], episodes["net_without_largest"],
                          paired["net"], episodes["net"]) > 0,
        pairs=pairs, pair_traces=pair_traces, segments=segments, operation_ledger=operation_ledger,
        path_windows=continuous,
    )


def save_csv(path, rows):
    if rows:
        with path.open("x", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists() or args.output.is_symlink():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    require(kernel.RULE_HASH == FROZEN_RULE and all(sha(Path(p).read_bytes()) == digest
            for p, digest in FROZEN_CODE.items()), "original rule and source")
    seal = verified_json(SEAL, SEAL_SHA)
    require(seal["baseline_rule_sha256"] == FROZEN_RULE, "seal rule")

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    specs, missing_specs = load_instrument_specs()
    report = study(SessionLocal, seal, specs, missing_specs)
    args.output.mkdir()
    with (args.output / "report.json").open("x", encoding="utf-8") as output:
        output.write(encoded(report))
    save_csv(args.output / "paired.csv", [{k: v for k, v in r.items() if k != "scenarios"} for r in report["pairs"]])
    save_csv(args.output / "segments.csv", report["segments"])
    save_csv(args.output / "operations.csv", report["operation_ledger"])
    windows = [
        {k: v for k, v in row.items() if k not in {"baseline", "candidate"}}
        | {f"{path}_{k}": row[path][k] for path in ("baseline", "candidate")
           for k in (*FIELDS, "realized_gross", "unrealized", "closed_cycles", "operations")}
        for row in report["path_windows"]
    ]
    save_csv(args.output / "path-windows.csv", windows)


if __name__ == "__main__":
    main()

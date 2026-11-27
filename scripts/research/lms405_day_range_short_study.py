"""Test the sealed day-session range-short hypothesis and entry filter."""

import argparse
import csv
import operator
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant import lms_near405 as kernel
from lms405_entry_diagnosis import SHANGHAI, ledger, reconcile_scope, summarize
from lms405_holdout_replay import FROZEN_CODE, FROZEN_RULE, US
from lms405_original_leg_study import verified_json
from lms405_regime_confirmation_study import (
    FIELDS,
    compact_execution,
    continuous_attribution,
    difference,
    label_operations,
    load_instrument_specs,
    load_market,
    run_execution,
    scoped_function,
    summarize_delta,
)
from lms_near405_backtest import EXECUTION_VERSION
from lms_near405_replay import encoded, sha

SEAL = Path("docs/research/lms405/evidence/day-range-short-d-seal.json")
SEAL_SHA = "79528da679a5420c6013f8f48075dd65a76e84d1cc459624f5780891203c2bc8"
SCENARIO = "fee3_tick1"
ZERO = Decimal(0)


def require(condition, location):
    if not condition:
        raise ValueError(f"DAY_RANGE_SHORT_RECONCILIATION_FAILED: {location}")


def skip_first_entry(evaluation):
    proposal = evaluation["proposal"]
    if proposal is None or not (
        proposal["action"] == "ENTER_SHORT" and proposal["reason"] == "FRESH_PLAN_KEYBAR"
        and proposal["plan"]["environment"] == "RANGE"
    ):
        return False
    hour = datetime.fromisoformat(evaluation["bar_end"]).astimezone(SHANGHAI).hour
    return 6 <= hour < 21


def filtered_evaluate(state, bars, index, **options):
    evaluation = kernel._evaluate(state, bars, index, **options)
    if skip_first_entry(evaluation):
        require(state["long"] == state["short"] == "0", (state["contract"], index, "first-entry preimage"))
        proposal = evaluation["proposal"]
        return evaluation | dict(status="RESEARCH_D_ENTRY_SKIPPED", proposal=None, skipped_proposal=proposal)
    return evaluation


def filtered_replay(bars, as_of):
    # The namespace is confined to this study. Neither source identity nor the
    # kernel's other decisions or accepted-state mechanics are mutated.
    replay = scoped_function(kernel.replay, _evaluate=filtered_evaluate)
    return replay(bars, as_of=as_of, timely_fixture=True)


def target_cycle(row):
    return row["entry_class"] == "RANGE_SHORT" and row["entry_session"] == "DAY"


def remove_worst_product(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["product"]].append(row)
    products = {key: summarize(group) for key, group in sorted(groups.items())}
    worst = min(products, key=lambda p: (products[p]["net"], p), default=None)
    return dict(
        all=summarize(rows), excluded=worst, without_worst=summarize([r for r in rows if r["product"] != worst]),
        by_product=products,
        leave_one_product_out={p: summarize([r for r in rows if r["product"] != p]) for p in products},
    )


def direct_effects(key, baseline, candidate, closed, terminal, segments, operations):
    baseline_entries = {row["proposal_id"]: row["after"]["cycle_id"] for row in baseline["transitions"]
                        if row["action"] == "ENTER_SHORT"}
    by_cycle = {row["cycle_id"]: (row, False) for row in closed}
    by_cycle.update({row["cycle_id"]: (row, True) for row in terminal})
    segments_by_id = {s["segment"]: s for s in segments}
    base_operations = defaultdict(list)
    for operation in operations:
        if operation["path"] == "baseline":
            base_operations[operation["cycle_id"]].append(operation)
    skips = []
    for evaluation in candidate["evaluations"]:
        proposal = evaluation.get("skipped_proposal")
        if proposal is None:
            continue
        identity = proposal["proposal_id"]
        cycle_id = baseline_entries.get(identity)
        row = key | dict(
            confirm_at=evaluation["bar_end"], available_at=proposal["generated_at"], proposal_id=identity,
            plan_id=proposal["plan_id"], state_fingerprint=proposal["state_fingerprint"], baseline_cycle_id=cycle_id,
            segment=None, status="NO_COMMON_PREIMAGE", closed=None, baseline_gross=None, baseline_cost=None,
            baseline_net=None, effect=None,
        )
        if cycle_id:
            row["status"] = "BASELINE_DID_NOT_OPEN_REFERENCE"
        if cycle_id in by_cycle:
            outcome, marked = by_cycle[cycle_id]
            require(target_cycle(outcome), (identity, cycle_id, "baseline cohort"))
            opens = [op for op in base_operations[cycle_id] if op["offset"] == "OPEN"
                     and op["side"] == "short" and op["at"] == outcome["entry_at"]]
            require(len(opens) == 1, (identity, cycle_id, "baseline opening identity"))
            if opens[0]["shared"]:
                row["status"] = "REFERENCE_OPEN_SHARED_AT_OTHER_DECISION"
            else:
                segment_id = opens[0]["segment"]
                require(segment_id is not None and {op["segment"] for op in base_operations[cycle_id]} == {segment_id},
                        (identity, cycle_id, "direct cycle stays inside one segment"))
                gross = outcome["realized_gross"] + outcome["mtm"] if marked else outcome["gross"]
                cost = outcome["fee"] + outcome["slippage"]
                net = gross - cost
                row.update(status="DIRECT_TERMINAL" if marked else "DIRECT_CLOSED", segment=segment_id,
                           closed=not marked, baseline_gross=gross, baseline_cost=cost, baseline_net=net, effect=-net)
        skips.append(row)
    direct = defaultdict(list)
    for row in skips:
        if row["segment"] is not None:
            direct[row["segment"]].append(row)
    for segment_id, segment in segments_by_id.items():
        rows = direct[segment_id]
        segment.update(direct_count=len(rows), direct_net=sum((r["effect"] for r in rows), ZERO))
        segment["remaining_path_net"] = segment["net"] - segment["direct_net"]
    return skips


def window_result(key, bars, minutes, spec):
    as_of = bars[-1].end + 3 * US
    baseline = kernel.replay(bars, as_of=as_of, timely_fixture=True)
    baseline_reference = run_execution(minutes, baseline["transitions"], spec, SCENARIO)
    old = compact_execution(baseline_reference)
    contract = key["contract"]
    baseline_closed, baseline_terminal = ledger(
        "D", key["window"], contract, baseline_reference["fills"], baseline["transitions"],
        spec["multiplier"], spec["tick"], {b.end.isoformat(): b.close for b in bars},
        (bars[-1].end.isoformat(), bars[-1].close),
    )
    reconcile_scope(key, baseline_closed, baseline_terminal, old)
    target_closed = [r for r in baseline_closed if target_cycle(r)]
    target_terminal = [r for r in baseline_terminal if target_cycle(r)]
    result = dict(cohort_closed=target_closed, cohort_terminal=target_terminal)
    candidate = filtered_replay(bars, as_of)
    try:
        candidate_reference = run_execution(minutes, candidate["transitions"], spec, SCENARIO)
    except ValueError as error:
        if str(error) != "NEW_CYCLE_WHILE_EXECUTION_NOT_FLAT":
            raise
        return result | dict(candidate_interruption=str(error), baseline_only=old)
    new = compact_execution(candidate_reference)
    segments, operations = continuous_attribution(**key, baseline=baseline_reference, candidate=candidate_reference)
    label_operations(operations, segments, baseline, candidate)
    skipped = direct_effects(key, baseline, candidate, baseline_closed, baseline_terminal, segments, operations)
    return result | dict(window=key | dict(baseline=old, candidate=new, **difference(new, old)),
                         segments=segments, operations=operations, skipped=skipped)


def known_windows(session_factory, seal):
    from app.market_data.market_data_service import MarketDataError
    from app.market_data.session_clock import SessionClockError

    specs, missing = load_instrument_specs()
    for window in seal["windows"]:
        days = tuple(map(date.fromisoformat, window["trading_days"]))
        for contract in window["contracts"]:
            key = dict(window=window["id"], contract=contract)
            if contract not in specs:
                yield key | dict(status="DATA_INSUFFICIENT",
                                 reason=missing.get(contract, "FROZEN_CONTRACT_SPEC_UNAVAILABLE")), None
                continue
            try:
                hashes, bars, minutes = load_market(session_factory, contract, days)
            except (MarketDataError, SessionClockError) as error:
                yield key | dict(status="DATA_INSUFFICIENT", reason=error.code), None
                continue
            except ValueError as error:
                yield key | dict(status="DATA_INSUFFICIENT", reason=str(error)), None
                continue
            evidence = key | dict(status="EXACT_SESSION_AND_OHLCV", inputs=hashes, specification=specs[contract])
            try:
                result = window_result(key, bars, minutes, specs[contract])
            except ValueError as error:
                if str(error) != "NEW_CYCLE_WHILE_EXECUTION_NOT_FLAT":
                    raise
                yield evidence | dict(status="BASELINE_EXECUTION_INTERRUPTED", reason=str(error)), None
                continue
            if "candidate_interruption" in result:
                evidence = evidence | dict(status="CANDIDATE_EXECUTION_INTERRUPTED",
                                           reason=result["candidate_interruption"], baseline=result["baseline_only"])
            yield evidence, result


def field_totals(rows, fields=FIELDS):
    return {f: sum((r[f] for r in rows), ZERO) for f in fields}


def scoped_totals(rows, field):
    groups = defaultdict(list)
    for row in rows:
        groups[row[field]].append(row)
    return {key: field_totals(group) for key, group in sorted(groups.items())}


def study(session_factory, seal):
    coverage, windows, closed, terminal, segments, operations, skipped = [], [], [], [], [], [], []
    for evidence, result in known_windows(session_factory, seal):
        coverage.append(evidence)
        if result is None:
            continue
        closed.extend(result["cohort_closed"])
        terminal.extend(result["cohort_terminal"])
        if "window" not in result:
            continue
        window = result["window"]
        windows.append(window | dict(product=window["contract"][:-4]))
        segments.extend(result["segments"])
        operations.extend(result["operations"])
        skipped.extend(result["skipped"])

    cohort = remove_worst_product(closed)
    sample_windows = {row["window"] for row in closed}
    sample_enough = len(closed) >= 15 and len(cohort["by_product"]) >= 3 and len(sample_windows) >= 2
    average = cohort["all"]["averages"]["net"]
    trimmed_average = cohort["without_worst"]["averages"]["net"]
    supported = sample_enough and average < 0 and trimmed_average < 0
    path_delta = summarize_delta(segments, "net", operator.itemgetter("window", "contract", "start"))
    direct = [row for row in skipped if row["status"] in {"DIRECT_CLOSED", "DIRECT_TERMINAL"}]
    direct_closed = [row for row in direct if row["closed"]]
    direct_terminal = [row for row in direct if not row["closed"]]
    avoided = sum((row["effect"] for row in direct_closed if row["effect"] > 0), ZERO)
    missed = -sum((row["effect"] for row in direct_closed if row["effect"] < 0), ZERO)
    terminal_net = sum((row["effect"] for row in direct_terminal), ZERO)
    net = field_totals(windows)["net"]
    effects = field_totals(segments, ("direct_net", "remaining_path_net"))
    require(path_delta["net"] == net == effects["direct_net"] + effects["remaining_path_net"]
            and effects["direct_net"] == avoided - missed + terminal_net, "portfolio P&L bridge")
    skip_windows = {row["window"] for row in skipped}
    return dict(
        identity=seal["research_identity"], seal_sha256=SEAL_SHA, original_rule=FROZEN_RULE,
        execution=EXECUTION_VERSION, scenario=SCENARIO, executable=False, coverage=coverage,
        hypothesis=cohort | dict(
            conclusion="SUPPORTED" if supported else "NOT_SUPPORTED" if sample_enough else "INSUFFICIENT_SAMPLE",
            eligible_windows=sorted(sample_windows), entry_reasons=Counter(r["entry_reason"] for r in closed),
            by_window={window["id"]: remove_worst_product([r for r in closed if r["window"] == window["id"]])
                       for window in seal["windows"]},
        ),
        path=path_delta | dict(
            conclusion="SUPPORTED" if len(skip_windows) >= 2 and min(net, path_delta["net_without_largest"]) > 0
                       else "INSUFFICIENT_SAMPLE" if len(skip_windows) < 2 else "NOT_SUPPORTED",
            skip_status=Counter(r["status"] for r in skipped), skip_windows=sorted(skip_windows),
            totals={path: field_totals([r[path] for r in windows], (*FIELDS, "realized_gross", "unrealized",
                                                                 "closed_cycles", "operations"))
                    for path in ("baseline", "candidate")},
            delta=field_totals(windows), by_window=scoped_totals(windows, "window"),
            by_product=scoped_totals(windows, "product"),
            direct=effects | dict(avoided_losses=avoided, missed_profits=missed, terminal_effect=terminal_net,
                                  avoided_count=sum(r["effect"] > 0 for r in direct_closed),
                                  missed_count=sum(r["effect"] < 0 for r in direct_closed),
                                  flat_count=sum(r["effect"] == 0 for r in direct_closed)),
        ),
        windows=windows, cohort_closed=closed, cohort_terminal=terminal, segments=segments,
        operations=operations, skipped=skipped,
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
            for p, digest in FROZEN_CODE.items()), "original strategy and reference executor")
    seal = verified_json(SEAL, SEAL_SHA)
    require(seal["baseline_rule_sha256"] == FROZEN_RULE, "sealed baseline")

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    result = study(SessionLocal, seal)
    args.output.mkdir()
    with (args.output / "report.json").open("x", encoding="utf-8") as output:
        output.write(encoded(result))
    for name in ("cohort_closed", "cohort_terminal", "segments", "operations", "skipped"):
        save_csv(args.output / f"{name.replace('_', '-')}.csv", result[name])
    windows = [
        {k: v for k, v in r.items() if k not in {"baseline", "candidate"}}
        | {f"{path}_{f}": r[path][f] for path in ("baseline", "candidate")
           for f in (*FIELDS, "realized_gross", "unrealized", "closed_cycles", "operations")}
        for r in result["windows"]
    ]
    save_csv(args.output / "path-windows.csv", windows)


if __name__ == "__main__":
    main()

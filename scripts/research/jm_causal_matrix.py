"""Fixed-window 42-cell Paper-kernel comparison; no broker or account writes."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frequency", choices=("5m", "15m", "30m", "60m", "1d", "1w"), required=True)
    parser.add_argument("--strategy", nargs="+", choices=("trend", "oscillation", "dual_fusion", "osc-test", "osc-test2", "osc-test3", "osc-test4"))
    parser.add_argument("--scenario", choices=("baseline", "double_commission", "double_slippage"), default="baseline")
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--market-env", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--owner-diagnostics", action="store_true")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.market_env, override=False)
    os.environ["GUIYI_CANONICAL_DATA_ROOT"] = str(args.canonical_root.resolve())
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
    from app.market_data.composition import build_database_coverage_source, build_market_data_service
    from app.market_data.newow.jm_matrix_input import load_matrix_input
    from app.market_data.newow.jm_pilot_research import (
        load_jm_execution_bars, load_jm_pilot_input, adapt_jm_execution_facts,
    )
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_release import candidate_input_quality_policy
    from app.market_data.operational_universe import load_active_products
    from app.paper.matrix import prepare_execution, run_matrix_cell, MATRIX_VERSION
    from guiyi_quant.newow.causal_matrix_signals import CausalMatrixStrategy
    from guiyi_quant.newow.product_contracts import ProductFrequency

    since, through = date(2025, 10, 11), date(2026, 10, 9)
    raw = json.loads(args.facts.read_text())
    original = args.facts.with_name("execution-facts.json")
    if sha256(original.read_bytes()).hexdigest() != raw["tick_amendment"]["original_sha256"]:
        raise ValueError("MATRIX_FACT_AMENDMENT_MISMATCH")
    frequency = ProductFrequency(args.frequency)
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=900):
        market = build_market_data_service(session)
        reader = NewowProductReader(market, coverage=build_database_coverage_source(session),
            active_products=load_active_products(), input_quality_policy=candidate_input_quality_policy(
                "jm", frequency, candidate_weekly=frequency is ProductFrequency.WEEKLY))
        source = load_matrix_input(market, reader, frequency, since=since,
            requested_through=date(2026, 10, 10), as_of=datetime(2026, 10, 11, tzinfo=ZoneInfo("Asia/Shanghai")))
        if source.actual_through != through:
            raise ValueError("MATRIX_WINDOW_MISMATCH")
        adapt_jm_execution_facts(load_jm_pilot_input(market, since=since, actual_through=through), raw)
        minutes = load_jm_execution_bars(market, since=since, actual_through=through)
        sessions = ActualDominantResearchSegmentLoader(market).sessions(symbol="jm",
            trading_days=tuple(sorted({b.trading_day for b in minutes})))
        if any(not any(s.start <= b.bar_end-timedelta(minutes=1) and b.bar_end <= s.end
                       for s in sessions[b.trading_day]) for b in minutes):
            raise ValueError("MATRIX_SESSION_UNPROVEN")
    templates, facts_hash, clock_hash = prepare_execution(minutes, raw)
    args.out.mkdir(parents=True, exist_ok=True)
    strategies = tuple(CausalMatrixStrategy(s) for s in args.strategy) if args.strategy else tuple(CausalMatrixStrategy)
    for strategy in strategies:
        path = args.out / f"{args.frequency}-{strategy.value}-{args.scenario}.json"
        if path.exists():
            raise ValueError("MATRIX_RESULT_ALREADY_EXISTS")
        result = run_matrix_cell(source, templates, facts_hash, clock_hash, strategy, scenario=args.scenario)
        diagnostics = []
        if args.owner_diagnostics:
            for contract in dict.fromkeys(b.physical_contract for b in source.bars):
                diagnostics.append(run_matrix_cell(source, templates, facts_hash, clock_hash, strategy,
                    scenario=args.scenario, physical_contract=contract))
        result["owner_diagnostics"] = diagnostics
        result["matrix_version"] = MATRIX_VERSION
        result["signal_bar_count"] = len(source.bars)
        result["execution_bar_count"] = len(minutes)
        result["facts_captured_at"] = raw["captured_at"]
        result["facts_composed_at"] = raw["tick_amendment"]["captured_at"]
        with path.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"frequency": args.frequency, "strategy": strategy.value,
            "status": result["status"], "equity": result["equity"], "annual_eligible": result["annual_eligible"],
            "owner_returns": [d["account_return_pct"] for d in diagnostics]}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        candidate = getattr(exc, "code", None) or str(exc)
        code = candidate if re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", str(candidate)) else "MATRIX_EXECUTION_FAILED"
        print(json.dumps({"status": "BLOCKED", "code": code}), flush=True)
        raise SystemExit(1) from None

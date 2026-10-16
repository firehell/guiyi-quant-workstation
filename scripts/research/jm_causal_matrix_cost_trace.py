"""Reproduce fixed matrix results and capture fee-induced execution path changes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--market-env", required=True)
    parser.add_argument("--canonical-root", required=True)
    args = parser.parse_args()
    # App imports initialize database settings, so load the existing secure
    # configuration before importing the reducer's application dependencies.
    from dotenv import load_dotenv
    load_dotenv(args.market_env, override=False)
    spec = importlib.util.spec_from_file_location("matrix_cli", Path(__file__).with_name("jm_causal_matrix.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    from app.paper import matrix
    original = matrix.apply_events
    traces = []
    for frequency, strategy in (("60m", "osc-test2"), ("1d", "osc-test")):
        for scenario in ("baseline", "double_commission"):
            fills, halts = [], []

            def capture(state, events):
                new = original(state, events)
                offset = len(state.fills) if state else 0
                fills.extend(asdict(fill) for fill in new.fills[offset:])
                if new.daily_halt and (state is None or not state.daily_halt):
                    halts.append({"trading_day": new.trading_day, "at": new.last_bar_end,
                                  "equity": new.equity, "day_start_equity": new.day_start_equity})
                return new

            previous_argv = sys.argv
            with TemporaryDirectory(prefix="jm-matrix-trace-") as temporary:
                try:
                    matrix.apply_events = capture
                    sys.argv = [str(cli.__file__), "--frequency", frequency, "--strategy", strategy,
                        "--scenario", scenario, "--facts", args.facts, "--market-env", args.market_env,
                        "--canonical-root", args.canonical_root, "--out", temporary]
                    cli.main()
                finally:
                    matrix.apply_events = original
                    sys.argv = previous_argv
                name = f"{frequency}-{strategy}-{scenario}.json"
                reproduced = json.loads((Path(temporary) / name).read_text())
                saved = json.loads((args.root / name).read_text())
                # Baseline originally included separate owner diagnostics; all
                # annual execution facts must otherwise reproduce exactly.
                if {k: v for k, v in reproduced.items() if k != "owner_diagnostics"} != {
                        k: v for k, v in saved.items() if k != "owner_diagnostics"}:
                    raise ValueError("MATRIX_TRACE_REPRODUCTION_MISMATCH")
            traces.append({"frequency": frequency, "strategy": strategy, "scenario": scenario,
                           "run_hash": saved["run_hash"], "exact_result_reproduced": True,
                           "fills": fills, "halt_transitions": halts})
    with (args.root / "cost-path-trace.json").open("x") as stream:
        json.dump({"traces": traces}, stream, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"status": "BLOCKED", "code": "MATRIX_COST_TRACE_FAILED"}))
        raise SystemExit(1) from None

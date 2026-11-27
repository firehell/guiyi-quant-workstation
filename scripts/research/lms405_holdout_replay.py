"""Read the frozen P5 date window through local MDS and replay unchanged candidate rules."""

import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_near405 import RULE_HASH, replay
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import CONTRACTS
from lms405_replay import ohlc, read_session_series
from lms405_reversal_stage_bounds import SPECS_SHA
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_backtest import EXECUTION_VERSION, SCENARIOS, execute_reference
from lms_near405_replay import encoded, sha

BASE = "9543960f860b8e780fe502178c5f417b2fa847c7"
SCOPE_BLOB = "182bc45f8e74f728bc8265e5df1cf202f608938e"
FROZEN_RULE = "ba4a3aa30e499496196bfa36afcd18907e4f4cf5bd50fc6e56cab91d9ef43d07"
COVERAGE_SHA = "d492ddf5b028774d3fbbd99f8440438a9382378a4c108e6e085bf531ae0c2074"
FROZEN_CODE = {
    "packages/quant-core/guiyi_quant/lms_near405.py": "5fe966df4dd447cbaf014640f7855a11931b399eb97737abecec5d122cd115f8",
    "scripts/research/lms_near405_backtest.py": "e69b02a2486a6c15c59bba6bf6d81c4c1d95191e4659ec0a533f474cccb1eaea",
}
DAYS = tuple(date(2026, 11, day) for day in range(16, 21))
US = timedelta(microseconds=1)


def study(session_factory, coverage):
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    if (RULE_HASH != FROZEN_RULE or coverage["rule_base"] != BASE[:9] or coverage["scope_blob"] != SCOPE_BLOB
            or coverage["trading_days"] != [day.isoformat() for day in DAYS]
            or set(coverage["contracts"]) != set(CONTRACTS)):
        raise ValueError("FROZEN_SCOPE_MISMATCH")
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    results = {}
    for contract in CONTRACTS:
        series = {}
        for period in (1, 5):
            try:
                with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
                    raw = read_session_series(session, build_market_data_service(session),
                        contract[:-4].lower(), contract, f"{period}m", timedelta(minutes=period), DAYS)
                digest = sha(encoded([(b.trading_day, b.bar_end, *ohlc(b), b.volume) for b in raw]).encode())
                expected = coverage["contracts"][contract][f"{period}m"]
                if digest != expected.get("sha256") or len(raw) != expected.get("bars"):
                    raise ValueError("FROZEN_INPUT_MISMATCH")
                series[period] = raw
            except MarketDataError as exc:
                results[contract] = dict(status="DATA_INSUFFICIENT", period=f"{period}m", reason=exc.code)
                break
            except ValueError as exc:
                results[contract] = dict(status="DATA_INSUFFICIENT", period=f"{period}m", reason=str(exc))
                break
        if len(series) != 2:
            continue
        if coverage["contracts"][contract]["ohlc_parity"] is not True:
            results[contract] = dict(status="DATA_INSUFFICIENT", reason="MINUTE_AGGREGATE_DIVERGED")
            continue
        bars = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - timedelta(minutes=5)) for b in series[5]]
        minutes = [
            dict(contract=contract, trading_day=b.trading_day.isoformat(), bar_end=b.bar_end.isoformat(),
                 open=str(b.open), high=str(b.high), low=str(b.low), close=str(b.close), volume=str(b.volume))
            for b in series[1]
        ]
        as_of = bars[-1].end + 3 * US
        manual = replay(bars, as_of=as_of)
        fixture = replay(bars, as_of=as_of, timely_fixture=True)
        spec = specs[contract]
        costs = {}
        for name, (fee, ticks) in SCENARIOS.items():
            try:
                costs[name] = execute_reference(minutes, fixture["transitions"],
                                                Decimal(spec["multiplier"]), Decimal(spec["tick"]), fee, ticks)
            except ValueError as exc:
                costs[name] = dict(status="REFERENCE_INTERRUPTED", reason=str(exc))
        results[contract] = dict(
            status="DATE_HOLDOUT_REPLAYED", tick=spec["tick"], multiplier=spec["multiplier"],
            spec_source_sha256=spec["source_sha256"], manual_proposals=len(manual["proposals"]),
            manual_transitions=len(manual["transitions"]), fixture_actions=Counter(
                t["action"] for t in fixture["transitions"]),
            fixture_transitions=fixture["transitions"], terminal=fixture["terminal_status"], reference=costs,
        )
    return dict(base=BASE, rule_hash=RULE_HASH, execution_version=EXECUTION_VERSION,
                code_hashes=FROZEN_CODE, input_coverage_sha256=COVERAGE_SHA,
                trading_days=DAYS, candidate_results=results,
                author_action_samples=0, author_action_match_rate=None,
                author_source_scope="NOT_EVALUATED_BY_INDEPENDENT_RUNNER",
                executable=False, historical_fees_verified=False, limit_history_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists() or args.output.is_symlink():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    if any(sha(Path(path).read_bytes()) != digest for path, digest in FROZEN_CODE.items()):
        parser.error("FROZEN_CODE_MISMATCH")

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    coverage = verified_json(args.coverage, COVERAGE_SHA)
    report = encoded(study(SessionLocal, coverage))
    with args.output.open("x", encoding="utf-8") as output:
        output.write(report)


if __name__ == "__main__":
    main()

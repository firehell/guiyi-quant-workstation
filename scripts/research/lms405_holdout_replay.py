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
from lms405_sizing_audit import SPECS, load_specs, positive_decimal
from lms_near405_backtest import EXECUTION_VERSION, SCENARIOS, execute_reference
from lms_near405_replay import encoded, sha

BASE = "9543960f860b8e780fe502178c5f417b2fa847c7"
SCOPE_BLOB = "182bc45f8e74f728bc8265e5df1cf202f608938e"
FROZEN_RULE = "ba4a3aa30e499496196bfa36afcd18907e4f4cf5bd50fc6e56cab91d9ef43d07"
COVERAGE_SHA = "d492ddf5b028774d3fbbd99f8440438a9382378a4c108e6e085bf531ae0c2074"
CROSS_COVERAGE_SHA = "2bc535acfccc84dd7f750d8c670c24e6307f157f5d992bf3a3b6b8d2f2cfdb25"
CROSS_SCOPE_BLOB = "f3cad247e44be55ce2c06bd7e17b22979772c881"
CROSS_SPECS = {
    "JM2609": (
        "output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/JM2609-instrument.json",
        "f5924387b4c9ec7f9555f6c8147d782d94be1b067299951c46f0e3ec4b608f89",
    ),
    "SH2611": (
        "output/htdy-60m-full-replay-20261025/evidence-002/provider/SH2611-instrument.json",
        "230166f9cf9904b9d922feb1118eecd7343cdd09433fa6623ffea4094175104f",
    ),
}
FROZEN_CODE = {
    "packages/quant-core/guiyi_quant/lms_near405.py": "5fe966df4dd447cbaf014640f7855a11931b399eb97737abecec5d122cd115f8",
    "scripts/research/lms_near405_backtest.py": "e69b02a2486a6c15c59bba6bf6d81c4c1d95191e4659ec0a533f474cccb1eaea",
}
DAYS = tuple(date(2026, 11, day) for day in range(16, 21))
US = timedelta(microseconds=1)
CROSS_DAYS = {
    "JM2609": tuple(date(2026, 7, day) for day in range(6, 11)),
    "SH2611": tuple(date(2026, 8, day) for day in range(24, 29)),
}


def cross_specs():
    result = {}
    for contract, (path, digest) in CROSS_SPECS.items():
        source = verified_json(Path(path), digest)
        if source["order_book_id"] != contract:
            raise ValueError("SPEC_CONTRACT_IDENTITY_MISMATCH")
        result[contract] = dict(multiplier=positive_decimal(source["contract_multiplier"]),
                                tick=positive_decimal(source["tick_size"]), source_sha256=digest)
    return result


def study(session_factory, coverage, *, cross_contract=False):
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    scope, digest = (CROSS_SCOPE_BLOB, CROSS_COVERAGE_SHA) if cross_contract else (SCOPE_BLOB, COVERAGE_SHA)
    windows = CROSS_DAYS if cross_contract else dict.fromkeys(CONTRACTS, DAYS)
    if (RULE_HASH != FROZEN_RULE or coverage["rule_base"] != BASE[:9] or coverage["scope_blob"] != scope
            or set(coverage["contracts"]) != set(windows)):
        raise ValueError("FROZEN_SCOPE_MISMATCH")
    for contract, days in windows.items():
        date_record = coverage["contracts"][contract] if cross_contract else coverage
        if date_record["trading_days"] != [day.isoformat() for day in days]:
            raise ValueError("FROZEN_SCOPE_MISMATCH")
    specs = cross_specs() if cross_contract else load_specs(verified_json(SPECS, SPECS_SHA))
    results = {}
    for contract, days in windows.items():
        series = {}
        for period in (1, 5):
            try:
                with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
                    raw = read_session_series(session, build_market_data_service(session),
                        contract[:-4].lower(), contract, f"{period}m", timedelta(minutes=period), days)
                input_hash = sha(encoded([(b.trading_day, b.bar_end, *ohlc(b), b.volume) for b in raw]).encode())
                expected = coverage["contracts"][contract][f"{period}m"]
                if input_hash != expected.get("sha256") or len(raw) != expected.get("bars"):
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
            status="DATE_HOLDOUT_REPLAYED" if not cross_contract else "CROSS_CONTRACT_HOLDOUT_REPLAYED",
            tick=spec["tick"], multiplier=spec["multiplier"],
            spec_source_sha256=spec["source_sha256"], manual_proposals=len(manual["proposals"]),
            manual_transitions=len(manual["transitions"]), fixture_actions=Counter(
                t["action"] for t in fixture["transitions"]),
            fixture_transitions=fixture["transitions"], terminal=fixture["terminal_status"], reference=costs,
        )
    return dict(base=BASE, rule_hash=RULE_HASH, execution_version=EXECUTION_VERSION,
                code_hashes=FROZEN_CODE, input_coverage_sha256=digest,
                trading_days=windows if cross_contract else DAYS, candidate_results=results,
                author_action_samples=0, author_action_match_rate=None,
                author_source_scope="NOT_EVALUATED_BY_INDEPENDENT_RUNNER",
                executable=False, historical_fees_verified=False, limit_history_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cross-contract", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists() or args.output.is_symlink():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    if any(sha(Path(path).read_bytes()) != digest for path, digest in FROZEN_CODE.items()):
        parser.error("FROZEN_CODE_MISMATCH")

    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    from app.db.session import SessionLocal

    coverage = verified_json(args.coverage, CROSS_COVERAGE_SHA if args.cross_contract else COVERAGE_SHA)
    report = encoded(study(SessionLocal, coverage, cross_contract=args.cross_contract))
    with args.output.open("x", encoding="utf-8") as output:
        output.write(report)


if __name__ == "__main__":
    main()

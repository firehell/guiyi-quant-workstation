"""Compare held-plan clocks only, on session-verified local 5m contracts."""

import argparse
from collections import Counter
from datetime import date, datetime
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_locked_exit_audit import BASELINE_SHA256
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

COMPARISON_DAYS = (date(2026, 11, 4), date(2026, 11, 5))


def transition_rows(result):
    return [dict(at=t["known_at"], action=t["action"], reason=t["reason"],
                 side=t["after"]["original_side"],
                 created_index=t["after"]["plan"]["created_index"],
                 since_entry_index=t["after"]["entry_index"],
                 before=[t["before"][leg] for leg in ("long", "short")],
                 after=[t["after"][leg] for leg in ("long", "short")],
                 lock_intervals=t["after"].get("lock_intervals"))
            for t in result["transitions"]]


def compare(series, clock, *, as_of):
    full = candidate.replay(series, as_of=as_of, timely_fixture=True, clock=clock)
    cut = series[len(series) // 2].end + candidate.US
    early = candidate.replay(series[:len(series) // 2 + 1], as_of=cut,
                             timely_fixture=True, clock=clock)
    if early != candidate.replay(series, as_of=cut, timely_fixture=True, clock=clock):
        raise ValueError("CLOCK_PREFIX_DIVERGED")
    restarted = candidate.replay(
        series, as_of=as_of, timely_fixture=True, clock=clock,
        checkpoint=json.loads(encoded(early["checkpoint"])),
    )
    if restarted != full:
        raise ValueError("CLOCK_JSON_RESTART_DIVERGED")
    manual = candidate.replay(series, as_of=as_of, clock=clock)
    if manual["transitions"]:
        raise ValueError("UNCONFIRMED_CLOCK_TRANSITIONS")
    return full


def study_window(session, market, days, baseline=None):
    inputs = {}
    for contract in CONTRACTS:
        bars = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, days)
        inputs[contract] = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in bars]
    as_of = max(bars[-1].end for bars in inputs.values()) + 3 * candidate.US
    if baseline and as_of != datetime.fromisoformat(baseline["as_of"]):
        raise ValueError("FROZEN_AS_OF_DIVERGED")
    results, expected = {}, []
    counts = {key: Counter() for key in ("BASELINE", *candidate.CLOCK_VERSIONS)}
    for contract, series in inputs.items():
        input_hash = sha(encoded([[b.end.isoformat(), *(str(p) for p in ohlc(b))]
                                 for b in series]).encode())
        if baseline and input_hash != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("FROZEN_INPUT_BAR_IDENTITY_DIVERGED")
        by_rule = {}
        for key in counts:
            result = compare(series, None if key == "BASELINE" else key, as_of=as_of)
            rows = transition_rows(result)
            counts[key].update(row["action"] for row in rows)
            by_rule[key] = dict(version=result["version"], rule_hash=result["rule_hash"],
                                terminal=result["terminal_status"], transitions=rows)
            if key == "BASELINE":
                expected.extend(result["transitions"])
        results[contract] = dict(bars=len(series), input_sha256=input_hash, results=by_rule)
    if baseline and batch_fixture_transitions(expected)[0] != [
        row for row in baseline["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"
    ]:
        raise ValueError("FROZEN_PORTFOLIO_BASELINE_DIVERGED")
    return dict(trading_days=[day.isoformat() for day in days], as_of=as_of.isoformat(),
                action_counts=counts, contracts=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or not args.baseline.is_file() or args.output.exists():
        parser.error("INPUT_MISSING_OR_OUTPUT_EXISTS")
    raw = args.baseline.read_bytes()
    if sha(raw) != BASELINE_SHA256:
        parser.error("BASELINE_SHA256_MISMATCH")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            result = dict(
                development=study_window(session, market, DAYS, json.loads(raw)),
                comparative=study_window(session, market, COMPARISON_DAYS),
                baseline_sha256=BASELINE_SHA256, fixture_only=True,
                author_action_matches=None, fills=None, pnl=None, executable=False,
            )
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded(result))


if __name__ == "__main__":
    main()

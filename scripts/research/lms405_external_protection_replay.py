"""Exercise explicit protection evidence in the frozen nine-contract research replay."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_hold_clock_study import transition_rows
from lms405_locked_exit_audit import BASELINE_SHA256
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

EVIDENCE_SHA256 = "f6e24d57ad056d999ca690033d247c81eded8c5feac4c29eeec54d223fa1a48d"
CLOCK = "DEFER_WHILE_LOCKED"
EXERCISE_CONTRACT = "SH2701"
EXERCISE_AT = datetime.fromisoformat("2026-10-23T09:45:00+08:00")


def state_exercise(bars, baseline, *, as_of):
    if not any(bar.end == EXERCISE_AT for bar in bars):
        raise ValueError("FIXTURE_EXERCISE_BAR_REQUIRED")
    cut = EXERCISE_AT - candidate.US
    early = candidate.replay(bars, as_of=cut, timely_fixture=True, clock=CLOCK, protection_confirmations=())
    state = early["current_state"]
    if state["long"] != "0" or state["short"] != "1":
        raise ValueError("FIXTURE_EXERCISE_OLD_SHORT_REQUIRED")
    proof = candidate.ProtectionConfirmation(
        EXERCISE_CONTRACT, candidate.fingerprint(state), EXERCISE_AT, EXERCISE_AT,
        EXERCISE_AT, "EXPLICIT_SH_LIFECYCLE_TEST_NOT_AUTHOR_EVIDENCE", "TEST_FIXTURE",
    )
    args = dict(timely_fixture=True, clock=CLOCK, protection_confirmations=(proof,))
    tested = candidate.replay(bars, as_of=as_of, **args)
    if candidate.replay(
        bars, as_of=as_of, checkpoint=json.loads(encoded(early["checkpoint"])), **args,
    ) != tested or candidate.replay(bars, as_of=cut, **args) != early:
        raise ValueError("EXTERNAL_PROTECTION_PREFIX_OR_RESTART_DIVERGED")
    cycle = state["cycle_id"]
    cycle_rows = [row for row in tested["transitions"] if row["before"]["cycle_id"] == cycle]
    if [row["action"] for row in cycle_rows] != ["LOCK", "UNLOCK_SHORT", "CLEAR"]:
        raise ValueError("FIXTURE_LIFECYCLE_NOT_REPRODUCIBLE")
    before_exercise = [
        [row for row in result["transitions"] if datetime.fromisoformat(row["known_at"]) < EXERCISE_AT]
        for result in (baseline, tested)
    ]
    if before_exercise[0] != before_exercise[1]:
        raise ValueError("EXTERNAL_PROTECTION_CHANGED_EARLY_PATH")
    return tested, dict(source=asdict(proof), cycle_rows=transition_rows({"transitions": cycle_rows}),
                        prefix_and_json_restart_verified=True)


def study(session, market, baseline, evidence, *, exercise):
    evidence_status = {
        name: row["assessment"]["decisions"]["LOCK_PROTECTION"]["status"]
        for name, row in evidence["episodes"].items()
    }
    if not evidence_status or any(status != "INDETERMINATE" for status in evidence_status.values()):
        raise ValueError("REVIEW_EVIDENCE_STATUS_CHANGED")
    as_of = datetime.fromisoformat(baseline["as_of"])
    old_transitions, comparison, exercised = [], {}, None
    versions = dict(no_evidence=[], explicit_sh_fixture=[]) if exercise else dict(no_evidence=[])
    for contract in CONTRACTS:
        original = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - FIVE) for bar in original]
        input_hash = sha(encoded([[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in bars]).encode())
        if input_hash != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("FROZEN_PORTFOLIO_INPUT_CHANGED")
        old_transitions.extend(candidate.replay(bars, as_of=as_of, timely_fixture=True)["transitions"])
        args = dict(as_of=as_of, clock=CLOCK, protection_confirmations=())
        manual = candidate.replay(bars, **args)
        basic = candidate.replay(bars, timely_fixture=True, **args)
        if manual["transitions"] or any(row["action"] == "LOCK" for row in basic["transitions"]):
            raise ValueError("UNSUPPORTED_HISTORICAL_TRANSITION")
        versions["no_evidence"].extend(basic["transitions"])
        comparison[contract] = dict(input_sha256=input_hash, bars=len(bars),
                                    manual_proposals=len(manual["proposals"]), manual_transitions=0,
                                    no_evidence=basic["terminal_status"])
        if exercise:
            if contract == EXERCISE_CONTRACT:
                tested, exercised = state_exercise(bars, basic, as_of=as_of)
            else:
                tested = basic
            versions["explicit_sh_fixture"].extend(tested["transitions"])
            comparison[contract]["explicit_sh_fixture"] = tested["terminal_status"]
    if batch_fixture_transitions(old_transitions)[0] != [
        row for row in baseline["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"
    ]:
        raise ValueError("FROZEN_PORTFOLIO_BASELINE_DIVERGED")
    return dict(
        version=candidate.EXTERNAL_PROTECTION_VERSION,
        held_plan_clock=CLOCK, as_of=as_of.isoformat(), actions={
            name: dict(counts=dict(Counter(row["action"] for row in events)),
                       timeline=batch_fixture_transitions(events)[0]) for name, events in versions.items()
        },
        contracts=comparison, evidence_protection_status=evidence_status,
        explicit_fixture=exercised, executable=False, admitted_author_samples=0,
        author_matches=None, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-sh-fixture", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        raw, evidence = args.baseline.read_bytes(), args.evidence.read_bytes()
        if sha(raw) != BASELINE_SHA256 or sha(evidence) != EVIDENCE_SHA256:
            raise ValueError("FROZEN_REPLAY_INPUT_HASH_MISMATCH")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), json.loads(raw), json.loads(evidence),
                           exercise=args.exercise_sh_fixture)
        result["input_sha256"] = dict(baseline=BASELINE_SHA256, evidence=EVIDENCE_SHA256)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

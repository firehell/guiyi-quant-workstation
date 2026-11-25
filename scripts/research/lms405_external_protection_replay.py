"""Exercise explicit protection evidence in the frozen nine-contract research replay."""

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_hold_clock_study import transition_rows
from lms405_locked_exit_audit import BASELINE_SHA256
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

EVIDENCE_SHA256 = "f6e24d57ad056d999ca690033d247c81eded8c5feac4c29eeec54d223fa1a48d"
HANDOFF_SHA256 = "2c5457ee76981579bafd87971af5b7e163fe8e7d610bea024dfd12573294ba61"
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


def scoped_state_exercise(bars, *, as_of):
    cut = EXERCISE_AT - candidate.US
    older = EXERCISE_AT - timedelta(minutes=3)
    newer = EXERCISE_AT - timedelta(minutes=2)
    prior_bar = next(b for b in reversed(bars) if b.end < older)
    target = ProtectionBandUpdate(EXERCISE_CONTRACT, "fixture-target", "TARGET", older, older,
                                  "TEST_FIXTURE_SCOPE", "SHORT", prior_bar.low, prior_bar.high)
    old = replace(target, role="PROTECTION", revision="fixture-old-protection")
    new = replace(old, revision="fixture-new-protection", known_at=newer, effective_after=newer)
    review = ProtectionBandUpdate(EXERCISE_CONTRACT, "fixture-review", "REVIEW_PENDING", cut, cut,
                                  "TEST_FIXTURE_SCOPE", "SHORT")
    bands = (target, old, new)
    args = dict(timely_fixture=True, clock=CLOCK)
    early = candidate.replay(bars, as_of=cut, protection_bands=bands, protection_confirmations=(), **args)
    state = early["current_state"]
    if (state["long"], state["short"]) != ("0", "1"):
        raise ValueError("FIXTURE_EXERCISE_OLD_SHORT_REQUIRED")
    proof = candidate.ScopedProtectionConfirmation(
        EXERCISE_CONTRACT, candidate.fingerprint(state), EXERCISE_AT, EXERCISE_AT,
        EXERCISE_AT, "EXPLICIT_SH_BAND_SWITCH_TEST_NOT_AUTHOR_EVIDENCE", "TEST_FIXTURE",
        new.scope, newer + candidate.US, "LONG",
    )
    checks = {}
    for name, active, item in (
        ("target_only", (target,), replace(proof, band_scope=target.scope)),
        ("superseded_protection", bands, replace(proof, band_scope=old.scope)),
        ("shape_started_before_protection", bands, replace(proof, signal_start=newer)),
        ("review_pending", bands + (review,), proof),
    ):
        result = candidate.replay(bars, as_of=as_of, protection_bands=active, protection_confirmations=(item,), **args)
        row = next(e for e in result["evaluations"] if datetime.fromisoformat(e["bar_end"]) == EXERCISE_AT)
        if any(p["action"] == "LOCK" for p in result["proposals"]):
            raise ValueError("UNSUPPORTED_SCOPED_LOCK_PROPOSAL")
        checks[name] = row["status"]

    replay_inputs = dict(protection_bands=bands, protection_confirmations=(proof,), **args)
    accepted = candidate.replay(bars, as_of=as_of, **replay_inputs)
    if (candidate.replay(bars, as_of=cut, **replay_inputs) != early
            or candidate.replay(bars, as_of=as_of, checkpoint=json.loads(encoded(early["checkpoint"])),
                                **replay_inputs) != accepted):
        raise ValueError("SCOPED_PROTECTION_PREFIX_OR_RESTART_DIVERGED")
    cycle_rows = [row for row in accepted["transitions"] if row["before"]["cycle_id"] == state["cycle_id"]]
    if [row["action"] for row in cycle_rows] != ["LOCK", "UNLOCK_SHORT", "CLEAR"]:
        raise ValueError("SCOPED_FIXTURE_NOT_REPRODUCIBLE")
    return accepted, dict(proof=asdict(proof), band_updates=[asdict(b) for b in bands],
                          rejected_proposals=checks, cycle_rows=transition_rows({"transitions": cycle_rows}),
                          prefix_and_json_restart_verified=True)


def study(session, market, baseline, evidence, *, exercise, scoped_evidence=None):
    evidence_status = {
        name: row["assessment"]["decisions"]["LOCK_PROTECTION"]["status"]
        for name, row in evidence["episodes"].items()
    }
    if not evidence_status or any(status != "INDETERMINATE" for status in evidence_status.values()):
        raise ValueError("REVIEW_EVIDENCE_STATUS_CHANGED")
    as_of = datetime.fromisoformat(baseline["as_of"])
    old_transitions, comparison, exercised = [], {}, None
    scoped = scoped_evidence is not None
    if scoped and (scoped_evidence["oil_may"]["author_may27_protection_band"] is not None
                   or scoped_evidence["soda_october"]["author_new_protection_band"] is not None):
        raise ValueError("HANDOFF_PROTECTION_UNKNOWN_STATUS_CHANGED")
    versions = dict(no_evidence=[], explicit_sh_fixture=[]) if exercise else dict(no_evidence=[])
    for contract in CONTRACTS:
        original = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - FIVE) for bar in original]
        input_hash = sha(encoded([[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in bars]).encode())
        if input_hash != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("FROZEN_PORTFOLIO_INPUT_CHANGED")
        old_transitions.extend(candidate.replay(bars, as_of=as_of, timely_fixture=True)["transitions"])
        args = dict(as_of=as_of, clock=CLOCK, protection_confirmations=())
        if scoped:
            args["protection_bands"] = ()
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
                tested, exercised = (scoped_state_exercise(bars, as_of=as_of) if scoped else
                                     state_exercise(bars, basic, as_of=as_of))
            else:
                tested = basic
            versions["explicit_sh_fixture"].extend(tested["transitions"])
            comparison[contract]["explicit_sh_fixture"] = tested["terminal_status"]
    if batch_fixture_transitions(old_transitions)[0] != [
        row for row in baseline["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"
    ]:
        raise ValueError("FROZEN_PORTFOLIO_BASELINE_DIVERGED")
    report = dict(
        version=candidate.SCOPED_PROTECTION_VERSION if scoped else candidate.EXTERNAL_PROTECTION_VERSION,
        held_plan_clock=CLOCK, as_of=as_of.isoformat(), actions={
            name: dict(counts=dict(Counter(row["action"] for row in events)),
                       timeline=batch_fixture_transitions(events)[0]) for name, events in versions.items()
        },
        contracts=comparison, evidence_protection_status=evidence_status,
        explicit_fixture=exercised, executable=False, admitted_author_samples=0,
        author_matches=None, fills=None, pnl=None,
    )
    if scoped:
        report["handoff_source_scopes"] = {
            "OI2609": dict(sources=scoped_evidence["oil_may"]["sources"], scope="OUTSIDE_PORTFOLIO_CONTRACT"),
            "SH2701": dict(sources=scoped_evidence["soda_october"]["sources"], scope="AUTHOR_NEW_PROTECTION_RANGE_UNKNOWN"),
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-sh-fixture", action="store_true")
    parser.add_argument("--scoped-handoff-evidence", type=Path)
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
        handoff = args.scoped_handoff_evidence.read_bytes() if args.scoped_handoff_evidence else None
        if handoff is not None and sha(handoff) != HANDOFF_SHA256:
            raise ValueError("FROZEN_HANDOFF_INPUT_HASH_MISMATCH")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), json.loads(raw), json.loads(evidence),
                           exercise=args.exercise_sh_fixture, scoped_evidence=json.loads(handoff) if handoff else None)
        result["input_sha256"] = dict(baseline=BASELINE_SHA256, evidence=EVIDENCE_SHA256)
        if handoff is not None:
            result["input_sha256"]["handoff"] = HANDOFF_SHA256
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

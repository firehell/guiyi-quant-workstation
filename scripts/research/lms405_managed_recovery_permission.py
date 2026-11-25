"""Replay the nine-product lifecycle with a lock-scoped recovery endpoint."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.recovery_permission import RecoveryPermission
from lms405_managed_portfolio import action_rows, first_difference
from lms405_managed_recovery_order import REFERENCE, REFERENCE_SHA
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_protection_lot_timing import verified_json
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import at
from lms_near405_replay import encoded, sha

MODES = ("PERMISSION_UNKNOWN", "ENDPOINT_DENIED_FIXTURE", "ENDPOINT_PERMITTED_FIXTURE")


def pta_record(baseline, decision):
    lock, = [row for row in baseline["transitions"] if row["action"] == "LOCK"
             and at("2026-10-23T14:10") < datetime.fromisoformat(row["known_at"]) < at("2026-10-23T14:11")]
    state = lock["after"]
    known = datetime.fromisoformat(state["since"])
    if state["original_side"] != "LONG" or Decimal(state["plan"]["upper"]) != Decimal(6550):
        raise ValueError("RECOVERY_PERMISSION_FIXTURE_PLAN_CHANGED")
    permit = decision == "PERMIT"
    return RecoveryPermission("TA2701", state["plan"]["plan_id"], state["cycle_id"], "LONG", known,
                              known + candidate.US, decision, "FAR" if permit else None,
                              Decimal(6550) if permit else None, "TA2701_GENERATED_6550_RESEARCH_FIXTURE",
                              "TEST_FIXTURE")


def replay_mode(bars, as_of, evidence):
    opts = dict(managed_lifecycle=True, managed_recovery_permissions=evidence, timely_fixture=True)
    result = candidate.replay(bars, as_of=as_of, **opts)
    cuts = {bars[len(bars) // 2].end + candidate.US}
    cuts.update(t for record in evidence for t in (record.known_at, record.known_at + candidate.US))
    cuts.update(datetime.fromisoformat(prop["generated_at"]) for prop in result["proposals"]
                if prop.get("recovery_permission"))
    for cut in sorted(cuts):
        visible = [bar for bar in bars if bar.end + candidate.US <= cut]
        known_evidence = tuple(record for record in evidence if record.known_at < cut)
        clipped = candidate.replay(visible, as_of=cut, **(opts | dict(managed_recovery_permissions=known_evidence)))
        if clipped != candidate.replay(bars, as_of=cut, **opts):
            raise ValueError("RECOVERY_PERMISSION_PREFIX_DIVERGED")
        checkpoint = json.loads(encoded(clipped["checkpoint"]))
        if result != candidate.replay(bars, as_of=as_of, checkpoint=checkpoint, **opts):
            raise ValueError("RECOVERY_PERMISSION_RESTART_DIVERGED")
    return result, len(cuts)


def study(session, market):
    ref = verified_json(REFERENCE, REFERENCE_SHA)
    cut = datetime.fromisoformat(ref["as_of"])
    counts = {mode: Counter() for mode in MODES}
    batches = {mode: [] for mode in MODES}
    contracts = {}
    for contract in CONTRACTS:
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, r.bar_end, *ohlc(r), start=r.bar_end - FIVE)
                for r in raw if r.bar_end + candidate.US <= cut]
        digest = sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))] for b in bars]).encode())
        frozen = ref["cases"][contract]
        if digest != frozen["input_prefix_sha256"]:
            raise ValueError("RECOVERY_PERMISSION_FROZEN_MARKET_CHANGED")
        base = candidate.replay(bars, as_of=cut, managed_lifecycle=True, timely_fixture=True)
        old_actions = action_rows(base)
        if old_actions != frozen["variants"]["managed"]["transitions"]:
            raise ValueError("RECOVERY_PERMISSION_FROZEN_ACTIONS_CHANGED")
        unknown, checks = replay_mode(bars, cut, ())
        inputs = {mode: () for mode in MODES}
        if contract == "TA2701":
            inputs[MODES[1]] = (pta_record(unknown, "DENY"),)
            inputs[MODES[2]] = (pta_record(unknown, "PERMIT"),)
        modes = {}
        for mode, records in inputs.items():
            result, verified = replay_mode(bars, cut, records) if records else (unknown, checks)
            actions = action_rows(result)
            modes[mode] = dict(actions=actions, terminal=result["terminal_status"], rule_hash=result["rule_hash"],
                               input_records=[asdict(record) for record in records],
                               first_difference=first_difference(old_actions, actions), checked_prefixes=verified,
                               recovery_proposals=[proposal for proposal in result["proposals"]
                                                   if proposal.get("recovery_permission")],
                               recovery_blocks=[dict(status=e["status"], bar_end=e["bar_end"])
                                                for e in result["evaluations"] if e["status"].startswith("RECOVERY_")])
            counts[mode].update(row["action"] for row in actions)
            batches[mode].extend(result["transitions"])
        human = candidate.replay(bars, as_of=cut, managed_lifecycle=True, managed_recovery_permissions=())
        if human["transitions"]:
            raise ValueError("RECOVERY_PERMISSION_UNCONFIRMED_STATE_CHANGED")
        contracts[contract] = dict(bars=len(bars), market_sha256=digest, modes=modes,
                                   human_proposals=len(human["proposals"]), human_transitions=0)
    return dict(version="lms405-managed-recovery-permission-study-v1", as_of=cut, baseline_sha256=REFERENCE_SHA,
                contracts=contracts, actions_by_mode=counts, policy=candidate.MANAGED_RECOVERY_PERMISSION_VERSION,
                batches_by_mode={mode: batch_fixture_transitions(rows)[0] for mode, rows in batches.items()},
                author_permission_records=0, author_action_samples=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("RECOVERY_PERMISSION_") and code.isidentifier()
                        else "RECOVERY_PERMISSION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

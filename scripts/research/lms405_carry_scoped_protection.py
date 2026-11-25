"""Replay explicit protection-band choices against the same carry-in and fixed exit."""

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import LOCAL, US, at
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded

CHOICES = Path("output/lms405-protection-band-choice-20261125/verified.json")
CHOICES_SHA = "e12cdaa59764fd5a27e57de298b03a36589acca573cac08d401a29e1f932ecf1"
CONTRACTS = ("OI2609", "SA2701")
CLOCKS = {"fast_research": "1m_to_1m", "same_15m": "15m_to_15m"}


def project(result):
    proposals = {p["proposal_id"]: p for p in result["proposals"]}
    bar_ends = {e["index"]: e["bar_end"] for e in result["evaluations"]}
    rows = []
    for step in result["transitions"]:
        proposal = proposals[step["proposal_id"]]
        rows.append(dict(
            action=step["action"], reason=step["reason"], accepted_at=step["known_at"],
            bar_end=bar_ends[proposal["index"]], signal_bar_end=proposal["signal_bar_end"],
            before=[step["before"]["long"], step["before"]["short"]],
            after=[step["after"]["long"], step["after"]["short"]],
            cycle_preserved=step["before"]["cycle_id"] == step["after"]["cycle_id"],
            plan_preserved=step["before"]["plan"] == step["after"]["plan"],
            band_revision=proposal.get("protection_band_revision"), record_kind=step["record_kind"],
        ))
    return rows


def build_proofs(contract, case, bands, clock, state):
    opposite = "SHORT" if state["original_side"] == "LONG" else "LONG"
    duration = timedelta(minutes=int(clock.split("m", 1)[0]))
    proofs = []
    for band in bands:
        geometry = case[band.revision]["hypotheses"][clock]["immediate_in_band"]
        for row in geometry:
            contact_end = datetime.fromisoformat(row["segment_first_touch"])
            shape_start = datetime.fromisoformat(row["shape_end"]) - duration
            signal_end = datetime.fromisoformat(row["confirmed_at"])
            known = datetime.fromisoformat(row["available_at"])
            if not band.effective_after < shape_start < signal_end < known or signal_end < contact_end:
                raise ValueError("CARRY_SCOPED_SIGNAL_CONTEXT_CHANGED")
            proofs.append(candidate.ScopedProtectionConfirmation(
                contract, candidate.fingerprint(state), contact_end + US, signal_end, known,
                "IN_BAND_GEOMETRY_STUDY_FIXTURE", "TEST_FIXTURE", band.scope, shape_start, opposite,
            ))
    return tuple(proofs)


def protection_evaluations(result, proofs):
    """Report the driver-Bar result that first had a chance to consume each proof."""
    rows = []
    for proof in proofs:
        evaluation = next((row for row in result["evaluations"]
                           if datetime.fromisoformat(row["bar_end"]) >= proof.known_at), None)
        rows.append(dict(
            evidence_known_at=proof.known_at,
            driver_bar_end=evaluation["bar_end"] if evaluation else None,
            status=evaluation["status"] if evaluation else None,
            active_revision=evaluation["protection_band_revision"] if evaluation else None,
        ))
    return rows


def run_case(contract, case, bars):
    start = datetime.fromisoformat(case["start"])
    as_of = datetime.fromisoformat(case["cut_exclusive"]) + US
    side = case["protected_side"]
    seed = candidate.CarryInSeed(contract, start, side, False, "AUTHOR_DIRECTION_ASSUMED_UNIT_CARRY")
    attrs = dict(contract=contract, known_at=start, effective_after=start, side=side,
                 source="HYPOTHETICAL_PROTECTION_BAND_SELECTION")
    bands = []
    for key in ("early", "late"):
        lower, upper = map(Decimal, case[key]["band"])
        bands.append(ProtectionBandUpdate(revision=key, role="PROTECTION", lower=lower, upper=upper, **attrs))
    early, late = bands
    pending = ProtectionBandUpdate(revision="unselected", role="REVIEW_PENDING", **attrs)
    selection = dict(early=(early,), late=(late,), unselected=(pending,), conflicting=(early, late))
    initial_args = dict(carry_in=seed, carry_exit_evidence=(), protection_confirmations=(), protection_bands=())
    initial = candidate.replay(bars, as_of=start, timely_fixture=True, **initial_args)["current_state"]
    exit_known = at(f"{start.astimezone(LOCAL).date()}T14:02")
    exit_cut = at(f"{exit_known.date()}T14:05") + 3 * US
    outcomes, protection_fixtures = {}, {}
    for name, clock in CLOCKS.items():
        proofs = build_proofs(contract, case, (early, late), clock, initial)
        protection_fixtures[name] = [asdict(proof) for proof in proofs]
        outcomes[name] = {}
        for option, active in selection.items():
            human = candidate.replay(bars, as_of=as_of, **(initial_args | dict(protection_bands=active)))
            if human["transitions"] or human["current_state"] != initial:
                raise ValueError("CARRY_SCOPED_HUMAN_UNCONFIRMED_TRANSITION")
            args = initial_args | dict(protection_bands=active, protection_confirmations=proofs, timely_fixture=True)
            no_exit = candidate.replay(bars, as_of=as_of, **args)
            before_exit = candidate.replay(bars, as_of=exit_known, **args)
            state = before_exit["current_state"]
            if not (state["plan"] == initial["plan"] and state["cycle_id"] == initial["cycle_id"]):
                raise ValueError("CARRY_SCOPED_CHANGED_SEED_WITHOUT_EXIT")
            exit_evidence = candidate.CarryInExitEvidence(
                contract, candidate.fingerprint(state), exit_known, exit_known,
                "FIXED_ORIGINAL_EXIT_STUDY_FIXTURE", "TEST_FIXTURE",
            )
            with_exit = args | dict(carry_exit_evidence=(exit_evidence,))
            if candidate.replay(bars, as_of=exit_known, **with_exit) != before_exit:
                raise ValueError("CARRY_SCOPED_EXIT_LEAKED_AT_KNOWLEDGE_BOUNDARY")
            cleared = candidate.replay(bars, as_of=exit_cut, **with_exit)
            resumed = candidate.replay(bars, as_of=exit_cut,
                                       checkpoint=json.loads(encoded(before_exit["checkpoint"])), **with_exit)
            prefix_only = candidate.replay([b for b in bars if b.end + US <= exit_known],
                                           as_of=exit_known, **args)
            if cleared != resumed or prefix_only != before_exit:
                raise ValueError("CARRY_SCOPED_PREFIX_OR_CHECKPOINT_DIVERGED")
            if cleared["terminal_status"] != "FLAT" or cleared["transitions"][-1]["reason"] != "EXPLICIT_CARRY_IN_EXIT":
                raise ValueError("CARRY_SCOPED_FIXED_EXIT_NOT_COMPARABLE")
            outcomes[name][option] = dict(
                protection_fixture_count=len(proofs),
                protection_driver_evaluations=protection_evaluations(no_exit, proofs),
                without_exit=project(no_exit), without_exit_status=no_exit["terminal_status"],
                with_fixed_exit=project(cleared), fixed_exit_status=cleared["terminal_status"],
                human_unconfirmed_transitions=len(human["transitions"]),
                study_rule_hash=cleared["rule_hash"], checkpoint_prefix_and_exit_knowledge_checks=True,
            )
    return dict(version=candidate.CARRY_SCOPED_PROTECTION_VERSION, initial_state=initial, exit_fixture_known_at=exit_known,
                exit_cut=exit_cut, bar_count=len(bars), clock_options=CLOCKS, variants=outcomes,
                protection_fixtures=protection_fixtures)


def study(session, market, reference):
    cases = {}
    for contract in CONTRACTS:
        case = reference["cases"][contract]
        day = datetime.fromisoformat(case["published_at"]).date()
        series = read_window(session, market, contract, day)
        hashes = {f"{p}m": digest(rows) for p, rows in series.items()}
        if hashes != case["market"]:
            raise ValueError("CARRY_SCOPED_FROZEN_MARKET_CHANGED")
        cases[contract] = run_case(contract, case, series[5]) | dict(
            trading_day=day, market=hashes, source_id=case["source_id"], source=case["source"],
        )
    return dict(version="lms405-carry-scoped-protection-study-v1", input_sha256=CHOICES_SHA,
                cases=cases, original_trade_actual_position=None, author_actions_scored=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
        reference = verified_json(CHOICES, CHOICES_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), reference)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('CARRY_SCOPED_') and code.isidentifier() else 'CARRY_SCOPED_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

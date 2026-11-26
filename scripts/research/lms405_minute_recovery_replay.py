"""Replay opt-in minute recovery on frozen SH, JM, and PVC research cases."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation
from guiyi_quant.lms405.minute_recovery import US, assess_minute_recovery
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.recovery_permission import MinuteRecoveryPermission
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import at
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded, sha

SNAPSHOTS = ("lms405-snapshot-recovery-timeframes-20261126/final-a.json",
             "1081de5487e6d19db057dac196c0948974591d71c738146c61ea0cbdbf333fd5")
CONTROLS = ("lms405-recovery-shape-controls-20261126/replay-a.json",
            "eeef685eac4acbbbcbfa865b0e75753d6ff887a67e651654d53b35a270c09ab8")
CASES = (
    ("SH2701", "2026-10-27", "SHORT", 20, "1516", 5, "14:08", "OLD_RESISTANCE_NEAR",
     "WRoAkcEppg/U03 snapshot quantity assumed"),
    ("JM2609", "2026-05-21", "SHORT", 20, "1210.5", 5, "13:44", "SECOND_SHORT_TARGET_NEAR",
     "G03/G04 snapshot quantity assumed"),
    ("V2609", "2026-04-27", "LONG", 1, "5226", 1, "09:33", "STRONG_TARGET_NEAR",
     "unit stress fixture; source says no unlock"),
)


def frozen_market(series, contract, reference):
    if contract == "JM2609":
        actual = {str(p): dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()}
    else:
        actual = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
            (b.start, b.end, b.open, b.high, b.low, b.close) for b in rows
        ]).encode())) for p, rows in series.items()}
    if actual != reference["market"]:
        raise ValueError("MINUTE_REPLAY_FROZEN_MARKET_CHANGED")
    return actual


def replay_case(series, start, cutoff, request, permit):
    opts = dict(version_405=True, allow_test_fixture=True)
    evaluations = {name: Counter() for name in ("NO_PERMISSION", "DENIED_FIXTURE", "PERMITTED_FIXTURE")}
    deny = MinuteRecoveryPermission(permit.contract, permit.plan_id, permit.cycle_id, permit.original_side,
                                    permit.locked_at, permit.known_at, "DENY", None, None,
                                    "DENIED_RECOVERY_FIXTURE", "TEST_FIXTURE")
    settings = dict(NO_PERMISSION=(), DENIED_FIXTURE=(deny,), PERMITTED_FIXTURE=(permit,))
    proposals, prefix_checks = [], 0
    for bar in series[1]:
        now = bar.end + 2 * US
        if bar.start < start or now > cutoff:
            continue
        for mode, records in settings.items():
            result = assess_minute_recovery(request, series[1], series[5], permissions=records, as_of=now, **opts)
            evaluations[mode][result["status"]] += 1
            if result["after"] is not None or (mode != "PERMITTED_FIXTURE" and result["proposal"] is not None):
                raise ValueError("MINUTE_REPLAY_PRECONFIRMATION_CHANGED_POSITION")
            if result["proposal"] is None:
                continue
            proposals.append(result["proposal"])
            for check in (now - US, now):
                prefix = {p: [b for b in series[p] if b.end + US < check] for p in (1, 5)}
                clipped = assess_minute_recovery(request, prefix[1], prefix[5], permissions=records, as_of=check, **opts)
                full = assess_minute_recovery(request, series[1], series[5], permissions=records, as_of=check, **opts)
                prior = clipped["proposal"]
                if clipped != full or (check == now - US and prior and prior["confirmed_at"] >= bar.end):
                    raise ValueError("MINUTE_REPLAY_PREFIX_DIVERGED")
                prefix_checks += 1
    if not proposals:
        raise ValueError("MINUTE_REPLAY_TEST_PROPOSAL_MISSING")
    first = proposals[0]
    approval_time = first["available_at"] + US
    approval = HandoffConfirmation(first["approval_scope"], "TEST_FIXTURE:" + first["source"], True,
                                   approval_time, approval_time, "TEST_FIXTURE")
    facts = tuple(Condition(name, request.scope, request.before.contract, True,
                            request.position_since, request.position_known_at, "TEST_FIXTURE", "EVENT_TIME")
                  for name in ("POSITION_PATH_CONFIRMED", "ORIGINAL_PLAN_VALID"))
    accepted = assess_minute_recovery(request, series[1], series[5], permissions=(permit,), facts=facts,
                                     approval=approval, as_of=approval_time + US, **opts)
    if accepted["after"] is None or accepted["hypothetical_active_id"] != request.cycle_id:
        raise ValueError("MINUTE_REPLAY_LEG_PROJECTION_CHANGED")
    return dict(scenarios=evaluations, hypothetical_permission_inputs=[asdict(deny), asdict(permit)],
                proposed_with_test_permission=proposals, first_test_fixture_projection=accepted,
                prefix_checks=prefix_checks)


def study(session, market):
    snapshots, controls = (verified_json(Path("output") / path, fingerprint)["cases"]
                           for path, fingerprint in (SNAPSHOTS, CONTROLS))
    cases = {}
    for contract, day, side, units, edge, period, expected, role, scope in CASES:
        reference = controls[contract + ":" + day] if contract == "V2609" else snapshots[contract]
        if contract == "V2609":
            start, cutoff = at(day + "T09:00"), datetime.fromisoformat(reference["cutoff_exclusive"])
        else:
            start, cutoff = (datetime.fromisoformat(reference["comparison"][key])
                             for key in ("start", "cutoff_exclusive"))
        series = read_window(session, market, contract, date.fromisoformat(day))
        market_id = frozen_market(series, contract, reference)
        request = Handoff("RESUME_ORIGINAL", Position(contract, Decimal(units), Decimal(units)), side,
                          contract + ":fixture-plan", contract + ":fixture-cycle", None, start, start)
        permit = MinuteRecoveryPermission(contract, request.plan_id, request.cycle_id, side, start, start + US,
                                          "PERMIT", "NEAR", Decimal(edge), "ALLOWED_RECOVERY_FIXTURE",
                                          "TEST_FIXTURE", shape_minutes=period)
        comparison = replay_case(series, start, cutoff, request, permit)
        if comparison["proposed_with_test_permission"][0]["confirmed_at"] != at(day + "T" + expected):
            raise ValueError("MINUTE_REPLAY_FROZEN_REFERENCE_CLOCK_CHANGED")
        cases[contract] = dict(start=start, cutoff_exclusive=cutoff, market=market_id, preimage_scope=scope,
                               author_permission=None, author_action_at=None,
                               original_reference_role=role,
                               evaluated_version_binding="EXPLICIT_405_RESEARCH_FIXTURE_ASSUMPTION",
                               before=asdict(request.before),
                               **comparison)
    return dict(version="lms405-minute-recovery-study-v1", cases=cases,
                input_refs={SNAPSHOTS[0]: SNAPSHOTS[1], CONTROLS[0]: CONTROLS[1]},
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
        parser.exit(2, (code if code.isidentifier() and code.startswith("MINUTE_")
                        else "MINUTE_REPLAY_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

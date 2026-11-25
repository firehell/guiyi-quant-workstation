"""Compare two recovery order hypotheses through the nine-product managed replay."""

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_managed_portfolio import action_rows, first_difference
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_protection_lot_timing import verified_json
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

REFERENCE = Path("output/lms405-managed-portfolio-20261125/verified-source.json")
REFERENCE_SHA = "189be2418f2872c1ef0060de54d3c1490d232534a39e34f5534a45dbdeb81a2d"
MODES = ("AT_CONFIRMATION", *candidate.MANAGED_RECOVERY_ORDER_VERSIONS)
BLOCKED = "RECOVERY_NOT_KNOWN_BEFORE_SIGNAL_WINDOW"


def compare(bars, as_of, mode):
    order = None if mode == "AT_CONFIRMATION" else mode
    options = dict(managed_lifecycle=True, managed_recovery_order=order)
    full = candidate.replay(bars, as_of=as_of, timely_fixture=True, **options)
    check = bars[len(bars) // 2].end + candidate.US
    cuts = {check} | {datetime.fromisoformat(row["available_at"])
                      for row in full["evaluations"] if row["status"] == BLOCKED}
    for cutoff in sorted(cuts):
        visible = [bar for bar in bars if bar.end + candidate.US <= cutoff]
        prefix = candidate.replay(visible, as_of=cutoff, timely_fixture=True, **options)
        if prefix != candidate.replay(bars, as_of=cutoff, timely_fixture=True, **options):
            raise ValueError("RECOVERY_ORDER_PREFIX_DIVERGED")
        resume = candidate.replay(bars, as_of=as_of, timely_fixture=True,
                                  checkpoint=json.loads(encoded(prefix["checkpoint"])), **options)
        if full != resume:
            raise ValueError("RECOVERY_ORDER_CHECKPOINT_DIVERGED")
    manual = candidate.replay(bars, as_of=as_of, **options)
    if manual["transitions"] or manual["current_state"] != manual["checkpoint"]["initial_state"]:
        raise ValueError("RECOVERY_ORDER_UNCONFIRMED_STATE_CHANGED")
    proposals = {row["proposal_id"]: row for row in full["proposals"]}
    recovery_windows = []
    for step in full["transitions"]:
        if not step["action"].startswith("UNLOCK_"):
            continue
        before = step["before"]
        index = proposals[step["proposal_id"]]["index"]
        edge = Decimal(before["plan"]["upper" if before["original_side"] == "LONG" else "lower"])
        known_at = candidate._managed_recovery_known_at(before, bars, index, edge)
        if known_at is None:
            raise ValueError("RECOVERY_ORDER_ACTIVATION_MISSING")
        recovery_windows.append(dict(
            side=before["original_side"], frozen_edge=edge, locked_at=before["since"], recovery_known_at=known_at,
            shape_start=bars[index - 1].start, confirmation_start=bars[index].start,
            confirmation_end=bars[index].end, fixture_accepted_at=step["known_at"],
        ))
    return full, dict(
        version=full["version"], rule_hash=full["rule_hash"], terminal_status=full["terminal_status"],
        transitions=action_rows(full),
        order_blocks=[dict(bar_end=row["bar_end"], pattern=row["pattern"], direction=row["signal_direction"])
                      for row in full["evaluations"] if row["status"] == BLOCKED],
        recovery_not_confirmed=sum(row["status"] == "RECOVERY_RETURN_UNCONFIRMED" for row in full["evaluations"]),
        recovery_windows=recovery_windows,
        checked_prefixes_and_restarts=len(cuts),
        manual_proposals=len(manual["proposals"]), manual_transitions=0,
    )


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_SHA)
    as_of = datetime.fromisoformat(reference["as_of"])
    results = {}
    actions = {mode: Counter() for mode in MODES}
    batches_input = {mode: [] for mode in MODES}
    for contract in CONTRACTS:
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, row.bar_end, *ohlc(row), start=row.bar_end - FIVE)
                for row in raw if row.bar_end + candidate.US <= as_of]
        digest = sha(encoded([[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in bars]).encode())
        frozen = reference["cases"][contract]
        if digest != frozen["input_prefix_sha256"]:
            raise ValueError("RECOVERY_ORDER_FROZEN_MARKET_CHANGED")
        by_mode = {}
        for mode in MODES:
            full, outcome = compare(bars, as_of, mode)
            by_mode[mode] = outcome
            actions[mode].update(row["action"] for row in outcome["transitions"])
            batches_input[mode].extend(full["transitions"])
        baseline = by_mode["AT_CONFIRMATION"]
        if any(baseline[key] != frozen["variants"]["managed"][key]
               for key in ("version", "rule_hash", "transitions", "terminal_status")):
            raise ValueError("RECOVERY_ORDER_FROZEN_BASELINE_CHANGED")
        results[contract] = dict(bars=len(bars), market_sha256=digest, modes=by_mode, differences={
            mode: first_difference(baseline["transitions"], by_mode[mode]["transitions"]) for mode in MODES[1:]
        })
    batches = {mode: batch_fixture_transitions(rows)[0] for mode, rows in batches_input.items()}
    if batches["AT_CONFIRMATION"] != reference["unit_portfolio_batches"]["managed"]:
        raise ValueError("RECOVERY_ORDER_FROZEN_PORTFOLIO_CHANGED")
    return dict(version="lms405-managed-recovery-order-study-v1", reference_sha256=REFERENCE_SHA, as_of=as_of,
                market_period="5m", input_scope="MANAGED_GENERATED_BOUNDARIES_AND_UNIT_FIXTURE_POSITIONS",
                cases=results, actions_by_mode=actions, batches_by_mode=batches,
                changed_contracts={mode: [contract for contract, row in results.items() if row["differences"][mode]]
                                   for mode in MODES[1:]},
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("RECOVERY_ORDER_") and code.isidentifier()
                        else "RECOVERY_ORDER_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

"""Compare the frozen LMS candidate and the managed lifecycle on identical local bars."""

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_carry_in_study import SNAPSHOT_SHA256
from lms405_locked_exit_audit import BASELINE_SHA256
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

BASELINE = Path("output/lms405-portfolio-oct-20261125/fixture.json")
SNAPSHOTS = Path("output/lms405-sized-portfolio-20261125/visible-snapshot-comparison.json")


def action_rows(replay):
    rows = []
    proposals = {p["proposal_id"]: p for p in replay["proposals"]}
    for transition in replay["transitions"]:
        before, after = transition["before"], transition["after"]
        proposal = proposals[transition["proposal_id"]]
        action = transition["action"]
        rows.append(dict(
            at=transition["known_at"], action=action, reason=transition["reason"],
            bar_index=proposal["index"], signal_bar_end=proposal["signal_bar_end"],
            original_side=after["original_side"],
            before=[before["long"], before["short"]], after=[after["long"], after["short"]],
            plan_origin_index=after["plan"]["created_index"],
            after_exit=action.startswith(("ENTER_", "REENTER_")) and before["last_exit_at"] is not None,
        ))
    return rows


def first_difference(base_rows, managed_rows):
    baseline = {row["at"]: row for row in base_rows}
    variant = {row["at"]: row for row in managed_rows}
    for at in sorted(baseline.keys() | variant.keys(), key=datetime.fromisoformat):
        old, new = baseline.get(at), variant.get(at)
        if old != new:
            return dict(at=at, baseline=old, managed=new)
    return None


def verified_managed_replay(series, *, as_of):
    full = candidate.replay(series, as_of=as_of, managed_lifecycle=True, timely_fixture=True)
    middle = len(series) // 2
    cut = series[middle].end + candidate.US
    short = candidate.replay(series[:middle + 1], as_of=cut, managed_lifecycle=True, timely_fixture=True)
    if short != candidate.replay(series, as_of=cut, managed_lifecycle=True, timely_fixture=True):
        raise ValueError("MANAGED_PREFIX_DIVERGED")
    resumed = candidate.replay(series, as_of=as_of, managed_lifecycle=True, timely_fixture=True,
                               checkpoint=json.loads(encoded(short["checkpoint"])))
    if full != resumed:
        raise ValueError("MANAGED_CHECKPOINT_DIVERGED")
    manual = candidate.replay(series, as_of=as_of, managed_lifecycle=True)
    if manual["transitions"] or manual["checkpoint"]["initial_state"] != manual["current_state"]:
        raise ValueError("MANAGED_UNCONFIRMED_STATE_CHANGED")
    return full, len(manual["proposals"])


def visible_comparisons(contract, bars, variants, snapshots):
    closes = {b.end: b.close for b in bars}
    comparisons = []
    for snapshot in snapshots:
        if contract not in snapshot["contracts"]:
            continue
        row = snapshot["contracts"][contract]
        anchor = datetime.fromisoformat(snapshot["quote_anchor"])
        if row["quote_aligned"] is not True or closes.get(anchor) != Decimal(row["mds_close"]):
            raise ValueError("MANAGED_SNAPSHOT_QUOTE_DIVERGED")
        visible = row["author_visible_legs"]
        by_version = {}
        for name, variant in variants.items():
            before = [entry for entry in variant["transitions"] if datetime.fromisoformat(entry["at"]) < anchor]
            legs = dict(zip(("long", "short"), before[-1]["after"] if before else ("0", "0"), strict=True))
            by_version[name] = dict(
                unit_legs=legs,
                visible_directions_present={side: Decimal(legs[side]) > 0 if side in visible else None for side in legs},
            )
        comparisons.append(dict(source=snapshot["source"], quote_anchor=snapshot["quote_anchor"],
                                binding=snapshot["binding"], visible_legs=visible, versions=by_version))
    return comparisons


def study(session, market, reference, snapshots):
    as_of = datetime.fromisoformat(reference["as_of"])
    cases, baseline_transitions, managed_transitions = {}, [], []
    counts = {name: Counter() for name in ("baseline", "managed")}
    for contract in CONTRACTS:
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw]
        visible = [b for b in bars if b.end + candidate.US <= as_of]
        digest = sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))] for b in visible]).encode())
        if digest != reference["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("MANAGED_FROZEN_INPUT_DIVERGED")
        baseline = candidate.replay(visible, as_of=as_of, timely_fixture=True)
        managed, manual_suggestions = verified_managed_replay(visible, as_of=as_of)
        baseline_transitions.extend(baseline["transitions"])
        managed_transitions.extend(managed["transitions"])
        variants = {}
        for name, result in (("baseline", baseline), ("managed", managed)):
            rows = action_rows(result)
            counts[name].update(row["action"] for row in rows)
            variants[name] = dict(version=result["version"], rule_hash=result["rule_hash"],
                                  terminal_status=result["terminal_status"], transitions=rows,
                                  new_entries_after_exit=sum(row["after_exit"] for row in rows))
        cases[contract] = dict(
            bars=len(visible), input_prefix_sha256=digest, variants=variants,
            first_difference=first_difference(variants["baseline"]["transitions"], variants["managed"]["transitions"]),
            manual_suggestions_without_confirmation=manual_suggestions,
            manual_transitions_without_confirmation=0,
            visible_snapshot_directions=visible_comparisons(contract, visible, variants, snapshots["snapshots"]),
        )
    baseline_batches, _ = batch_fixture_transitions(baseline_transitions)
    if baseline_batches != [row for row in reference["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"]:
        raise ValueError("MANAGED_FROZEN_BASELINE_DIVERGED")
    managed_batches, _ = batch_fixture_transitions(managed_transitions)
    return dict(
        version="lms405-managed-portfolio-comparison-v1", baseline_sha256=BASELINE_SHA256,
        snapshots_sha256=SNAPSHOT_SHA256, snapshot_account_continuity=None,
        as_of=as_of, trading_days=[d.isoformat() for d in DAYS], cases=cases,
        actions_by_version=counts,
        unit_portfolio_batches={"baseline": baseline_batches, "managed": managed_batches},
        fixture_only=True, author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


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
        reference = verified_json(BASELINE, BASELINE_SHA256)
        snapshots = verified_json(SNAPSHOTS, SNAPSHOT_SHA256)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            value = study(session, build_market_data_service(session), reference, snapshots)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(value))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError):
        parser.exit(2, "MANAGED_PORTFOLIO_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

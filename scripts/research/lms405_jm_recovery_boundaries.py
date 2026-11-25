"""Compare carry-in recovery timing against documented JM2601 price boundaries."""

import argparse
import csv
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from lms405_carry_scoped_protection import project
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_recovery_confirmation_audit import edge_candidates
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded, sha

CONTRACT = "JM2601"
SOURCE_DIR = Path("docs/research/lms405/evidence")
SOURCE_TABLES = ("jm2601-recovery-chain-20261023.csv", "jm2601-original-records-20261023.csv")
FROZEN = Path("output/lms405-recovery-confirmation-20261125/checked.json")
FROZEN_SHA = "1d38f1d4c6f869458f5b1760ee4e488721cd928089c388b0135d1cadc0024f82"
ARTICLE_ENTRY_TIME = "2025-11-27T17:06"
WINDOWS = {
    "november_27_reported_unlock": ("2025-11-27", "2025-11-27T09:00", "2025-11-27T11:34",
                                    ("1072", "1061"), "N03", ("O01",), "jm_reported_recovery"),
    "november_28_old_boundary": ("2025-11-28", "2025-11-27T21:00", "2025-11-28T15:00:00.000003",
                                  ("1072", "1061"), "N03", ("N01", "O03"), None),
    "december_1_before_counter_m_report": ("2025-12-01", "2025-12-01T09:35", "2025-12-01T10:04",
                                          ("1077.5", "1069"), "N02", ("O02",),
                                          "jm_waiting_then_counter_m"),
}


def read_sources():
    sources = {}
    for filename in SOURCE_TABLES:
        path = SOURCE_DIR / filename
        file_sha = sha(path.read_bytes())
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                sources[row["source_id"]] = row | dict(path=str(path), sha256=file_sha)
    return sources


def geometry_comparison(series, *, start, cut, side, edges):
    result = {}
    for shape, confirm in VARIANTS:
        events = signals(series, shape, confirm, side=side, start=start + US, cut=cut)
        closes = completed(series[confirm], start, cut)
        result[f"{shape}m_to_{confirm}m"] = dict(
            signal_count=len(events), first_signal=next(iter(events), None),
            near=edge_candidates(closes, events, edges[0], side),
            far=edge_candidates(closes, events, edges[1], side),
        )
    return result


def carry_comparison(bars, *, start, cut, side, edges, known_at, source):
    base = dict(carry_in=candidate.CarryInSeed(CONTRACT, start, side, True, "HYPOTHETICAL_LOCKED_UNIT_CARRY"),
                carry_exit_evidence=(), protection_bands=(), protection_confirmations=())
    variants = {"signal_only": None}
    for location, edge in zip(("near", "far"), edges, strict=True):
        for confirmation in ("CLOSE_BEYOND", "FRESH_TWO_CLOSES"):
            variants[f"{location}_{confirmation.lower()}"] = candidate.CarryRecoveryBoundary(
                CONTRACT, side, edge, known_at, confirmation, source,
            )
    results = {}
    as_of, prefix_cut = cut - US, start + (cut - start) / 2
    for label, boundary in variants.items():
        args = base | dict(carry_recovery=boundary)
        full = candidate.replay(bars, as_of=as_of, timely_fixture=True, **args)
        prefix = candidate.replay(bars, as_of=prefix_cut, timely_fixture=True, **args)
        cut_bars = [bar for bar in bars if bar.end + US <= prefix_cut]
        if (prefix != candidate.replay(cut_bars, as_of=prefix_cut, timely_fixture=True, **args)
                or full != candidate.replay(bars, as_of=as_of, timely_fixture=True,
                                           checkpoint=json.loads(encoded(prefix["checkpoint"])), **args)):
            raise ValueError("JM_RECOVERY_PREFIX_DIVERGED")
        observations = project(full)
        if any(row["action"] != "UNLOCK_" + side or not row["cycle_preserved"] or not row["plan_preserved"]
               for row in observations):
            raise ValueError("JM_RECOVERY_ORIGINAL_LEG_CHANGED")
        manual = candidate.replay(bars, as_of=as_of, **args)
        if manual["transitions"]:
            raise ValueError("JM_RECOVERY_UNACCEPTED_ACTION")
        results[label] = dict(version=full["version"], rule_hash=full["rule_hash"],
                              transitions=observations, terminal_status=full["terminal_status"],
                              unaccepted_proposal_count=len(manual["proposals"]), prefix_and_restart_verified=True)
    return results


def study(session, market, reference):
    sources = read_sources()
    outcomes = {}
    series_by_day = {}
    side = "SHORT"
    for label, (day, raw_start, raw_cut, raw_edges, source_id, context_ids, old_key) in WINDOWS.items():
        source = sources[source_id]
        publication = ARTICLE_ENTRY_TIME if source_id == "N03" else source["published_shanghai"]
        start, cut, posted = at(raw_start), at(raw_cut), at(publication)
        edges = tuple(map(Decimal, raw_edges))
        is_review = posted >= cut
        known = start - US if is_review else posted + ONE
        if not is_review and known > start:
            raise ValueError("JM_RECOVERY_RULE_NOT_AVAILABLE_AT_START")
        series = read_window(session, market, CONTRACT, date.fromisoformat(day))
        series_by_day[day] = series
        preseed = series_by_day["2025-11-27"][5] if label == "november_28_old_boundary" else []
        hashes = {f"{period}m": digest(rows) for period, rows in series.items()}
        if old_key and hashes != {period: value["sha256"]
                                  for period, value in reference["cases"][old_key]["market"].items()}:
            raise ValueError("JM_RECOVERY_FROZEN_INPUT_CHANGED")
        minutes = completed(series[1], start, cut)
        trade_scope = ("POST_SESSION_REVIEW_HYPOTHESIS" if is_review else
                       "PRIOR_DAY_RULE_APPLICABILITY_UNKNOWN" if label == "november_28_old_boundary" else
                       "PUBLISHED_SAME_SESSION_HISTORICAL_TEXT_REVISION_UNKNOWN")
        outcomes[label] = dict(
            contract=CONTRACT, trading_day=day, start=start, cut_exclusive=cut, minute_count=len(minutes),
            extrema=[min(row.low for row in minutes), max(row.high for row in minutes)],
            original_side_hypothesis=side, near=edges[0], far=edges[1], source_id=source_id, source=source,
            observation_sources=[sources[key] for key in context_ids],
            publication=posted, boundary_scope=trade_scope, boundary_known_in_simulation=known,
            observed_author_action_at=None, market=hashes,
            extra_preseed_5m=dict(count=len(preseed), sha256=digest(preseed)) if preseed else None,
            geometry=geometry_comparison(series, start=start, cut=cut, side=side, edges=edges),
            carry=carry_comparison([*preseed, *series[5]], start=start, cut=cut, side=side, edges=edges,
                                   known_at=known, source=source_id),
        )
    return dict(version="lms405-jm-carry-recovery-boundaries-v1", cases=outcomes, original_position_actual=None,
                old_market_comparison_sha256=FROZEN_SHA, author_actions_scored=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


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
        reference = verified_json(FROZEN, FROZEN_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), reference)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('JM_RECOVERY_') and code.isidentifier() else 'JM_RECOVERY_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

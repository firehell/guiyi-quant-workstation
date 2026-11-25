"""Compare an earlier same-session break with price at original-side keybar confirmation."""

import argparse
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_study import beyond
from lms405_jm_recovery_boundaries import FROZEN, FROZEN_SHA
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_recovery_confirmation_audit import CASES
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded

JM_REFERENCE = Path("output/lms405-jm-recovery-boundaries-20261125/verified.json")
JM_SHA = "748b658565e1eca6d0e7a46907e25a1d1c569103f555701bcbb0335d83267b03"
JM_28 = "november_28_old_boundary"


def compare_boundary(bars, events, edge, side):
    """Distinguish a prior crossing in this segment from one carried across a break."""
    by_end = defaultdict(list)
    for event in events:
        by_end[event["confirmed_at"]].append(event)
    previous = segment_break = window_break = None
    first_crossing = None
    decisions = []
    for bar in bars:
        continuous = previous is not None and bar.start == previous.end
        if not continuous:
            segment_break = None
        outside = beyond(bar.close, edge, side)
        crossing = continuous and outside and not beyond(previous.close, edge, side)
        for event in by_end.pop(bar.end, ()):
            if event["available_at"] != bar.end + US or event["close"] != bar.close:
                raise ValueError("RECOVERY_SEQUENCE_CONFIRMATION_MISMATCH")
            decisions.append(event | dict(prior_break_at=segment_break, prior_break_in_window_at=window_break,
                                          close_beyond=outside,
                                          new_crossing_on_confirmation=crossing))
        if crossing:
            segment_break = window_break = bar.end + US
            if first_crossing is None:
                first_crossing = segment_break
        previous = bar
    if by_end:
        raise ValueError("RECOVERY_SEQUENCE_CONFIRMATION_MISSING")
    return dict(edge=edge, first_new_crossing_at=first_crossing, decisions=decisions)


def outcomes(series, start, cut, *, side, band):
    near, far = band if side == "LONG" else band[::-1]
    result = {}
    for shape, confirm in VARIANTS:
        events = signals(series, shape, confirm, side=side, start=start + US, cut=cut)
        closes = completed(series[confirm], start, cut)
        result[f"{shape}m_to_{confirm}m"] = {
            label: compare_boundary(closes, events, edge, side) for label, edge in (("near", near), ("far", far))
        }
    return result


def check_prefix(series, start, cut, full, *, side, band):
    # Test every candidate exactly at availability, and the same strict cutoff on a truncated input.
    cuts = {row["available_at"] for group in full.values() for edge in group.values() for row in edge["decisions"]}
    cuts.add(start + (cut - start) / 2)
    for split in sorted(cuts):
        prefix = {period: [bar for bar in bars if bar.end + US < split] for period, bars in series.items()}
        earlier = outcomes(prefix, start, split, side=side, band=band)
        for key, group in full.items():
            for location, edge in group.items():
                expected = [row for row in edge["decisions"] if row["available_at"] < split]
                prior = earlier[key][location]
                crossing = edge["first_new_crossing_at"]
                expected_crossing = crossing if crossing is not None and crossing < split else None
                if prior["decisions"] != expected or prior["first_new_crossing_at"] != expected_crossing:
                    raise ValueError("RECOVERY_SEQUENCE_PREFIX_DIVERGED")
    return len(cuts)


def study(session, market, prior_audit, jm_audit):
    from app.market_data.market_data_service import MarketDataError

    jm_following_day = jm_audit["cases"][JM_28]
    windows = (*CASES, (JM_28, "JM2601", "2025-11-28", jm_following_day["start"],
                        jm_following_day["cut_exclusive"], "SHORT", "1061 1072", "N03",
                        jm_following_day["boundary_scope"], "BOTH_LEGS_DISPLAYED_AFTER_WINDOW"))
    cases, gaps = {}, {}
    for name, contract, day, lower, upper, side, raw_band, source_id, scope, observation in windows:
        reference = jm_following_day if name == JM_28 else prior_audit["cases"].get(name)
        try:
            series = read_window(session, market, contract, date.fromisoformat(day))
        except MarketDataError as exc:
            if exc.code != "DATASET_OR_PARTITION_MISSING" or reference is not None:
                raise
            gaps[name] = dict(contract=contract, trading_day=day, code=exc.code, source_id=source_id)
            continue
        hashes = {f"{period}m": digest(rows) for period, rows in series.items()}
        if reference is not None:
            expected = reference["market"] if name == JM_28 else {
                key: row["sha256"] for key, row in reference["market"].items()
            }
            if hashes != expected:
                raise ValueError("RECOVERY_SEQUENCE_FROZEN_MARKET_CHANGED")
        start, cut, band = at(lower), at(upper), tuple(map(Decimal, raw_band.split()))
        result = outcomes(series, start, cut, side=side, band=band)
        cases[name] = dict(
            contract=contract, trading_day=day, side=side, start=start, cut_exclusive=cut, source_id=source_id,
            price_scope=scope, observation=observation, market=hashes, frozen_reference_verified=reference is not None,
            source=reference["source"] if reference is not None else None,
            minute_count=len(completed(series[1], start, cut)), result=result,
            verified_prefixes=check_prefix(series, start, cut, result, side=side, band=band),
        )
    return dict(version="lms405-recovery-sequence-study-v1", cases=cases, data_gaps=gaps,
                source_reports=dict(original=FROZEN_SHA, subsequent=JM_SHA),
                admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
        prior_audit = verified_json(FROZEN, FROZEN_SHA)
        jm_audit = verified_json(JM_REFERENCE, JM_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), prior_audit, jm_audit)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('RECOVERY_SEQUENCE_') and code.isidentifier() else 'RECOVERY_SEQUENCE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

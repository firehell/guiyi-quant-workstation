"""Check whether approximate key-bars belong to the currently active recovery run."""

import argparse
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Zone
from guiyi_quant.lms405.recovery_path import RecoveryPlan
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import verified_json
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_recovery_path_replay import CASES, replay
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import signals
from lms_near405_replay import encoded, sha

REFERENCE = Path("output/lms405-recovery-path-20261125/final.json")
REFERENCE_SHA = "46eaa17983c645fd9035dd4317851e2d47ffc26b7105f45aed37e1efaa768fa7"


def signal_context(event, by_end, shape_period, confirm_period, earliest_recovery):
    end = event["confirmed_at"]
    frame = by_end[end]
    if frame.bar_end != end or frame.known_at != event["available_at"]:
        raise ValueError("RECOVERY_SIGNAL_FRAME_TIME_MISMATCH")
    current = frame.price_recovery_candidate
    # A run of n consecutive closed minutes first qualified when the second one completed.
    active_since = end - (frame.consecutive_recovery_closes - 2) * ONE + US if current else None
    shape_start = event["shape_end"] - shape_period * ONE
    mother_start = shape_start - shape_period * ONE
    confirm_start = end - confirm_period * ONE
    if not shape_start < event["shape_end"] <= confirm_start < end:
        raise ValueError("RECOVERY_SIGNAL_GEOMETRY_ORDER_MISMATCH")
    earlier_recovery = earliest_recovery is not None and earliest_recovery < frame.known_at
    prior_confirm = current and active_since < confirm_start
    prior_shape = current and active_since < shape_start
    if not current:
        category = "RECOVERY_WITHDRAWN" if earlier_recovery else "RECOVERY_NOT_YET_OBSERVED"
    elif prior_shape:
        category = "REACHED_BEFORE_SHAPE_SAME_RUN"
    elif prior_confirm:
        category = "REACHED_ONLY_BEFORE_CONFIRMATION_SAME_RUN"
    else:
        category = "REACHED_AT_OR_DURING_CONFIRMATION_WINDOW"
    return event | dict(
        mother_start=mother_start, mother_entirely_after_release=mother_start > frame.plan.recovery.known_at,
        shape_start=shape_start, confirmation_start=confirm_start, recovery_run_known_from=active_since,
        any_prior_recovery=earlier_recovery, recovery_at_confirmation=current,
        recovery_strictly_before_confirmation_start_same_run=prior_confirm,
        recovery_strictly_before_shape_start_same_run=prior_shape, relation=category,
        first_target_already_known=frame.plan.targets[0].id in frame.previously_known_targets,
        all_targets_already_known=len(frame.previously_known_targets) == len(frame.plan.targets),
    )


def compare(series, plan, shape_period, confirm_period, cut, *, whole_pair_after_release=False):
    prefix = [bar for bar in series[1] if bar.end + US < cut]
    frames = replay(plan, prefix)
    by_end = {frame.bar_end: frame for frame in frames}
    earliest = next((frame.known_at for frame in frames if frame.price_recovery_candidate), None)
    first_full_start = plan.recovery.known_at + US
    geometry_bars = ({period: [bar for bar in rows if bar.start >= first_full_start] for period, rows in series.items()}
                     if whole_pair_after_release else series)
    events = signals(geometry_bars, shape_period, confirm_period, side=plan.side, start=first_full_start, cut=cut)
    return [signal_context(event, by_end, shape_period, confirm_period, earliest) for event in events]


def study(session, market):
    prior = verified_json(REFERENCE, REFERENCE_SHA)
    series, cases = {}, {}
    for name, contract, day, side, source, raw_bands in CASES:
        initial = prior["cases"][name]
        source_row = initial["source"]
        if sha((ARCHIVE.parent / source_row["archive_path"]).read_bytes()) != source_row["sha256"]:
            raise ValueError("RECOVERY_SIGNAL_SOURCE_CHANGED")
        availability = datetime.fromisoformat(initial["plan"]["recovery"]["known_at"])
        bounds = [tuple(map(Decimal, band.split())) for band in raw_bands]
        frozen_zones = (initial["plan"]["recovery"], *initial["plan"]["targets"])
        if initial["plan"]["side"] != side or any(
            (row["contract"], row["source"], Decimal(row["lower"]), Decimal(row["upper"]))
            != (contract, source, lo, hi) for row, (lo, hi) in zip(frozen_zones, bounds, strict=True)
        ):
            raise ValueError("RECOVERY_SIGNAL_PLAN_CHANGED")
        recovery, *targets = [Zone(f"band-{i}", contract, lo, hi, availability, source)
                              for i, (lo, hi) in enumerate(bounds)]
        plan = RecoveryPlan(side, recovery, tuple(targets))
        if (contract, day) not in series:
            series[contract, day] = read_window(session, market, contract, date.fromisoformat(day))
        bars = series[contract, day]
        digest = sha(encoded(price_digest(bars[1])).encode())
        if digest != initial["local_market_sha256"]:
            raise ValueError("RECOVERY_SIGNAL_MARKET_CHANGED")
        cap = bars[1][-1].end + 2 * US
        variants = {}
        for shape, confirm in VARIANTS:
            expanded = compare(bars, plan, shape, confirm, cap)
            whole_pair = compare(bars, plan, shape, confirm, cap, whole_pair_after_release=True)
            if whole_pair != [event for event in expanded if event["mother_entirely_after_release"]]:
                raise ValueError("RECOVERY_SIGNAL_MOTHER_WINDOW_DIVERGED")
            # Re-run at each material transition time using strict visibility to compare causal prefixes.
            cutoffs = {event["available_at"] for event in expanded} | {
                datetime.fromisoformat(row["observed_at"])
                for row in initial["routes"]["price_recovery_candidate"]["transitions"]
            }
            for cut in sorted(cutoffs):
                prefix = compare(bars, plan, shape, confirm, cut)
                if prefix != [event for event in expanded if event["available_at"] < cut]:
                    raise ValueError("RECOVERY_SIGNAL_PREFIX_DIVERGED")
            variants[f"{shape}m_to_{confirm}m"] = dict(
                events=expanded, checked_prefixes=len(cutoffs),
                relation_counts=Counter(event["relation"] for event in expanded),
                whole_pair_after_release_counts=Counter(event["relation"] for event in whole_pair),
            )
        cases[name] = dict(source=initial["source"], contract=contract, trading_day=day, side=side,
                           recovery_band=bounds[0], targets=bounds[1:], market_sha256=digest,
                           variants=variants, author_signal_at=None, author_momentum=None, author_action_at=None)
    return dict(version="lms405-recovery-signal-study-v1", evidence_kind="APPROXIMATE_PRICE_AND_KEYBAR_GEOMETRY",
                prior_report_sha256=REFERENCE_SHA, cases=cases, admitted_author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("RECOVERY_SIGNAL_") and code.isidentifier()
                        else "RECOVERY_SIGNAL_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

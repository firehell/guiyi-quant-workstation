"""Replay two independent price observations and their combinations on published bands."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Zone
from guiyi_quant.lms405.recovery_path import VERSION, RecoveryPlan, advance_recovery
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_shape_audit import price_digest
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded, sha

OLD_AUDIT = Path("output/lms405-iron-strong-side-20261125/final.json")
OLD_HASH = "9caf1ab000e388d19158b66d08a04adc2b14d38fb4cfdb7be05cca10a09c0965"
OI = "S5341725283323022"
CASES = (
    ("OI-long", "OI2701", "2026-09-11", "LONG", OI, ("10233 10270", "10318 10378", "10399 10461")),
    ("OI-short", "OI2701", "2026-09-11", "SHORT", OI, ("10198 10225", "10126 10167", "10053 10085")),
    ("I-short", "I2701", "2026-10-27", "SHORT", "A5358325549629506", ("668.5 671.5", "654 662.5")),
    ("FG-short", "FG2701", "2026-10-27", "SHORT", "A5358325549629506", ("828 832", "825 825", "814 821")),
    ("RU-short", "RU2701", "2026-10-27", "SHORT", "A5358325972992140", ("19505 19570", "19320 19420", "19220 19290")),
)
CANDIDATES = ("price_recovery_candidate", "first_target_and_recovery_candidate", "all_targets_and_recovery_candidate")


def replay(plan, minutes):
    state, frames = None, []
    for bar in minutes:
        current = advance_recovery(plan, bar, state)
        if current is not None:
            frames.append(current)
            state = current
    return frames


def summarize(frames, attribute):
    transitions = []
    active = False
    for frame in frames:
        current = getattr(frame, attribute)
        if current != active:
            transitions.append(dict(bar_end=display(frame.bar_end), observed_at=frame.known_at, active=current))
            active = current
    return dict(transitions=transitions, first_active=transitions[0]["bar_end"] if transitions else None,
                active_at_close=active)


def study(session, market):
    archive = input_sources()
    audit = verified_json(OLD_AUDIT, OLD_HASH)
    series, results = {}, {}
    for name, contract, day, side, source_id, bands in CASES:
        source = archive[source_id]
        published = datetime.fromisoformat(source["published_at"])
        source_full_minute = published.replace(second=0, microsecond=0) + ONE - US
        # Exclude the whole publication minute when the displayed timestamp is minute-precision.
        bounds = [tuple(map(Decimal, band.split())) for band in bands]
        recovery, *targets = [Zone(f"band-{i}", contract, lo, hi, source_full_minute, source_id)
                              for i, (lo, hi) in enumerate(bounds)]
        plan = RecoveryPlan(side, recovery, tuple(targets))
        if (contract, day) not in series:
            series[contract, day] = read_window(session, market, contract, date.fromisoformat(day))
        minutes = series[contract, day][1]
        market_hash = sha(encoded(price_digest(minutes)).encode())
        selected = [bar for bar in minutes if bar.start > source_full_minute]
        if not selected:
            raise ValueError("RECOVERY_PATH_WINDOW_EMPTY")
        frames = replay(plan, minutes)
        checkpoints = (len(frames) // 2, len(frames) - 1)
        for offset in checkpoints:
            if replay(plan, selected[:offset + 1]) != frames[:offset + 1]:
                raise ValueError("RECOVERY_PATH_PREFIX_DIVERGED")
            # The same immutable prior frame can continue a replay with only the later input.
            last = frames[offset]
            for bar in selected[offset + 1:]:
                last = advance_recovery(plan, bar, last)
            if last != frames[-1]:
                raise ValueError("RECOVERY_PATH_CHECKPOINT_DIVERGED")
        routes = {attribute: summarize(frames, attribute) for attribute in CANDIDATES}
        old = None
        if contract in audit["cases"]:
            old = audit["cases"][contract]["trading_days"][day]
            if old["paths"]["1m"]["sha256"] != market_hash:
                raise ValueError("RECOVERY_PATH_FROZEN_MARKET_CHANGED")
            previous = old["persistence_after_old_target_1m"]
            for attr, key in zip(CANDIDATES[1:], ("first_target", "all_targets"), strict=True):
                first = previous[key]["first_qualified_at"]
                if routes[attr]["first_active"] != (display(datetime.fromisoformat(first)) if first else None) or (
                    routes[attr]["active_at_close"] != previous[key]["qualified_at_end"]
                ):
                    raise ValueError("RECOVERY_PATH_PRIOR_DIAGNOSTIC_DIVERGED")
        results[name] = dict(
            plan=asdict(plan), trading_day=day, source=source | dict(
                sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes())),
            local_market_sha256=market_hash, plan_observable_minutes=len(selected),
            range_after_visible_publication=(min(bar.low for bar in selected), max(bar.high for bar in selected)),
            close=selected[-1].close, first_eligible_minute_end=display(selected[0].end),
            target_seen_at=frames[-1].target_seen_at, routes=routes,
            previous_author_wording=old["after_session_wording"] if old else None,
            before_publication_excluded=len(minutes) - len(selected), historical_content_verified=False,
            author_momentum=None, author_vplus=None, author_action_at=None,
            second_target_is_optional_extension=contract == "OI2701",
        )
    return dict(
        version=VERSION, cases=results, independent_permissions=True, admitted_author_action_samples=0,
        author_action_match_rate=None, executable=False, fills=None, pnl=None,
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
        parser.exit(2, (code if code.startswith("RECOVERY_PATH_") and code.isidentifier()
                        else "RECOVERY_PATH_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

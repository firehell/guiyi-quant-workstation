"""Read-only comparison of OI range, continuation and protection disclosures."""

import argparse
from datetime import date, datetime
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_replay import display
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import digest, signals
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

OLD_DIVIDER, AUG_DIVIDER = (9868, 9938), (10142, 10166)
CASES = (
    ("july_referenced_day", "OI2609", "2026-07-13", "S5320629345324155", "NEXT_DAY_REVIEW_REFERENCE",
     OLD_DIVIDER, ()),
    ("july_return", "OI2609", "2026-07-14", "S5320629345324155", "SAME_DAY_REVIEW",
     OLD_DIVIDER, ()),
    ("august_range", "OI2609", "2026-08-03", "S5327857507107123", "SAME_DAY_REVIEW",
     OLD_DIVIDER, ()),
    ("august_incomplete_short", "OI2609", "2026-08-12", "S5331132834646048", "SAME_DAY_REVIEW",
     AUG_DIVIDER, (((10051, 10073), "SHORT"),)),
    ("august_continuation", "OI2609", "2026-08-13", "S5331495384520216", "SAME_DAY_REVIEW",
     AUG_DIVIDER, (((10167, 10190), "LONG"),)),
    ("september_disclosed_extreme", "OI2701", "2026-09-16", "S5343801842598111", "SAME_DAY_REVIEW",
     None, (((10185, 10203), "LONG"),)),
    ("september_protection_plan", "OI2701", "2026-09-17", "S5343801842598111", "PREVIOUS_DAY_DISCLOSURE",
     None, ()),
)
PROTECTION = (10059, 10109)


def inside(bar, band):
    return band[0] <= bar.close <= band[1]


def range_activity(bars, band):
    low, high = band
    returns = [current for previous, current in zip(bars, bars[1:])
               if previous.end == current.start and not inside(previous, band) and inside(current, band)]
    return dict(
        band=band, bars=len(bars),
        overlap_bars=sum(bar.low <= high and bar.high >= low for bar in bars),
        closes_inside=sum(inside(bar, band) for bar in bars),
        initial_close_inside=inside(bars[0], band), final_close_inside=inside(bars[-1], band),
        first_same_segment_close_return=display(returns[0].end) if returns else None,
        same_segment_return_count=len(returns),
    )


def study(session, market):
    index = input_sources()
    cases = {}
    for label, contract, trading_day, source_id, scope, divider, nodes in CASES:
        source = index[source_id]
        _, series = read_pair(session, market, contract, (date.fromisoformat(trading_day),))
        bars = series[1]
        day = [bar for bar in bars if bar.start >= at(trading_day + "T09:00")]
        close = at(trading_day + "T15:00")
        publication = datetime.fromisoformat(source["published_at"])
        if (bars[-1].end != close or not day or not bars[0].start < close
                or (scope == "PREVIOUS_DAY_DISCLOSURE" and not publication < bars[0].start)
                or (scope != "PREVIOUS_DAY_DISCLOSURE" and not close < publication)):
            raise ValueError("OI_RANGE_CASE_TIME_SCOPE_UNVERIFIED")
        entry = dict(
            contract=contract, trading_day=trading_day, source_time_scope=scope, source_id=source_id,
            source=source | dict(archive_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes())),
            first=display(bars[0].start), last=display(bars[-1].end),
            minute_range=[min(bar.low for bar in bars), max(bar.high for bar in bars)],
            daytime_range=[min(bar.low for bar in day), max(bar.high for bar in day)],
            last_close=bars[-1].close,
            market={f"{period}m": dict(count=len(rows), sha256=digest(rows)) for period, rows in series.items()},
            divider=range_activity(bars, divider) if divider else None,
            directional_nodes=[dict(band=band, side=side, path=observations(bars, band, side)) for band, side in nodes],
            author_signal_at=None, account_position=None, author_action_at=None,
        )
        if label == "august_incomplete_short":
            ((low, high), _), = nodes
            first_touch = next((bar for bar in bars if bar.low <= high and bar.high >= low), None)
            back = next((bar for bar in bars if first_touch and first_touch.end < bar.end and inside(bar, divider)), None)
            entry["first_close_back_to_divider_after_target_entry"] = display(back.end) if back else None
        if label == "september_protection_plan":
            nearest_low = min(bar.low for bar in bars)
            entry["disclosed_protection"] = dict(
                band=PROTECTION,
                touched=any(bar.low <= PROTECTION[1] and bar.high >= PROTECTION[0] for bar in bars),
                closest_distance_above_band=nearest_low - PROTECTION[1] if nearest_low > PROTECTION[1] else None,
                long_shape_candidates={f"{shape}m_to_{confirm}m": signals(
                    series, shape, confirm, side="LONG", start=bars[0].start + US, cut=close + 2 * US,
                ) for shape, confirm in ((1, 1), (5, 1), (5, 5))},
                author_proximity_threshold=None,
            )
        cases[label] = entry
    return dict(version="lms405-oi-range-roles-v1", cases=cases, author_action_samples=0,
                author_matches=None, executable=False, fills=None, pnl=None)


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
    except (KeyError, ValueError, OSError):
        parser.exit(2, "OI_RANGE_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()

"""Compare original-direction exits and later permission using source-linked cases."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import PERIODS, VARIANTS, geometry_events, read_window
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US, at
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

SOURCE = "G25519-231"
REFERENCES = {
    "glass": (Path("output/lms405-fg-exit-20261125/final.json"),
              "42263c39dfe67167ede40436e5f0f50cd35e33225e2c4cd4ac899fffa21ef78f"),
    "pvc": (Path("output/lms405-v-exit-20261125/verified.json"),
            "b6082e514c80036c0907d39bb2690f6c9416ba1e852beab2a7ad087f64939e58"),
}
EXIT_DAY = date(2025, 11, 11)
NEXT_DAY = date(2025, 11, 12)
NEXT_NIGHT = at("2025-11-11T21:00")
NEXT_CUTOFF = at("2025-11-12T15:00:00.000002")
BASE_ZONE = (Decimal("1213"), Decimal("1224"))
EXTENSION_ZONE = (Decimal("1233"), Decimal("1244"))


def later_extension(minutes, base_edge, target_edge):
    """Price-only candidate. Two completed closes establish the base in one session."""
    previous = ready = first_ready = first_touch = first_close = None
    count = 0
    for bar in minutes:
        continuous = previous is not None and bar.start == previous.end
        above = bar.close > base_edge
        if not continuous or not above:
            count, ready = 0, None
        if above:
            if ready is not None and ready < bar.start:
                if first_touch is None and bar.high >= target_edge:
                    first_touch = dict(base_known_at=ready, bar_end=bar.end)
                if first_close is None and bar.close > target_edge:
                    first_close = dict(base_known_at=ready, bar_end=bar.end)
            count += 1
            if count == 2:
                ready = bar.end + US
                first_ready = first_ready or ready
        previous = bar
    return dict(base_edge=base_edge, extension_edge=target_edge, first_base_known_at=first_ready,
                first_extension_touch=first_touch, first_extension_strict_close=first_close)


def market_identity(series):
    return {f"{p}m": dict(bars=len(rows), sha256=sha(encoded(
        [[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in rows]).encode())) for p, rows in series.items()}


def exit_geometry(series, cutoff):
    minutes = [bar for bar in series[1] if bar.end + US < cutoff]
    if not minutes:
        raise ValueError("DIRECTIONAL_EXIT_WINDOW_EMPTY")
    return dict(
        low=min(bar.low for bar in minutes), high=max(bar.high for bar in minutes), close=minutes[-1].close,
        geometry={f"{shape}m_to_{confirm}m": geometry_events(series, shape, confirm, start=minutes[0].start,
                                                             as_of=cutoff, side="SHORT")
                  for shape, confirm in VARIANTS},
        market=market_identity(series),
    )


def study(session, market, references):
    from app.market_data.market_data_service import MarketDataError

    source = input_sources()[SOURCE]
    cutoff = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0)
    if cutoff + ONE > NEXT_NIGHT:
        raise ValueError("DIRECTIONAL_EXIT_PUBLICATION_AFTER_PLAN_START")
    windows, gaps = {}, {}
    for name, contract, day in (("soda_exit", "SA2601", EXIT_DAY), ("glass_context", "FG2601", EXIT_DAY),
                                ("soda_next_session", "SA2601", NEXT_DAY)):
        try:
            series = read_window(session, market, contract, day)
        except MarketDataError as exc:
            if exc.code != "DATASET_OR_PARTITION_MISSING":
                raise
            gaps[name] = dict(contract=contract, trading_day=day, required_periods=PERIODS, code=exc.code)
            continue
        if name == "soda_next_session":
            minutes = [bar for bar in series[1] if NEXT_NIGHT <= bar.start and bar.end + US < NEXT_CUTOFF]
            if not minutes:
                raise ValueError("DIRECTIONAL_REENTRY_WINDOW_EMPTY")
            windows[name] = dict(
                base_progress=observations(minutes, BASE_ZONE, "LONG"),
                extension_progress=observations(minutes, EXTENSION_ZONE, "LONG"),
                base_near=later_extension(minutes, BASE_ZONE[0], EXTENSION_ZONE[1]),
                base_far=later_extension(minutes, BASE_ZONE[1], EXTENSION_ZONE[1]),
                high=max(bar.high for bar in minutes), low=min(bar.low for bar in minutes),
                market=market_identity(series),
            )
        else:
            windows[name] = exit_geometry(series, cutoff)

    pair = None
    if {"soda_exit", "glass_context"} <= windows.keys():
        soda, glass = (windows[name]["geometry"] for name in ("soda_exit", "glass_context"))
        pair = {variant: sorted({row["confirmed_at"] for row in events}
                               & {row["confirmed_at"] for row in glass[variant]})
                for variant, events in soda.items()}
    glass, pvc = references["glass"], references["pvc"]
    return dict(
        version="lms405-directional-exit-audit-v1", windows=windows, data_gaps=gaps,
        source=source | dict(id=SOURCE, sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes())),
        author_reported_soda_exit=dict(position_side="LONG", confirmation_side="SHORT", trigger="VPLUS",
                                       system_automation_reported=True, system_version=None,
                                       actual_time=None, actual_quantity=None, position_after=None),
        same_minute_geometry=pair, simultaneous_glass_confirmation_required_by_author=None,
        comparison={
            "glass_reported_take_profit": dict(system="4.0.5", quantity=glass["september"]["reported_exit_size"]),
            "glass_software_close": dict(row=glass["october"]["software_rows"]["buy_close"],
                                         quantity=glass["october"]["row_quantities"],
                                         linked_to_take_profit_statement=None),
            "pvc_daytime_statement": pvc["daytime_report"],
            "pvc_later_software_close": pvc["software_row"],
            "pvc_old_lots_remaining_if_same_account": pvc["conditional_older_lots_remaining_at_first_night_if_same_account"],
        },
        reference_sha256={name: digest for name, (_, digest) in REFERENCES.items()},
        plan_historical_revision_verified=False, exit_before_reentry_sequence_confirmed=None,
        fully_flat_observed=None, admitted_author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


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
        references = {name: verified_json(path, digest) for name, (path, digest) in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            result = study(session, build_market_data_service(session), references)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "DIRECTIONAL_EXIT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

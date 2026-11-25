"""Compare two timestamp readings of the SA2701 BD and protection excerpts."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_cycle_order import fresh_geometry
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_band_choice import SODA_LIST
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

CONTRACT = "SA2701"
VERSION = "lms405-sa-bd-clock-v1"
PRIOR = (Path("output/lms405-protection-band-choice-20261125/verified.json"),
         "e12cdaa59764fd5a27e57de298b03a36589acca573cac08d401a29e1f932ecf1")
CONTROLS = {"S5353961748169131": "2026-10-14T08:43", "WRo1n9FjvJ": "2026-10-23T10:35",
            "WRot1I9NxX": "2026-10-26T09:00", "WRoCtNmpu8": "2026-10-27T09:03"}
BD_DISPLAYED = "2026-10-16T08:42"
CHOICE_DISPLAYED = "2026-10-19T09:02"
DAYS = (date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20))


def clock_controls(index):
    rows, offsets = {}, set()
    for source_id, label in CONTROLS.items():
        source = index[source_id]
        original = datetime.fromisoformat(source["published_at"])
        delta = original - at(label)
        offsets.add(delta)
        rows[source_id] = dict(displayed_label=label, original_local=original,
                               original_url=source["source_url"], offset_minutes=delta // ONE,
                               archive_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()))
    if offsets != {timedelta(hours=8)}:
        raise ValueError("SA_BD_CLOCK_CONTROLS_DIVERGED")
    return rows, offsets.pop()


def path(series, start, cutoff, bands):
    active = {period: completed(bars, start, cutoff) for period, bars in series.items()}
    minutes = active[1]
    result = dict(start=start, cutoff_exclusive=cutoff, minutes=len(minutes),
                  observed_range=[min(b.low for b in minutes), max(b.high for b in minutes)] if minutes else None,
                  last_15m_end=active[15][-1].end if active[15] else None)
    shapes = fresh_geometry(active, start, cutoff, "LONG")
    result["long_geometry"] = {key: [row["confirmed_at"] for row in rows] for key, rows in shapes.items()}
    checks = {}
    for key, (low, high) in bands.items():
        contacts = [b for b in minutes if b.low <= high and b.high >= low]
        confirms = [b for older, b in zip(minutes, minutes[1:])
                    if older.end == b.start and older.close <= high < b.close]
        checks[key] = dict(first_touch=contacts[0].end if contacts else None, touch_minutes=len(contacts),
                           first_fresh_close_cross_above=confirms[0].end if confirms else None,
                           geometry_inside={clock: [event["confirmed_at"] for event in rows if low <= event["close"] <= high]
                                            for clock, rows in shapes.items()})
    return result | dict(price_areas=checks)


def study(session, market, prior):
    controls, offset = clock_controls(input_sources())
    rows = {day: read_window(session, market, CONTRACT, day) for day in DAYS}
    market_info = {str(day): {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
                   for day, series in rows.items()}
    _, choice_day, after_day = DAYS
    if ({p: row["sha256"] for p, row in market_info[str(choice_day)].items()} != prior["market"]
            or prior["source"]["source_url"] != SODA_LIST):
        raise ValueError("SA_BD_FROZEN_CHOICE_DIVERGED")
    bd_day = DAYS[0]
    bd_bars = rows[bd_day]
    band_roles = {name: tuple(map(Decimal, prior[f"{name}_band"])) for name in ("early", "late")}
    band_roles["extreme_m_reference"] = (Decimal(960), Decimal(966))

    def through_end(day):
        return rows[day][1][-1].end + 2 * US

    def full_start(day):
        return rows[day][1][0].start

    scenarios = {}
    for name, delta in (("display_as_local_sensitivity", timedelta()), ("eight_hour_calibration", offset)):
        bd_assumed = at(BD_DISPLAYED) + delta
        choice_assumed = at(CHOICE_DISPLAYED) + delta
        scenarios[name] = dict(
            assumed_bd_published_at=bd_assumed, assumed_choice_published_at=choice_assumed,
            bd_same_trading_day_before_display=path(bd_bars, full_start(bd_day), bd_assumed, {}),
            bd_same_trading_day_after_display=path(bd_bars, bd_assumed + ONE, through_end(bd_day), {}),
            choice_before_assumed_publication=path(rows[choice_day], full_start(choice_day), choice_assumed, band_roles),
            choice_same_trading_day_after_assumed_publication=path(
                rows[choice_day], choice_assumed + ONE, through_end(choice_day), band_roles,
            ),
        )
    # The next trading day starts after both possible Oct 19 publication minutes.
    if not all(s["assumed_choice_published_at"] + ONE < full_start(after_day) for s in scenarios.values()):
        raise ValueError("SA_BD_NEXT_TRADING_DAY_PRECEDES_SOURCE")
    return dict(version=VERSION, contract=CONTRACT, excerpt_url=SODA_LIST, controls=controls,
                publication_timestamp_verified=False, scope="PUBLICATION_SENSITIVITY_AND_PRICE_ONLY",
                scenarios=scenarios, price_areas=band_roles, before_source_paths_are_retrospective=True,
                next_trading_day_after_both_readings=path(rows[after_day], full_start(after_day), through_end(after_day), band_roles),
                market=market_info, prior_report_sha256=PRIOR[1], author_bd_value=None,
                author_bd_at=None, author_action_at=None, author_actions_scored=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


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
        prior = verified_json(*PRIOR)["cases"][CONTRACT]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), prior)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "SA_BD_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

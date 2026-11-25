"""Compare distinct pressure and renewed-break events for original-short recovery."""

import argparse
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_break_pressure_comparison import continuous_groups, first_shape_after, inspect
from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

OI_SOURCE = Path("docs/research/lms405/evidence/public-conditions-20261017.csv")
OI_PUBLICATION = at("2025-12-17T22:02")
OI_PRESSURE = Decimal(9010), Decimal(9043)
OI_TRIGGER = Decimal(8969)
SH_BAND = Decimal(1859), Decimal(1870)
PRESSURE_VARIANTS = (
    "uninterrupted_observed_retest",
    "uninterrupted_full_bar_retest",
    "renewed_break_after_inside_close",
)


def ordered_followups(minutes, pressure, trigger, signals):
    fresh_breaks = [bar for group in continuous_groups(minutes)
                    for prior, bar in zip(group, group[1:]) if prior.close >= trigger > bar.close]
    branches = []
    for initial in pressure:
        for variant in PRESSURE_VARIANTS:
            observation = initial[variant]
            if observation is None:
                continue
            ready = observation["bar_end"] + US
            expires = observation["observed_until"]
            later = [bar for bar in fresh_breaks if ready < bar.start]
            attempts = []
            for cross in later:
                if cross.end + US >= expires:
                    break
                recapture = next((bar.end for bar in minutes if cross.end < bar.end
                                  and bar.end + US < expires and bar.close >= trigger), None)
                attempts.append(dict(
                    trigger_at=cross.end, trigger_recaptured_at=recapture,
                    fresh_shapes_before_pressure_reset=first_shape_after(signals, cross.end, expires),
                    fresh_shapes_before_trigger_recapture=first_shape_after(
                        signals, cross.end, recapture + US if recapture else expires,
                    ),
                ))
            branches.append(dict(
                variant=variant, pressure_at=observation["bar_end"], expires_before=expires,
                first_later_cross=later[0].end if later else None, trigger_attempts=attempts,
            ))
    return dict(fresh_crosses=[dict(at=bar.end, close=bar.close) for bar in fresh_breaks],
                branches=branches, already_below_first_close=minutes[0].close < trigger)


def observe(series, windows, band, trigger=None):
    records = {}
    for key, start, cut in windows:
        result = inspect(series, start, cut, band, None)
        records[key] = dict(start=start, as_of=cut, pressure=result)
        if trigger is not None:
            minutes = completed(series[1], start, cut)
            signals, _ = window_signals(series, start, cut, "SHORT") if result["new_breaks"] else ({}, 0)
            records[key]["renewed_trigger"] = ordered_followups(minutes, result["new_breaks"], trigger, signals)
    return records


def study(session, market):
    payload = OI_SOURCE.read_bytes()
    row = next(row for row in csv.reader(payload.decode().splitlines()) if row[0] == "I11")
    if row[1] != "https://weibo.com/1885745060/QiRHvgfga" or at(row[2].replace(" ", "T")) != OI_PUBLICATION:
        raise ValueError("LMS_SHORT_SOURCE_IDENTITY_CHANGED")
    cases = {}
    sources = input_sources()
    for contract, observed_day, source_id, band, trigger in (
        ("OI2605", "2025-12-18", "I11", OI_PRESSURE, OI_TRIGGER),
        ("OI2605", "2025-12-19", "I11", OI_PRESSURE, OI_TRIGGER),
        ("SH2609", "2026-07-27", "S5325329692361179", SH_BAND, None),
        ("SH2609", "2026-07-28", "S5325700674619111", SH_BAND, None),
    ):
        series = read_window(session, market, contract, date.fromisoformat(observed_day))
        start, end = series[1][0].start, series[1][-1].end
        day_open = at(f"{observed_day}T09:00")
        is_oil = source_id == "I11"
        if is_oil:
            source = dict(source_url=row[1], published_at=OI_PUBLICATION, evidence_id=source_id,
                          local_index=str(OI_SOURCE), local_index_sha256=sha(payload))
        else:
            source = load_source(sources, source_id)
        scopes = [("trading_night", start, day_open), ("day_session", day_open, end + 2 * US)]
        if is_oil and start <= OI_PUBLICATION < day_open:
            scopes.extend((("night_before_displayed_publication", start, OI_PUBLICATION),
                           ("after_displayed_publication_minute", OI_PUBLICATION + ONE, day_open)))
        cases[observed_day] = dict(contract=contract, evidence=source, pressure_band=band, trigger=trigger,
                                   windows=observe(series, scopes, band, trigger),
                                   market={str(p): dict(count=len(bars), sha256=digest(bars))
                                           for p, bars in series.items()},
                                   author_historical_revision_verified=False, author_version=None,
                                   author_action_at=None, author_signal_at=None,
                                   following_day_band_applicability_verified=False)
    return dict(version="lms405-ordered-original-short-v1", cases=cases, author_action_samples=0,
                author_match_rate=None, author_permission_from_market=None, fills=None, executable=False)


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
    except (OSError, KeyError, ValueError, StopIteration):
        parser.exit(2, "LMS_SHORT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

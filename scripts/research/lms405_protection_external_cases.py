"""Apply the frozen protection geometry to evidence outside the October fitting windows."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_route_comparison import WICK_VERSION, candidate_clocks
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded

FROZEN = (Path("output/lms405-protection-wick-comparison-20261126/final.json"),
          "2f6cba97a88c4ece825834485977b57e7a1ac2f860c48a29788c64b412b02b43")
# Author outcomes are source admissions only. They never enter candidate_clocks.
CASES = {
    "coal_previous_reference": ("S5290900347693045", "JM2609", "SHORT", ("1262", "1265.5"),
                                "PROTECTION_REFERENCE", "AUTHOR_REPORTED_LOCK_PROFIT_405"),
    "coal_advanced_reference": ("S5290900347693045", "JM2609", "SHORT", ("1269", "1275.5"),
                                "PROTECTION_REFERENCE", "AUTHOR_REPORTED_LOCK_PROFIT_405"),
    "caustic": ("S5293454072479751", "SH2607", "LONG", ("2017", "2039"),
                "PROTECTION_REFERENCE", "AUTHOR_REPORTED_LOCK_405"),
    "glass": ("S5301053876602715", "FG2609", "LONG", None,
              "REFERENCE_ENDPOINTS_MISSING", "AUTHOR_DESCRIBES_LOCK_NEED_405"),
    "oil": ("S5321717736278116", "OI2609", "SHORT", ("9992", "10004"),
            "PROTECTION_REFERENCE", "AUTHOR_DESCRIBES_RESPONSE_VERSION_UNKNOWN"),
    "pvc": ("S5292358960155373", "V2609", "LONG", ("5226", "5262"),
            "RECOVERY_REFERENCE_CONTROL", "AUTHOR_REPORTS_NO_LONG_UNLOCK_405"),
    "pta": ("S5311207311147936", "TA2609", "LONG", ("5800", "5820"),
            "PROTECTION_REFERENCE", "AUTHOR_REPORTS_SHORT_PAUSE_OTHER_VERSION_UNKNOWN"),
}


def evaluate_geometry(series, band, *, cutoff, side):
    start = series[1][0].start
    args = dict(start=start, side=side, compare_wick=True)
    clocks, contact = candidate_clocks(series, band, cutoff=cutoff, **args)
    checks = {instant + offset * US for instant in clocks.values() for offset in (0, 1)}
    if contact is not None:
        checks |= {contact.end + US, contact.end + 2 * US}
    for stop in checks:
        prefix = {period: [b for b in bars if b.end + US < stop] for period, bars in series.items()}
        prefix_clocks, prefix_contact = candidate_clocks(prefix, band, cutoff=stop, **args)
        if (prefix_clocks != {key: instant for key, instant in clocks.items() if instant < stop}
                or prefix_contact != (contact if contact is not None and contact.end + US < stop else None)):
            raise ValueError("EXTERNAL_PROTECTION_PREFIX_CHANGED")
    closes = {bar.end: bar.close for bar in series[1]}
    geometry_names = {name: instant for name, instant in clocks.items() if name not in ("contact", "opening")}
    locations = {}
    for name, instant in geometry_names.items():
        confirmed_at = instant - US
        close = closes[confirmed_at]
        locations[name] = dict(confirmed_at=confirmed_at, close=close,
                               distance_to_band=max(band[0] - close, close - band[1], Decimal(0)))
    return dict(
        touch_bar=asdict(contact) if contact else None, ordinary=clocks.get("ordinary"),
        advance=clocks.get("precontact"), wick={k: v for k, v in clocks.items() if k.startswith("wick_")},
        confirmation_locations=locations, checked_prefixes=len(checks),
    )


def study(session, market):
    base = verified_json(*FROZEN)
    if base["version"] != WICK_VERSION:
        raise ValueError("EXTERNAL_PROTECTION_GEOMETRY_CHANGED")
    index, loaded, results = input_sources(), {}, {}
    for label, (source_id, contract, side, raw_band, role, author) in CASES.items():
        source = load_source(index, source_id)
        published = datetime.fromisoformat(source["published_at"])
        day = date.fromisoformat(source["published_at"][:10])
        if (contract, day) not in loaded:
            loaded[contract, day] = read_window(session, market, contract, day)
        series = loaded[contract, day]
        cutoff = series[1][-1].end + 2 * US
        if cutoff > published:
            raise ValueError("EXTERNAL_PROTECTION_REPORT_NOT_AFTER_WINDOW")
        band = tuple(map(Decimal, raw_band)) if raw_band else None
        geometry = evaluate_geometry(series, band, cutoff=cutoff, side=side) if band else None
        minutes = completed(series[1], series[1][0].start, cutoff)
        results[label] = dict(
            source=source, contract=contract, trading_day=day, side=side, band=band, band_role=role,
            author_report=author, observation_cutoff=cutoff, geometry=geometry,
            geometry_use="ROLE_BLIND_CONTROL_ONLY" if role == "RECOVERY_REFERENCE_CONTROL" else "RETROSPECTIVE_ONLY",
            market={f"{period}m": dict(count=len(bars), sha256=digest(bars)) for period, bars in series.items()},
            extreme_low=asdict(min(minutes, key=lambda b: b.low)), extreme_high=asdict(max(minutes, key=lambda b: b.high)),
            original_position=None, author_signal=None, author_permission=None, author_action_at=None,
        )
    return dict(version="lms405-protection-external-cases-v1", frozen_geometry_sha256=FROZEN[1], cases=results,
                evaluation="OUTSIDE_OCTOBER_DEVELOPMENT_WINDOWS_NOT_BLIND", author_negative_lock_samples=0,
                admitted_author_timed_actions=0, author_action_match_rate=None, fills=None, pnl=None, executable=False)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("EXTERNAL_PROTECTION_") and code.isidentifier()
                        else "EXTERNAL_PROTECTION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

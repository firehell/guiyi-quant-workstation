"""Compare SH2609 price roles and recovery observations with author reports."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_handoff_study import price_window
from lms405_protection_timeframes import geometry_events
from lms405_right_side_study import ONE, at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "SH2609"
WINDOWS = {
    "jun26_old_target": ("2026-06-26", "2026-06-25T21:00", "2026-06-26T10:53", "SHORT",
                         {"old_target": "1926 1950"}),
    "jun26_reused_for_protection": ("2026-06-26", "2026-06-26T10:54", "2026-06-26T15:01", "LONG",
                                    {"new_protection": "1926 1950"}),
    "jun26_new_downside": ("2026-06-26", "2026-06-26T10:54", "2026-06-26T15:01", "SHORT",
                           {"new_target": "1912 1920", "extreme_reference": "1900 1900"}),
    "jul01_incomplete": ("2026-07-01", "2026-06-30T21:00", "2026-07-01T15:01", "SHORT",
                         {"target": "1870 1878"}),
    "jul24_wait": ("2026-07-24", "2026-07-23T21:00", "2026-07-24T15:01", "SHORT",
                   {"first_target": "1877 1888", "next_target": "1854 1863"}),
    "jul27_extreme_m": ("2026-07-27", "2026-07-24T21:00", "2026-07-27T15:01", "LONG",
                        {"extreme_m_band": "1896 1911"}),
    "jul27_no_unlock_reported": ("2026-07-27", "2026-07-24T21:00", "2026-07-27T15:01", "SHORT",
                                 {"same_day_retrospective_reference": "1859 1870"}),
    "jul28_prior_band_sensitivity": ("2026-07-28", "2026-07-27T21:00", "2026-07-28T15:01", "SHORT",
                                     {"previous_posts_reference": "1859 1870"}),
}
SOURCES = (
    "S5314010922615018", "S5314112097878799", "S5315919708685519", "S5324249205048926",
    "S5325329692361179", "S5325700674619111",
)
MINUTE_HASHES = {
    "2026-06-26": "72dc7f0ca3804cc78acb9fe27bc4e74f884818cbd72c1e3aa6bc272c167df28d",
    "2026-07-01": "08f908a7082271ba59ae195703407ec75970f725d77e6c4959cef68aae85045c",
    "2026-07-24": "2039d863991477782c46c303dc7eb0a94a46cc933ee0ad567c06d061ac0f5bc1",
    "2026-07-27": "e7cd4c6789d17135a7b9e58542ffa22ca4831b938278c7a94c66fada3cb940f8",
    "2026-07-28": "76aceb14041d6210dd46187a516979c84132bc5d2720373a859b9edc4e53c56c",
}


def confirmation_comparison(series, *, start, cutoff, side, band):
    lower, upper = tuple(map(Decimal, band.split()))
    groups = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = geometry_events(series, shape, confirm, start=start, as_of=cutoff, side=side)
        groups[f"{shape}m_to_{confirm}m"] = [
            row | dict(inside_reference_band=lower <= row["close"] <= upper,
                       strictly_beyond_far=row["close"] > upper if side == "LONG" else row["close"] < lower)
            for row in events
        ]
    return groups


def study(session, market):
    index = input_sources()
    sources = {
        key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
        for key in SOURCES
    }
    series, prices, windows = {}, {}, {}
    for day, digest in MINUTE_HASHES.items():
        raw, series[day] = read_pair(session, market, CONTRACT, (date.fromisoformat(day),))
        hashes = {f"{period}m": bars_sha(rows) for period, rows in raw.items()}
        if digest != hashes["1m"]:
            raise ValueError("FROZEN_SH2609_MARKET_CHANGED")
        minutes = series[day][1]
        prices[day] = dict(low=min(b.low for b in minutes), high=max(b.high for b in minutes),
                           close=minutes[-1].close, hashes=hashes, bars={p: len(rows) for p, rows in raw.items()})

    for name, (day, start, cutoff, side, bands) in WINDOWS.items():
        windows[name] = price_window(series[day][1], start, cutoff, side, bands)
    update_at = datetime.fromisoformat(sources[SOURCES[0]]["published_at"])
    minute = update_at.replace(second=0, microsecond=0)
    if (windows["jun26_old_target"]["cutoff_exclusive"] != minute
            or windows["jun26_reused_for_protection"]["start"] != minute + ONE):
        raise ValueError("SH2609_PLAN_PUBLICATION_WINDOW_CHANGED")
    for name in ("jun26_reused_for_protection", "jul28_prior_band_sensitivity"):
        day, start, cutoff, side, bands = WINDOWS[name]
        (band,) = bands.values()
        windows[name]["geometry"] = confirmation_comparison(series[day], start=at(start), cutoff=at(cutoff),
                                                            side=side, band=band)
    return dict(
        version="lms405-sh2609-price-roles-v1", contract=CONTRACT, sources=sources, trading_days=prices, windows=windows,
        june26_position_reports_not_bound_to_specific_system=True,
        jul28_previous_band_status="SENSITIVITY_ONLY_AUTHOR_CONTINUITY_UNVERIFIED",
        author_bar=None, author_action_at=None, actual_account_continuity=None,
        admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "SH2609_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()

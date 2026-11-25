"""Check SH2609 July price paths against the author's wait and protection descriptions."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import compare_paths, read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import US, at
from lms405_sh2609_handoff import MINUTE_HASHES
from lms405_v_zone_progress import observations
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "SH2609"
CASES = {
    "2026-07-02": ("S5316283950171905", (("weak_side_interruption", "LONG", "1895 1895"),)),
    "2026-07-13": ("S5320268287574150", (("failed_m_return", "SHORT", "1912 1917"),)),
    "2026-07-16": ("S5321356478516103", (("long_trend_prerequisite", "LONG", "1943 1955"),)),
    "2026-07-17": ("S5321719892938234", (("first_target", "SHORT", "1877 1888"),
                                        ("continuation_target", "SHORT", "1820 1840"))),
    "2026-07-21": ("S5323162820805178", (("divider_down", "SHORT", "1912 1917"),
                                        ("divider_up", "LONG", "1912 1917"))),
    "2026-07-24": ("S5324249205048926", (("first_target", "SHORT", "1877 1888"),
                                        ("second_target", "SHORT", "1854 1863"))),
    "2026-07-27": ("S5325329692361179", (("later_protection", "SHORT", "1859 1870"),
                                        ("extreme_m", "LONG", "1896 1911"))),
    "2026-07-30": ("S5326428943946299", (("next_target_upper_edge", "SHORT", "1826 1826"),)),
    "2026-07-31": ("S5326787454176470", (("reported_m_high", "LONG", "1854 1854"),
                                        ("prior_target_upper_edge", "SHORT", "1826 1826"))),
}


def study(session, market):
    index = input_sources()
    cases = {}
    for day, (source_id, levels) in CASES.items():
        raw, series = read_pair(session, market, CONTRACT, (date.fromisoformat(day),))
        hashes = {f"{period}m": bars_sha(rows) for period, rows in raw.items()}
        if day in MINUTE_HASHES and hashes["1m"] != MINUTE_HASHES[day]:
            raise ValueError("FROZEN_SH2609_MARKET_CHANGED")
        source = index[source_id]
        minutes = series[1]
        start = minutes[0].start
        cutoff = at(f"{day}T15:01")
        published_at = datetime.fromisoformat(source["published_at"]).astimezone(cutoff.tzinfo)
        if published_at.date().isoformat() != day or published_at < cutoff or minutes[-1].end + US >= cutoff:
            raise ValueError("SH2609_JULY_PRICE_WINDOW_UNVERIFIED")

        bands = {}
        for key, side, band in levels:
            lower, upper = tuple(map(Decimal, band.split()))
            far = upper if side == "LONG" else lower
            geometry = compare_paths(series, start=start, cutoff=cutoff, side=side, level=far, band=(lower, upper))
            runs = strict_runs(minutes, far, side)
            for events in geometry["events"].values():
                for event in events:
                    event["run_at_confirmation"] = runs.get(event["confirmed_at"])
            bands[key] = dict(observations=observations(minutes, (lower, upper), side), geometry=geometry)

        path = ARCHIVE.parent / source["archive_path"]
        cases[day] = dict(
            source_id=source_id, source=source | dict(archive_sha256=sha(path.read_bytes())),
            bars={f"{period}m": len(rows) for period, rows in raw.items()}, hashes=hashes,
            session_start=start, cutoff_exclusive=cutoff,
            low=min(b.low for b in minutes), high=max(b.high for b in minutes), close=minutes[-1].close,
            bands=bands,
        )
    return dict(version="lms405-sh2609-july-wait-v1", contract=CONTRACT, cases=cases,
                lookback_only=True, author_signal_matches=None, admitted_author_samples=0,
                author_action_at=None, executable=False, fills=None, pnl=None)


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
        parser.exit(2, "SH2609_JULY_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()

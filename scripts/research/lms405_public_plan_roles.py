"""Replay three public commodity plans while preserving their distinct price-area roles."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_recovery_confirmation_audit import examine
from lms405_protection_timeframes import read_window
from lms405_right_side_study import ONE, US, at
from lms_near405_replay import encoded, sha

TA_TARGET_COMMENT_AT = "2025-09-25T14:57"
CASES = {
    "G63272-537": ("RU2601", "2025-08-26", "11:30", (
        ("morning_recovery_reference", "09:00", "published", "LONG", "15885 15960"),
        ("morning_strong_target", "09:00", "published", "LONG", "16095 16200"),
        ("later_recovery_reference", "after_publication", "close", "LONG", "15885 15960"),
    )),
    "G63272-538": ("SH2601", "2025-08-28", "17:02", (
        ("first_resistance", "session_start", "close", "SHORT", "2689 2708"),
        ("second_resistance", "session_start", "close", "SHORT", "2671 2682"),
    )),
    "G63272-549": ("TA2601", "2025-09-25", "11:18", (
        ("initial_target", "09:00", "published", "LONG", "4648 4660"),
        ("expanded_target_by_comment_cutoff", "after_publication", "author_comment", "LONG", "4674 4684"),
        ("new_extreme_target", "after_publication", "close", "LONG", "4692 4696"),
        ("reused_protection_reference", "after_publication", "close", "SHORT", "4648 4660"),
        ("separate_m_reference", "after_publication", "close", "SHORT", "4640 4648"),
    )),
}
UNALIGNED_SOURCE = "S5215089620682840"


def load_source(index, key):
    source = index[key]
    path = ARCHIVE.parent / source["archive_path"]
    return source | dict(archive_sha256=sha(path.read_bytes()))


def study(session, market):
    index = input_sources()
    records = {}
    for source_id, (contract, day, published_minute, roles) in CASES.items():
        source = load_source(index, source_id)
        published = datetime.fromisoformat(source["published_at"])
        if published != at(f"{day}T{published_minute}"):
            raise ValueError("PUBLIC_PLAN_SOURCE_TIME_CHANGED")
        series = read_window(session, market, contract, date.fromisoformat(day))
        close = at(f"{day}T15:00") + 2 * US
        boundaries = dict(published=published, after_publication=published + ONE,
                          session_start=series[1][0].start, close=close)
        if source_id == "G63272-549":
            boundaries["author_comment"] = at(TA_TARGET_COMMENT_AT)
        results = {}
        for role, start, cut, side, levels in roles:
            start_at = boundaries.get(start) or at(f"{day}T{start}")
            cut_at = boundaries.get(cut) or at(f"{day}T{cut}")
            band = tuple(map(Decimal, levels.split()))
            results[role] = examine(series, start=start_at, cut=cut_at, side=side, band=band)
        records[source_id] = dict(contract=contract, source=source, trading_day=day, role_windows=results)

    return dict(version="lms405-public-plan-roles-v1", cases=records,
                author_comment=dict(source_id="G63272-549", published_at=at(TA_TARGET_COMMENT_AT),
                                    role="REPORTED_TARGET_REACHED"),
                reported_unlock_without_contract=load_source(index, UNALIGNED_SOURCE),
                originals_before_current_archives=None, admitted_author_action_samples=0,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "PUBLIC_PLAN_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()

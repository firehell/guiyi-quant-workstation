"""Replay public commodity plans while preserving their distinct price-area roles."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_recovery_confirmation_audit import examine
from lms405_protection_timeframes import read_window
from lms405_replay import display
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
MANAGEMENT_CASES = {
    "S5290904148773752": ("V2609", "2026-04-23", "16:35", (
        ("strong_target_on_gap_day", "session_start", "close", "LONG", "5226 5262"),
    )),
    "S5292358960155373": ("V2609", "2026-04-27", "16:56", (
        ("uncompleted_long_unlock_reference", "session_start", "close", "LONG", "5226 5262"),
    )),
    "S5292720017903146": ("V2609", "2026-04-28", "16:50", (
        ("first_strong_target", "session_start", "close", "LONG", "5226 5262"),
        ("second_strong_target", "session_start", "close", "LONG", "5285 5297"),
    )),
    "S5301418816702075": ("V2609", "2026-05-22", "16:56", (
        ("uncompleted_short_target", "session_start", "close", "SHORT", "4802 4830"),
    )),
    "S5311207311147936": ("TA2609", "2026-06-18", "17:12", (
        ("short_protection_reference", "session_start", "close", "LONG", "5800 5820"),
        ("counter_m_reference", "session_start", "close", "LONG", "5868 5888"),
    )),
    "S5315919112832178": ("TA2609", "2026-07-01", "17:15", (
        ("short_reentry_reference", "session_start", "close", "SHORT", "5432 5494"),
    )),
}


def load_source(index, key):
    source = index[key]
    path = ARCHIVE.parent / source["archive_path"]
    return source | dict(archive_sha256=sha(path.read_bytes()))


def study(session, market, *, batch="published-updates"):
    index = input_sources()
    use_management = batch == "management"
    cases = MANAGEMENT_CASES if use_management else CASES
    records = {}
    for source_id, (contract, day, published_minute, roles) in cases.items():
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
        record = dict(contract=contract, source=source, trading_day=day, role_windows=results)
        if use_management:
            minutes = series[1]
            record["market_extrema"] = dict(
                first_minute_end=display(minutes[0].end), open=minutes[0].open, close=minutes[-1].close,
                high_at=display(max(minutes, key=lambda bar: bar.high).end),
                low_at=display(min(minutes, key=lambda bar: bar.low).end),
            )
        records[source_id] = record

    report = dict(cases=records, originals_before_current_archives=None, admitted_author_action_samples=0,
                  executable=False, fills=None, pnl=None)
    if use_management:
        return report | dict(version="lms405-public-management-roles-v1", price_roles_retrospective_only=True)
    return report | dict(version="lms405-public-plan-roles-v1",
                         author_comment=dict(source_id="G63272-549", published_at=at(TA_TARGET_COMMENT_AT),
                                             role="REPORTED_TARGET_REACHED"),
                         reported_unlock_without_contract=load_source(index, UNALIGNED_SOURCE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", choices=("published-updates", "management"), default="published-updates")
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
            result = study(session, build_market_data_service(session), batch=args.batch)
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

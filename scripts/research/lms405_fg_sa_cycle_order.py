"""Check fresh unload and re-protect signal order against FG/SA evidence windows."""

import argparse
from datetime import date, datetime
from pathlib import Path

from lms405_fresh_reprotection import annotated_geometry
from lms405_glass_lock_followup import LOCK
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import LOCAL, ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

VERSION = "lms405-fg-sa-cycle-order-v1"
GLASS = (Path("output/lms405-glass-lock-followup-20261125/reviewed.json"),
         "cbc1a8e41badb0cf18cc97c3ce63b82953f916b5f863643561d0cd996690f9f8")
PAIR = (Path("output/lms405-fg-sa-leg-handoff-20261125/final.json"),
        "4e947ef9365180cb4330016fc18cff6737478c44f0473601f641425e8001d5da")
MORNING, CLOSE = "WRnY5bznUE", "WRo00BFM1E"
OCT_DAY = date(2026, 10, 23)
JUNE_DAY = date(2026, 6, 15)


def ordered_pairs(restores, protects):
    return [dict(restore=restore, re_protect=protect)
            for restore in restores for protect in protects
            if restore["available_at"] < protect["shape_start"]]


def fresh_geometry(series, start, cutoff, side):
    return {key: [row for row in events if row["survives_resetting_ibar_at_session_gap"]]
            for key, events in annotated_geometry(series, start, cutoff, side=side).items()}


def compare(series, start, cutoff):
    active = {period: completed(bars, start, cutoff) for period, bars in series.items()}
    by_side = {side: fresh_geometry(active, start, cutoff, side) for side in ("SHORT", "LONG")}
    checks = {event["available_at"] for clocks in by_side.values() for rows in clocks.values() for event in rows}
    checks |= {instant + US for instant in checks if instant + US < cutoff}
    for cut in sorted(checks):
        prefix = {period: completed(bars, start, cut) for period, bars in active.items()}
        for side, clocks in by_side.items():
            expected = {key: [row for row in events if row["available_at"] < cut] for key, events in clocks.items()}
            if fresh_geometry(prefix, start, cut, side) != expected:
                raise ValueError("FG_SA_CYCLE_PREFIX_DIVERGED")
    short, long = by_side["SHORT"], by_side["LONG"]
    clocks = {key: dict(short_events=short[key], long_events=long[key],
                        ordered_fresh_pairs=ordered_pairs(short[key], long[key])) for key in short}
    return dict(start=start, cutoff_exclusive=cutoff, minute_count=len(active[1]),
                prefix_checks=len(checks), clocks=clocks)


def verified_market(session, market, contract, trading_day, expected):
    series = read_window(session, market, contract, trading_day)
    if {f"{period}m": digest(bars) for period, bars in series.items()} != expected:
        raise ValueError("FG_SA_CYCLE_MARKET_CHANGED")
    return series


def study(session, market, june, october):
    evidence = {key: june["evidence"][key] for key in (LOCK, "F12")}
    for source in evidence.values():
        if sha(Path(source["evidence_path"]).read_bytes()) != source["sha256"]:
            raise ValueError("FG_SA_CYCLE_SOURCE_CHANGED")
    posts = [datetime.fromisoformat(evidence[key]["published_at"]).astimezone(LOCAL) for key in (LOCK, "F12")]
    begin, end = (post.replace(second=0, microsecond=0) for post in posts)
    glass = verified_market(session, market, "FG2609", JUNE_DAY,
                            {p: row["sha256"] for p, row in june["market_digests"][str(JUNE_DAY)].items()})
    fg_june = compare(glass, begin + ONE, end)

    stamps = october["quote_anchors"]["FG2701"]
    if stamps[MORNING] != october["quote_anchors"]["SA2701"][MORNING]:
        raise ValueError("FG_SA_CYCLE_ANCHORS_DIVERGED")
    close, = stamps[CLOSE]
    cutoff = datetime.fromisoformat(close)
    starts = [datetime.fromisoformat(t) for t in stamps[MORNING]]
    morning_post = datetime.fromisoformat(october["sources"][MORNING]["published_at"])
    starts.append(morning_post.replace(second=0, microsecond=0) + ONE)
    positions = october["positions"]
    oct_cases = {}
    for contract in ("FG2701", "SA2701"):
        series = verified_market(session, market, contract, OCT_DAY, october["markets"][contract][str(OCT_DAY)])
        snapshots = {key: value for key, value in positions[contract].items() if key in (MORNING, CLOSE)}
        for snapshot in snapshots.values():
            image = snapshot["image"]
            if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
                raise ValueError("FG_SA_CYCLE_IMAGE_CHANGED")
        oct_cases[contract] = dict(snapshots=snapshots, windows=[compare(series, t, cutoff) for t in starts])
    return dict(version=VERSION, scope="SIGNAL_ORDER_WITHOUT_AUTHOR_ACTION_ADMISSION",
                market_contract_days=[("FG2609", JUNE_DAY.isoformat()), ("FG2701", OCT_DAY.isoformat()),
                                      ("SA2701", OCT_DAY.isoformat())],
                inputs={"june": GLASS[1], "october": PAIR[1]},
                june=dict(contract="FG2609", evidence=evidence, inferred_original_short=True,
                          actual_intermediate_release=None, actual_second_lock=None, **fg_june),
                october=oct_cases, actual_trade_at=None, actual_account_continuity=None,
                absent_leg_as_zero=False, author_actions_scored=0, author_match_rate=None,
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
        june, october = verified_json(*GLASS), verified_json(*PAIR)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), june, october)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "FG_SA_CYCLE_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

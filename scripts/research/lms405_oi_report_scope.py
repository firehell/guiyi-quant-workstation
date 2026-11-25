"""Cross-check OI2701 report copies, position identities, and minute price limits."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import readback
from lms405_oi_short_retention import CONTRACT, FIRST, TICK
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_origins import allocations
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_replay import read_session_series
from lms405_right_side_study import ONE, US, at
from lms_near405_replay import encoded, sha

RETENTION = Path("output/lms405-oi-short-retention-20261125/position-report.json")
RETENTION_SHA = "290ca705a2aa5384acd0058cd02e75cb2f75a4c8f76a0468edabcd9f4f88b10c"
REPORTS = (
    ("WRov2ceWt6", "Rov2ceWt6-image3-screen.png"),
    ("WRovrUdwHi", "WRovrUdwHi-image4-screen.png"),
    ("WRozNMci2y", "RozNMci2y-report-screen.png"),
    ("WRoAkcEppg", "WRoAkcEppg-orders4-screen.png"),
    ("U03", "U03-orders5-screen.png"),
)
PLAN = "A5358325549629506"
DIVIDER = (Decimal(10240), Decimal(10283))
TRADE_DAY = date(2026, 10, 27)
EVENT = at("2026-10-26T21:05:52")  # Candidate date, since the source displays no date for the row.


def archived_image(index, source, filename):
    row = index[source]
    paths = row["images"].split(";")
    hashes = row["sha256"].split(";")
    ((path, fingerprint),) = [(path, fingerprint) for path, fingerprint in zip(paths, hashes, strict=True)
                              if Path(path).name == filename]
    if sha((ARCHIVE.parent / path).read_bytes()) != fingerprint:
        raise ValueError("OI_REPORT_ARCHIVE_CHANGED")
    return dict(source_id=source, path=path, sha256=fingerprint, published_at=row["published_at"],
                post_version=row["versions"])


def opening_contribution(minutes, event_bar, quote_end, *, lots, average):
    if event_bar.bar_end > quote_end:
        raise ValueError("OI_REPORT_AFTER_QUOTE_WINDOW")
    totals = displayed_tick_totals(average, lots, TICK)
    event_envelope = tick_bounds((event_bar,), TICK)
    earlier = tick_bounds([bar for bar in minutes if bar.bar_end < event_bar.bar_end], TICK)
    later = tick_bounds([bar for bar in minutes if event_bar.bar_end < bar.bar_end <= quote_end], TICK)
    joint = allocations(lots, None, (earlier, event_envelope, later), None, totals)
    if not joint:
        raise ValueError("OI_REPORT_DISCLOSED_AVERAGE_OUTSIDE_FULL_ENVELOPE")
    feasible = sorted({row[2] for row in joint})
    return dict(quote_minute_end=quote_end, event_tick_bounds=event_envelope,
                earlier_tick_bounds=earlier, later_tick_bounds=later, compatible_event_minute_lots=feasible,
                minimum_before_event_minute=min(row[1] for row in joint),
                minimum_after_event_minute=min(row[3] for row in joint), minimum_elsewhere=lots - max(feasible))


def study(session, market):
    with ARCHIVE.open(newline="", encoding="utf-8") as stream:
        index = {row["source_id"]: row for row in csv.DictReader(stream)}
    holdings = verified_json(RETENTION, RETENTION_SHA)
    report_copies = [archived_image(index, source, name) for source, name in REPORTS]
    if sorted(report_copies, key=lambda row: row["published_at"]) != report_copies or report_copies[0]["post_version"] != "5.0":
        raise ValueError("OI_REPORT_EARLIEST_SOURCE_CHANGED")
    context_50 = archived_image(index, REPORTS[0][0], "Rov2ceWt6-image2-screen.png")
    shot_405 = holdings["snapshots"][FIRST]
    image_405 = archived_image(index, FIRST, Path(shot_405["image"]["path"]).name)
    if image_405["sha256"] != shot_405["image"]["sha256"] or image_405["post_version"].split("（", 1)[0] != "4.0.5":
        raise ValueError("OI_REPORT_HOLDINGS_ID_CHANGED")
    actual_405 = shot_405["legs"]["short"]
    if (actual_405["quantity"], actual_405["today_quantity"], Decimal(actual_405["opening_average"])) != (
        40, 40, Decimal("10340.0"),
    ):
        raise ValueError("OI_REPORT_HOLDINGS_FIELDS_CHANGED")
    minutes = read_session_series(session, market, "oi", CONTRACT, "1m", ONE, (TRADE_DAY,))
    market_input = readback(minutes)
    if market_input.get(str(TRADE_DAY)) != holdings["market"].get(str(TRADE_DAY)):
        raise ValueError("OI_REPORT_MARKET_CHANGED")
    (event_bar,) = [row for row in minutes if row.bar_end - ONE <= EVENT < row.bar_end]
    if event_bar.bar_end + US >= datetime.fromisoformat(report_copies[0]["published_at"]):
        raise ValueError("OI_REPORT_AFTER_EARLIEST_VISIBLE_SOURCE")
    first_touch = next((row for row in minutes if row.low <= DIVIDER[1] and row.high >= DIVIDER[0]), None)
    first_close_below_upper = next((row for row in minutes if row.close < DIVIDER[1]), None)
    snapshot_window = [opening_contribution(minutes, event_bar, datetime.fromisoformat(end), lots=40,
                                            average=Decimal("10340.0"))
                       for end in holdings["capture_minutes"][FIRST]]
    return dict(
        version="lms405-oi-software-report-scope-v1", contract=CONTRACT,
        screenshots=report_copies, earlier_holdings_sha256=RETENTION_SHA,
        visible_reports=[dict(order_number=number, side="SELL", offset=offset, clock="21:05:52",
                              status="ALL_FILLED_IN_INTERFACE", order_lots=None, actual_date=None)
                         for number, offset in (("1415102", "OPEN"), ("1415109", "CLOSE"))],
        two_report_rows_have_no_verified_ordering=True,
        author_report_account=None, author_report_strategy_version=None,
        version_50_context=dict(image=context_50, displayed_side="SHORT", opening_average=Decimal("10283.0"),
                                lots=None, average_in_candidate_minute=event_bar.low <= 10283 <= event_bar.high),
        version_405_snapshot=dict(image=image_405, short=actual_405, opening_average_as_displayed="10340.0",
                                  opening_average_in_candidate_minute=(
                                      event_bar.low <= Decimal(actual_405["opening_average"]) <= event_bar.high)),
        plan=dict(source_id=PLAN, url=index[PLAN]["url"], divider=DIVIDER, publication=index[PLAN]["published_at"],
                  archive_sha256=sha((ARCHIVE.parent / index[PLAN]["path"]).read_bytes()), historical_revision_verified=False),
        candidate_date=dict(event=EVENT, trading_day=TRADE_DAY, bar_end=event_bar.bar_end,
                            event_ohlc=[event_bar.open, event_bar.high, event_bar.low, event_bar.close],
                            first_divider_touch_bar_end=first_touch.bar_end if first_touch else None,
                            first_close_below_divider_high_bar_end=first_close_below_upper.bar_end if first_close_below_upper else None),
        conditional_405_opening_price_cases=snapshot_window,
        max_405_ending_lots_from_event_minute=max(max(row["compatible_event_minute_lots"]) for row in snapshot_window),
        min_405_ending_lots_before_event_minute=min(row["minimum_before_event_minute"] for row in snapshot_window),
        min_405_ending_lots_after_event_minute=min(row["minimum_after_event_minute"] for row in snapshot_window),
        scope="HYPOTHETICAL_EVENT_DATE_AND_SAME_PRICE_ACCOUNT_FOR_MINUTE_CONTRIBUTION_ONLY",
        market=market_input, author_partial_release_lots=None, author_action_samples=0,
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
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    load_dotenv(args.env_file, override=False)
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "OI_REPORT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

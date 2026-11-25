"""Reconcile FG2701 take-profit text and software rows with completed local bars."""

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

CONTRACT = "FG2701"
SOURCE_IDS = (
    "S5343083008886025", "S5344171942741583", "A5358325549629506", "WRoCswszPF",
    "WRov1j6e10", "WRovrUdwHi", "WRoAkcEppg", "U03",
)
MINUTE_HASHES = {
    "2026-09-14": "c91019bae89eec405aacfa8492048121abd12c96d20cd36c3bdbd848326b461c",
    "2026-09-15": "16f52b4f9dc7f3a906cf5701145459fe0bc35660681adf9e466d4ebed278887f",
    "2026-09-17": "b24da503f619cbcd3c28fe6c015019bd75484465054ab3f1ebf4b1df1e13a298",
    "2026-10-27": "c8b9b516d1051a775f47ae443ae0cf632af6bcb62096cfe06073db1a1ebe637c",
}
IMAGES = {
    "close_log": ("2026-10-27/U03-orders5-screen.png",
                  "2ae117882abaf8cf38ec50e99ea662d85a3fcfdfc1a7ab4733a892ace3e2db25"),
    "lunch_log": ("2026-10-27/WRoAkcEppg-orders4-screen.png",
                  "5f6f64336c5a267e1654ad15fd951424c71161be1b0dcad609c417ee12dd72ff"),
    "earlier_night_log": ("2026-10-26/WRovrUdwHi-image4-screen.png",
                          "f5afb7da82441bcea7e0b2e96b67b038fb421e9cc51de753fe149e8fc81f0165"),
}


def minute_context(minutes, disclosed_minute, opening_averages):
    """Assume a natural date for price comparison while leaving the row undated."""
    stamp = at(disclosed_minute)
    earlier = next((b for b in minutes if b.end == stamp), None)
    during = next((b for b in minutes if b.start == stamp), None)
    if earlier is None or during is None:
        raise ValueError("FG_ORDER_COMPARISON_MINUTE_MISSING")
    if earlier.start != stamp - ONE or during.end != stamp + ONE:
        raise ValueError("FG_ORDER_COMPARISON_MINUTE_INVALID")
    return dict(assumed_minute=stamp, last_bar_ending_at_minute=dict(end=earlier.end, close=earlier.close),
                containing_bar=dict(start=during.start, end=during.end, low=during.low,
                                    high=during.high, close=during.close),
                reference_opening_averages={str(avg): dict(inside_bar=during.low <= avg <= during.high,
                                                          strictly_above_all_prices=avg > during.high,
                                                          strictly_below_all_prices=avg < during.low)
                                            for avg in map(Decimal, opening_averages)})


def shapes(series, start, cutoff, direction):
    return {f"5m_to_{confirm}m": geometry_events(series, 5, confirm, start=at(start),
                                                as_of=at(cutoff), side=direction) for confirm in (1, 5)}


def analyze_september(series):
    mark = {"retrospective_extreme_m": "940 946"}
    day = price_window(series["2026-09-14"][1], "2026-09-14T09:00", "2026-09-14T15:01", "LONG", mark)
    night = price_window(series["2026-09-15"][1], "2026-09-14T21:00", "2026-09-14T23:01", "LONG", mark)
    sept17 = price_window(series["2026-09-17"][1], "2026-09-17T09:00", "2026-09-17T15:01", "SHORT",
                          {"reported_strong_side_test": "902 902"})
    return dict(
        source="S5343083008886025", reported_low=925, day=day, followup_night=night,
        night_short_candidates=shapes(series["2026-09-15"], "2026-09-14T21:00", "2026-09-14T23:01", "SHORT"),
        later_source="S5344171942741583", later_reported_low=902, later_day=sept17,
        trading_day_lows={day: min(b.low for b in series[day][1]) for day in ("2026-09-14", "2026-09-17")},
        historical_plan_verified=False, reported_exit_size=None, later_same_system=None,
        later_reentry_verified=False,
    )


def analyze_october(series, sources):
    minutes = series[1]
    day = "2026-10-27"
    open_mark, close_mark = ("2026-10-26T22:10", f"{day}T14:08")
    recognized = {
        "sell_open": {"row_time": "22:10:35", "side": "SHORT", "displayed_status": "FILLED",
                      "same_visible_report_row_sources": ["WRovrUdwHi", "WRoAkcEppg", "U03"]},
        "buy_close": {"row_time": "14:08", "side_closed": "SHORT", "displayed_status": "FILLED",
                      "known_source": "U03"},
    }
    previous_short_post = datetime.fromisoformat(sources["WRov1j6e10"]["published_at"])
    assumed_sell_time = at("2026-10-26T22:10:35")
    plan_publication = datetime.fromisoformat(sources["A5358325549629506"]["published_at"])
    if not plan_publication < at("2026-10-26T21:00") <= previous_short_post < assumed_sell_time:
        raise ValueError("FG_EXIT_SOURCE_TIMELINE_CHANGED")
    return dict(
        software_rows=recognized, row_dates=None, row_prices=None, row_quantities=None, account=None,
        short_display_before_assumed_sell_open=dict(source="WRov1j6e10", publication=previous_short_post,
                                                    lots=20, opening_average="832"),
        sell_open_context=minute_context(minutes, open_mark, ("831", "832")),
        buy_close_context=minute_context(minutes, close_mark, ("831", "832")),
        before_open_path=price_window(minutes, "2026-10-26T21:00", open_mark, "SHORT",
                                      {"restart": "828 832", "short_target": "825 825"}),
        before_close_downside=price_window(minutes, f"{day}T09:00", close_mark, "SHORT",
                                          {"short_first_target": "825 825", "short_extension": "814 821"}),
        before_close_upside=price_window(minutes, f"{day}T09:00", close_mark, "LONG",
                                        {"protection": "829 836", "counter_m": "842 844"}),
        eligible_geometry_before_close_minute={
            direction: shapes(series, f"{day}T11:35", close_mark, direction) for direction in ("LONG", "SHORT")
        },
        visible_short_at_lunch={"with_quantity": {"lots": 20, "opening_average": "832"},
                                "without_quantity": {"lots": None, "opening_average": "831"}},
        visible_short_at_close=None, author_exit_reason=None, actual_reentry=None, cross_log_same_account=None,
    )


def compute(session, market):
    index = input_sources()
    sources = {key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
               for key in SOURCE_IDS}
    images = {}
    for key, (relative, digest) in IMAGES.items():
        source = ARCHIVE.parent / "02-持仓记录" / relative
        if sha(source.read_bytes()) != digest:
            raise ValueError("FG_EXIT_IMAGE_CHANGED")
        images[key] = dict(path=str(source), sha256=digest)
    series, coverage = {}, {}
    for day, minute_hash in MINUTE_HASHES.items():
        raw, series[day] = read_pair(session, market, CONTRACT, (date.fromisoformat(day),))
        coverage[day] = {f"{period}m": dict(count=len(rows), sha256=bars_sha(rows)) for period, rows in raw.items()}
        if coverage[day]["1m"]["sha256"] != minute_hash:
            raise ValueError("FG_EXIT_FROZEN_MARKET_CHANGED")
    return dict(version="lms405-fg-exit-study-v1", contract=CONTRACT, sources=sources, images=images, market=coverage,
                september=analyze_september(series), october=analyze_october(series["2026-10-27"], sources),
                admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None)


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
            result = compute(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError):
        parser.exit(2, "FG_EXIT_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()

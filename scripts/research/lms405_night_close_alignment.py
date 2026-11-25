"""Compare an archived night-close holdings image with subsequent protection price paths."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_i2701_case import readback
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_band_return_study import OCTOBER, OCTOBER_SHA, compare_band
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_snapshot_window import price_window
from lms405_replay import photo_comparison, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_v_ta_case import opening_gaps
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 27)
PREVIOUS = date(2026, 10, 26)
NIGHT_START = at("2026-10-26T21:00")
EXPECTED_ANCHOR = at("2026-10-26T23:00")
SOURCE = "WRovrUdwHi"
IMAGE = ARCHIVE.parent / "02-持仓记录/2026-10-26/WRovrUdwHi-image2-screen.png"
IMAGE_SHA = "db7ff1b65fc7a54a284fa7b6e1a2b20dbfb1612525d784d41bc2e7a6e5a49444"
BAND_REPORT = Path("output/lms405-band-return-20261125/final.json")
BAND_SHA = "d2ec4f106ea89339c72a2e207168881a173774d89321bd01908bde89fc3fb972"
# Image 2 shows all seven shorts. Iron's opening average is obscured.
# Where readable, the mark is opening average minus the displayed gain in price points.
ROWS = {
    "fg": (20, "832.0", "3.0"), "oi": (40, "10340.0", "97.0"), "sa": (20, "960.0", "2.0"),
    "rb": (40, "3068.3", "44.3"), "sh": (20, "1720.0", "236.0"), "i": (16, None, "18.50"),
    "ru": (20, "19575.0", "105.0"),
}
DISPLAYED_TOTAL = 176


def completed_window(bars, after, before):
    return [bar for bar in bars if bar.bar_end - ONE > after and bar.bar_end + US < before]


def candidate_window(event, bars, cutoff, anchor, tick, lots, totals):
    if event is None:
        return None
    available = datetime.fromisoformat(str(event["available_at"]))
    return dict(
        known_after_quote=available > anchor,
        completed_minute_price_window=price_window(completed_window(bars, max(anchor, available), cutoff),
                                                   tick, lots, totals),
    )


def case_result(bars, frozen, previous_candidates, comparison_bands, anchor):
    target_day = [bar for bar in bars if bar.trading_day == DAY]
    if readback(target_day)[DAY.isoformat()] != frozen["market"]:
        raise ValueError("NIGHT_CLOSE_MARKET_CHANGED")
    cutoff = datetime.fromisoformat(frozen["cutoff"])
    frontier = datetime.fromisoformat(frozen["optimistic_latest_whole_leg_start"])
    tick, lots = Decimal(frozen["tick_size"]), frozen["observed_lots"]
    totals = displayed_tick_totals(Decimal(frozen["displayed_opening_average"]), lots, tick)
    eligible = completed_window(target_day, anchor, cutoff)
    checks = {}
    for label, (levels, prerequisite, ordered) in comparison_bands.items():
        start = max(anchor, prerequisite)
        path = compare_band(completed_window(target_day, start, cutoff), band=levels, side="LONG", frontier=frontier)
        event = path["first_later_far_after_near" if ordered else "first_fresh_far_close"]
        checks[label] = dict(window_start=start, path=path, price_after_candidate=(
            candidate_window(event, target_day, cutoff, anchor, tick, lots, totals)
        ))
    gaps = [row for row in opening_gaps(bars) if row["trading_day"] == DAY.isoformat()]
    if len(gaps) != 2:
        raise ValueError("EXPECTED_NIGHT_AND_DAY_OPENINGS")
    return dict(
        later_visible_lots=lots, later_visible_average=frozen["displayed_opening_average"],
        later_cutoff=cutoff, whole_leg_latest_optimistic_start=frontier,
        whole_leg_price_after_anchor=price_window(eligible, tick, lots, totals),
        previously_identified_candidates={
            name: dict(event=event, timing=candidate_window(event, target_day, cutoff, anchor, tick, lots, totals))
            for name, event in previous_candidates.items()
        },
        fresh_price_returns_after_anchor=checks, opening_gaps=gaps,
        author_exception_definition=None, author_vplus=None, author_lock_at=None,
    )


def study(session, market, lots, bands):
    source = input_sources()[SOURCE]
    published = datetime.fromisoformat(source["published_at"])
    if sha(IMAGE.read_bytes()) != IMAGE_SHA or sum(row[0] for row in ROWS.values()) != DISPLAYED_TOTAL:
        raise ValueError("NIGHT_CLOSE_SCREENSHOT_CHANGED")
    marks = {symbol: str(Decimal(opening) - Decimal(gain))
             for symbol, (_, opening, gain) in ROWS.items() if opening is not None}
    series = {
        symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "1m", ONE,
                                    (PREVIOUS, DAY) if symbol in {"i", "sh"} else (DAY,))
        for symbol in ROWS
    }
    quotes = photo_comparison(series, NIGHT_START, published, marks)
    (match,) = quotes["joint_equal_close"]
    anchor = datetime.fromisoformat(match)
    if quotes["joint_contains"] != [match] or anchor != EXPECTED_ANCHOR:
        raise ValueError("NIGHT_CLOSE_QUOTE_ANCHOR_CHANGED")

    iron = bands["cases"]["iron_oct"]["price_only_hypotheses"]
    soda = bands["cases"]["soda_oct"]
    completion = soda["target_reuse_completion_sensitivity"]
    previous_soda = {label: row["return_path"]["first_later_far_after_near"] for label, row in completion.items()}
    previous_soda["1498_reuse"] = soda["price_only_hypotheses"]["completed_target_reuse_hypothesis"][
        "first_fresh_far_close"
    ]
    comparison_soda = {
        label: ((Decimal("1483"), Decimal("1485")), datetime.fromisoformat(row["trigger"]) + US, True)
        for label, row in completion.items()
    }
    comparison_soda["1498_reuse"] = ((Decimal("1498"), Decimal("1498")), anchor, False)
    comparison_iron = {
        "published_protection": ((Decimal("667"), Decimal("671")), anchor, False),
        "target_reuse_without_full_completion": ((Decimal("654"), Decimal("662.5")), anchor, False),
    }
    return dict(
        version="lms405-night-close-alignment-v1", source=source, image_path=str(IMAGE), image_sha256=IMAGE_SHA,
        visible_shorts={symbol: dict(lots=row[0], opening_average=row[1], gain_points=row[2])
                        for symbol, row in ROWS.items()},
        displayed_total_lots=DISPLAYED_TOTAL, quote_alignment=quotes,
        same_complete_account_scope=None, position_synchronized_with_quote=None, actual_capture_at=None,
        market={symbol: dict(bars=len(rows), sha256=bars_sha(rows)) for symbol, rows in series.items()},
        source_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()),
        lots_reference_sha256=OCTOBER_SHA, bands_reference_sha256=BAND_SHA,
        cases={
            "SH2701": case_result(series["sh"], lots["cases"]["SH2701"], previous_soda, comparison_soda, anchor),
            "I2701": case_result(series["i"], lots["cases"]["I2701"],
                                 {"target_reuse_without_full_completion": iron["target_reuse_hypothesis"][
                                     "first_fresh_far_close"]}, comparison_iron, anchor),
        },
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


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
        lots, bands = verified_json(OCTOBER, OCTOBER_SHA), verified_json(BAND_REPORT, BAND_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=40):
            result = study(session, build_market_data_service(session), lots, bands)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "NIGHT_CLOSE_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

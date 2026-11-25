"""Check RU and TA contract changes without transferring old prices or positions."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display, ohlc, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_contract_handoff import summarize_prices
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

VERSION = "lms405-ru-ta-contract-handoff-v1"
RU_OLD, RU_FIRST, RU_RANGE, RU_TREND = (
    "A5331138280554800", "S5332945076224633", "S5333311590502796", "S5334033292329356",
)
RU_LOCK, TA_PLAN, TA_PHOTO = "S5338021307876929", "A5355789916438626", "WRo2KQ43iX"
TA_IMAGE_SHA = "c98d0864d8120f9c4b7276e72d570da113e846952d504f67c877892a6a2a18a6"
OLD_RU_BANDS = {"old_strong_extension": (17050, 17100), "old_resistance": (17065, 17150)}
RU_RECAP_EDGES = {17: (17930, 18080, 18175), 18: (17930, 18080), 20: (18175, 18415)}


def first_edges(rows, edges):
    return {
        edge: dict(first_containing=next((display(b.bar_end) for b in rows if b.low <= edge <= b.high), None),
                   first_reach=next((display(b.bar_end) for b in rows if b.high >= edge), None),
                   first_strict_close=next((display(b.bar_end) for b in rows if b.close > edge), None))
        for edge in edges
    }


def old_band_diagnostic(old_close, new_rows):
    new_open = new_rows[0].open
    return {
        role: dict(bounds=bounds, synthetic_old_close_to_new_open_cross=old_close < bounds[1] < new_open,
                   physical_range_overlap_minutes=sum(b.low <= bounds[1] and b.high >= bounds[0] for b in new_rows),
                   first_valid_on_new_contract=None)
        for role, bounds in OLD_RU_BANDS.items()
    }


def lock_window(series):
    minutes = series[1]
    lower, upper = Decimal(18810), Decimal(18940)
    breach = next(b.end for b in minutes if b.close < lower)
    afterwards = [b for b in minutes if b.start >= breach]
    signals, checks = window_signals(series, breach + US, minutes[-1].end + 2 * US, "LONG")
    return dict(first_strict_close_below=display(breach),
                first_reclose_inside=next((display(b.end) for b in afterwards if lower <= b.close <= upper), None),
                first_strict_above_upper=next((display(b.end) for b in afterwards if b.close > upper), None),
                first_close_above_upper_with_fresh_shape_after_breach={
                    clock: next((display(e["confirmed_at"]) for e in events if e["close"] > upper), None)
                    for clock, events in signals.items()
                },
                shape_prefix_checks=checks, author_m_band=None, author_lock_at=None, author_unlock_at=None)


def study(session, market):
    index = input_sources()
    sources = {key: load_source(index, key) for key in (RU_OLD, RU_FIRST, RU_RANGE, RU_TREND, RU_LOCK, TA_PLAN, TA_PHOTO)}
    photo = Path(sources[TA_PHOTO]["archive_path"]).parent / "Ro2KQ43iX-position-screen.png"
    if sha((ARCHIVE.parent / photo).read_bytes()) != TA_IMAGE_SHA:
        raise ValueError("RU_TA_PHOTO_CHANGED")
    windows = {"ru": (date(2026, 8, 12), date(2026, 8, 31)), "ta": (date(2026, 8, 19), date(2026, 10, 23))}
    mapping = {
        symbol: [asdict(segment) | dict(start_trading_day=max(start, segment.start_trading_day),
                                       end_trading_day=min(end, segment.end_trading_day))
                 for segment in market.actual_dominant_segments(symbol, start, end)]
        for symbol, (start, end) in windows.items()
    }
    if [(item["contract"], item["start_trading_day"]) for item in mapping["ru"]] != [
        ("RU2609", date(2026, 8, 12)), ("RU2701", date(2026, 8, 13)),
    ]:
        raise ValueError("RU_TA_RUBBER_RANK1_BOUNDARY_CHANGED")
    coverage = {}

    def read(contract, day):
        rows = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (day,))
        coverage[f"{day}:{contract}"] = identity(rows)
        return rows

    last_old = read("RU2609", date(2026, 8, 12))
    last_pre_switch_new = read("RU2701", date(2026, 8, 12))
    first_new = read("RU2701", date(2026, 8, 13))
    old_close, prior_new_close, new_open = last_old[-1].close, last_pre_switch_new[-1].close, first_new[0].open
    recaps = {}
    for number, edges in RU_RECAP_EDGES.items():
        day = date(2026, 8, number)
        rows = read("RU2701", day)
        day_rows = [bar for bar in rows if bar.bar_end > at(f"{day}T09:00")]
        recaps[day.isoformat()] = dict(whole=summarize_prices(rows), day=summarize_prices(day_rows),
                                     target_edges=first_edges(rows, edges), author_plan_history_verified=False)
    lock_day = date(2026, 8, 31)
    lock_series = read_window(session, market, "RU2701", lock_day)
    lock_minutes = read("RU2701", lock_day)
    if [(bar.bar_end, ohlc(bar)) for bar in lock_minutes] != [(bar.end, ohlc(bar)) for bar in lock_series[1]]:
        raise ValueError("RU_TA_LOCK_MINUTE_IDENTITY_MISMATCH")
    ta_first = read("TA2701", date(2026, 8, 20))
    ta_plan_day = date(2026, 10, 19)
    ta_rows = read("TA2701", ta_plan_day)
    ta_rank1_start = next(seg["start_trading_day"] for seg in mapping["ta"] if seg["contract"] == "TA2701")
    if ta_rank1_start != ta_first[0].trading_day:
        raise ValueError("RU_TA_RANK1_START_CHANGED")
    return dict(
        version=VERSION, sources=sources, rank1=mapping, coverage=coverage,
        ru_boundary=dict(prior_old_close=old_close, same_physical_prior_close=prior_new_close,
                         new_night_open=new_open, old_to_new_open_difference=new_open - old_close,
                         same_physical_open_difference=new_open - prior_new_close,
                         new_market=summarize_prices(first_new), old_band_test=old_band_diagnostic(old_close, first_new),
                         actual_author_roll=None),
        ru_recaps=recaps, ru_lock_without_claimed_m=lock_window(lock_series),
        ta_boundary=dict(rank1_start=ta_rank1_start, first_session_open=display(ta_first[0].bar_end - ONE),
                         plan_publication=datetime.fromisoformat(sources[TA_PLAN]["published_at"]),
                         elapsed_calendar_days=(ta_plan_day - ta_rank1_start).days,
                         plan_day_prices=summarize_prices(ta_rows), author_first_use_at=None,
                         price_areas_disclosed_in_observed_plan=False, historical_content_verified=False,
                         later_visible_long_lots=34,
                         holding_image=dict(path=photo.as_posix(), sha256=TA_IMAGE_SHA)),
        mapping_scope="RETROSPECTIVE_LOCAL_RANK1_TRADING_DAY_CONTEXT", author_actions_scored=0, author_match_rate=None,
        orders=None, fills=None, pnl=None, executable=False,
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
    except (OSError, KeyError, StopIteration, ValueError) as exc:
        name = str(exc)
        parser.exit(2, (name if name.startswith("RU_TA_") and name.isidentifier() else "RU_TA_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

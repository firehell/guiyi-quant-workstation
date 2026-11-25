"""Align the August 11 coal holdings snapshot and review its later V+ target."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import photo_comparison, read_session_series
from lms405_right_side_study import ONE, at
from lms405_sh_lock_lifecycle import digest
from lms405_v_ta_case import identity
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

VERSION = "lms405-jm-august-carry-v1"
NIGHT, PHOTO, CLOSE, RECAP, ARTICLE = (
    "S5330486536971532", "WRcSq3muJk", "WRcTPnwIJV", "S5330762639348522", "A5330772570800434",
)
IMAGE = Path("02-持仓记录/2026-08-11/0023CoqUgy1ifzqicrvdrj50iq090dkz2.jpg")
IMAGE_SHA = "8a4f889d36375fb7830d976615c51cdb41f3633e86aca8d81bda83d5f8ba9d74"
DAYS = tuple(date(2026, 8, day) for day in (7, 10, 11))
# Software fields transcribed from one image. Keys map one-to-one to physical contracts.
QUOTES = {
    "fg": ("893.0", "892.0", "7.0"), "oi": ("10145.0", "10145.0", "30.0"),
    "sa": ("943.0", "959.0", "50.0"), "jm": ("1207.00", "1274.50", "99.00"),
    "j": ("1777.85", "1872.50", "103.15"), "sh": ("1874.0", "1874.0", "7.0"),
    "i": ("719.50", "719.50", "3.50"), "ru": ("16480.0", "16900.0", "475.0"),
}
COAL_LOTS = {"jm": 20, "j": 10}


def study(session, market):
    index = input_sources()
    sources = {key: load_source(index, key) for key in (NIGHT, PHOTO, CLOSE, RECAP, ARTICLE)}
    if sha((ARCHIVE.parent / IMAGE).read_bytes()) != IMAGE_SHA:
        raise ValueError("JM_AUG_PHOTO_CHANGED")
    published = datetime.fromisoformat(sources[PHOTO]["published_at"])
    recap = datetime.fromisoformat(sources[RECAP]["published_at"])
    day = DAYS[-1]
    night_start = at("2026-08-10T21:00")
    close = at("2026-08-11T15:00")
    if not night_start < datetime.fromisoformat(sources[NIGHT]["published_at"]) < published < close < recap:
        raise ValueError("JM_AUG_SOURCE_ORDER_CHANGED")
    picture_market = {
        product: read_session_series(session, market, product, f"{product.upper()}2609", "1m", ONE, (day,))
        for product in QUOTES
    }
    marks = {product: str(Decimal(open_avg) + Decimal(spread))
             for product, (open_avg, _, spread) in QUOTES.items()}
    holding_marks = {product: str(Decimal(hold_avg) + Decimal(spread))
                     for product, (_, hold_avg, spread) in QUOTES.items()}
    photo = photo_comparison(picture_market, night_start, published, marks)
    alternative = photo_comparison(picture_market, night_start, published, holding_marks)
    quote_times = tuple(datetime.fromisoformat(value) for value in photo["joint_contains"])
    if not quote_times:
        raise ValueError("JM_AUG_SHARED_QUOTE_UNVERIFIED")
    periods = {key: read_window(session, market, "JM2609", key) for key in DAYS}
    if [(b.bar_end, b.open, b.high, b.low, b.close) for b in picture_market["jm"]] != [
        (b.end, b.open, b.high, b.low, b.close) for b in periods[day][1]
    ]:
        raise ValueError("JM_AUG_AGGREGATE_INPUT_DIVERGED")
    minutes = periods[day][1]
    earlier = [b for key in DAYS[:-1] for b in periods[key][1]]
    before_quote = [b for b in minutes if b.end <= max(quote_times)]
    opening = Decimal(QUOTES["jm"][0])
    cutoff = max(quote_times)
    prefix_low = min(b.low for b in earlier + before_quote)
    prefix_high = max(b.high for b in earlier + before_quote)
    targets = (Decimal(1339), Decimal(1348))
    old_longs = {
        product: dict(quantity=lots, today_quantity=0, opening_average=Decimal(QUOTES[product][0]),
                      holding_average=Decimal(QUOTES[product][1]), strategy_identity=None,
                      since_before_trading_day_if_today_field_is_exchange_day=night_start)
        for product, lots in COAL_LOTS.items()
    }
    return dict(
        version=VERSION, sources=sources, quote_image=dict(path=IMAGE.as_posix(), sha256=IMAGE_SHA),
        minute_inputs={key: identity(rows) for key, rows in picture_market.items()},
        focal_inputs={str(key): {f"{period}m": dict(count=len(rows), sha256=digest(rows))
                                for period, rows in series.items()} for key, series in periods.items()},
        quote=photo, holding_average_alternative=alternative, visible_long_rows=old_longs,
        focal_prefix=dict(start=earlier[0].start, inclusive_quote_upper_bound=cutoff,
                          prior_two_days_low=min(b.low for b in earlier),
                          current_before_quote_low=min(b.low for b in before_quote),
                          current_before_quote_high=max(b.high for b in before_quote),
                          whole_long_rebuilt_after_prefix_start_price_compatible=prefix_low <= opening <= prefix_high),
        target=dict(role="POST_CLOSE_RECAP_OF_INTRADAY_EXTENSIONS", originally_known_at=None,
                    through_latest_joint_quote_minute=observations(before_quote, targets, "LONG"),
                    through_close=observations(minutes, targets, "LONG"),
                    high=max(b.high for b in minutes), close=minutes[-1].close,
                    permit_or_action_from_price=None),
        screenshot_exact_time=None, account_continuity=None, author_actions_scored=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
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
    except (KeyError, OSError, ValueError) as exc:
        name = str(exc)
        parser.exit(2, (name if name.startswith("JM_AUG_") and name.isidentifier() else "JM_AUG_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

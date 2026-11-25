"""Audit the PVC December 22 public counter-M context against physical-contract bars."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_break_clock import check_prefixes
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

CONTRACT = "V2605"
DAY = date(2025, 12, 23)
START, POST, NIGHT_END = map(at, (
    "2025-12-22T21:00", "2025-12-22T21:25:18", "2025-12-22T23:00",
))
POST_CUTOFF = POST + timedelta(seconds=1)
DAY_END = at("2025-12-23T15:00")
SOURCE = "S5246765834970856"
BAND = (Decimal(4690), Decimal(4704))
TARGET = (Decimal(4780), Decimal(4788))


def first_return(minutes, *, band, after):
    """A new observable overlap from above, in the same uninterrupted minute segment."""
    lower, upper = band
    return next((bar for previous, bar in zip(minutes, minutes[1:]) if bar.start > after and previous.end == bar.start
                 and previous.close > upper and bar.low <= upper and bar.high >= lower), None)


def price_path(bars, levels):
    return {str(level): dict(
        first_price_at_or_above=next((bar.end for bar in bars if bar.high >= level), None),
        first_strict_close_above=next((bar.end for bar in bars if bar.close > level), None),
    ) for level in levels}


def study(session, market):
    from app.market_data.market_data_service import MarketDataError

    dominant = market.dominant_segment_for_day("v", DAY)
    if dominant.contract != CONTRACT:
        raise ValueError("PVC_DECEMBER_MAIN_MAPPING_CHANGED")
    index = input_sources()
    source = load_source(index, SOURCE)
    if (datetime.fromisoformat(source["published_at"]) != POST
            or source["archive_sha256"] != "29c7dd29b932e8e3e471249e84a4fbec9f781de09846e6257445ad0ea6c631a3"):
        raise ValueError("PVC_DECEMBER_SOURCE_CHANGED")
    main = read_window(session, market, CONTRACT, DAY)
    night = completed(main[1], START, NIGHT_END + 2 * US)
    prepost = completed(night, START, POST)
    alternatives = {}
    for contract in ("V2601", "V2609"):
        try:
            rows = read_session_series(session, market, "v", contract, "1m", ONE, (DAY,))
        except MarketDataError as exc:
            alternatives[contract] = dict(status="LOCAL_DATA_UNVERIFIED", code=exc.code)
            continue
        until_post = [bar for bar in rows if START < bar.bar_end and bar.bar_end + US < POST]
        alternatives[contract] = dict(status="READABLE_CONTRAST_ONLY", full_day_sha256=bars_sha(rows),
                                      night_open=until_post[0].open, prior_post_min=min(bar.low for bar in until_post),
                                      prior_post_max=max(bar.high for bar in until_post))
    retest = first_return(night, band=BAND, after=POST_CUTOFF)
    follow = None
    if retest is not None:
        available = retest.end + US
        later = [bar for bar in night if bar.end > retest.end]
        follow = dict(
            bar_end=retest.end, low=retest.low, high=retest.high, close=retest.close,
            same_bar_order_known=False,
            first_later_close_below={str(edge): next((b.end for b in later if b.close < edge), None) for edge in BAND},
            subsequent_only={
                role: check_prefixes(main, side="LONG", edge=edge, start=available + US, cut=NIGHT_END + 2 * US)
                for role, edge in zip(("extreme_near", "extreme_far"), BAND, strict=True)
            },
        )
    return dict(
        version="lms405-pvc-december-counter-m-v1", trading_day=DAY, research_contract=CONTRACT,
        market_identity_scope="RANK1_PHYSICAL_CONTEXT_AUTHOR_CONTRACT_UNVERIFIED", actual_author_contract=None,
        rank1_segment=dict(start=dominant.start_trading_day, end=dominant.end_trading_day),
        author_source=source, author_post_displayed_at=POST, retrospective_publication_cutoff=POST_CUTOFF,
        historical_content_verified=False,
        night_open=night[0].open, last_prepost_close=prepost[-1].close,
        prepost_high=max(bar.high for bar in prepost), night_high=max(bar.high for bar in night),
        alternative_physical_contracts=alternatives,
        before_author_post_retrospective={
            role: check_prefixes(main, side="LONG", edge=edge, start=START, cut=POST)
            for role, edge in zip(("extreme_near", "extreme_far"), BAND, strict=True)
        },
        prepost_extreme_progress=price_path(prepost, BAND), post_retest_night=follow,
        target_progress_by_night_close=price_path(night, TARGET),
        target_progress_by_trading_day_close=price_path(completed(main[1], START, DAY_END + 2 * US), TARGET),
        market={f"{period}m": dict(count=len(rows), sha256=digest(rows)) for period, rows in main.items()},
        earlier_rebound_band=None, author_version=None, author_signal_at=None, author_action_at=None,
        author_standing_rule=None, author_action_samples=0, author_match_rate=None, fills=None, pnl=None,
        executable=False,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PVC_DECEMBER_")
                        else "PVC_DECEMBER_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

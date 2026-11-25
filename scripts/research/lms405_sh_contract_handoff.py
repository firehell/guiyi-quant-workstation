"""Compare public SH contract coverage, rank-1 sessions and the visible 2701 short."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds
from lms405_public_plan_roles import load_source
from lms405_replay import display, read_session_series
from lms405_right_side_study import ONE, at
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

VERSION = "lms405-sh-contract-handoff-v1"
PREVIEW, UPDATE, RECAP = "S5331563156866590", "S5331858361683855", "R20260817SH2611"
PLAN, OCTOBER_PHOTO, AUGUST_PHOTO = "A5355789916438626", "WRnTlEfj1t", "WRcSq3muJk"
SNAPSHOTS = {
    AUGUST_PHOTO: ("0023CoqUgy1ifzqicrvdrj50iq090dkz2.jpg",
                   "8a4f889d36375fb7830d976615c51cdb41f3633e86aca8d81bda83d5f8ba9d74"),
    OCTOBER_PHOTO: ("RnTlEfj1t-table2-screen.png",
                    "eb6bc29a2f01068202e0f79c6570602edc0b3c7acbf7a6b5102d91ec6d6f9802"),
}
WINDOWS = {
    "2026-08-13": ("SH2609", "SH2611"), "2026-08-14": ("SH2609", "SH2611"),
    "2026-08-17": ("SH2609", "SH2611", "SH2701"), "2026-10-16": ("SH2611", "SH2701"),
    "2026-10-19": ("SH2611", "SH2701"),
    **{f"2026-10-{day}": ("SH2701",) for day in (20, 21, 22, 23)},
}
OCTOBER_SHORT_AVERAGE = Decimal("1720.0")


def summarize_prices(rows):
    return dict(
        minimum=min(bar.low for bar in rows), maximum=max(bar.high for bar in rows),
        closing_price=rows[-1].close, first_end=display(rows[0].bar_end), last_end=display(rows[-1].bar_end),
    )


def average_window(bars):
    bounds = tick_bounds(bars, Decimal(1))
    if not bounds:
        raise ValueError("SH_HANDOFF_OCTOBER_PRICE_WINDOW_EMPTY")
    lots = 20
    totals = displayed_tick_totals(OCTOBER_SHORT_AVERAGE, lots, Decimal(1))
    containing = [display(b.bar_end) for b in bars if b.low <= OCTOBER_SHORT_AVERAGE <= b.high]
    return summarize_prices(bars) | dict(
        containing_minutes=len(containing), first_containing=containing[0] if containing else None,
        last_containing=containing[-1] if containing else None,
        whole_leg_price_envelope_compatible=any(bounds[0] * lots <= value <= bounds[1] * lots for value in totals),
    )


def target_progress(rows):
    return {
        edge: dict(first_reach=next((display(b.bar_end) for b in rows if b.high >= edge), None),
                   first_close_beyond=next((display(b.bar_end) for b in rows if b.close > edge), None))
        for edge in (1892, 1911, 1915)
    }


def study(session, market):
    from app.market_data.market_data_service import MarketDataError
    from app.market_data.session_clock import resolved_session_windows_for_trading_day

    index = input_sources()
    sources = {key: load_source(index, key) for key in (PREVIEW, UPDATE, RECAP, PLAN, OCTOBER_PHOTO, AUGUST_PHOTO)}
    for key, (name, digest) in SNAPSHOTS.items():
        path = Path(sources[key]["archive_path"]).parent / name
        if sha((ARCHIVE.parent / path).read_bytes()) != digest:
            raise ValueError("SH_HANDOFF_SNAPSHOT_CHANGED")
    first_day, last_day = date(2026, 8, 11), date(2026, 10, 23)
    mapping = market.actual_dominant_segments("sh", first_day, last_day)
    exchange = market.catalog.exchange_for_symbol("sh")
    aug_day = date(2026, 8, 14)
    sessions = resolved_session_windows_for_trading_day(session, exchange=exchange, symbol="sh", trading_day=aug_day)
    preview_at = datetime.fromisoformat(sources[PREVIEW]["published_at"])
    night = next((item.window for item in sessions
                  if item.is_night and item.window.start <= preview_at < item.window.end), None)
    if night is None:
        raise ValueError("SH_HANDOFF_PREVIEW_SESSION_MISMATCH")

    series, coverage = {}, {}
    for day, contracts in WINDOWS.items():
        trading_day = date.fromisoformat(day)
        for contract in contracts:
            key = f"{day}:{contract}"
            try:
                rows = read_session_series(session, market, "sh", contract, "1m", ONE, (trading_day,))
            except MarketDataError as exc:
                coverage[key] = dict(status="MDS_UNAVAILABLE", error=exc.code)
                continue
            series[key] = rows
            day_rows = [bar for bar in rows if bar.bar_end > at(f"{day}T09:00")]
            coverage[key] = dict(status="READ", identity=identity(rows), full=summarize_prices(rows),
                                 day_session=summarize_prices(day_rows))

    def rank1(day):
        value = date.fromisoformat(day)
        return next(row.contract for row in mapping if row.start_trading_day <= value <= row.end_trading_day)

    recap_day = "2026-08-17"
    recap_rows = [bar for bar in series[f"{recap_day}:SH2611"] if bar.bar_end > at(f"{recap_day}T09:00")]
    plan_cutoff = datetime.fromisoformat(sources[PLAN]["published_at"]) + ONE
    photo_at = datetime.fromisoformat(sources[OCTOBER_PHOTO]["published_at"])
    october_bars = [bar for day in (16, 19, 20, 21, 22, 23) for bar in series[f"2026-10-{day}:SH2701"]]
    october = [bar for bar in october_bars if bar.bar_end < photo_at]
    return dict(
        version=VERSION,
        mapping_scope="RETROSPECTIVE_LOCAL_RANK1_TRADING_DAY_CONTEXT",
        rank1_segments=[asdict(row) | dict(start_trading_day=max(first_day, row.start_trading_day),
                                           end_trading_day=min(last_day, row.end_trading_day)) for row in mapping],
        sources=sources, image_hashes={key: digest for key, (_, digest) in SNAPSHOTS.items()}, coverage=coverage,
        august_preview=dict(natural_day_rank1=rank1("2026-08-13"), open_session_rank1=rank1("2026-08-14"),
                            author_price_reference="SH2609", session_start=display(night.start),
                            preview_at=preview_at, author_trade_handoff_at=None),
        august_recap=dict(reported_high=1912, observed_day_high=max(b.high for b in recap_rows),
                          strong_far_edges=target_progress(recap_rows), original_plan_at=None),
        october=dict(
            retrospective_publication_cutoff=plan_cutoff, historical_content_verified=False,
            author_plan_contract="SH2701",
            plan_trading_day_rank1=rank1("2026-10-19"),
            visible_short=dict(quantity=20, today_quantity=0, opening_average=OCTOBER_SHORT_AVERAGE),
            last_pre_rank1_day=average_window([b for b in october if b.trading_day == date(2026, 10, 16)]),
            from_rank1_night_before_plan=average_window(
                [b for b in october if b.trading_day >= date(2026, 10, 19) and b.bar_end < plan_cutoff]),
            from_after_public_plan=average_window([b for b in october if b.bar_end - ONE >= plan_cutoff]),
            from_oct21_trading_day=average_window([b for b in october if b.trading_day >= date(2026, 10, 21)]),
            from_oct21_including_photo_publication_minute=average_window([
                b for b in october_bars if b.trading_day >= date(2026, 10, 21) and b.bar_end <= photo_at + ONE
            ]),
        ),
        august_visible_long=dict(contract="SH2609", quantity=16, today_quantity=16, opening_average=Decimal(1874),
                                 row_strategy=None),
        execution_roll_at=None, account_continuity=None, lot_change_formula=None, author_actions_scored=0,
        author_match_rate=None, fills=None, pnl=None, executable=False,
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
    except (OSError, KeyError, ValueError, StopIteration) as exc:
        name = str(exc)
        parser.exit(2, (name if name.startswith("SH_HANDOFF_") and name.isidentifier()
                        else "SH_HANDOFF_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

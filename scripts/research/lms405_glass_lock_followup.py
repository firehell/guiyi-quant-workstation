"""Compare glass protection hypotheses with two published 4.0.5 cases."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, EVIDENCE, LOCAL, input_sources
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_replay import display
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

CONTRACT = "FG2609"
LOCK = "S5309094833425065"
JULY = "S5318448139471722"
CONTROL = EVIDENCE / "evidence/author-control-20261016.csv"


def window(series, start, cut, *, band=None):
    segment = {period: completed(bars, start, cut) for period, bars in series.items()}
    minutes = segment[1]
    if not minutes:
        raise ValueError("GLASS_LOCK_WINDOW_EMPTY")
    candidates = {}
    for shape, confirm in VARIANTS:
        found = signals(segment, shape, confirm, side="LONG", start=start, cut=cut)
        for event in found:
            prefix_cut = event["available_at"]
            prefix = {period: [bar for bar in bars if bar.end + US < prefix_cut]
                      for period, bars in segment.items()}
            observed = signals(prefix, shape, confirm, side="LONG", start=start, cut=prefix_cut)
            if observed != [row for row in found if row["available_at"] < prefix_cut]:
                raise ValueError("GLASS_LOCK_PREFIX_DIVERGED")
        candidates[f"{shape}m_to_{confirm}m"] = found
    return dict(start=start, cutoff_exclusive=cut, minute_count=len(minutes),
                low=min(b.low for b in minutes), high=max(b.high for b in minutes), close=minutes[-1].close,
                band_observations=observations(minutes, band, "LONG") if band is not None else None,
                candidates=candidates)


def study(session, market):
    index = input_sources()
    sources = {}
    for key in ("F10", "F11", LOCK, "F12", JULY):
        source = index[key]
        file = ARCHIVE.parent / source["archive_path"] if source["archive_path"] else CONTROL
        sources[key] = source | dict(evidence_path=str(file), sha256=sha(file.read_bytes()))
    day = read_window(session, market, CONTRACT, date(2026, 6, 12))
    night = read_window(session, market, CONTRACT, date(2026, 6, 15))
    july = read_window(session, market, CONTRACT, date(2026, 7, 8))
    first_post = datetime.fromisoformat(sources[LOCK]["published_at"]).astimezone(LOCAL).replace(second=0, microsecond=0)
    batch_post = datetime.fromisoformat(sources["F12"]["published_at"]).astimezone(LOCAL).replace(second=0, microsecond=0)
    night_start = night[1][0].start
    if not night_start < first_post < batch_post or night_start.astimezone(LOCAL).date() != first_post.date():
        raise ValueError("GLASS_LOCK_NIGHT_SOURCE_WINDOW_CHANGED")
    june = dict(
        day_session=window(day, at("2026-06-12T09:00"), at("2026-06-12T15:01")),
        before_lock_report=window(night, night_start, first_post),
        between_reports=window(night, first_post + ONE, batch_post),
        night_trading_day="2026-06-15", night_start=display(night_start),
        observation="LOCK_REPORTED_BY_21_18_AND_LATER_COMBINED_REPORT",
        later_report_independent_lock=None, stop_profit_system=None,
    )
    july_case = window(july, july[1][0].start, at("2026-07-08T15:01"),
                       band=(Decimal(957), Decimal(960))) | dict(
        observation="REPORTED_PROTECTION_BAND_AND_MODEL_RESPONSE", published_before_session_verified=False,
        author_action_at=None,
    )
    market_digests = {key: {f"{period}m": dict(bars=len(bars), sha256=digest(bars))
                            for period, bars in series.items()}
                      for key, series in (("2026-06-12", day), ("2026-06-15", night), ("2026-07-08", july))}
    return dict(version="lms405-glass-lock-followup-v1", contract=CONTRACT, evidence=sources,
                june=june, july=july_case, market_digests=market_digests, author_signal_at=None,
                author_trade_at=None, admitted_author_action_samples=0, executable=False, fills=None, pnl=None)


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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "GLASS_LOCK_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

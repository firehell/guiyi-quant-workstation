"""Compare two reports that distinguish version-specific lock and profit-taking."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_glass_lock_followup import window
from lms405_portfolio_replay import ARCHIVE, LOCAL, input_sources
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

JM, RU = "S5307830937850724", "S5291275490430891"


def study(session, market):
    index = input_sources()
    sources = {}
    for key in (JM, RU):
        source = index[key]
        sources[key] = source | dict(sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()))
    jm_day = read_window(session, market, "JM2609", date(2026, 6, 8))
    jm_next = read_window(session, market, "JM2609", date(2026, 6, 9))
    ru = read_window(session, market, "RU2609", date(2026, 4, 24))
    band = Decimal(1446), Decimal(1464)
    june_open = jm_next[1][0].start
    jm_report = datetime.fromisoformat(sources[JM]["published_at"]).astimezone(LOCAL)
    cut = jm_report.replace(second=0, microsecond=0)
    if display(june_open) != "2026-06-08T21:00+08:00" or display(cut) != "2026-06-09T09:36+08:00":
        raise ValueError("VERSIONED_LOCK_SOURCE_WINDOW_CHANGED")
    prior = window(jm_day, at("2026-06-08T09:00"), at("2026-06-08T15:01"), band=band, side="SHORT")
    night_end = at("2026-06-09T09:00")
    night = window(jm_next, june_open, night_end, band=band, side="SHORT")
    night_minutes = completed(jm_next[1], june_open, night_end)
    limit_ref = Decimal("1340.5")
    morning = window(jm_next, night_end, cut, band=band, side="SHORT")
    after_report = completed(jm_next[1], cut + ONE, at("2026-06-09T15:01"))
    if not after_report:
        raise ValueError("VERSIONED_LOCK_FORWARD_WINDOW_MISSING")
    divider = Decimal(1360), Decimal("1366.5")
    rebound = Decimal("1411.5")
    ru_band = Decimal(16930), Decimal(17040)
    ru_cut = datetime.fromisoformat(sources[RU]["published_at"]).astimezone(LOCAL)
    market = {key: {f"{p}m": dict(bars=len(bars), sha256=digest(bars)) for p, bars in series.items()}
              for key, series in (("JM2609_0608", jm_day), ("JM2609_0609", jm_next), ("RU2609_0424", ru))}
    return dict(
        version="lms405-versioned-lock-audit-v1", sources=sources, market=market,
        coal=dict(
            contract="JM2609", before_night=prior, night=night, morning_before_review=morning,
            day_to_night_open_gap=night_minutes[0].open - prior["close"],
            night_low_first_at=display(next(b.end for b in night_minutes if b.low == night["low"])),
            author_limit_reference=limit_ref, night_touched_author_limit_reference=night["low"] <= limit_ref,
            forward_plan_price_only=dict(
                minute_count=len(after_report), first_bar_end=display(after_report[0].end),
                low=min(b.low for b in after_report), high=max(b.high for b in after_report),
                short_divider=observations(after_report, divider, "SHORT"),
                continuation_up=observations(after_report, (rebound, rebound), "LONG"),
                author_hold_or_reentry=None,
            ),
            actions_reported={"4.0.5": "LOCKED_YESTERDAY_TIME_UNRESOLVED", "5.0": "NIGHT_PROFIT_TAKING_REPORTED"},
            prior_band_revision_known_at=None, lock_time=None, order_binding=None,
        ),
        rubber=dict(
            contract="RU2609", trading_day=window(ru, ru[1][0].start, ru_cut, band=ru_band, side="SHORT"),
            day_session=window(ru, at("2026-04-24T09:00"), ru_cut, band=ru_band, side="SHORT"),
            band_role="AUTHOR_CORRECTION_TEST_RANGE", lock_band=None,
            actions_reported={"4.0.5": "LOCK_REPORTED", "5.0": "PROFIT_TAKING_REPORTED"},
            lock_time=None, order_binding=None,
        ),
        admitted_author_action_samples=0, executable=False, fills=None, pnl=None,
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError, StopIteration):
        parser.exit(2, "VERSIONED_LOCK_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

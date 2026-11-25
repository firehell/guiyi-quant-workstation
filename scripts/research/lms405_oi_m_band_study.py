"""Test OI2609 price and shape prerequisites while the original M band is unknown."""

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_locked_exit_audit import verify_aggregation
from lms405_m_difficulty_study import fresh_candidates
from lms405_oi_june_case import CONTRACT, DAYS, EARLY_BASELINE_SHA256, local_time, observe_band
from lms405_protection_timeframes import geometry_events
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_sa_reentry_study import source_evidence
from lms_near405_replay import encoded, sha

PROTECTION = Decimal("10273"), Decimal("10315")
PRIOR_LOW = Decimal("10230")
LATER_NODE = Decimal("9924"), Decimal("9952")
SOURCE_HASHES = {
    "S5306128623993006": "5c2a279c35b99c747079a472df1aa664087e507d40931ae721af5c5d30ba7273",
    "S5306393997347489": "d3a1e977dc9c20d92f021609e35595c7e6959826008641a0702d2d0f4c933c9d",
    "WR2IUYCQHj": "6165a81cfe8cac419d14993511a564fe5e8f696923499d7b571d3aa0e4e19cd7",
}
WINDOWS = (
    ("june4_day", DAYS[1], at("2026-06-04T09:00"), at("2026-06-04T15:01")),
    ("june5_night", DAYS[2], at("2026-06-04T21:00"), at("2026-06-04T23:01")),
    ("june5_before_morning_post", DAYS[2], at("2026-06-05T09:00"), at("2026-06-05T10:26")),
    ("june5_day", DAYS[2], at("2026-06-05T09:00"), at("2026-06-05T15:01")),
)


def market_digest(rows):
    values = [[local_time(b.bar_end), *map(str, ohlc(b))] for b in rows]
    return sha(json.dumps(values, separators=(",", ":")).encode())


def first_strict_close_below(bars, level):
    return next((bar.bar_end for bar in bars if bar.close < level), None)


def inspect_window(minute_series, five_series, trading_day, start, cutoff):
    minute = [b for b in minute_series if b.trading_day == trading_day and start < b.bar_end < cutoff]
    five = [b for b in five_series if b.trading_day == trading_day and start < b.bar_end < cutoff]
    if not minute or not five:
        raise ValueError("OI_M_WINDOW_EMPTY")
    input_bars = {
        frequency: [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - step) for b in raw]
        for frequency, raw, step in ((1, minute, ONE), (5, five, FIVE))
    }
    verify_aggregation(input_bars[5], minute)
    thresholds = {"protection_lower": PROTECTION[0], "prior_trading_day_low": PRIOR_LOW}
    trigger = {key: first_strict_close_below(minute, price) for key, price in thresholds.items()}
    contact = observe_band(minute, *PROTECTION)["intersects"]
    shapes = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = geometry_events(input_bars, shape, confirm, start=start, as_of=cutoff, side="SHORT")
        cuts = {"after_protection_contact": contact} | {f"after_{key}_break": value for key, value in trigger.items()}
        after = {name: fresh_candidates(events, shape, when, PROTECTION, "SHORT") if when else []
                 for name, when in cuts.items()}
        # Geometry flags refer only to the supplied protection band in this study.
        for rows in after.values():
            for row in rows:
                row["inside_protection"] = row.pop("inside_m")
                row["below_protection"] = row.pop("beyond_m")
        shapes[f"{shape}m_to_{confirm}m"] = dict(events=events, **after)
    return dict(
        trading_day=trading_day.isoformat(), start=start, cutoff_exclusive=cutoff,
        bars={"1m": len(minute), "5m": len(five)},
        low=min(b.low for b in minute), high=max(b.high for b in minute),
        protection_contact=contact, first_close_below=trigger,
        first_close_below_available={key: value + US if value else None for key, value in trigger.items()},
        touches_later_node=observe_band(minute, *LATER_NODE)["intersects"], short_geometry=shapes,
    )


def study(minutes, fives, baseline, evidence):
    identities = {key: market_digest(rows) for key, rows in (("1m", minutes), ("5m", fives))}
    if any(digest != baseline["input_ohlc_sha256"][name] for name, digest in identities.items()):
        raise ValueError("OI_M_FROZEN_MARKET_INPUT_CHANGED")
    pre, morning, evening = (datetime.fromisoformat(evidence[name]["published_at"]) for name in SOURCE_HASHES)
    if not WINDOWS[0][3] < pre < WINDOWS[1][2] < WINDOWS[2][2] < morning == WINDOWS[2][3] < WINDOWS[3][3] < evening:
        raise ValueError("OI_M_SOURCE_CHRONOLOGY_CHANGED")
    prior_rows = [b for b in minutes if b.trading_day == DAYS[1]]
    if min(b.low for b in prior_rows) != PRIOR_LOW or any(b.bar_end + US >= WINDOWS[1][2] for b in prior_rows):
        raise ValueError("OI_M_PRIOR_LOW_NOT_ESTABLISHED")
    results = {key: inspect_window(minutes, fives, day, start, cutoff) for key, day, start, cutoff in WINDOWS}
    results["june4_day"]["source_scope"] = "RETROSPECTIVE_COMPARISON_BEFORE_CURRENT_SOURCE_PUBLICATION"
    return dict(
        version="lms405-oi-m-band-study-v1", contract=CONTRACT, source_evidence=evidence,
        frozen_reference_sha256=EARLY_BASELINE_SHA256, input_ohlc_sha256=identities,
        published_protection_band=PROTECTION, prior_low_hypothesis=PRIOR_LOW,
        later_node_observed_by_evening=LATER_NODE, later_node_used_for_permission=False,
        author_reported_transition="LOCKED_LONG_TO_SHORT_M_REPORTED_NO_ORDER_EVIDENCE",
        author_m_band=None, author_m_band_gate_status="INDETERMINATE_M_BAND_AND_ACTION_TIME_UNKNOWN",
        author_signal=None, author_action_at=None, band_geometry_used_as_author_permission=False,
        windows=results, admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
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
        reference = args.reference.read_bytes()
        if sha(reference) != EARLY_BASELINE_SHA256:
            parser.exit(2, "OI_M_FROZEN_REPORT_CHANGED\n")
        evidence = source_evidence(SOURCE_HASHES, {})
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            minutes, fives = (read_session_series(session, market, "oi", CONTRACT, freq, step, DAYS)
                              for freq, step in (("1m", ONE), ("5m", FIVE)))
        result = study(minutes, fives, json.loads(reference), evidence)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "OI_M_SOURCE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()

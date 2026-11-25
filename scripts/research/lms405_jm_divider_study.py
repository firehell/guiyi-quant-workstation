"""Bound the visible JM2701 long leg around the return to the public divider."""

import argparse
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import json
from math import ceil
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_carry_in_study import SNAPSHOT_SHA256
from lms405_fg_sa_case import FIVE, ONE, at, identity
from lms405_protection_timeframes import geometry_events
from lms405_replay import display, ohlc, read_session_series
from lms405_sa_reentry_study import SHORT_DAY, SHORT_IMAGES, source_evidence
from lms405_session_carry_study import ARCHIVE_PLANS, DAYS, MARKET_HASHES
from lms_near405_replay import encoded, sha

CONTRACT = "JM2701"
AVERAGE = Decimal("1385.25")
QTY = 20
DIVIDER = Decimal("1392"), Decimal("1415.5")
PREVIOUS_POST = "WRov1j6e10"
LUNCH = "WRoAkcEppg"
CLOSE = "U03"
NEXT_NIGHT = "WRoEvasxQR"
IMAGES = {
    PREVIOUS_POST: SHORT_IMAGES[PREVIOUS_POST],
    LUNCH: (
        "WRoAkcEppg-pos2-screen.png", "482969294bdf44a7d4f6bd8b7527708f3d94719b26648befcc00cf72d8b788f8",
        "2026-10-27T11:34:00+08:00",
    ),
    CLOSE: (
        "U03-pos3-screen.png", "7bacf30d3be4cce2de4268c91e01defc1310fc4897a5bc98329f31d29f838c23",
        "2026-10-27T15:16:00+08:00",
    ),
    NEXT_NIGHT: (
        "RoEvasxQR-position-screen.png", "67854d29d606b65cd88efe9af1fa939e86e20b713325732929b8a5a5aa6f9b0a",
        "2026-10-27T22:12:00+08:00",
    ),
}


def price_envelope(bars):
    return (min(b.low for b in bars), max(b.high for b in bars)) if bars else None


def minimum_early_quantity(average, total, earlier, later):
    """Return the price-envelope lower bound or None when the combined envelope excludes the mean."""
    if not earlier or not later or not min(earlier[0], later[0]) <= average <= max(earlier[1], later[1]):
        return None
    if later[0] <= average <= later[1]:
        return 0
    if average < later[0]:
        best_early, best_late = earlier[0], later[0]
    else:
        best_early, best_late = earlier[1], later[1]
    target, early, late = map(Fraction, (average, best_early, best_late))
    return ceil(total * (target - late) / (early - late))


def price_check(bars):
    limits = price_envelope(bars)
    return dict(
        bars=len(bars), range=limits,
        mean_inside_single_minute_range=[display(b.bar_end) for b in bars if b.low <= AVERAGE <= b.high],
        average_range_compatible=limits[0] <= AVERAGE <= limits[1] if limits else None,
    )


def quote_witnesses(comparison, evidence, minutes):
    anchors = {}
    closes = {b.bar_end: b.close for b in minutes if b.trading_day == SHORT_DAY}
    for source in (LUNCH, CLOSE):
        snap, = [s for s in comparison["snapshots"] if s["source"] == source]
        at_quote = datetime.fromisoformat(snap["quote_anchor"])
        jm = snap["contracts"][CONTRACT]
        if (not at_quote < datetime.fromisoformat(evidence[source]["published_at"])
                or snap["image"]["sha256"] != evidence[source]["image_sha256"]
                or jm["quote_aligned"] is not True or closes.get(at_quote) != Decimal(jm["displayed_quote"])):
            raise ValueError("JM_QUOTE_ANCHOR_UNVERIFIED")
        if jm["author_visible_legs"].get("long") != dict(opening_average=str(AVERAGE), quantity=QTY,
                                                        today_quantity=QTY):
            raise ValueError("JM_VISIBLE_LONG_CHANGED")
        baseline = jm["variants"]["BASELINE"]["before_quote_close"]
        anchors[source] = dict(time=at_quote, quote=jm["displayed_quote"], binding=snap["binding"],
                               legs=jm["author_visible_legs"], baseline=dict(
                                   classification=baseline["classification"], last_action=baseline["last_action"],
                               ))
    return anchors


def day_signal_checks(day, fives, morning, quote):
    series = {1: [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - ONE) for b in day if b.bar_end < quote],
              5: [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in fives
                  if morning < b.bar_end < quote]}
    result = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = geometry_events(series, shape, confirm, start=morning, as_of=quote, side="LONG")
        result[f"{shape}m_to_{confirm}m"] = [
            event | dict(after=price_check([b for b in day if b.bar_end > event["confirmed_at"]]))
            for event in events
        ]
    return result


def study(minutes, fives, evidence, comparison):
    frozen = {"1m": identity(minutes), "5m": identity(fives)}
    if tuple(item["ohlc_sha256"] for item in frozen.values()) != MARKET_HASHES[CONTRACT]:
        raise ValueError("JM_FROZEN_MARKET_INPUT_CHANGED")
    anchors = quote_witnesses(comparison, evidence, minutes)
    quote = anchors[LUNCH]["time"]
    morning = at("27T09:00")
    prior_post = datetime.fromisoformat(evidence[PREVIOUS_POST]["published_at"])
    through_quote = [b for b in minutes if b.trading_day == SHORT_DAY and b.bar_end <= quote]
    since_post = [b for b in through_quote if b.bar_end > prior_post]
    day = [b for b in through_quote if b.bar_end > morning]
    if (len(through_quote), len(day)) != (255, 135):
        raise ValueError("JM_SESSION_COVERAGE_CHANGED")
    lower, upper = DIVIDER
    touch = next(b for b in since_post if b.low <= upper and b.high >= lower)
    close = next(b for b in since_post if lower <= b.close <= upper)
    gates = {}
    for name, trigger, split in (
        ("at_or_after_intrabar_return", touch, touch.bar_end - ONE),
        ("after_completed_close_in_divider", close, close.bar_end),
    ):
        gates[name] = dict(bar_end=display(trigger.bar_end), trigger_ohlc=ohlc(trigger),
                           subsequent_prices=price_check([b for b in through_quote if b.bar_end > split]),
                           minimum_earlier_lots={
                               label: minimum_early_quantity(
                                   AVERAGE, QTY, price_envelope([b for b in bars if b.bar_end <= split]),
                                   price_envelope([b for b in bars if b.bar_end > split]),
                               ) for label, bars in (("whole_trading_day", through_quote),
                                                     ("since_short_post_minute", since_post), ("day_session", day))
                           })
    return dict(
        version="lms405-jm-divider-return-study-v1", contract=CONTRACT, trading_day=SHORT_DAY.isoformat(),
        sources=evidence, frozen_inputs=frozen, snapshot_comparison_sha256=SNAPSHOT_SHA256,
        divider=DIVIDER, anchors=anchors, observed=dict(
            prior_short=dict(source=PREVIOUS_POST, quantity=20, today_quantity=20, average="1372"),
            next_night_long=dict(source=NEXT_NIGHT, quantity=QTY, today_quantity=0, average=str(AVERAGE)),
            absent_leg=None, account_identity=None, author_transition=None,
        ),
        overnight_since_short_post=price_check([b for b in since_post if b.bar_end < morning]),
        overnight_entire=price_check([b for b in through_quote if b.bar_end < morning]),
        day_to_lunch=price_check(day), gates=gates,
        day_geometric_hypotheses=day_signal_checks(day, fives, morning, quote),
        quantity_bound_assumption="PARTITION_SURVIVING_DISPLAYED_LOTS_BY_ENTRY_TIME_PRICE_ENVELOPE_ONLY",
        clock="RETROSPECTIVE_CURRENT_ARCHIVE_REVISION_AND_QUOTE_WITNESS_ONLY",
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--snapshot-comparison", type=Path, required=True)
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
        raw = args.snapshot_comparison.read_bytes()
        if sha(raw) != SNAPSHOT_SHA256:
            parser.exit(2, "JM_SNAPSHOT_COMPARISON_CHANGED\n")
        evidence = source_evidence(ARCHIVE_PLANS, IMAGES)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            minutes = read_session_series(session, market, "jm", CONTRACT, "1m", ONE, DAYS)
            fives = read_session_series(session, market, "jm", CONTRACT, "5m", FIVE, DAYS)
        result = study(minutes, fives, evidence, json.loads(raw))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError, StopIteration):
        parser.exit(2, "JM_DIVIDER_SOURCE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()

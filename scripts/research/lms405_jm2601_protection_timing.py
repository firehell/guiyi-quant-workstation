"""Constrain JM2601 protection timing from the author's diagram and displayed opening average."""

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms_keybar_approx import classify_research_period
from lms405_jm2601_m_window import OLD_AVERAGE, OLD_LOTS, RECOVERY_BAND, TICK, read_sources
from lms405_jm2601_structure import ANCHOR, DAYS, LOCAL
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_next_night_replay import price_timing
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_replay import ohlc
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded, sha

CONTRACT = "JM2601"
DAY = DAYS[1]
START, PUBLISHED = at("2025-11-27T21:00"), at("2025-11-28T15:13")
WEAK_BAND, STRONG_BAND = RECOVERY_BAND, (Decimal("1048"), Decimal("1052"))
FROZEN = Path("output/lms405-jm2601-structure-20261125/report.json")
FROZEN_SHA = "327c96688431553cc1a569cc7299f8ef2247835aa3eecf653070b5fbfbc041fe"
EVIDENCE = Path("docs/research/lms405/evidence")
ANCHOR_FILES = {
    "jm-signal-followup-20261023.csv": "bb923ea5e5b5113bf0daa0f1a16cf60cf4c4225f24be2e70c68f1ffad9304a91",
    "keybar-sample-admission-20261028.csv": "0be665b006c0e5bc2fedc0440ab323bc4c9f559d3e512d0e64e1c49e3a6ce2b0",
}


def study(session, market):
    sources = read_sources()
    if any(sha((EVIDENCE / name).read_bytes()) != expected for name, expected in ANCHOR_FILES.items()):
        raise ValueError("JM_PROTECTION_SOURCE_CHANGED")
    with (EVIDENCE / "jm-signal-followup-20261023.csv").open(encoding="utf-8") as stream:
        (sources["M01"],) = [r for r in csv.DictReader(stream) if r["source_id"] == "M01"]
    frozen = verified_json(FROZEN, FROZEN_SHA)
    days = {day: read_window(session, market, CONTRACT, day) for day in DAYS}
    for period in (1, 5):
        bars = [b for series in days.values() for b in series[period]]
        reference = frozen["input"]["jm"]["bars"][f"{period}m"]
        if len(bars) != reference["count"] or digest(bars) != reference["hash"]:
            raise ValueError("JM_PROTECTION_FROZEN_MARKET_CHANGED")
    series = days[DAY]
    minutes = completed(series[1], START, PUBLISHED)
    if len(minutes) != len(series[1]) or at(sources["N01"]["published_shanghai"]) != PUBLISHED:
        raise ValueError("JM_PROTECTION_SNAPSHOT_WINDOW_CHANGED")
    bounds = dict(lots=OLD_LOTS, tick=TICK, totals=displayed_tick_totals(OLD_AVERAGE, OLD_LOTS, TICK))

    def after(bar):
        if bar is None:
            return None
        first = tick_bounds([b for b in minutes if b.end <= bar.end], TICK)
        later = tick_bounds([b for b in minutes if b.end > bar.end], TICK)
        optimistic = earlier_lot_counts(first, later, OLD_LOTS, bounds["totals"])
        return dict(bar_end=bar.end.astimezone(LOCAL), bar_ohlc=ohlc(bar),
                    minimum_earlier_lots_even_allowing_overlap=min(optimistic),
                    **price_timing(minutes, bar.end + US, **bounds))

    (anchor,) = [b for b in minutes if b.low == ANCHOR]
    index = minutes.index(anchor)
    mother, following = minutes[index - 1], minutes[index + 1]
    if mother.end != anchor.start or anchor.end != following.start:
        raise ValueError("JM_PROTECTION_ANCHOR_SESSION_CHANGED")
    shape = classify_research_period(mother, anchor, minutes=1)
    anchor_prefix = [b for b in minutes if b.end <= anchor.end]
    low = min(b.low for b in anchor_prefix)
    after_low = next(b for b in anchor_prefix if b.low == low)
    anchor_session = []
    previous = anchor
    for bar in minutes[index + 1:]:
        if previous.end != bar.start:
            break
        anchor_session.append(bar)
        previous = bar
    local_envelope = tick_bounds(anchor_session, TICK)
    prior_lots = earlier_lot_counts(tick_bounds(anchor_prefix, TICK), local_envelope, OLD_LOTS, bounds["totals"])
    first_overlap = next((b for b in minutes if b.low <= WEAK_BAND[1] and WEAK_BAND[0] <= b.high), None)
    first_return = next((b for b in minutes[index + 1:] if b.low <= WEAK_BAND[1] and WEAK_BAND[0] <= b.high), None)
    first_retaken = next((b for b in minutes[index + 1:] if b.close > WEAK_BAND[1]), None)
    geometries = {}
    for timeframe in VARIANTS:
        inputs = dict(side="LONG", start=START)
        full = [e for e in signals(series, *timeframe, cut=PUBLISHED, **inputs) if e["confirmed_at"] > after_low.end]
        for cut in (anchor.end + 2 * US, after_low.end + 2 * US,
                    first_return.end + 2 * US if first_return else PUBLISHED):
            prefix = {p: completed(rows, START, cut) for p, rows in series.items()}
            earlier = [e for e in signals(prefix, *timeframe, cut=cut, **inputs) if e["confirmed_at"] > after_low.end]
            if earlier != [e for e in full if e["available_at"] < cut]:
                raise ValueError("JM_PROTECTION_SIGNAL_PREFIX_CHANGED")
        geometries[f"{timeframe[0]}m_to_{timeframe[1]}m"] = [e | dict(
            relation="BELOW" if e["close"] < WEAK_BAND[0] else
            "ABOVE" if e["close"] > WEAK_BAND[1] else "INSIDE",
            price_support=after(next(b for b in minutes if b.end == e["confirmed_at"])),
        ) for e in full]

    return dict(version="lms405-jm2601-protection-timing-v1", contract=CONTRACT, trading_day=DAY,
                sources={key: sources[key] for key in ("M01", "N01", "N03", "N04")}, archived_source_digests=ANCHOR_FILES,
                retrospective_references=dict(strong_target=STRONG_BAND, weak_interruption=WEAK_BAND,
                                              exact_pretrade_plan_found=False),
                snapshot_published=PUBLISHED, snapshot_capture_at=None, snapshot_scope="MIXED_SYSTEM_POST",
                new_long=dict(lots=OLD_LOTS, displayed_average=OLD_AVERAGE, tick=TICK, tick_totals=list(bounds["totals"])),
                market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
                strong_target_touched=any(b.low <= STRONG_BAND[1] and b.high >= STRONG_BAND[0] for b in minutes),
                opening_ohlc=ohlc(minutes[0]), first_weak_contact=after(first_overlap),
                first_weak_contact_after_anchor=after(first_return), first_close_above_weak_after_anchor=after(first_retaken),
                earlier_low_before_anchor=after(after_low), exact_price_anchor=after(anchor) | dict(
                    ibar=shape.ibar, pinbar=shape.pinbar, following_close=following.close, following_end=following.end,
                ), candidates=geometries, author_event_at=None, author_period=None, author_match_rate=None,
                anchor_session_price_sensitivity=dict(
                    session_end=previous.end.astimezone(LOCAL), including_entire_overlap_minute=True,
                    later_tick_envelope=local_envelope, whole_leg_after_anchor_possible=0 in prior_lots,
                    minimum_earlier_lots_if_complete_within_same_session=min(prior_lots),
                ),
                hypothesis="CONDITIONAL_SAME_ACCOUNT_TODAY_LOTS_AND_MINUTE_PRICE_ENVELOPES", fills=None, executable=False)


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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("JM_PROTECTION_") and code.isidentifier()
                        else "JM_PROTECTION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

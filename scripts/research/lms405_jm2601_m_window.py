"""Compare JM2601 original-short recovery with the long-M snapshot window."""

import argparse
import csv
import json
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

from lms405_i2701_case import average_envelope, rounded_average_ticks
from lms405_jm2601_structure import CUTOFF, DAYS, FIVE, LOCAL, ONE, market_rows
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

CONTRACT = "JM2601"
TICK = Decimal("0.5")
TICK_SOURCE = "https://www.dzqh.com.cn/UploadFileDir/content_file/20220415153704099579727.pdf"
REFERENCE_SHA = "327c96688431553cc1a569cc7299f8ef2247835aa3eecf653070b5fbfbc041fe"
EVIDENCE = Path(__file__).resolve().parents[2] / "docs/research/lms405/evidence"
SOURCE_TABLES = {
    "jm2601-recovery-chain-20261023.csv": "b622a66382a2846abd764d8aaeded1c6b722a7b3b68b5428183e1d547da25a66",
    "jm2601-original-records-20261023.csv": "814b0378adb22d3ad3e9c34e265a01119e81163985d462524fc15c5a92dc05e8",
}
RECOVERY_BAND = Decimal("1069"), Decimal("1077.5")
OLDER_M_BAND = Decimal("1103.5"), Decimal("1111.5")
OLD_LOTS, OLD_AVERAGE = 20, Decimal("1061.50")
VISIBLE_LOTS, VISIBLE_AVERAGE = 22, Decimal("1063.61")


def read_sources():
    sources = {}
    for name, digest in SOURCE_TABLES.items():
        raw = (EVIDENCE / name).read_bytes()
        if sha(raw) != digest:
            raise ValueError("JM_M_SOURCE_TABLE_CHANGED")
        sources.update({row["source_id"]: row for row in csv.DictReader(StringIO(raw.decode("utf-8")))})
    return {key: sources[key] for key in ("N01", "N02", "O02", "N03", "N04", "N05")}


def added_lot_average():
    added = VISIBLE_LOTS - OLD_LOTS
    estimate = (VISIBLE_AVERAGE * VISIBLE_LOTS - OLD_AVERAGE * OLD_LOTS) / added
    uncertainty = Decimal("0.005") * (VISIBLE_LOTS + OLD_LOTS) / added
    old_ticks = rounded_average_ticks(OLD_AVERAGE, OLD_LOTS, TICK)
    new_ticks = rounded_average_ticks(VISIBLE_AVERAGE, VISIBLE_LOTS, TICK)
    totals = sorted({new_total - old_total for new_total in new_ticks for old_total in old_ticks})
    return dict(
        old_lots=OLD_LOTS, old_display_open_average=OLD_AVERAGE,
        visible_lots=VISIBLE_LOTS, visible_display_open_average=VISIBLE_AVERAGE,
        visible_today_lots=2, added_lots=added, display_arithmetic_mean=estimate,
        conservative_rounding_interval=(estimate - uncertainty, estimate + uncertainty),
        conditional_total_ticks=totals, conditional_mean_values=[TICK * n / added for n in totals],
        tick=TICK, tick_source=TICK_SOURCE,
        assumptions=["SAME_ACCOUNT", "ALL_20_OLD_LONG_LOTS_RETAINED", "EXACTLY_TWO_NEW_LONG_LOTS",
                     "OPENING_AVERAGE_NOT_REBASED", "NEAREST_CENT_HALF_UP_DISPLAY"],
    )


def first_compatible_prefix(rows, means):
    if not rows:
        return None
    low, high = rows[0].low, rows[0].high
    for index, bar in enumerate(rows):
        prior_high = high if index else None
        low, high = min(low, bar.low), max(high, bar.high)
        if any(low <= mean <= high for mean in means):
            return dict(bar_end=bar.bar_end.astimezone(LOCAL), high_before_compatible_bar=prior_high,
                        same_minute_compatible=any(bar.low <= mean <= bar.high for mean in means))
    return None


def inspect_windows(day, *, locked_post, confirmed, midpoint, cutoff):
    # Minute end labels describe intervals, not the time of the opening or high.
    day = [bar for bar in day if bar.bar_end < cutoff]
    after_post = [bar for bar in day if bar.bar_end - ONE >= locked_post + ONE]
    by_confirmation = [bar for bar in after_post if bar.bar_end <= confirmed]
    boundary = [bar for bar in after_post if bar.bar_end - ONE == confirmed]
    fully_later = [bar for bar in after_post if bar.bar_end - ONE > confirmed]
    lower, upper = RECOVERY_BAND
    old_m_lower, old_m_upper = OLDER_M_BAND
    timing = added_lot_average()
    envelopes = {
        label: average_envelope(rows, TICK, timing["added_lots"], timing["conditional_total_ticks"])
        for label, rows in (
            ("trading_day_before_locked_post_minute", [b for b in day if b.bar_end < locked_post]),
            ("trading_day_through_snapshot_cutoff", day),
            ("after_locked_post_through_confirmation", by_confirmation),
            ("confirmation_boundary_minute", boundary),
            ("minutes_starting_strictly_after_confirmation", fully_later),
        )
    }
    means = timing["conditional_mean_values"]

    def first_end(predicate):
        return next((bar.bar_end.astimezone(LOCAL) for bar in after_post if predicate(bar)), None)

    return dict(
        after_locked_post_completed_bar_count=len(after_post),
        original_short_recovery_band=RECOVERY_BAND,
        first_band_contact=first_end(lambda b: b.low <= upper and b.high >= lower),
        first_strict_low_below_upper=first_end(lambda b: b.low < upper),
        first_strict_close_below_upper=first_end(lambda b: b.close < upper),
        first_strict_low_below_lower=first_end(lambda b: b.low < lower),
        first_strict_close_below_lower=first_end(lambda b: b.close < lower),
        older_m_band_retrospective_only=OLDER_M_BAND,
        first_older_m_band_contact=first_end(lambda b: b.low <= old_m_upper and b.high >= old_m_lower),
        final_structure_midpoint_retrospective_only=midpoint,
        first_close_above_final_structure_midpoint=first_end(lambda b: b.close > midpoint),
        first_preconfirmation_prefix_allowing_mean=first_compatible_prefix(by_confirmation, means),
        first_trading_day_prefix_allowing_mean=first_compatible_prefix(day, means),
        conditional_price_envelopes=envelopes,
    )


def study(raw, reference, sources):
    previous = reference["input"]["jm"]
    current = {period: dict(count=len(rows), hash=sha(encoded([
        (b.bar_end.isoformat(), *map(str, ohlc(b))) for b in rows
    ]).encode())) for period, rows in raw.items()}
    if previous["contract"] != CONTRACT or current != previous["bars"]:
        raise ValueError("JM_M_FROZEN_MARKET_INPUT_CHANGED")
    market_rows(raw, CONTRACT, CUTOFF)
    locked_post = datetime.fromisoformat(sources["N02"]["published_shanghai"]).replace(tzinfo=LOCAL)
    cutoff = datetime.fromisoformat(sources["O02"]["published_shanghai"]).replace(tzinfo=LOCAL)
    event, = [e for e in reference["events"] if e["timing"] == "JOINT_COMPLETED_BAR" and
              locked_post + ONE <= datetime.fromisoformat(e["confirmation_bar_end"]) < cutoff]
    confirmed = datetime.fromisoformat(event["confirmation_bar_end"]).astimezone(LOCAL)
    if cutoff != CUTOFF:
        raise ValueError("JM_M_REFERENCE_CUTOFF_CHANGED")
    day = [b for b in raw["1m"] if b.trading_day == DAYS[-1]]
    return dict(
        version="lms405-jm2601-m-window-v1", contract=CONTRACT, trading_day=DAYS[-1].isoformat(),
        frozen_structure_reference_sha256=REFERENCE_SHA, input_ohlc=current,
        sources=sources, source_table_sha256=SOURCE_TABLES, locked_post_display_minute=locked_post,
        snapshot_post_display_minute=cutoff, prior_structure_candidate_bar_end=confirmed,
        added_lot_hypothesis=added_lot_average(),
        **inspect_windows(day, locked_post=locked_post, confirmed=confirmed,
                          midpoint=Decimal(event["pivots"][1]["price"]), cutoff=cutoff),
        author_signal=None, author_action_at=None, author_m_band=None, same_account=None,
        author_matches=None, admitted_author_samples=0, fills=None, pnl=None, executable=False,
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
        ref = args.reference.read_bytes()
        if sha(ref) != REFERENCE_SHA:
            raise ValueError("JM_M_FROZEN_STRUCTURE_REPORT_CHANGED")
        sources = read_sources()
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            raw = {freq: read_session_series(session, market, "jm", CONTRACT, freq, step, DAYS)
                   for freq, step in (("1m", ONE), ("5m", FIVE))}
        result = study(raw, json.loads(ref), sources)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "JM_M_SOURCE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()

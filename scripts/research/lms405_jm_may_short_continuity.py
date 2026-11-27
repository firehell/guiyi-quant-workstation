"""Bound same-day short or overnight long replacement in the May JM2609 displays."""

import argparse
import csv
from datetime import datetime
from decimal import Decimal
from itertools import groupby
from pathlib import Path

from lms405_jm_may_leg_timing import (
    CONTRACT,
    INPUT_HASH,
    LONG_AVERAGE,
    LOTS,
    MAY_INDEX,
    MAY_INDEX_HASH,
    NEXT_SHORT_AVERAGE,
    TICK,
    frozen_minutes,
)
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_right_side_study import at
from lms405_sh_protection_replacement import compatible_counts
from lms405_trial_to_trend import frozen
from lms_near405_replay import encoded, sha

PRIOR = "S5300324676929242"
SESSION_START = at("2026-05-20T21:00")
LUNCH = at("2026-05-21T11:30")
AFTERNOON_START = at("2026-05-21T13:30")
CLOSE = at("2026-05-21T15:00")
LEVELS = tuple(map(Decimal, ("1216", "1214.5", "1210.5", "1206", "1205.5", "1196.5")))
MAY20_START = at("2026-05-19T21:00")
MAY20_DAY_START = at("2026-05-20T09:00")
MAY20_CLOSE = at("2026-05-20T15:00")
MAY20_SETTLEMENT = Decimal("1211.00")
SETTLEMENT_FACTS_SHA = "b15ec9ad682f0ce6f7d40749bc395f8bf2269935235c0900b50aa87316785d5e"


def retention(old_ticks, replacement_ticks, totals):
    # Count compatibility uses OHLC price envelopes, allowing any tick in them. It gives bounds only.
    allowed = compatible_counts(LOTS, totals, totals, old_ticks, replacement_ticks, None)
    counts = sorted({old for old, _, _ in allowed})
    return dict(compatible_old_lots=counts, minimum_retained=min(counts), maximum_replaced=LOTS - min(counts),
                unchanged_leg_compatible=LOTS in counts, complete_rebuild_compatible=0 in counts,
                replacement_tick_envelope=replacement_ticks)


def long_snapshot_bounds(prior_session, clocks, totals):
    """Return compatible counts at hypothetical whole-minute screenshot clocks."""
    results = []
    for instant in clocks:
        earlier = tick_bounds([bar for bar in prior_session if bar.end <= instant], TICK)
        later = tick_bounds([bar for bar in prior_session if bar.end > instant], TICK)
        allowed = [] if earlier is None else [retained for retained, _, _ in compatible_counts(
            LOTS, totals, totals, earlier, later, None,
        )]
        results.append(dict(at=instant, compatible_old_lots=allowed))
    return results


def study_long(market_path, facts_path):
    minutes = frozen_minutes(market_path)
    source_rows = {row["id"]: row for row in csv.DictReader(frozen(MAY_INDEX, MAY_INDEX_HASH).decode().splitlines())}
    prior, following = (source_rows[key] for key in ("G05", "G03"))
    prior_post, later_post = (datetime.fromisoformat(row["published_at"]) for row in (prior, following))
    if any(row["contract"] != CONTRACT for row in (prior, following)):
        raise ValueError("JM_MAY_SNAPSHOT_CONTRACT_CHANGED")
    if not MAY20_CLOSE < prior_post < SESSION_START < LUNCH < later_post < AFTERNOON_START:
        raise ValueError("JM_MAY_SNAPSHOT_ORDER_CHANGED")
    facts = verified_json(facts_path, SETTLEMENT_FACTS_SHA)
    daily = {row["date"]: row for row in facts["contracts"][CONTRACT]["daily"]}
    if facts["source"] != "rqdata" or (
        Decimal(daily["2026-05-20"]["settlement"]) != MAY20_SETTLEMENT
        or Decimal(daily["2026-05-21"]["prev_settlement"]) != MAY20_SETTLEMENT
    ):
        raise ValueError("JM_MAY_SETTLEMENT_UNVERIFIED")
    # The next image reports zero today longs. A replacement on the next trading day cannot survive in that row.
    prior_session = [bar for bar in minutes if MAY20_START < bar.end <= MAY20_CLOSE]
    daytime_ends = [bar.end for bar in prior_session if bar.start >= MAY20_DAY_START]
    if len(prior_session) != 345 or len(daytime_ends) != 225:
        raise ValueError("JM_MAY_SNAPSHOT_WINDOW_INCOMPLETE")
    totals = displayed_tick_totals(LONG_AVERAGE, LOTS, TICK)
    clocks = long_snapshot_bounds(prior_session, [MAY20_DAY_START, *daytime_ends], totals)
    ranges = []
    for allowed, group in groupby(clocks, key=lambda row: row["compatible_old_lots"]):
        rows = list(group)
        ranges.append(dict(first=rows[0]["at"], last=rows[-1]["at"], clock_count=len(rows), compatible_old_lots=allowed))
    return dict(
        version="lms405-jm-may-long-continuity-v1", contract=CONTRACT, market_sha256=INPUT_HASH,
        source_index_sha256=MAY_INDEX_HASH, settlement_facts_sha256=SETTLEMENT_FACTS_SHA,
        position_sources={row["id"]: row for row in (prior, following)},
        lots=LOTS, displayed_open_average=LONG_AVERAGE, displayed_sum_in_ticks=list(totals),
        prior_settlement=MAY20_SETTLEMENT, next_displayed_position_average=MAY20_SETTLEMENT,
        market_minutes=len(prior_session), clock_ranges=ranges,
        assumptions=["SAME_ACCOUNT_AND_FILTER", "SURVIVING_LOT_OPEN_PRICES", "TRADING_DAY_TODAY_FIELD",
                     "HALF_UP_CENT_DISPLAY", "CANDIDATE_CLOCK_AT_MINUTE_BOUNDARY"],
        snapshot_times_verified=False, account_continuity=None, author_role_assignment=None,
        author_action_at=None, admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def study(market_path):
    minutes = frozen_minutes(market_path)
    source = input_sources()[PRIOR]
    published = datetime.fromisoformat(source["published_at"])
    if not published < at("2026-05-19T21:00"):
        raise ValueError("JM_MAY_PRIOR_SOURCE_ORDER_CHANGED")
    source_digest = sha((ARCHIVE.parent / source["archive_path"]).read_bytes())
    source_rows = {row["id"]: row for row in csv.DictReader(frozen(MAY_INDEX, MAY_INDEX_HASH).decode().splitlines())}
    lunch, close = (source_rows[role] for role in ("G03", "G04"))
    if lunch["contract"] != CONTRACT or close["contract"] != CONTRACT:
        raise ValueError("JM_MAY_SNAPSHOT_CONTRACT_CHANGED")
    if not (LUNCH < datetime.fromisoformat(lunch["published_at"]) < AFTERNOON_START < CLOSE
            < datetime.fromisoformat(close["published_at"])):
        raise ValueError("JM_MAY_SNAPSHOT_ORDER_CHANGED")
    through_lunch = [bar for bar in minutes if SESSION_START < bar.end <= LUNCH]
    afternoon = [bar for bar in minutes if LUNCH < bar.end <= CLOSE]
    if (len(through_lunch), len(afternoon)) != (255, 90) or afternoon[0].start != AFTERNOON_START:
        raise ValueError("JM_MAY_SNAPSHOT_WINDOW_INCOMPLETE")
    totals = displayed_tick_totals(NEXT_SHORT_AVERAGE, LOTS, TICK)
    old_ticks, afternoon_ticks = tick_bounds(through_lunch, TICK), tick_bounds(afternoon, TICK)
    bound = retention(old_ticks, afternoon_ticks, totals)
    price_only = earlier_lot_counts(old_ticks, afternoon_ticks, LOTS, totals)
    gates = []
    for level in LEVELS:
        gate = next(bar for bar in afternoon if bar.close < level)
        # The strict alternative excludes the minute immediately following the confirming close.
        rows = dict(overlap_allowed=[bar for bar in afternoon if bar.end > gate.end],
                    only_wholly_later=[bar for bar in afternoon if bar.start > gate.end])
        gates.append(dict(level=level, first_afternoon_close_below=gate.end, close=gate.close,
                          if_all_replacements_occur_after={kind: retention(old_ticks, tick_bounds(bars, TICK), totals)
                                                           for kind, bars in rows.items()}))
    return dict(
        version="lms405-jm-may-short-continuity-v1", contract=CONTRACT, market_sha256=INPUT_HASH,
        source_index_sha256=MAY_INDEX_HASH, prior_source=source | dict(archive_sha256=source_digest),
        position_sources={row["id"]: {key: row[key] for key in ("url", "published_at", "image_location", "summary")}
                          for row in (lunch, close)},
        assumed_snapshot_at=dict(lunch=LUNCH, close=CLOSE), disclosed_short_average=NEXT_SHORT_AVERAGE, lots=LOTS,
        displayed_sum_in_ticks=list(totals), market_windows=dict(through_lunch=len(through_lunch),
                                                                afternoon=len(afternoon)),
        market_ranges_in_ticks=dict(through_lunch=old_ticks, afternoon=afternoon_ticks),
        price_only_minimum_lots_older_than_afternoon=min(price_only), same_table_retention=bound,
        conditional_replacement_after_level=gates,
        assumption="SAMEDAY_AVERAGES_AND_TODAY_LOTS_COMPARABLE_SNAPSHOTS_AT_LUNCH_AND_CLOSE_SAME_ACCOUNT",
        if_today_fields_are_comparable_previous_day_short_lots_in_display=0,
        snapshot_times_verified=False, account_continuity=None, author_role_assignment=None,
        author_signal_at=None, author_action_at=None, admitted_author_actions=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--long-settlement-facts", type=Path,
                        help="Use the overnight long comparison with the preserved RQData facts.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    try:
        result = study_long(args.market, args.long_settlement_facts) if args.long_settlement_facts else study(args.market)
        content = encoded(result)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except (KeyError, OSError, ValueError):
        parser.exit(2, "JM_MAY_CONTINUITY_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

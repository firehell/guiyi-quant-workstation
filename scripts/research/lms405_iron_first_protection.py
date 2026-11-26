"""Check I2701's first visible protection while retaining its original short."""

from argparse import ArgumentParser
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_first_night_confirmation_clocks import DAY, POST, START
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH, documented_price_events
from lms405_iron_original_exit import CONTRACT
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display, ohlc
from lms405_reversal_stage_bounds import PHOTO as QUOTE_REFERENCE
from lms405_reversal_stage_bounds import PHOTO_SHA as QUOTE_REFERENCE_SHA
from lms405_right_side_study import ONE, US
from lms405_sh_first_protection_rearm import reclaim_tape
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

ORIGINAL = (Path("output/lms405-iron-original-exit-20261126/verified-a.json"),
            "a0568f2c2f6b1000509ecb6dd60dcc6b4e107af93c1726b79d90bbc6205830c3")
PHOTO, PLAN, NEXT_PLAN = "WRnTlEfj1t", "A5356884629782554", "A5357264059367516"
NEAR, FAR = Decimal(667), Decimal(671)


def support(minutes, end, eligible, *, tick, lots, totals, include_quote):
    """Allow any integer tick within each envelope. No fill is inferred."""
    scope = [bar for bar in minutes if bar.end < end or (include_quote and bar.end == end)]
    early = [bar for bar in scope if bar.end not in eligible]
    late = [bar for bar in scope if bar.end in eligible]
    bounds = tick_bounds(early, tick), tick_bounds(late, tick)
    counts = earlier_lot_counts(*bounds, lots, totals)
    return dict(
        allowed_complete_minute_ends=[display(b.end) for b in late], early_and_late_tick_bounds=bounds,
        entire_leg_allowed=0 in counts, minimum_lots_outside_allowed_minutes=min(counts, default=None),
        possible_base_early_lot_counts=counts,
    )


def by_knowledge(minutes, known, *, overlapping):
    if known is None:
        return set()
    return {b.end for b in minutes if known < (b.end if overlapping else b.start)}


def fixed_quote_span(anchor, other_quotes):
    """Minimum end-label spread covering the fixed row and every other row."""
    candidates = []
    for right in sorted({anchor, *(stamp for row in other_quotes for stamp in row if stamp >= anchor)}):
        latest = [max((stamp for stamp in row if stamp <= right), default=None) for row in other_quotes]
        if all(stamp is not None for stamp in latest):
            candidates.append(right - min(anchor, *latest))
    return min(candidates) // ONE


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_HASH)
    original = verified_json(*ORIGINAL)
    iron = reference["cases"][CONTRACT]
    evidence = original["windows"]["2026-10-19"]["comparisons"]["require_disclosed_exit"]
    (long,), (short,) = ([r for r in evidence["comparisons"] if r.get("source") == PHOTO and r.get("side") == side]
                        for side in ("long", "short"))
    quote_support = short["by_variant"]["strict_replay"]
    origins = {r["origin_at"] for r in quote_support.values() if r["status"] == "PRICE_COMPATIBLE"}
    if len(origins) != 1 or any(r["status"] != "PRICE_COMPATIBLE" for r in quote_support.values()):
        raise ValueError("IRON_FIRST_SHORT_NOT_RETAINED")
    index = input_sources()
    source, next_plan = (load_source(index, key) for key in (PLAN, NEXT_PLAN))
    photo = reference["photo"]
    if (source != iron["plan"] or load_source(index, PHOTO) != reference["photo_source"]
            or sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]
            or not datetime.fromisoformat(source["published_at"]) < START < POST
            < datetime.fromisoformat(next_plan["published_at"])):
        raise ValueError("IRON_FIRST_SOURCE_CHANGED")
    series = read_window(session, market, CONTRACT, DAY)
    if {f"{p}m": digest(rows) for p, rows in series.items()} != iron["market"]:
        raise ValueError("IRON_FIRST_MARKET_CHANGED")
    windows = {p: completed(rows, START, POST) for p, rows in series.items()}
    minutes = windows[1]
    tick, average = Decimal(iron["tick"]), Decimal(iron["average"])
    lots = long["visible"]["quantity"]
    if long["visible"]["today_quantity"] != lots or Decimal(long["visible"]["opening_average"]) != average:
        raise ValueError("IRON_FIRST_POSITION_CHANGED")
    totals = displayed_tick_totals(average, lots, tick)
    mark = Decimal(iron["quote"])
    anchors = [bar.end for bar in minutes if bar.low <= mark <= bar.high]
    if (anchors != [datetime.fromisoformat(value) for value in quote_support]
            or anchors != [datetime.fromisoformat(value) for value in iron["individual_quote_ends"]]
            or quote_support.keys() != long["by_variant"]["strict_replay"].keys()):
        raise ValueError("IRON_FIRST_QUOTE_CHANGED")
    quote_rows = verified_json(QUOTE_REFERENCE, QUOTE_REFERENCE_SHA)["photos"][PHOTO]["per_symbol"]
    if set(quote_rows) != {"fg", "sa", "jm", "j", "rb", "sh", "i", "ru"} or (
        [display(a) for a in anchors] != quote_rows["i"]["contains"] or Decimal(quote_rows["i"]["mark"]) != mark
    ):
        raise ValueError("IRON_FIRST_CROSS_ROW_SCOPE_CHANGED")
    other_quotes = [[datetime.fromisoformat(value) for value in row["contains"]]
                    for symbol, row in quote_rows.items() if symbol != "i"]

    first = minutes[0]
    near = documented_price_events(windows, NEAR, first.open)
    far = documented_price_events(windows, FAR, first.open)
    last = far["first_known_upward_excursion_inside_minute"]
    fixed = {"first_minute_complete": first.end + US,
             "near_upcross_minute_complete": near["first_known_upward_excursion_inside_minute"].end + US,
             **{f"near_{period}_first_close": bar.end + US for period, bar in near["first_close_strictly_above"].items()},
             "far_upcross_minute_complete": last.end + US,
             "far_one_minute_strict_close": None}
    if any(far["first_close_strictly_above"].values()):
        raise ValueError("IRON_FIRST_FAR_CLOSE_CHANGED")
    worlds = {}
    for end in anchors:
        prefix = [b for b in minutes if b.end <= end]
        # Completed data that is observable at the end label excludes that minute's own close.
        known_prefix = [b for b in prefix if b.end + US < end]
        quotes = {}
        for overlap in (False, True):
            rules = {"preauthorized_at_session_open": {b.end for b in prefix},
                     **{k: by_knowledge(prefix, known if known is not None and known < end else None,
                                         overlapping=overlap) for k, known in fixed.items()}}
            for required in (1, 2):
                _, tape = reclaim_tape(prefix, edge=NEAR, required=required)
                _, prior = reclaim_tape(known_prefix, edge=NEAR, required=required)
                if tape != [*prior, *[(b, known) for b, known in tape if b.end == end]]:
                    raise ValueError("IRON_FIRST_PREFIX_DIVERGED")
                rules[f"near_{required}_closes_while_valid"] = {
                    b.end for b, known in tape if overlap or known < b.start
                }
            if overlap:
                # Retrospective bound only. Nothing is available on a completed tape until the trigger minute ends.
                rules["far_intraminute_with_entire_cross_minute"] = {b.end for b in prefix if b.start >= last.start}
            quotes["allow_overlap" if overlap else "strict_after_knowledge"] = {
                name: {"without_quote_minute": support(prefix, end, allowed, tick=tick, lots=lots,
                                                       totals=totals, include_quote=False),
                       "with_quote_minute": support(prefix, end, allowed, tick=tick, lots=lots,
                                                    totals=totals, include_quote=True)}
                for name, allowed in rules.items()
            }
        worlds[display(end)] = dict(quote_minute_ohlc=ohlc(prefix[-1]), price_checks=quotes,
                                    min_eight_row_end_label_spread_minutes=fixed_quote_span(end, other_quotes))
    low, high = tick_bounds([first], tick)
    opened = int(first.open / tick)
    by_open = earlier_lot_counts((low, opened - 1), (opened, high), lots, totals)
    return dict(
        study="IRON_FIRST_PROTECTION_OPEN_AND_RECLAIM_PRICE_BOUNDS", contract=CONTRACT,
        plan=source, next_plan=next_plan, photo=photo, verified_original_entry=origins.pop(),
        open_minute_ohlc=ohlc(first), candidate_open_minute_minimum_lots_below_open=min(by_open),
        fixed_gate_known_at=fixed, by_quote_minute=worlds, market=iron["market"],
        cross_row_quote_reference_sha256=QUOTE_REFERENCE_SHA,
        historical_protection_clause_conflicting=True, actual_quote_time=None, author_match_rate=None,
        author_action_samples=0, actionable_author_permission=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = ArgumentParser(description=__doc__)
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
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("IRON_FIRST_")
                        else "IRON_FIRST_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

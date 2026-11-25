"""Compare RU2701 M triggers against two independently visible position averages."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE
from lms405_rubber_leg_transition import CONTRACT, DAY, FIRST, LATER, MINUTE_SHA, PLAN
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sh_protection_replacement import compatible_counts
from lms405_visible_lock_handoff import compare_paths, stamp
from lms_near405_replay import encoded, sha

REFERENCE = Path("output/lms405-rubber-leg-transition-20261125/final.json")
REFERENCE_SHA = "b73fbed1e6052c56e98fe232906b561408159895d069d63edfcbf06b26943541"
BANDS = {"protection": (Decimal(19530), Decimal(19680)), "m": (Decimal(19790), Decimal(19935))}


def first_gates(series, start, cut):
    minutes = completed(series[1], start, cut)
    result = {}
    for role, band in BANDS.items():
        paths = compare_paths(series, "LONG", band, start, cut)
        for edge, price in zip(("near", "far"), band, strict=True):
            name = f"{role}_{edge}"
            touch = next((row.end for row in minutes if row.high >= price), None)
            result[f"{name}_touch"] = dict(end=touch, price=price)
            strict_close = paths["edges"][edge]["first_strict_close"]
            result[f"{name}_strict_close"] = dict(end=strict_close, price=price)
            for variant, events in paths["groups"].items():
                for criterion, key in (("prior_close", "prior_strict_close"),
                                       ("same_run", "current_run_before_shape"),
                                       ("new_crossing", "current_run_started_with_new_crossing")):
                    event = next((row for row in events if row["checks"][edge][key]
                                  and row["checks"][edge]["still_beyond"]), None)
                    if event is not None:
                        result[f"{name}_{variant}_{criterion}"] = dict(
                            end=event["confirmed_at"], price=price, geometry=event,
                        )
    return result


def partition(minute, gate_end, boundary):
    # Minute containing the event is deliberately permissive. Strict full-after also
    # puts the immediately following minute into the earlier/overlapping bucket.
    if boundary == "EVENT_MINUTE_ALLOWED_AFTER":
        return minute.end >= gate_end
    if boundary == "ONLY_COMPLETE_MINUTES_AFTER":
        return minute.start > gate_end
    raise ValueError("RU_M_UNKNOWN_BOUNDARY")


def count_bounds(allowed, lots):
    if not allowed:
        raise ValueError("RU_M_QUOTE_PAIR_NO_COMPATIBLE_COUNTS")
    retained_if_late = [old for old, before, after in allowed if before == 0 and after > 0]
    return dict(
        min_old_retained=min(row[0] for row in allowed), max_old_retained=max(row[0] for row in allowed),
        min_new_earlier_or_overlapping=min(row[1] for row in allowed), min_new_later=min(row[2] for row in allowed),
        max_new_later=max(row[2] for row in allowed),
        all_replacement_after_possible=bool(retained_if_late),
        min_old_retained_if_all_replacement_after=min(retained_if_late, default=None),
        max_old_retained_if_all_replacement_after=max(retained_if_late, default=None),
        all_ending_lots_new_after_possible=any(after == lots for _, _, after in allowed),
        no_replacement_after_possible=any(after == 0 for _, _, after in allowed),
    )


def compare_gate(minutes, quote_pairs, gate_end, *, boundary, tick, lots, old_totals, new_totals):
    rows = {}
    for first, final in quote_pairs:
        if gate_end <= first:
            raise ValueError("RU_M_GATE_NOT_AFTER_SEED_BOUND")
        key = f"{display(first)} / {display(final)}"
        if gate_end > final:
            rows[key] = dict(status="GATE_AFTER_QUOTE_MINUTE")
            continue
        original = tick_bounds([bar for bar in minutes if bar.end <= first], tick)
        possible_new = [bar for bar in minutes if first <= bar.end <= final]
        after = [bar for bar in possible_new if partition(bar, gate_end, boundary)]
        earlier = [bar for bar in possible_new if not partition(bar, gate_end, boundary)]
        allowed = compatible_counts(lots, old_totals, new_totals, original,
                                    tick_bounds(earlier, tick), tick_bounds(after, tick))
        rows[key] = dict(status="EVENT_MINUTE_EQUALS_QUOTE" if gate_end == final else "EVENT_BEFORE_QUOTE_MINUTE",
                         **count_bounds(allowed, lots))
    eligible = [row for row in rows.values() if row["status"] != "GATE_AFTER_QUOTE_MINUTE"]
    late_only = [row for row in eligible if row["all_replacement_after_possible"]]
    return dict(
        pair_details=rows, eligible_pairs=len(eligible), equal_minute_pairs=sum(
            row["status"] == "EVENT_MINUTE_EQUALS_QUOTE" for row in eligible),
        minimum_new_earlier_or_overlapping=min((row["min_new_earlier_or_overlapping"] for row in eligible), default=None),
        minimum_old_retained_if_all_replacement_after=min(
            (row["min_old_retained_if_all_replacement_after"] for row in late_only), default=None),
        maximum_old_retained_if_all_replacement_after=max(
            (row["max_old_retained_if_all_replacement_after"] for row in late_only), default=None),
        **{f"pairs_{name}": sum(row[name] for row in eligible) for name in (
            "all_replacement_after_possible", "all_ending_lots_new_after_possible", "no_replacement_after_possible",
        )},
    )


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_SHA)
    for key in (FIRST, LATER):
        image = reference["source_images"][key]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("RU_M_POSITION_IMAGE_CHANGED")
    series = read_window(session, market, CONTRACT, DAY)
    minutes = series[1]
    if len(minutes) != 345 or digest(minutes) != MINUTE_SHA:
        raise ValueError("RU_M_FROZEN_MARKET_CHANGED")
    sources = reference["sources"]
    start = max(stamp(sources[PLAN]), stamp(sources[FIRST])) + ONE
    cut = stamp(sources[LATER])
    quote_pairs = [(datetime.fromisoformat(first), datetime.fromisoformat(final))
                   for first, captures in reference["pairwise_conditional_bounds"].items() for final in captures]
    if len(quote_pairs) != 44:
        raise ValueError("RU_M_QUOTE_PAIR_COUNT_CHANGED")
    lots, tick = reference["initial"]["lots"], Decimal(reference["tick"])
    old_totals, new_totals = (displayed_tick_totals(Decimal(reference[key]["opening_average"]), lots, tick)
                              for key in ("initial", "later"))
    gates = first_gates(series, start, cut)
    for row in gates.values():
        if row["end"] is not None:
            row["partitions"] = {boundary: compare_gate(
                minutes, quote_pairs, row["end"], boundary=boundary, tick=tick, lots=lots,
                old_totals=old_totals, new_totals=new_totals,
            ) for boundary in ("EVENT_MINUTE_ALLOWED_AFTER", "ONLY_COMPLETE_MINUTES_AFTER")}
    baseline = gates["m_near_touch"]["partitions"]["EVENT_MINUTE_ALLOWED_AFTER"]["pair_details"]
    for first, final in quote_pairs:
        old = reference["pairwise_conditional_bounds"][display(first)][display(final)]
        current = baseline[f"{display(first)} / {display(final)}"]
        if lots - current["max_old_retained"] != old["minimum_replaced_lots"] or (
            lots - current["max_new_later"] != old["minimum_lots_originating_before_m"]
        ):
            raise ValueError("RU_M_PRIOR_TOUCH_TEST_CHANGED")
    return dict(
        version="lms405-rubber-m-replacements-v1", contract=CONTRACT, trade_day=DAY.isoformat(),
        reference_sha256=REFERENCE_SHA, sources=sources, seed_images=reference["source_images"],
        market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
        start=start, cutoff_exclusive=cut, quote_pair_count=len(quote_pairs), gates=gates,
        complete_trading_day_high=max(bar.high for bar in minutes),
        publication_scope="RETROSPECTIVE_EDIT_HISTORY_UNVERIFIED", same_account_is_assumed=True,
        author_account_continuity=None, author_action_at=None, actual_replacement=None,
        admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('RU_M_') and code.isidentifier() else 'RU_M_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

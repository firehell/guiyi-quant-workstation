"""Replay feasible old/new lot allocations and compare exposure during partial replacement."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby
from pathlib import Path

from guiyi_quant.lms405 import Position
from lms405_oi_leg_intent import SPECS_SHA
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_origins import allocations
from lms405_protection_lot_timing import tick_bounds, verified_json
from lms405_replay import read_session_series
from lms405_right_side_study import ONE, at
from lms405_sizing_audit import SPECS, load_specs
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

INPUT = Path("output/lms405-portfolio-retention-prices-20261126/final-a.json")
INPUT_SHA = "6dffbea40a4f4b8763794555902ac1f33ba1d00cc1e70f9f46bac0f2dc605364"
DAY = date(2026, 10, 27)
START, MIDDLE, LATE, END = (at(f"{DAY}T{clock}") for clock in ("11:30", "14:00", "14:30", "15:00"))
SOURCE_PAIR = ("WRoAkcEppg", "U03")
CASES = {"OI2701": "short", "JM2701": "long", "V2701": "long", "I2701": "long"}
STEPS = ("reference_start", "before_any_new_lots", "through_14_00", "through_14_30",
         "all_new_lots_present_before_end_cleanup", "reference_end")
POLICIES = ("REMOVE_NONRETAINED_FIRST", "REPLACE_IN_MATCHED_BATCHES", "REMOVE_OLD_AT_END")


def cohorts(counts, policy):
    """Keep the same retained cohort in every checkpoint of this hypothesis."""
    kept, first, second, last = counts
    total_new = first + second + last
    opened = (0, 0, first, first + second, total_new, total_new)
    pending = {
        POLICIES[0]: (total_new, 0, 0, 0, 0, 0),
        POLICIES[1]: tuple(total_new - total for total in opened),
        POLICIES[2]: (total_new, total_new, total_new, total_new, total_new, 0),
    }[policy]
    return tuple(dict(retained_old=kept, old_yet_to_remove=old, new_present=new,
                      side_lots=kept + old + new) for old, new in zip(pending, opened, strict=True))


def position_view(contract, side, opposite, state):
    quantity = state["side_lots"]
    signed = quantity if side == "long" else -quantity
    result = state | dict(signed_visible_side=signed, net_lots=None, gross_lots=None)
    if opposite is not None:
        long, short = (quantity, opposite) if side == "long" else (opposite, quantity)
        position = Position(contract, Decimal(long), Decimal(short))
        result |= dict(net_lots=position.long - position.short, gross_lots=position.long + position.short)
    return result


def summary(contract, side, opposite, combinations, policy):
    if not combinations:
        return dict(allocation_count=0, checkpoints=None, minimum_retained_witness=None)
    paths = [(counts, [position_view(contract, side, opposite, state) for state in cohorts(counts, policy)])
             for counts in combinations]
    checkpoints = {}
    for index, name in enumerate(STEPS):
        rows = [path[index] for _, path in paths]
        checkpoints[name] = {field: [min(row[field] for row in rows), max(row[field] for row in rows)]
                             if rows[0][field] is not None else None
                             for field in ("side_lots", "signed_visible_side", "net_lots", "gross_lots")}
    counts, path = min(paths, key=lambda row: tuple(row[0]))
    return dict(allocation_count=len(paths), checkpoints=checkpoints,
                minimum_retained_witness=dict(allocation=counts, steps=dict(zip(STEPS, path, strict=True))))


def price_allocations(bars, row, tick, *, include_earlier_quote):
    bucket = (
        [bar for bar in bars if (START <= bar.bar_end if include_earlier_quote else START < bar.bar_end)
         and bar.bar_end <= MIDDLE],
        [bar for bar in bars if MIDDLE < bar.bar_end <= LATE],
        [bar for bar in bars if LATE < bar.bar_end <= END],
    )
    ticks = [tick_bounds(rows, tick) for rows in bucket]
    old_total, new_total = (range(row[key][0], row[key][1] + 1) for key in ("old_tick_sum", "new_tick_sum"))
    candidates = allocations(row["earlier_leg"]["quantity"], row["old_ticks"], ticks, old_total, new_total)
    allowed = sorted({counts for counts in candidates if counts[0] in row["retained"]})
    return dict(price_ticks=ticks, minutes=[len(rows) for rows in bucket], allocations=allowed)


def additions_by_retained(combinations):
    result = {}
    for retained, group in groupby(combinations, key=lambda row: row[0]):
        rows = list(group)
        first = [row[1] for row in rows]
        through_second = [row[1] + row[2] for row in rows]
        result[retained] = dict(through_14_00=[min(first), max(first)],
                                through_14_30=[min(through_second), max(through_second)])
    return result


def case_study(contract, side, report, bars, tick):
    scopes = report["capture_scopes"]
    for source, expected in zip(SOURCE_PAIR, (START, END), strict=True):
        scope = scopes[source]
        if (scope["scope"] != "JOINT_QUOTE_ANCHOR" or scope["day"] != str(DAY)
                or any(datetime.fromisoformat(scope[key]) != expected for key in ("earliest", "latest"))):
            raise ValueError("LMS_LOT_REPLAY_CAPTURE_CHANGED")
    legs = {row["side"]: row for row in report["checks"] if (row["before"], row["after"]) == SOURCE_PAIR}
    row = legs[side]
    opposite_leg = legs["long" if side == "short" else "short"]
    lots = row["earlier_leg"]["quantity"]
    if (lots != row["later_leg"]["quantity"] or row["prior_session_close"]
            or row["earlier_leg"]["today_quantity"] != lots
            or row["later_leg"]["today_quantity"] not in (None, lots)):
        raise ValueError("LMS_LOT_REPLAY_ENDPOINTS_CHANGED")
    opposite = None
    if opposite_leg["retained"] is not None:
        retained = opposite_leg["retained"]
        if retained != [opposite_leg["earlier_leg"]["quantity"]] or retained != [opposite_leg["later_leg"]["quantity"]]:
            raise ValueError("LMS_LOT_REPLAY_OPPOSITE_NOT_FIXED")
        opposite = retained[0]
    scenarios = {}
    for name, permit_quote in (("ALLOW_REFERENCE_MINUTE", True), ("AFTER_REFERENCE_MINUTE", False)):
        result = price_allocations(bars, row, tick, include_earlier_quote=permit_quote)
        combinations = result.pop("allocations")
        feasible = sorted({counts[0] for counts in combinations})
        if permit_quote and feasible != row["retained"]:
            raise ValueError("LMS_LOT_REPLAY_RETAINED_PARITY_FAILED")
        if not combinations:
            raise ValueError("LMS_LOT_REPLAY_NO_COHERENT_ALLOCATION")
        partial = [counts for counts in combinations if 0 < counts[0] < lots]
        full = [counts for counts in combinations if counts[0] == 0]
        scenarios[name] = result | dict(
            feasible_retained=feasible, unchanged_possible=lots in feasible, full_rebuild_possible=bool(full),
            new_counts_by_retained=additions_by_retained(combinations),
            partial_replacement={policy: summary(contract, side, opposite, partial, policy) for policy in POLICIES},
            full_rebuild_remove_first=summary(contract, side, opposite, full, POLICIES[0]),
            comparison_whole_leg_exit=dict(min_visible_side_lots=0, compatible=bool(full)),
        )
    return dict(
        side=side, visible_side_lots=lots, endpoint_identity=SOURCE_PAIR, opposite_lots_assumed_fixed=opposite,
        opposite_observation=opposite_leg, earlier_observation=row["earlier_leg"],
        later_observation=row["later_leg"], scenarios=scenarios,
    )


def study(session, market):
    frozen = verified_json(INPUT, INPUT_SHA)
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    sources = {source: frozen["snapshot_sources"][source] for source in SOURCE_PAIR}
    for record in sources.values():
        image = record["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("LMS_LOT_REPLAY_ATTACHMENT_CHANGED")
    results = {}
    for contract, side in CASES.items():
        bars = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (DAY,))
        fingerprint = dict(count=len(bars), sha256=bars_sha(bars))
        source = frozen["contracts"][contract]
        if fingerprint != source["market"][str(DAY)]:
            raise ValueError("LMS_LOT_REPLAY_MARKET_CHANGED")
        results[contract] = case_study(contract, side, source, bars, specs[contract]["tick"]) | dict(market=fingerprint)
    return dict(
        version="lms405-partial-leg-exposure-v1", quote_sources=sources, references=dict(retention=INPUT_SHA, specs=SPECS_SHA),
        phase_end_times=[MIDDLE, LATE, END], trading_day=DAY, cases=results,
        scope="RETROSPECTIVE_ENDPOINT_CONDITIONED_HYPOTHESES_NO_TEMPORARY_UNOBSERVED_LOTS",
        price_path="TICK_ENVELOPES_WITH_JOINT_ENDPOINT_SUMS_NOT_FILLABILITY",
        author_permissions=None, checkpoints_are_marginal_ranges=True,
        author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False,
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
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("LMS_LOT_REPLAY_") and code.isidentifier()
                        else "LMS_LOT_REPLAY_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

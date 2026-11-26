"""Extend the fixed nine-contract LMS replay without seeding positions from photos."""

from argparse import ArgumentParser
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import (
    FIRST, FIRST_LEG_DISPLAY, MANAGED, MANAGED_SHA, NIGHT, SIZE, SIZE_SHA, SPECS, SPECS_SHA,
    compare_leg, leg_changes, load_specs, lot_profile, pta_example, summarize,
)
from lms405_portfolio_replay import CONTRACTS, DAYS, input_sources
from lms405_portfolio_task_policy import replay_scoped_policy
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest
from lms405_sized_portfolio_replay import PTA_CASE_ENTRY
from lms405_v_ta_case import identity
from lms_near405_replay import encoded

CONTROL = (Path("output/lms405-portfolio-advance-wait-20261126/final-a.json"),
           "880478bf2ad0d4c9d6d2c075d32118b430a787a8cfeed70dfafff516a4b09279")
EXTRA_DAYS = tuple(date(2026, 10, day) for day in (16, 19, 20, 21, 22))
ALL_DAYS = (*EXTRA_DAYS, *DAYS)
STARTS = tuple(day for day in ALL_DAYS if day.day in (16, 19, 22, 23))
FROZEN_SCOPE = dict(published_bands=True, right_entries=True, left_mode="shape-overlap", advance_at_touch=True)


def cohort_price_support(leg, average, trading_day, quote_end, minutes, tick):
    """Bound the reported prior/current lots using minutes strictly before the quote minute."""
    lots, today = leg["quantity"], leg["today_quantity"]
    if today is None:
        return dict(status="TODAY_UNKNOWN")
    if type(lots) is not int or type(today) is not int or not 0 <= today <= lots or lots <= 0:
        raise ValueError("ORIGIN_WINDOW_LOT_FIELDS_INVALID")
    eligible = [bar for bar in minutes if bar.bar_end <= quote_end - ONE]
    prior_minutes = [bar for bar in eligible if bar.trading_day < trading_day]
    earlier = tick_bounds(prior_minutes, tick)
    current = tick_bounds([bar for bar in eligible if bar.trading_day == trading_day], tick)
    required_earlier = lots - today
    result = dict(earlier_tick_bounds=earlier, current_tick_bounds=current, required_earlier_lots=required_earlier)
    if (required_earlier and earlier is None) or (today and current is None):
        return result | dict(status="REQUIRED_COHORT_HAS_NO_MINUTES")
    totals = displayed_tick_totals(average, lots, tick)
    allowed = earlier_lot_counts(earlier, current, lots, totals)
    status = "COHORT_PRICE_COMPATIBLE" if required_earlier in allowed else "COHORT_PRICE_OUTSIDE_ENVELOPE"
    if today == 0:
        prior_days = defaultdict(list)
        for bar in prior_minutes:
            prior_days[bar.trading_day].append(bar)
        result["prior_whole_leg_price_days"] = [
            day for day, bars in sorted(prior_days.items()) if earlier_lot_counts(None, tick_bounds(bars, tick), lots, totals)
        ]
    return result | dict(status=status)


def observed_average(contract, row):
    if row["source"] == FIRST and row["side"] == "long":
        return Decimal(FIRST_LEG_DISPLAY[contract][0])
    if (row["source"], contract, row["side"]) == (NIGHT, "SH2701", "long"):
        return Decimal("1492.0")
    return Decimal(row["visible"]["opening_average"])


def compare_rows(contract, rows, control_name, actions, minutes, size, ta_lots, tick):
    changes = leg_changes(contract, actions)
    minute_index = {bar.bar_end: bar for bar in minutes}
    checked = []
    for row in rows:
        if row["status"] != "CHECKED":
            checked.append({key: value for key, value in row.items() if key != "by_variant"})
            continue
        day = date.fromisoformat(row["assumed_trading_day"])
        average, mark = observed_average(contract, row), Decimal(row["reported_quote"])
        leg, side = row["visible"], row["side"]
        replay, strict_replay, cohorts = {}, {}, {}
        for at in row["by_variant"][control_name]:
            end = datetime.fromisoformat(at)
            bar = minute_index[end]
            if (bar.trading_day != day or not bar.low <= mark <= bar.high
                    or (row["quote_scope"] == "ALIGNED" and bar.close != mark)):
                raise ValueError("ORIGIN_WINDOW_QUOTE_CHANGED")
            for checks, decision_cutoff in ((replay, end), (strict_replay, end - ONE)):
                active = next((state.get(side) for when, state in reversed(changes) if when < decision_cutoff), None)
                if checks is strict_replay and active and active[2] is not None and active[2] >= decision_cutoff:
                    active = (*active[:2], None)
                projected_size = ta_lots if contract == "TA2701" and active and active[0] == PTA_CASE_ENTRY else size
                check = compare_leg(leg, average, day, decision_cutoff, active, minutes, projected_size, tick)
                if (checks is strict_replay and check["status"] == "PRICE_COMPATIBLE"
                        and not check["price_compatible_strict"]):
                    check = check | dict(status="STRICT_PRICE_OUTSIDE_ENVELOPE")
                checks[at] = check
            cohorts[at] = cohort_price_support(leg, average, day, end, minutes, tick)
        checked.append(row | dict(by_variant={"replay": replay, "strict_replay": strict_replay},
                                  cohort_price_by_quote=cohorts))
    return checked


def prior_counts(rows):
    counts = Counter()
    for row in rows:
        if "visible" not in row:
            continue
        leg = row["visible"]
        today = leg["today_quantity"]
        if today is None or today >= leg["quantity"]:
            continue
        counts["VISIBLE_PRIOR_LOT_ROWS"] += 1
        counts["ALL_LOTS_PRIOR_ROWS"] += today == 0
        if row["status"] != "CHECKED":
            counts["PRIOR_LOT_ROWS_WITHOUT_QUOTE"] += 1
            continue
        counts["PRIOR_LOT_ROWS_WITH_QUOTE"] += 1
        cohort = {item["status"] for item in row["cohort_price_by_quote"].values()}
        replay = {item["status"] for item in row["by_variant"]["replay"].values()}
        strict = {item["status"] for item in row["by_variant"]["strict_replay"].values()}
        counts["PRICE_WITHOUT_STRICT_REPLAY_COMPATIBILITY"] += (
            "COHORT_PRICE_COMPATIBLE" in cohort and "PRICE_COMPATIBLE" not in strict
        )
        counts["PRICE_COMPATIBLE"] += "COHORT_PRICE_COMPATIBLE" in cohort
        counts["SINGLE_PRIOR_DAY_PRICE_COMPATIBLE"] += any(
            item.get("prior_whole_leg_price_days") for item in row["cohort_price_by_quote"].values()
        )
        counts["ALL_QUOTES_WITHOUT_REQUIRED_MINUTES"] += cohort == {"REQUIRED_COHORT_HAS_NO_MINUTES"}
        counts["REPLAY_COMPATIBLE"] += "PRICE_COMPATIBLE" in replay
        counts["STRICT_REPLAY_COMPATIBLE"] += "PRICE_COMPATIBLE" in strict
    return dict(counts)


def study(session, market):
    from app.market_data.market_data_service import MarketDataError

    control = verified_json(*CONTROL)["rolling_nine_contract_comparison"]
    if set(control["contracts"]) != set(CONTRACTS) or control["variant"] != (
        "published_entries_left_shape_overlap_advance_waits_first_touch"
    ):
        raise ValueError("ORIGIN_WINDOW_CONTROL_SCOPE_CHANGED")
    managed = verified_json(MANAGED, MANAGED_SHA)
    cutoff = datetime.fromisoformat(managed["as_of"])
    sized = verified_json(SIZE, SIZE_SHA)
    profile, ta_lots = lot_profile(sized), pta_example(sized)
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    index = input_sources()
    contracts = {}
    for contract in CONTRACTS:
        windows, cached = {}, None
        for start in STARTS:
            days = tuple(day for day in ALL_DAYS if day >= start)
            try:
                if cached is None:
                    cached = read_pair(session, market, contract, days)
            except MarketDataError as error:
                windows[start.isoformat()] = dict(status="LOCAL_MDS_BLOCKED", reason=error.code)
                continue
            except ValueError as error:
                if str(error) != "SESSION_OR_BAR_COVERAGE_MISMATCH":
                    raise
                windows[start.isoformat()] = dict(status="LOCAL_MDS_BLOCKED", reason=str(error))
                continue
            raw, series = cached
            minutes = [bar for bar in raw[1] if bar.trading_day >= start]
            fives = [bar for raw_bar, bar in zip(raw[5], series[5], strict=True)
                     if raw_bar.trading_day >= start and bar.end + US <= cutoff]
            control_fives = [bar for raw_bar, bar in zip(raw[5], series[5], strict=True)
                             if raw_bar.trading_day >= DAYS[0] and bar.end + US <= cutoff]
            frozen_market = managed["cases"][contract]
            if len(control_fives) != frozen_market["bars"] or digest(control_fives) != frozen_market["input_prefix_sha256"]:
                raise ValueError("ORIGIN_WINDOW_CONTROL_MARKET_CHANGED")
            actions, blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, **FROZEN_SCOPE)
            rows = compare_rows(contract, control["contracts"][contract], control["variant"], actions, minutes,
                                profile.get(contract), ta_lots, specs[contract]["tick"])
            if start == DAYS[0]:
                for previous, row in zip(control["contracts"][contract], rows, strict=True):
                    if row["status"] == "CHECKED" and json.loads(encoded(row["by_variant"]["replay"])) != (
                        previous["by_variant"][control["variant"]]
                    ):
                        raise ValueError("ORIGIN_WINDOW_CONTROL_QUOTE_RESULT_CHANGED")
            counts = summarize({contract: rows})[contract]
            windows[start.isoformat()] = dict(
                status="CHECKED", trading_days=days, first_bar_start=minutes[0].bar_end - ONE,
                market={"1m": identity(minutes), "5m_prefix_sha256": digest(fives), "5m_bars": len(fives)},
                replay=counts["replay"], strict_replay=counts["strict_replay"], prior_lot_rows=prior_counts(rows),
                actions=actions, blocked=blocked, comparisons=rows,
            )
        contracts[contract] = windows
    return dict(version="lms405-portfolio-origin-window-v1", control_sha256=CONTROL[1],
                start_trading_days=STARTS, as_of=cutoff, replay_uses_fixture_approvals=True,
                source_revision_history_verified=False, screenshot_positions_used_as_inputs=False,
                contracts=contracts, author_action_samples=0, author_match_rate=None, fills=None, pnl=None,
                executable=False)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from sqlalchemy.exc import OperationalError
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as out:
            out.write(encoded(report))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as error:
        code = str(error)
        parser.exit(2, f"{code if code.startswith('ORIGIN_WINDOW_') and code.isidentifier() else 'ORIGIN_WINDOW_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

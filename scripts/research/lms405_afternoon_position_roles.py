"""Compare same-table noon/close position roles and the minute-only FG report."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from lms405_fg_exit_study import (
    CONTRACT, IMAGES, ORDER_BASELINE, ORDER_BASELINE_SHA, position_cutoffs, pressure_timeline,
)
from lms405_fg_sa_cycle_order import fresh_geometry
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 27)
LUNCH, CLOSE = "WRoAkcEppg", "U03"
CONTRACTS = (CONTRACT, "SH2701", "I2701")
REPORT_START = at(f"{DAY}T14:08")
RETENTION = (Path("output/lms405-portfolio-retention-prices-20261126/final-a.json"),
             "6dffbea40a4f4b8763794555902ac1f33ba1d00cc1e70f9f46bac0f2dc605364")


def quantities(table, contract):
    return tuple(table["legs"].get(f"{contract}:{side}", {}).get("quantity") for side in ("long", "short"))


def compare_paths(contract, before, after):
    """Keep unlisted rows unknown except in the explicit common-position-scope hypothesis."""
    seed = Position(contract, *(Decimal(n) if n is not None else Decimal(0) for n in before))
    paths = {"hold": (), "close_original_short": (Action("EXIT_SHORT", seed.short),)}
    if seed.long == seed.short:
        paths["withdraw_protective_long"] = (Action("UNLOCK_SHORT", seed.short),)
        paths["clear_both"] = (Action("CLEAR", seed.long + seed.short),)
    elif seed.long == 0:
        lock = Action("LOCK", seed.short)
        paths["add_protective_long"] = (lock,)
        paths["lock_then_clear"] = (lock, Action("CLEAR", 2 * seed.short))

    results = {}
    for name, steps in paths.items():
        position = seed
        states = []
        short_reduces = False
        for step in steps:
            next_position = apply_action(position, step)
            short_reduces |= next_position.short < position.short
            position = next_position
            states.append(dict(action=step.kind, long=position.long, short=position.short))
        projected = (position.long, position.short)
        visible_checks = [actual == observed for actual, observed in zip(projected, after, strict=True)
                          if observed is not None]
        results[name] = dict(
            timeline=states, after=dict(long=position.long, short=position.short),
            visible_close_compatible=all(visible_checks) if visible_checks else None,
            complete_scope_close_compatible=all(actual == (0 if observed is None else observed)
                                                for actual, observed in zip(projected, after, strict=True)),
            contains_short_reduction=short_reduces,
        )
    return results


def report_clocks(series, from_time, through_time):
    prices = completed(series[1], from_time, through_time)
    timeline = {str(edge): pressure_timeline(prices, edge) for edge in map(Decimal, (836, 842, 844))}
    geometry = {side: fresh_geometry(series, from_time, through_time, side) for side in ("LONG", "SHORT")}
    return dict(edges=timeline, signals=geometry, complete_minutes=len(prices))


def study(session, market):
    order = verified_json(ORDER_BASELINE, ORDER_BASELINE_SHA)
    retention = verified_json(*RETENTION)
    tables = position_cutoffs()
    if tables != order["position_tables"]:
        raise ValueError("AFTERNOON_SCOPE_SNAPSHOT_DRIFT")
    before, after = tables[LUNCH], tables[CLOSE]
    start, end = (datetime.fromisoformat(row["quote_anchor"]) for row in (before, after))
    if not start == at(f"{DAY}T11:30") < REPORT_START < REPORT_START + ONE < end == at(f"{DAY}T15:00"):
        raise ValueError("AFTERNOON_SCOPE_CLOCK_DRIFT")
    report = order["software_buy_close"]
    relative, expected = IMAGES["close_log"]
    if (sha((ARCHIVE.parent / "02-持仓记录" / relative).read_bytes()) != expected
            or report["displayed_time"] != "14:08" or report["report_order_id"] not in order["newly_visible_at_close"]
            or not report["displayed_filled"] or any(report[k] is not None for k in (
                "executed_date", "executed_quantity", "executed_price", "strategy_version", "account",
            ))):
        raise ValueError("AFTERNOON_SCOPE_REPORT_DRIFT")
    index = input_sources()
    audit_sources = {key: load_source(index, key) for key in (LUNCH, CLOSE, "WRoCswszPF", "WRoCCdf0i5")}
    if any(datetime.fromisoformat(audit_sources[key]["published_at"]) <= end for key in ("WRoCswszPF", "WRoCCdf0i5")):
        raise ValueError("AFTERNOON_SCOPE_RECAP_PRECEDED_CLOSE")

    cases = {}
    for contract in CONTRACTS:
        prior, later = quantities(before, contract), quantities(after, contract)
        paths = compare_paths(contract, prior, later)
        if contract != CONTRACT:
            (old_short,) = [row for row in retention["contracts"][contract]["checks"]
                            if (row["before"], row["after"], row["side"]) == (LUNCH, CLOSE, "short")]
            if (old_short["retained"] != [prior[1]] or old_short["earlier_leg"] != before["legs"][f"{contract}:short"]
                    or old_short["later_leg"] != after["legs"][f"{contract}:short"]):
                raise ValueError("AFTERNOON_SCOPE_OLD_SHORT_DRIFT")
        cases[contract] = dict(
            noon_observed_long_short=prior, close_observed_long_short=later, paths=paths,
            assumed_missing_noon_leg_zero_for_projection=any(n is None for n in prior),
            report_contract_match=contract == CONTRACT,
            applicable_software_short_reduction_paths=[name for name, result in paths.items()
                                                     if result["contains_short_reduction"]] if contract == CONTRACT else None,
            conditional_retained_short=prior[1] if contract != CONTRACT else None,
        )

    series = read_window(session, market, CONTRACT, DAY)
    fingerprint = {f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()}
    if fingerprint != order["market"]:
        raise ValueError("AFTERNOON_SCOPE_MARKET_DRIFT")
    clocks = {}
    for label, cutoff in (("before_minute", REPORT_START), ("inside_minute_possible", REPORT_START + ONE),
                          ("after_minute_control", end)):
        clocks[label] = report_clocks(series, start, cutoff)
        prefix = {p: [b for b in rows if b.end + US < cutoff] for p, rows in series.items()}
        if report_clocks(prefix, start, cutoff) != clocks[label]:
            raise ValueError("AFTERNOON_SCOPE_PREFIX_DRIFT")
    return dict(
        version="lms405-afternoon-position-roles-v1", attachments=order["software_images"], sources=audit_sources,
        report=report, report_minute_start_assumed=REPORT_START, report_seconds=None, histories=cases,
        fg_clocks=clocks, market=fingerprint,
        missing_row_scope="UNKNOWN_WITHOUT_SAME_ACCOUNT_COMPLETE_POSITIONS_AND_SYNCHRONIZED_CAPTURE",
        report_relationship="SCREENSHOT_BUY_CLOSE_ONLY_NO_ACCOUNT_OR_QUANTITY_BINDING",
        author_actions_scored=0, author_match_rate=None, fills=None, pnl=None, executable=False,
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
        parser.exit(2, f"{code if code.startswith('AFTERNOON_SCOPE_') else 'AFTERNOON_SCOPE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

"""Compare a separately confirmed range-target exit against the frozen nine-contract replay."""

from argparse import ArgumentParser
from datetime import date, datetime
import json
from pathlib import Path

from lms405_directional_exit_audit import REFERENCES as EXIT_SOURCES
from lms405_m_permission_study import read_pair
from lms405_old_short_entry_retention import ORIGIN
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, load_specs, lot_profile, pta_example, summarize
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE, compare_rows, prior_counts
from lms405_portfolio_replay import CONTRACTS, input_sources
from lms405_portfolio_task_policy import RANGE_TARGET_EXIT, replay_scoped_policy
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import digest
from lms405_v_ta_case import identity
from lms_near405_replay import encoded

STARTS = (date(2026, 10, 19), date(2026, 10, 23))
VARIANT = "lms405-range-target-requires-trend-exit-confirmation-v1"
EXIT_AUDIT = (Path("output/lms405-directional-exit-20261125/final.json"),
              "617e8befb050958c5b441cda3b9ed9c205efd1bb7dcfc2a2f5112c5d7e99b090")


def compatibility_changes(before, after):
    changes = []
    for old, new in zip(before, after, strict=True):
        if (old["source"], old["side"], old["status"]) != (new["source"], new["side"], new["status"]):
            raise ValueError("RANGE_EXIT_QUOTE_SCOPE_CHANGED")
        if old["status"] != "CHECKED":
            continue
        old_quotes = old["by_variant"]["strict_replay"]
        new_quotes = new["by_variant"]["strict_replay"]
        if old_quotes.keys() != new_quotes.keys():
            raise ValueError("RANGE_EXIT_QUOTE_CLOCKS_CHANGED")
        gains = [quote for quote, record in new_quotes.items()
                 if record["status"] == "PRICE_COMPATIBLE" and old_quotes[quote]["status"] != "PRICE_COMPATIBLE"]
        losses = [quote for quote, record in old_quotes.items()
                  if record["status"] == "PRICE_COMPATIBLE" and new_quotes[quote]["status"] != "PRICE_COMPATIBLE"]
        if gains or losses:
            changes.append(dict(source=old["source"], side=old["side"], before_visible=old["visible"],
                                newly_compatible_quotes=gains, lost_compatible_quotes=losses))
    return changes


def study(session, market):
    control = verified_json(*ORIGIN)
    exit_evidence = verified_json(*EXIT_AUDIT)
    cutoff = datetime.fromisoformat(control["as_of"])
    sized = verified_json(SIZE, SIZE_SHA)
    profile, ta_lots = lot_profile(sized), pta_example(sized)
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    index = input_sources()
    all_days = tuple(day for day in ALL_DAYS if day >= STARTS[0])
    contracts = {}
    for contract in CONTRACTS:
        raw, series = read_pair(session, market, contract, all_days)
        windows = {}
        for start in STARTS:
            frozen = control["contracts"][contract][start.isoformat()]
            minutes = [bar for bar in raw[1] if start <= bar.trading_day]
            fives = [bar for native, bar in zip(raw[5], series[5], strict=True)
                     if start <= native.trading_day and bar.end + US <= cutoff]
            if identity(minutes) != frozen["market"]["1m"] or digest(fives) != frozen["market"]["5m_prefix_sha256"]:
                raise ValueError("RANGE_EXIT_FROZEN_MARKET_CHANGED")
            original, original_blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, **FROZEN_SCOPE)
            if json.loads(encoded((original, original_blocked))) != [frozen["actions"], frozen["blocked"]]:
                raise ValueError("RANGE_EXIT_FROZEN_TAPE_CHANGED")
            actions, blocked, *_ = replay_scoped_policy(
                fives, minutes, cutoff, index, range_exit_requires_confirmation=True, **FROZEN_SCOPE,
            )
            rows = compare_rows(contract, frozen["comparisons"], "replay", actions, minutes,
                                profile.get(contract), ta_lots, specs[contract]["tick"])
            counts = summarize({contract: rows})[contract]
            windows[start.isoformat()] = dict(
                market=frozen["market"], actions=actions, blocked=blocked,
                newly_pending_range_exits=[row for row in blocked if row.get("reason") == RANGE_TARGET_EXIT],
                control=dict(replay=frozen["replay"], strict_replay=frozen["strict_replay"],
                             prior_rows=frozen["prior_lot_rows"], action_count=len(original)),
                replay=counts["replay"], strict_replay=counts["strict_replay"], prior_rows=prior_counts(rows),
                changed_quotes=compatibility_changes(frozen["comparisons"], rows), comparisons=rows,
            )
        contracts[contract] = windows
    return dict(version=VARIANT, as_of=cutoff, start_trading_days=STARTS, contracts=contracts,
                references=dict(origin=ORIGIN[1], exit_audit=EXIT_AUDIT[1],
                                exit_examples={key: value[1] for key, value in EXIT_SOURCES.items()}),
                author_reported_exit=exit_evidence["author_reported_soda_exit"],
                admitted_author_action_samples=0, screenshots_used_as_inputs=False, new_exit_permissions=0,
                author_match_rate=None, fills=None, pnl=None, executable=False)


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
    from app.market_data.market_data_service import MarketDataError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as out:
            out.write(encoded(report))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except MarketDataError as error:
        parser.exit(2, f"MDS_BLOCKED: {error.code}\n")
    except (OSError, ValueError, KeyError) as error:
        code = str(error)
        parser.exit(2, f"{code if code.startswith('RANGE_EXIT_') and code.isidentifier() else 'RANGE_EXIT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

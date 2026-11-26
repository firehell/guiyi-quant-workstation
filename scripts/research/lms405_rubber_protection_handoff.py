"""Replay a two-revision rubber hedge handoff without importing screenshot positions."""

from argparse import ArgumentParser
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, leg_changes, load_specs, lot_profile, summarize
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE, compare_rows
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, input_sources
from lms405_portfolio_task_policy import replay_scoped_policy
from lms405_protection_handoff_candidates import HandoffPlan
from lms405_protection_lot_timing import verified_json
from lms405_public_plan_roles import load_source
from lms405_range_exit_portfolio import STARTS, compatibility_changes
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

CONTROL = (Path("output/lms405-range-exit-portfolio-20261126/final-a.json"),
           "00ffb053035f4062b8ac60e584fc69740a69d5a6172be1c9d5521e65a7c522d6")
CONTRACT = "RU2701"
OLD, RECOVER, REPLACE = "A5357264793370945", "A5358325972992140", "A5358686695981271"
CLOCKS = ("FAR_CLOSE", "FAR_CLOSE_THEN_SHAPE")
NIGHT = "WRoEvasxQR"
OLD_PHOTO = "WRov1j6e10"
OLD_IMAGE = ("Rov1j6e10-position-screen.png", "35106f37378f2410b5235773a58c3e9c44581fe3eb84a2af66bf2402405cc9cb")


def displayed_minute_end(source):
    return datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE


def totals(portfolio, start, rubber):
    counters = [rubber, *(windows[start]["strict_replay"] for symbol, windows in portfolio.items() if symbol != CONTRACT)]
    identities = ("VISIBLE_LEGS_CHECKED", "AT_LEAST_ONE_QUOTE_COMPATIBLE", "TWO_VISIBLE_LEGS_CHECKED",
                  "BOTH_LEGS_COMPATIBLE_AT_SAME_QUOTE")
    return {key: sum(counts.get(key, 0) for counts in counters) for key in identities}


def night_joint_quotes(rows):
    long, short = ({quote for quote, check in row["by_variant"]["strict_replay"].items()
                    if check["status"] == "PRICE_COMPATIBLE"}
                   for row in rows if row["source"] == NIGHT and row["status"] == "CHECKED")
    return sorted(long & short)


def old_photo_assuming_complete_display(rows, actions):
    """Test the earlier no-long display as a separate, explicitly conditional check."""
    row, = (item for item in rows if item["source"] == OLD_PHOTO and item["side"] == "short")
    changes = leg_changes(CONTRACT, actions)
    result = {}
    for quote_end, check in row["by_variant"]["strict_replay"].items():
        start = datetime.fromisoformat(quote_end) - ONE
        state = next((current for when, current in reversed(changes) if when < start), {})
        result[quote_end] = dict(short_compatible=check["status"] == "PRICE_COMPATIBLE",
                                 modeled_long_present="long" in state)
    return result


def study(session, market):
    frozen = verified_json(*CONTROL)
    portfolio = frozen["contracts"]
    if set(portfolio) != set(CONTRACTS):
        raise ValueError("RUBBER_HANDOFF_CONTROL_SCOPE_CHANGED")
    cutoff = datetime.fromisoformat(frozen["as_of"])
    profile = lot_profile(verified_json(SIZE, SIZE_SHA))
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    index = input_sources()
    sources = {key: load_source(index, key) for key in (OLD, RECOVER, REPLACE)}
    for row in sources.values():
        row["archive_sha256"] = sha((ARCHIVE.parent / row["archive_path"]).read_bytes())
    old_photo = load_source(index, OLD_PHOTO)
    image = Path(old_photo["archive_path"]).with_name(OLD_IMAGE[0])
    if sha((ARCHIVE.parent / image).read_bytes()) != OLD_IMAGE[1]:
        raise ValueError("RUBBER_HANDOFF_OLD_PHOTO_CHANGED")
    raw, series = read_pair(session, market, CONTRACT, tuple(day for day in ALL_DAYS if day >= STARTS[0]))
    windows = {}
    for start in STARTS:
        key = start.isoformat()
        control = portfolio[CONTRACT][key]
        minutes = [bar for bar in raw[1] if bar.trading_day >= start]
        fives = [bar for native, bar in zip(raw[5], series[5], strict=True)
                 if native.trading_day >= start and bar.end + US <= cutoff]
        if identity(minutes) != control["market"]["1m"] or digest(fives) != control["market"]["5m_prefix_sha256"]:
            raise ValueError("RUBBER_HANDOFF_MARKET_CHANGED")
        opts = dict(FROZEN_SCOPE, range_exit_requires_confirmation=True)
        actions, blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, **opts)
        if json.loads(encoded((actions, blocked))) != [control["actions"], control["blocked"]]:
            raise ValueError("RUBBER_HANDOFF_CONTROL_ACTIONS_CHANGED")
        variants = {}
        for clock in CLOCKS:
            plan = HandoffPlan(CONTRACT, OLD, RECOVER, displayed_minute_end(sources[RECOVER]), at("2026-10-26T21:00"),
                               Decimal(19505), REPLACE, displayed_minute_end(sources[REPLACE]), at("2026-10-27T21:00"), clock)
            candidate, diagnostics, *_ = replay_scoped_policy(fives, minutes, cutoff, index, handoff_plan=plan, **opts)
            rows = compare_rows(CONTRACT, control["comparisons"], "replay", candidate, minutes, profile[CONTRACT], None, tick)
            counts = summarize({CONTRACT: rows})[CONTRACT]["strict_replay"]
            variants[clock] = dict(plan=asdict(plan), actions=candidate, diagnostics=diagnostics,
                                   portfolio=totals(portfolio, key, counts), rubber=counts,
                                   changed_quotes=compatibility_changes(control["comparisons"], rows),
                                   strict_night_joint_quotes=night_joint_quotes(rows),
                                   old_photo_if_complete=old_photo_assuming_complete_display(rows, candidate), rows=rows)
        windows[key] = dict(control=totals(portfolio, key, control["strict_replay"]), rubber_market=control["market"],
                            control_night_joint_quotes=night_joint_quotes(control["comparisons"]),
                            control_old_photo_if_complete=old_photo_assuming_complete_display(control["comparisons"], actions),
                            variants=variants)
    return dict(version="lms405-rubber-two-revision-protection-handoff-v1", control_sha256=CONTROL[1],
                scoped_contract=CONTRACT, other_contracts_frozen=list(c for c in CONTRACTS if c != CONTRACT),
                sources=sources, old_photo=old_photo | dict(image_path=image.as_posix(), image_sha256=OLD_IMAGE[1],
                                                            visible_rows=10, visible_total_lots=246,
                                                            full_account_display_verified=False),
                windows=windows, historical_source_revisions_verified=False,
                approvals_are_test_fixtures=True, screenshot_positions_used_as_inputs=False,
                author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False)


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
        parser.exit(2, f"{code if code.startswith('RUBBER_HANDOFF_') and code.isidentifier() else 'RUBBER_HANDOFF_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

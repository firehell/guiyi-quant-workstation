"""Replay source-scoped early SH2701 entry and later protection as separate hypotheses."""

from argparse import ArgumentParser
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_divider_short_candidates import DividerShortPlan
from lms405_m_permission_study import read_pair
from lms405_old_short_entry_retention import strict_price
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, load_specs, lot_profile, summarize
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE, compare_rows
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import replay_scoped_policy
from lms405_protection_handoff_candidates import HandoffPlan
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_public_plan_roles import load_source
from lms405_range_exit_portfolio import compatibility_changes
from lms405_rubber_protection_handoff import CONTROL, displayed_minute_end
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

CONTRACT = "SH2701"
ENTRY, OLD_LOCK, RECOVERY_REF, NEW_PROTECTION = ("A5355789916438626", "A5356884885635211",
                                               "A5358325972992140", "A5358686695981271")
REREVIEW = "WRouYm67Bc"
RUBBER = (Path("output/lms405-rubber-protection-handoff-20261126/verified-a.json"),
          "1848f79804a4483ab2217270e414e34c0d41a29b009004558f39628189e7f01f")
STARTS = (date(2026, 10, 19), date(2026, 10, 20))
ENTRY_MODES = (None, "INSIDE_KEYBAR", "FIRST_FAR_CLOSE")


def case_options(sources, mode, with_handoff):
    entry = DividerShortPlan(CONTRACT, ENTRY, displayed_minute_end(sources[ENTRY]), at("2026-10-19T21:00"),
                             at("2026-10-20T15:01"), Decimal(1726), Decimal(1738), mode) if mode else None
    handoff = HandoffPlan(CONTRACT, OLD_LOCK, RECOVERY_REF, displayed_minute_end(sources[RECOVERY_REF]),
                          at("2026-10-27T11:35"), Decimal(1511), NEW_PROTECTION,
                          displayed_minute_end(sources[NEW_PROTECTION]), at("2026-10-27T21:00"),
                          "FAR_CLOSE_THEN_SHAPE", "ARM_THEN_TOUCH") if with_handoff else None
    return entry, handoff


def portfolio_counts(rubber, frozen_sh, result_sh):
    return {key: value - frozen_sh.get(key, 0) + result_sh.get(key, 0) for key, value in rubber.items()}


def entry_price_witness(actions, minutes, observed, tick):
    """Retrospective price constraint after the chosen entry. Does not seed the replay."""
    entry = next((row for row in actions if "divider_short" in row), None)
    if entry is None:
        return None
    since = datetime.fromisoformat(entry["at"])
    entry_day = next((bar.trading_day for bar in minutes if bar.bar_end < since < bar.bar_end + ONE), None)
    if entry_day is None:
        raise ValueError("SH_ENTRY_HANDOFF_ENTRY_TRADING_DAY_MISSING")
    same_day = [bar for bar in minutes if bar.trading_day == entry_day]
    lots = observed["quantity"]
    average = Decimal(observed["opening_average"])
    totals = displayed_tick_totals(average, lots, tick)
    return strict_price(same_day, since=since, through=same_day[-1].bar_end, lots=lots, totals=totals, tick=tick)


def study(session, market):
    control = verified_json(*CONTROL)
    rubber = verified_json(*RUBBER)
    cutoff = datetime.fromisoformat(control["as_of"])
    reference = control["contracts"][CONTRACT][STARTS[0].isoformat()]
    observed, = (row["visible"] for row in reference["comparisons"]
                 if row["source"] == "WRnTlEfj1t" and row["side"] == "short")
    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    lots = lot_profile(verified_json(SIZE, SIZE_SHA))[CONTRACT]
    index = input_sources()
    sources = {name: load_source(index, name) for name in (ENTRY, OLD_LOCK, RECOVERY_REF, REREVIEW, NEW_PROTECTION)}
    for source in sources.values():
        source["archive_sha256"] = sha((ARCHIVE.parent / source["archive_path"]).read_bytes())
    raw, series = read_pair(session, market, CONTRACT, tuple(day for day in ALL_DAYS if day >= STARTS[0]))
    control_fives = [b for b in series[5] if b.end + US <= cutoff]
    if identity(raw[1]) != reference["market"]["1m"] or digest(control_fives) != reference["market"]["5m_prefix_sha256"]:
        raise ValueError("SH_ENTRY_HANDOFF_MARKET_CHANGED")
    portfolio_baseline = rubber["windows"][STARTS[0].isoformat()]["variants"]["FAR_CLOSE"]["portfolio"]
    windows = {}
    opts = dict(FROZEN_SCOPE, range_exit_requires_confirmation=True)
    for start in STARTS:
        minutes = [b for b in raw[1] if b.trading_day >= start]
        fives = [b for native, b in zip(raw[5], series[5], strict=True)
                 if native.trading_day >= start and b.end + US <= cutoff]
        results, baseline = {}, None
        for mode in ENTRY_MODES:
            for with_handoff in (False, True):
                entry, handoff = case_options(sources, mode, with_handoff)
                actions, blocked, *_ = replay_scoped_policy(fives, minutes, cutoff, index, divider_short_plan=entry,
                                                           handoff_plan=handoff, **opts)
                if mode is None and not with_handoff and start == STARTS[0]:
                    if json.loads(encoded((actions, blocked))) != [reference["actions"], reference["blocked"]]:
                        raise ValueError("SH_ENTRY_HANDOFF_CONTROL_CHANGED")
                rows = compare_rows(CONTRACT, reference["comparisons"], "replay", actions, minutes, lots, None, tick)
                if baseline is None:
                    baseline = rows
                counts = summarize({CONTRACT: rows})[CONTRACT]["strict_replay"]
                key = mode or "BASELINE"
                if with_handoff:
                    key += "_WITH_HANDOFF"
                results[key] = dict(actions=actions, blocked=blocked, comparisons=rows, strict=counts,
                                    entry_same_day_price_witness=entry_price_witness(actions, minutes, observed, tick),
                                    changed_quotes=compatibility_changes(baseline, rows),
                                    portfolio=portfolio_counts(portfolio_baseline, reference["strict_replay"], counts)
                                    if start == STARTS[0] else None)
        windows[start.isoformat()] = dict(market=dict(minutes=identity(minutes), five_digest=digest(fives)), cases=results)
    return dict(version="lms405-sh-divider-entry-and-handoff-v1", sources=sources, windows=windows,
                source_revision_history_verified=False, frozen_range_exit_sha256=CONTROL[1],
                frozen_rubber_handoff_sha256=RUBBER[1], action_kind="TEST_FIXTURE",
                early_recovery_edge_is_old_resistance_sensitivity=True, screenshot_positions_used_as_inputs=False,
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
    except (OSError, KeyError, ValueError) as error:
        code = str(error)
        parser.exit(2, f"{code if code.startswith('SH_ENTRY_HANDOFF_') and code.isidentifier() else 'SH_ENTRY_HANDOFF_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

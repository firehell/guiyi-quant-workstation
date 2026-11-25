"""Compare PTA public-plan availability, short participation and existing-leg management."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position
from guiyi_quant.lms405.validation import decide
from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_pta_pause_carry import MORNING
from lms405_pta_pause_entry import PLAN
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded

VERSION = "lms405-pta-pause-scopes-v1"
JUNE, ENTRY, JULY = "S5311207311147936", "A5315553815822385", "S5315919112832178"
SHORT_PAUSE, NO_NEW_PLAN, REFERENCE_ONLY = "SHORT_PAUSE_REPORTED", "NO_NEW_PUBLIC_PLAN", "REENTRY_REFERENCE_ONLY"
SHORT_REENTRY_ZONE = Decimal(5432), Decimal(5494)
FROZEN_JUNE = (Path("output/lms405-protection-external-cases-20261126/final.json"),
               "c1f891277fad085eef5b70d8209ad40204c892d7b38c0d621e79d80bd878a81a")
FROZEN_OCT = (Path("output/lms405-pta-pause-carry-20261126/reviewed-a.json"),
              "f3d0e65fefc9f64265809b1bff2f861078b39e2b61beda70ebff06dfdafa71ff")
ONE_UNIT = Decimal(1)


def assess_snapshot(contract, system, description, source, *, known_at, as_of):
    """Compare evidence at its report clock, using unit preimages only."""
    visible = known_at < as_of
    no_plan = False if visible and description == NO_NEW_PLAN else None
    short_unpaused = False if visible and description == SHORT_PAUSE and system == "5.0" else None
    flat = Position(contract)
    old_long, old_short = Position(contract, long=ONE_UNIT), Position(contract, short=ONE_UNIT)
    common = dict(source_visible=True if visible else None, specific_signal_and_permission=None)
    routes = {
        "open_short_with_new_public_plan": (flat, "ENTER_SHORT", dict(public_new_plan_available=no_plan,
                                                                     short_participation_unpaused=short_unpaused)),
        "open_long_with_new_public_plan": (flat, "ENTER_LONG", dict(public_new_plan_available=no_plan)),
        "reenter_short_under_separate_permission": (flat, "REENTER_SHORT", dict(short_participation_unpaused=short_unpaused)),
        "open_short_under_separate_permission": (flat, "ENTER_SHORT", dict(short_participation_unpaused=short_unpaused)),
        "open_long_under_separate_permission": (flat, "ENTER_LONG", {}),
        "protect_existing_long": (old_long, "LOCK", dict(existing_leg_path_confirmed=None)),
        "exit_existing_long": (old_long, "EXIT_LONG", dict(existing_leg_path_confirmed=None)),
        "exit_existing_short": (old_short, "EXIT_SHORT", dict(existing_leg_path_confirmed=None)),
    }
    results = {}
    for name, (before, action, conditions) in routes.items():
        result = decide(before, Action(action, ONE_UNIT), common | conditions, (source,))
        if not visible:
            result["sources"] = []
        results[name] = result
    return results


def source_clock(source):
    return datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE


def market_context(series, day, bands):
    minutes = series[1]
    end = at(f"{day}T15:00")
    if minutes[-1].end != end:
        raise ValueError("PTA_SCOPE_SESSION_CUTOFF_CHANGED")
    return dict(start=minutes[0].start, end=end, low=min(b.low for b in minutes), high=max(b.high for b in minutes),
                market={f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()},
                bands={name: observations(minutes, bounds, side) for name, (bounds, side) in bands.items()})


def reentry_context(series, day, known_at):
    context = market_context(series, day, {"short_reentry_reference": (SHORT_REENTRY_ZONE, "SHORT")})
    events, checks = window_signals(series, context["start"], context["end"] + 2 * US, "SHORT")
    near, far = SHORT_REENTRY_ZONE[1], SHORT_REENTRY_ZONE[0]
    candidates = {clock: [event | dict(
        recap_known_before_shape=known_at < event["shape_start"], in_reentry_reference=far <= event["close"] <= near,
        strictly_below_far=event["close"] < far,
    ) for event in rows] for clock, rows in events.items()}
    return context | dict(geometry=candidates, signal_prefix_checks=checks, original_plan_available=None,
                          actual_reentry_at=None, actual_restart_at=None)


def study(session, market, june_ref, october):
    index = input_sources()
    sources = {key: load_source(index, key) for key in (JUNE, ENTRY, JULY, PLAN, MORNING)}
    if (sources[JUNE] != june_ref["source"] or sources[PLAN] != october["sources"][PLAN]
            or sources[MORNING] != october["sources"][MORNING]):
        raise ValueError("PTA_SCOPE_FROZEN_SOURCE_CHANGED")
    contract = "TA2609"
    scopes = ((JUNE, contract, "5.0", SHORT_PAUSE), (JUNE, contract, "4.0.5", SHORT_PAUSE),
              (JULY, contract, "UNRESOLVED", REFERENCE_ONLY), (PLAN, "TA2701", "4.0.5", NO_NEW_PLAN))
    checks = {}
    for key, physical, system, description in scopes:
        known = source_clock(sources[key])
        snapshots = {label: assess_snapshot(physical, system, description, sources[key]["source_url"], known_at=known,
                                           as_of=as_of)
                     for label, as_of in (("before", known - US), ("equal", known), ("after", known + US))}
        if snapshots["before"] != snapshots["equal"] or any(
            row["after"] is not None for snapshot in snapshots.values() for row in snapshot.values()
        ):
            raise ValueError("PTA_SCOPE_UNAUTHORIZED_ACTION_OR_TIME_DIVERGENCE")
        checks[f"{key}:{system}"] = dict(source=key, system=system, description=description, known_at=known,
                                        evaluation_scope="AT_DISCLOSURE_NOT_DURATION_OR_EXECUTION", snapshots=snapshots)
    frozen_bands = {"defense": ((Decimal(5800), Decimal(5820)), "LONG"),
                    "weak_side_m": ((Decimal(5868), Decimal(5888)), "LONG")}
    june = market_context(read_window(session, market, contract, date(2026, 6, 18)), "2026-06-18", frozen_bands)
    if june["market"] != june_ref["market"]:
        raise ValueError("PTA_SCOPE_FROZEN_JUNE_MARKET_CHANGED")
    july = {day: reentry_context(read_window(session, market, contract, date.fromisoformat(day)), day,
                                 source_clock(sources[JULY])) for day in ("2026-07-01", "2026-07-02")}
    if not (source_clock(sources[ENTRY]) < july["2026-07-01"]["start"] < july["2026-07-01"]["end"]
            < source_clock(sources[JULY]) < july["2026-07-02"]["start"]):
        raise ValueError("PTA_SCOPE_ARTICLE_CLOCK_CHANGED")
    kept = min(row["minimum_retained_across_pairs"] for row in october["retention"].values())
    return dict(version=VERSION, sources=sources, assessments=checks, june=june, july=july,
                october=dict(conditional_old_longs_at_least=kept, snapshot_account_continuity=None,
                             new_public_zone_reported_unavailable=True, actual_execution_permission=None),
                june_other_system_identity=None, actual_restart_at=None, author_actions_scored=0, author_match_rate=None,
                original_implementation_unverified=True, executable=False, pnl=None, fills=None,
                frozen_inputs=dict(june=FROZEN_JUNE[1], october=FROZEN_OCT[1]))


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
        june = verified_json(*FROZEN_JUNE)["cases"]["pta"]
        october = verified_json(*FROZEN_OCT)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), june, october)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        name = str(exc)
        parser.exit(2, (name if name.startswith("PTA_SCOPE_") and name.isidentifier() else "PTA_SCOPE_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

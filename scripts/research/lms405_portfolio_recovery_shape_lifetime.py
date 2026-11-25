"""Replay recovery with either an active earlier shape or a new post-cross shape."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff
from lms405_break_pressure_comparison import continuous_groups
from lms405_counter_m_study import beyond
from lms405_fg_sa_cycle_order import fresh_geometry
from lms405_portfolio_recovery_progress import SOURCES, position_at, simulated_confirmation
from lms405_portfolio_replay import ARCHIVE, CONTRACTS
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 27)
NEXT = date(2026, 10, 28)
VERSION = "lms405-portfolio-recovery-shape-lifetime-v1"
EARLIER, NEW = MODES = ("active_shape", "active_shape_started_after_cross")
IRON_REPORT = Path("output/lms405-iron-release-lifetime-20261126/verified-a.json")
IRON_SHA = "546471f7aa95729dcdd64164bd52352df0f0449f4b49bc7d7f451c551dc970f9"


def first_candidates(minutes, geometry, *, edge, side):
    """Both modes share the same consecutive closes and shape invalidation rule."""
    first = {mode: {} for mode in MODES}
    by_end = {}
    for variant, events in geometry.items():
        shape, confirm = (int(part.removesuffix("m")) for part in variant.split("_to_"))
        for event in events:
            if event["available_at"] != event["confirmed_at"] + US:
                raise ValueError("LMS_SHAPE_LIFETIME_GEOMETRY_CLOCK_CHANGED")
            annotated = event | dict(shape_minutes=shape, confirm_minutes=confirm)
            by_end.setdefault(event["confirmed_at"], []).append((variant, annotated))
    for segment in continuous_groups(minutes):
        active = []
        runs = strict_runs(segment, edge, side)
        for bar in segment:
            active = [(variant, event) for variant, event in active if beyond(bar.close, event["boundary"], side)]
            active.extend((variant, event) for variant, event in by_end.get(bar.end, ())
                          if event["shape_start"] >= segment[0].start and beyond(bar.close, event["boundary"], side))
            run = runs.get(bar.end)
            if run is None or run["fresh_crossing_known_at"] is None or run["close_count"] < 2:
                continue
            crossing = run["fresh_crossing_known_at"]
            for variant, event in active:
                candidate = dict(
                    variant=variant, shape_minutes=event["shape_minutes"], confirm_minutes=event["confirm_minutes"],
                    shape_start=event["shape_start"], original_geometry_confirmed_at=event["confirmed_at"],
                    confirmed_at=bar.end, available_at=bar.end + US, crossing_known_at=crossing,
                    conditions={EARLIER: True, NEW: crossing < event["shape_start"]},
                )
                for mode in MODES:
                    if candidate["conditions"][mode]:
                        first[mode].setdefault(variant, candidate)
    return first


def compare(series, start, cutoff, *, side, edge):
    def evaluate(inputs, as_of):
        return first_candidates(completed(inputs[1], start, as_of),
                                fresh_geometry(inputs, start, as_of, side), edge=edge, side=side)

    result = evaluate(series, cutoff)
    clocks = {v["available_at"] for rows in result.values() for v in rows.values()}
    cuts = {cutoff} | clocks | {value + US for value in clocks}
    for as_of in sorted(cuts):
        prefix = {p: [bar for bar in rows if bar.end + US < as_of] for p, rows in series.items()}
        expected = {mode: {variant: row for variant, row in candidates.items() if row["available_at"] < as_of}
                    for mode, candidates in result.items()}
        if evaluate(prefix, as_of) != expected:
            raise ValueError("LMS_SHAPE_LIFETIME_PREFIX_DIVERGED")
    overall = {mode: min(rows.values(), key=lambda row: (row["available_at"], row["variant"]), default=None)
               for mode, rows in result.items()}
    earlier, newer = (overall[mode] for mode in MODES)
    if newer and (not earlier or earlier["available_at"] > newer["available_at"]):
        raise ValueError("LMS_SHAPE_LIFETIME_BRANCH_ORDER_CHANGED")
    return dict(first_by_clock=result, earliest=overall, prefix_checks=len(cuts),
                delay_minutes=(newer["confirmed_at"] - earlier["confirmed_at"]) // ONE if newer else None,
                eligible_price_minutes=len(completed(series[1], start, cutoff)))


def project_seed(evidence, case, *, start, cutoff, scenario):
    contract = evidence["contract"]
    before = evidence["before_visible"]
    seed = Position(contract, Decimal(before["long"]["quantity"]), Decimal(before["short"]["quantity"]))
    request = Handoff("RESUME_ORIGINAL", seed, "SHORT", f"{VERSION}:{case}:plan",
                      f"{VERSION}:{case}:cycle", None, start, start)
    for photo in evidence["photos"].values():
        image = photo["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("LMS_SHAPE_LIFETIME_SOURCE_IMAGE_CHANGED")
    rows = {}
    for mode, event in scenario["earliest"].items():
        confirmation = simulated_confirmation(request, mode, event) if event else None
        rows[mode] = dict(
            without_permission=position_at(request, event, mode=mode, as_of=cutoff),
            fixture=position_at(request, event, mode=mode, as_of=cutoff, approval=confirmation),
        )
    return dict(before_display=before, later_display=evidence["later_visible"], outcome=rows,
                account_continuity=None, actual_release_at=None)


def study(session, market):
    refs = {key: verified_json(Path("output") / name, h) for key, (name, h) in SOURCES.items()
            if key in ("roles", "seeds")}
    table, series_cache = {}, {}
    for contract in CONTRACTS:
        evidence = refs["roles"]["portfolio"][contract]
        series = series_cache[contract] = read_window(session, market, contract, DAY)
        market_id = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in rows
        ]).encode())) for p, rows in series.items()}
        if market_id != evidence["market_input"]:
            raise ValueError("LMS_SHAPE_LIFETIME_MARKET_CHANGED")
        if evidence["band"] is None:
            table[contract] = dict(role=evidence["role"], market=market_id, comparison=None,
                                   actual_recovery_permission=None)
            continue
        start, cutoff = (datetime.fromisoformat(evidence[key]) for key in ("start", "cutoff_exclusive"))
        side = evidence["side_scenario"]
        edge = Decimal(evidence["band"][0 if side == "LONG" else 1])
        table[contract] = dict(role=evidence["role"], near_edge=edge, sources=evidence["sources"],
                               market=market_id, comparison=compare(series, start, cutoff, side=side, edge=edge),
                               actual_recovery_permission=None)

    iron = verified_json(IRON_REPORT, IRON_SHA)
    night = read_window(session, market, "I2701", NEXT)
    for p in (1, 5):
        rows = [[b.end.isoformat(), *map(str, ohlc(b))] for b in night[p]]
        identity = dict(bars=len(rows), ohlc_sha256=sha(json.dumps(rows, separators=(",", ":")).encode()))
        if identity != iron["market"][str(p)][str(NEXT)]:
            raise ValueError("LMS_SHAPE_LIFETIME_IRON_NIGHT_CHANGED")
    seeds = {}
    for name, evidence in refs["seeds"]["cases"].items():
        contract = evidence["contract"]
        start, cutoff = (datetime.fromisoformat(evidence[key]) for key in ("start", "cut"))
        series, edge = series_cache[contract], table[contract]["near_edge"]
        price_role = table[contract]["role"]
        if name == "iron_night":
            series, edge = night, Decimal("662.5")
            start = max(start, at("2026-10-27T21:00"))
            price_role = "OLD_SHORT_TARGET_NEAR_SENSITIVITY"
        scenario = compare(series, start, cutoff, side="SHORT", edge=edge)
        seeds[name] = dict(start=start, cutoff_exclusive=cutoff, near_edge=edge, comparison=scenario,
                           price_role=price_role,
                           projection=project_seed(evidence, name, start=start, cutoff=cutoff, scenario=scenario))
    return dict(version=VERSION, portfolio=table, seeded=seeds, iron_reference_sha256=IRON_SHA,
                portfolio_reference_sha256={key: SOURCES[key][1] for key in ("roles", "seeds")},
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("LMS_SHAPE_LIFETIME_")
                        else "LMS_SHAPE_LIFETIME_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

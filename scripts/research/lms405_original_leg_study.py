"""Read-only comparison of original-leg retention and protection removal."""

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from lms405_i2701_case import DAYS, FROZEN_COMPARISON_SHA256, readback
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_timeframes import geometry_events
from lms405_right_side_study import ONE, US, at
from lms405_volatility_context import bars_sha
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

CONTRACTS = ("I2701", "SH2701")
SNAPSHOT_HASH = "1075e7bfedb49307b28ef0ae7139f9d355f025e831e7c235c336f7caf093310a"
PLANS = {
    "I2701": ("A5358325549629506", "A5358686423089344"),
    "SH2701": ("A5358325972992140", "A5358686695981271"),
}
# Region roles follow the archived summaries. For the afternoon these are
# sensitivity inputs. In particular SH's earlier protection was under review.
LEVELS = {
    "iron_afternoon": {
        "restart_strong_side": ("668.5 671.5", "SHORT"),
        "short_target": ("654 662.5", "SHORT"),
        "rebound_interruption": ("667 671", "LONG"),
    },
    "sh_afternoon": {
        "older_rebound_resistance": ("1511 1516", "LONG"),
        "return_below_older_resistance": ("1511 1516", "SHORT"),
        "older_rebound_interruption": ("1516 1529", "LONG"),
    },
    "iron_night": {
        "restart_strong_side": ("668.5 671.5", "SHORT"),
        "short_target": ("654 662.5", "SHORT"),
        "rebound_interruption": ("667 671", "LONG"),
    },
    "sh_night": {
        "short_target": ("1450 1460", "SHORT"),
        "rebound_interruption": ("1490 1501", "LONG"),
        "counter_m": ("1513 1523", "LONG"),
    },
}


def local_publication(source):
    return datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0)


def window(series, start, cutoff, levels):
    if start >= cutoff:
        raise ValueError("ORIGINAL_LEG_INVALID_WINDOW")
    complete = {
        period: [b for b in bars if b.start >= start and b.end + US < cutoff]
        for period, bars in series.items()
    }
    if not complete[1] or not complete[5]:
        raise ValueError("ORIGINAL_LEG_EMPTY_WINDOW")
    shapes = {
        f"5m_to_{period}m": geometry_events(series, 5, period, start=start, as_of=cutoff, side="SHORT")
        for period in (1, 5)
    }
    regions = {}
    for role, (text, direction) in levels.items():
        band = tuple(map(Decimal, text.split()))
        stats = {f"{period}m": observations(bars, band, direction) for period, bars in complete.items()}
        candidates = None
        if direction == "SHORT":
            candidates = {
                label: {
                    "first_confirmed_below_near": next((x for x in rows if x["close"] < band[1]), None),
                    "first_confirmed_below_far": next((x for x in rows if x["close"] < band[0]), None),
                }
                for label, rows in shapes.items()
            }
        regions[role] = dict(band=band, direction=direction, observations=stats,
                             short_confirmations=candidates)
    return dict(start=start, cutoff_exclusive=cutoff, regions=regions, short_confirmations=shapes,
                first_close=complete[1][0].close,
                minimum=min(bar.low for bar in complete[1]), maximum=max(bar.high for bar in complete[1]))


def state_scenarios(contract, legs):
    short, long = (Decimal(legs[side]["quantity"]) for side in ("short", "long"))
    if not long == short > 0 or legs["short"]["today_quantity"] != 0:
        raise ValueError("EXPECTED_MATCHED_LOCK_WITH_OLDER_SHORT")
    seed = Position(contract, long=long, short=short)
    recovered = apply_action(seed, Action("UNLOCK_SHORT", short))
    flat = apply_action(seed, Action("CLEAR", long + short))
    return {name: dict(long=p.long, short=p.short) for name, p in
            (("retain_lock", seed), ("remove_protection", recovered), ("exit_both", flat))}


def compare_afternoon(contract, afternoon, endpoints):
    seeds = [row["author_visible_legs"] for row in endpoints]
    states = state_scenarios(contract, seeds[0])
    projections = {}
    for policy, signals in afternoon["short_confirmations"].items():
        first = signals[0] if signals else None
        scenario = "remove_protection" if first else "retain_lock"
        projections[policy] = dict(scenario=scenario, later_legs=states[scenario], first_signal=first)
    visible_checks = {
        name: {side: lots == Decimal(seeds[1][side]["quantity"]) if side in seeds[1] else None
               for side, lots in quantities.items()}
        for name, quantities in states.items()
    }
    return dict(
        observed_legs_at_endpoints=seeds, possible_state_changes=states,
        visible_quantity_agrees=visible_checks, geometry_only_projections=projections,
        original_direction_assumption="SHORT", author_permission=None,
    )


def compute(session, market, reference, snapshots):
    index = input_sources()
    source_ids = {source for pair in PLANS.values() for source in pair}
    source_ids.update(("WRoAkcEppg", "U03", "WRoEvasxQR", "WRoCldvp4f", "WRoCCdf0i5", "WRouYm67Bc",
                       "WRozPmaK10"))
    sources = {
        key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
        for key in sorted(source_ids)
    }
    by_source = {row["source"]: row for row in snapshots["snapshots"]}
    cases, coverage = {}, {}
    for contract, prefix in zip(CONTRACTS, ("iron", "sh"), strict=True):
        raw, series = read_pair(session, market, contract, DAYS)
        if readback(raw[1]) != reference["market_1m"][contract[:-4].lower()]:
            raise ValueError("ORIGINAL_LEG_FROZEN_MINUTES_CHANGED")
        coverage[contract] = {f"{period}m": dict(count=len(rows), sha256=bars_sha(rows))
                              for period, rows in raw.items()}
        lunch, day_close = (by_source[source] for source in ("WRoAkcEppg", "U03"))
        endpoints = [row["contracts"][contract] for row in (lunch, day_close)]
        closes = {b.end: b.close for b in series[1]}
        if any(
            row["quote_aligned"] is not True
            or closes[datetime.fromisoformat(snap["quote_anchor"])] != Decimal(row["mds_close"])
            for snap, row in zip((lunch, day_close), endpoints, strict=True)
        ):
            raise ValueError("ORIGINAL_LEG_QUOTE_ANCHOR_CHANGED")
        old, new = (sources[key] for key in PLANS[contract])
        lunch_known = local_publication(sources["WRoAkcEppg"]) + ONE
        closing_quote = datetime.fromisoformat(day_close["quote_anchor"])
        night_open = at("2026-10-27T21:00")
        night_cutoff = local_publication(sources["WRoEvasxQR"])
        if not local_publication(old) < lunch_known < closing_quote < local_publication(new) < night_open:
            raise ValueError("ORIGINAL_LEG_PLAN_TIMELINE_CHANGED")
        afternoon = window(series, lunch_known, closing_quote, LEVELS[f"{prefix}_afternoon"])
        cases[contract] = dict(
            afternoon=afternoon,
            afternoon_plan_scope="OLDER_VISIBLE_TEXT_SENSITIVITY_ONLY",
            afternoon_comparison=compare_afternoon(contract, afternoon, endpoints),
            frozen_cold_starts=[row["variants"]["BASELINE"]["before_quote_close"] for row in endpoints],
            night=window(series, night_open, night_cutoff, LEVELS[f"{prefix}_night"]),
            night_plan_scope="POST_PUBLICATION_VISIBLE_TEXT_SENSITIVITY_ONLY",
        )
    return dict(version="lms405-original-leg-study-v1", sources=sources, market=coverage, cases=cases,
                account_continuity=None, author_exit_rule=None, author_action_at=None,
                admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None)


def verified_json(path, expected_hash):
    payload = path.read_bytes()
    if sha(payload) != expected_hash:
        raise ValueError("ORIGINAL_LEG_REFERENCE_CHANGED")
    return json.loads(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--iron-reference", required=True, type=Path)
    parser.add_argument("--snapshot-reference", required=True, type=Path)
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
        reference = verified_json(args.iron_reference, FROZEN_COMPARISON_SHA256)
        snapshots = verified_json(args.snapshot_reference, SNAPSHOT_HASH)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = compute(session, build_market_data_service(session), reference, snapshots)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "ORIGINAL_LEG_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()

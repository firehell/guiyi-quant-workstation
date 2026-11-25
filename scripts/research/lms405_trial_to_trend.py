"""Compare observed price-path completion with the author's trial and holding roles."""

import argparse
import csv
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_jm_may_case import INPUT_HASH, NODES
from lms405_portfolio_replay import EVIDENCE, input_sources
from lms405_right_side_study import at
from lms405_v_zone_progress import observations
from lms_near405_replay import encoded, sha

VERSION = "lms405-trial-to-trend-study-v1"
OI_HASH = "2270fc86233facf687b31566dd9d24d557e258cfbabaed2380fbe8fe3e04451e"
SH_HASH = "65c6494ad19377baa6cce0261f1cb233a0a7dbe1fe8d327dd7e7ded8671749a3"


def frozen(path, expected):
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError(f"FROZEN_TRIAL_INPUT_CHANGED: {path.name}")
    return raw


def milestones(nodes):
    """First observations of each published endpoint, without imputing path continuity."""
    result = {}
    for label, key in (("far_reach", "first_far_reach"), ("far_close_cross", "first_strict_close_beyond_far")):
        first = [node[key] for node in nodes]
        all_seen = bool(first) and all(first)
        times = [datetime.fromisoformat(value) for value in first] if all_seen else []
        ordered = None
        if len(times) > 1:
            between = list(zip(times, times[1:], strict=False))
            if any(a > b for a, b in between):
                ordered = False
            elif all(a < b for a, b in between):
                ordered = True
        result[label] = dict(all_visible_endpoints_seen=all_seen if first else None,
                             last_first_observation=max(times).isoformat(timespec="minutes") if times else None,
                             first_observations_in_strict_order=ordered)
    return result


def assess_role(*, trend, trial_success, current_position_is_trial, version_405, author_role):
    """Retrospective conditions. Success and identity refer to the same trial cycle."""
    checks = dict(trend_reported_in_direction=trend, same_trial_succeeded=trial_success,
                  current_position_is_same_trial=current_position_is_trial, version_405=version_405)
    if author_role == "SHORT_TERM":
        status = "AUTHOR_SHORT_TERM"
    elif False in checks.values():
        status = "CONDITION_REJECTED"
    elif None in checks.values():
        status = "INDETERMINATE"
    else:
        status = "CONDITIONS_MET"
    return dict(status=status, conditions=checks, author_role=author_role, action=None)


def report(jm_path, oi_path, sh_path):
    jm_raw = frozen(jm_path, INPUT_HASH)
    oi = json.loads(frozen(oi_path, OI_HASH))["cases"]
    sh = json.loads(frozen(sh_path, SH_HASH))["windows"]
    bars = [
        Bar(row["contract"], datetime.fromisoformat(row["bar_end_shanghai"]),
            *(Decimal(row[key]) for key in ("open", "high", "low", "close")))
        for row in csv.DictReader(jm_raw.decode().splitlines())
    ]
    may20_start, may20_end = at("2026-05-20T09:00"), at("2026-05-20T15:00")
    may21_start, may21_end = at("2026-05-21T09:00"), at("2026-05-21T15:00")
    may22_start, may22_end = at("2026-05-21T21:00"), at("2026-05-22T15:00")
    jm20 = [bar for bar in bars if may20_start < bar.end <= may20_end]
    jm21 = [bar for bar in bars if may21_start < bar.end <= may21_end]
    jm22 = [bar for bar in bars if may22_start < bar.end <= may22_end]
    jm_short = [observations(jm20, (Decimal(lo), Decimal(hi)), "SHORT")
                for name, lo, hi in NODES if name.startswith("short-target")]
    jm_long = [observations(jm21, (Decimal(lo), Decimal(hi)), "LONG")
               for name, lo, hi in NODES if name.startswith("long-target")]
    jm_extension = [observations(jm22, (price, price), "SHORT")
                    for price in map(Decimal, ("1170.5", "1160.5"))]
    source_catalog = input_sources()
    with (EVIDENCE / "evidence/jm2609-may-20261016.csv").open(newline="", encoding="utf-8") as stream:
        source_catalog.update(
            (row["id"], dict(source_url=row["url"], published_at=row["published_at"], edited=row["edit_marker"]))
            for row in csv.DictReader(stream) if row["id"] == "G02"
        )
    cases = {}

    def add(identity, contract, source_ids, side, nodes, *, window, trend=None, role=None, version=None,
            node_scope="DISCLOSED_LEVELS_ONLY", limitation):
        cases[identity] = dict(
            contract=contract, sources={key: source_catalog[key] for key in source_ids},
            observation_window=window,
            price_path_side=side, node_scope=node_scope, nodes=nodes, endpoint_comparison=milestones(nodes),
            holding_review=assess_role(trend=trend, trial_success=None, current_position_is_trial=None,
                                       version_405=version, author_role=role),
            limitation=limitation, effective_at=None, actual_action_at=None,
        )

    add("oi_range", "OI2609", ("S5327857507107123",), None, [], window="2026-08-03 TRADING_DAY",
        trend=False, role="SHORT_TERM", version=True,
        limitation="Complex range; waiting for trend and a successful trial. No dated entry or fill.")
    add("oi_incomplete_short", "OI2609", ("S5331132834646048",), "SHORT",
        [entry["path"] for entry in oi["august_incomplete_short"]["directional_nodes"]],
        window="2026-08-12 TRADING_DAY", trend=False,
        limitation="Author describes the failed strong cycle and return to the divider. Trial identity unknown.")
    add("oi_long_continuation", "OI2609", ("S5331495384520216",), "LONG",
        [entry["path"] for entry in oi["august_continuation"]["directional_nodes"]],
        window="2026-08-13 TRADING_DAY", trend=True,
        limitation="Author describes bullish continuation. No result for a specific trial or verified 4.0.5 use.")
    add("jm_may20", "JM2609", ("S5300688465954469", "G02"), "SHORT", jm_short,
        window="2026-05-20 DAY_SESSION", role="SHORT_TERM", version=True,
        limitation="The disclosed directional path was short; the late M trial direction and leg are unconfirmed. "
                   "The afternoon review describes a strategy switch, not the result of a same-direction trial.")
    add("jm_may21", "JM2609", ("F08", "G02"), "LONG", jm_long,
        window="2026-05-21 DAY_SESSION", trend=False, version=True,
        limitation="Failed bullish cycle. The author describes long-side locking and a counter-M task, "
                   "followed by unlock and short reentry. Exact leg operations and orders are unverified.")
    cases["jm_may21"]["long_watershed"] = observations(jm21, (Decimal("1223"), Decimal("1228.5")), "LONG")
    add("jm_may22", "JM2609", ("S5301412923184383",), "SHORT", jm_extension,
        window="2026-05-22 TRADING_DAY", node_scope="TWO_DISCLOSED_PRICE_REFERENCES_NOT_FULL_EXTENSION",
        limitation="Writer reports a night update, but exact publication time and full new band are unverified.")
    add("sh_jul24_wait", "SH2609", ("S5324249205048926",), "SHORT",
        [sh["jul24_wait"]["levels"][key] for key in ("first_target", "next_target")],
        window="2026-07-24 TRADING_DAY", version=True,
        limitation="Author describes trend-like structure but poor momentum. 4.0.5 waits, 5.0 reenters short. "
                   "This is permission for a new short, not a labeled hold of an existing trial.")
    cases["sh_jul24_wait"]["short_reentry_reported"] = {"4.0.5": "WAIT", "5.0": "REENTER", "actual_action_at": None}
    add("sh_jul27_m", "SH2609", ("S5325329692361179",), "LONG",
        [sh["jul27_extreme_m"]["levels"]["extreme_m_band"]],
        window="2026-07-27 TRADING_DAY", role="SHORT_TERM",
        node_scope="EXTREME_M_REFERENCE",
        limitation="Long M remains a short-term task; author says original short cannot yet unlock. Version unknown.")
    cases["sh_jul27_m"]["original_short_recovery"] = dict(
        author_permission=False, exact_action_at=None,
        price_observation=sh["jul27_no_unlock_reported"]["levels"]["same_day_retrospective_reference"],
    )
    add("sh_jul28_range", "SH2609", ("S5325700674619111", "S5325329692361179"), "SHORT",
        [sh["jul28_prior_band_sensitivity"]["levels"]["previous_posts_reference"]],
        window="2026-07-28 TRADING_DAY", trend=False,
        node_scope="PRIOR_DAY_REFERENCE_CURRENT_VALIDITY_UNKNOWN",
        limitation="Author calls it range; full chosen path not documented. No trial outcome or current band identity.")
    return dict(version=VERSION, mode="RETROSPECTIVE_CONDITION_REVIEW", cases=cases,
                frozen_inputs=dict(jm_market_export=INPUT_HASH, oi_report=OI_HASH, sh_report=SH_HASH),
                admitted_author_actions=0, author_matches=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("jm", "oi", "sh", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    data = encoded(report(args.jm, args.oi, args.sh))
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(data)
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()

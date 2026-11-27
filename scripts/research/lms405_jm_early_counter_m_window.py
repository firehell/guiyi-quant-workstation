"""Test whether JM2701's later visible long could already be assembled at the early photo."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from itertools import product
from pathlib import Path

from lms405_jm_m_leg_handoff import CLOSE, CONTRACT, FIRST, LATER, SPECS_SHA
from lms405_m_permission_study import read_pair
from lms405_plan_driven_replay import local_market_case
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_replay import display
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA
from lms405_right_side_study import LOCAL, ONE, US
from lms405_sh_protection_replacement import compatible_counts
from lms405_sizing_audit import SPECS, load_specs
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

EARLY = "WRnY5bznUE"
EARLY_HASH = "8fc91662bf312c2e966c97be4c192ad4730638a6cfcc1a7a089830e845ae1434"
DAY = date(2026, 10, 23)
CLOCKS = (Path("output/lms405-counter-m-first-session-20261128/verified.json"),
          "38923d5f61767e633aacb8af679d6928a464e3cba324fec001a48606ea953dd6")
LEGS = (Path("output/lms405-jm-m-leg-handoff-20261125/final.json"),
        "3f768f34ccacc10739ef168aa119f3b5d6beb8c2fbf6ebe4d31e5caa787719ae")
FIRST_LOCK = (Path("output/lms405-jm-first-lock-handoff-20261126/final-a.json"),
              "477cd10a951d399f3e8bc44641d37a899634ae82c532055f4e3412b0f0594310")


def price_window(minutes, *, after, through, tick):
    return tick_bounds([bar for bar in minutes if after < bar.start and bar.end <= through], tick)


def assess(minutes, *, early_quote, close_quote, old_ticks, gate, tick, lots, old_total, end_total):
    # Use fully separated price observations. The whole early quote minute is excluded from the split.
    early_ticks = price_window(minutes, after=gate, through=early_quote - ONE, tick=tick)
    late_ticks = price_window(minutes, after=max(gate, early_quote - US), through=close_quote - ONE, tick=tick)
    close_ticks = price_window(minutes, after=gate, through=close_quote - ONE, tick=tick)
    early_snapshot = compatible_counts(lots, old_total, end_total, old_ticks, early_ticks, None)
    partitioned_close = compatible_counts(lots, old_total, end_total, old_ticks, early_ticks, late_ticks)
    normal_close = compatible_counts(lots, old_total, end_total, old_ticks, None, close_ticks)
    return dict(early_price_ticks=early_ticks, late_price_ticks=late_ticks,
                full_replacement_before_early_possible=[0, lots, 0] in early_snapshot,
                ending_leg_before_early_possible=bool(early_snapshot),
                flat_at_early_then_full_new_leg_possible=[0, 0, lots] in partitioned_close,
                early_ending_replacement_counts=sorted({early for _, early, _ in partitioned_close}),
                late_ending_replacement_counts=sorted({late for _, _, late in partitioned_close}),
                old_retained_counts=sorted({old for old, _, _ in partitioned_close}),
                feasible_allocations=partitioned_close,
                full_replacement_by_close_possible=[0, 0, lots] in normal_close)


def study(session, market):
    clock = verified_json(*CLOCKS)["cases"][f"{CONTRACT}/{DAY}"]
    legs = verified_json(*LEGS)
    quote_reports = verified_json(PHOTO, PHOTO_SHA)["photos"]
    with ARCHIVE.open(encoding="utf-8", newline="") as file:
        observed = {row["source_id"]: row for row in csv.DictReader(file)}
    attachments = {}
    for key in (FIRST, EARLY, LATER, CLOSE):
        current = observed[key]
        path, expected = current["images"].split(";")[0], current["sha256"].split(";")[0]
        if sha((ARCHIVE.parent / path).read_bytes()) != expected:
            raise ValueError("EARLY_M_ATTACHMENT_CHANGED")
        attachments[key] = dict(path=path, sha256=expected)
    for key in (FIRST, LATER, CLOSE):
        expected = legs["visible"][key]["image"]
        if attachments[key] != expected:
            raise ValueError("EARLY_M_ATTACHMENT_IDENTITY_MISMATCH")
    if attachments[EARLY]["sha256"] != EARLY_HASH:
        raise ValueError("EARLY_M_SNAPSHOT_IDENTITY_MISMATCH")
    raw, bars = read_pair(session, market, CONTRACT, (DAY,))
    identity = {str(period): dict(count=len(rows), sha256=bars_sha(rows)) for period, rows in raw.items()}
    if identity != clock["inputs"]:
        raise ValueError("EARLY_M_FROZEN_MARKET_CHANGED")

    tick = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]["tick"]
    old, ending = (legs["visible"][k]["legs"]["long"] for k in (FIRST, CLOSE))
    lots = old["quantity"]
    if ending != legs["visible"][LATER]["legs"]["long"] or ending["quantity"] != lots:
        raise ValueError("EARLY_M_QUANTITIES_CHANGED")
    old_total, end_total = (displayed_tick_totals(Decimal(row["opening_average"]), lots, tick)
                            for row in (old, ending))
    protection_known = datetime.fromisoformat(verified_json(*FIRST_LOCK)["protection_known_at"])
    first_options = tuple(map(datetime.fromisoformat, legs["anchors"][FIRST]))
    early_options = tuple(map(datetime.fromisoformat, quote_reports[EARLY]["joint_contains"]))
    later_options = tuple(map(datetime.fromisoformat, legs["anchors"][LATER]))
    close_quote, = map(datetime.fromisoformat, legs["anchors"][CLOSE])
    if not first_options or not early_options or not later_options:
        raise ValueError("EARLY_M_QUOTE_ANCHORS_MISSING")
    window = clock["windows"]["published_interruption_far"]
    gates = {}
    for period, rows in window["events"].items():
        for row in rows:
            if row["interruption_fresh"]["carry_unbroken"]:
                local_time = datetime.fromisoformat(row["confirmed_at"]).astimezone(LOCAL).strftime("%H%M")
                gates[f"carry_5m_to_{period}m_{local_time}"] = datetime.fromisoformat(row["available_at"])
    gates["late_extreme_far_price_proxy"] = datetime.fromisoformat(legs["long_gates"][
        "extreme_m_far_strict_close"]["end"]) + US

    by_gate = {}
    for name, known in sorted(gates.items(), key=lambda item: item[1]):
        rows = {}
        for first, early in product(first_options, early_options):
            old_ticks = price_window(bars[1], after=protection_known, through=first - ONE, tick=tick)
            if old_ticks is None:
                raise ValueError("EARLY_M_OLD_PRICE_WINDOW_MISSING")
            rows[f"{display(first)} / {display(early)}"] = assess(
                bars[1], early_quote=early, close_quote=close_quote, old_ticks=old_ticks, gate=known,
                tick=tick, lots=lots, old_total=old_total, end_total=end_total,
            )
        later_anchored = {}
        for terminal in later_options:
            compatible_early = []
            for early in early_options:
                new_ticks = price_window(bars[1], after=max(known, early - US), through=terminal - ONE, tick=tick)
                if earlier_lot_counts(None, new_ticks, lots, end_total):
                    compatible_early.append(early)
            later_anchored[display(terminal)] = compatible_early
        by_gate[name] = dict(known_at=known, target_filter_applied=False,
                             prior_target_touch_in_same_trading_day=window["first_reference_known_at"]["same_trading_day"],
                             close_comparison=rows, later_photo_flat_at_early_compatible_anchors=later_anchored)
    return dict(version="lms405-jm-early-counter-m-window-v1", contract=CONTRACT, inputs=identity,
                attachments=attachments, early_observation_price_anchors=early_options, close_quote=close_quote,
                displayed_long_lots=lots, tick_size=tick, old_sum_ticks=list(old_total), ending_sum_ticks=list(end_total),
                early_account_and_scope_verified=False, morning_m_action=None, author_actions_scored=0,
                author_match_rate=None, fills=None, executable=False, gates=by_gate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("EARLY_M_OUTPUT_EXISTS")
    try:
        result = local_market_case(args.env_file, case=lambda market_input: study(*market_input))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() else "EARLY_M_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

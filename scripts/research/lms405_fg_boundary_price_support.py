"""Bound the low-price lots required for FG2701 two-stage protection."""

import argparse
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_public_plan_roles import load_source
from lms_near405_replay import encoded, sha

STAGES = Path("output/lms405-staged-protection-clocks-20261126/final-a.json")
STAGES_SHA = "71c047ec62718af9b085d7fe74fb41056ce4bda2f9a5dc10bc756802fbadcb31"
SOFTWARE = "WRnTmqo3x5"
SOFTWARE_IMAGE = "RnTmqo3x5-software3-screen.png"
SOFTWARE_SHA = "06b8a8e2beb8da91dddd1619d3701e3c17feac67a14d70370df8495a7ffc71a6"


def count_low_price_lots(first, lots, *, low_prices, early, late, totals):
    """Enumerate necessary counts under integer tick envelopes for two low levels."""
    cheaper, dearer = low_prices
    if not 0 <= first <= lots or not cheaper < dearer < early[0] or not totals:
        raise ValueError("FG_BOUNDARY_PRICE_INPUT_INVALID")
    later = lots - first
    for cheap_count in range(first + 1):
        for dear_count in range(first - cheap_count + 1):
            other = first - cheap_count - dear_count
            low_lot_value = cheaper * cheap_count + dearer * dear_count
            lower = low_lot_value + other * early[0] + later * late[0]
            upper = low_lot_value + other * early[1] + later * late[1]
            if lower <= totals.stop - 1 and totals.start <= upper:
                yield cheap_count, dear_count


def summarize_prices(lots, *, low_prices, early, late, totals):
    results = {}
    for first in range(lots + 1):
        feasible = list(count_low_price_lots(first, lots, low_prices=low_prices, early=early, late=late,
                                             totals=totals))
        if not feasible:
            continue
        only_dearer = [count for cheap, count in feasible if cheap == 0]
        results[first] = dict(minimum_lots_at_lowest=min(cheap for cheap, _ in feasible),
                              minimum_lots_at_either_low_price=min(cheap + dear for cheap, dear in feasible),
                              minimum_lots_at_higher_low_if_lowest_unavailable=min(only_dearer, default=None),
                              possible_using_neither_low_price=(0, 0) in feasible)
    return results


def study():
    frozen = verified_json(STAGES, STAGES_SHA)
    source = frozen["cases"]["FG2701"]
    case = source["first_stage_clock_comparison"]["FIRST_RANGE_TOUCH"]
    minute = case["permission_overlapping_minutes"]["early"]
    low_prices = 826, 827
    if (source["snapshot"]["tick_size"] != "1.0" or minute["low"] != "826.000000000000000000"
            or source["snapshot"]["quantity"] != 20 or source["snapshot"]["shown_as_today_quantity"] != 20):
        raise ValueError("FG_BOUNDARY_PRICE_EVIDENCE_CHANGED")
    image = source["snapshot"]["image"]
    author = load_source(input_sources(), SOFTWARE)
    software = (ARCHIVE.parent / author["archive_path"]).with_name(SOFTWARE_IMAGE)
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"] or sha(software.read_bytes()) != SOFTWARE_SHA:
        raise ValueError("FG_BOUNDARY_PRICE_IMAGE_CHANGED")
    lo, hi = source["snapshot"]["displayed_tick_total_interval"]
    results = {}
    for stamp, row in case["quote_checks"].items():
        strict = row["WHOLE_MINUTES_AFTER_EACH_PERMISSION"]
        broad = row["ALLOW_ONLY_EARLY_PERMISSION_MINUTE"]
        early, late = strict["price_ranges_in_ticks"]
        if (broad["price_ranges_in_ticks"] != [[low_prices[0], early[1]], late] or early[0] != low_prices[1] + 1):
            raise ValueError("FG_BOUNDARY_PRICE_WINDOW_CHANGED")
        tiers = summarize_prices(20, low_prices=low_prices, early=early, late=late, totals=range(lo, hi + 1))
        if (list(tiers) != broad["price_compatible_first_lots"]
                or [qty for qty, tier in tiers.items() if tier["possible_using_neither_low_price"]]
                != strict["price_compatible_first_lots"]):
            raise ValueError("FG_BOUNDARY_PRICE_RECONCILIATION_FAILED")
        results[stamp] = dict(regular_first_price_range=early, later_price_range=late, by_first_slice=tiers,
                              allowed_if_lowest_unavailable=[qty for qty, tier in tiers.items()
                                                             if tier["minimum_lots_at_higher_low_if_lowest_unavailable"]
                                                             is not None])
    return dict(version="lms405-fg-boundary-price-support-v1", contract="FG2701", snapshot=source["snapshot"],
                source_report_sha256=STAGES_SHA, first_permission_overlapping_minute=minute, low_price_levels=low_prices,
                quote_checks=results, software_source=author,
                software_image=dict(path=str(software.relative_to(ARCHIVE.parent)), sha256=SOFTWARE_SHA),
                software_visible_rows=[dict(contract="PP2701", time="21:30:39", side="BUY", offset="OPEN"),
                                       dict(contract="PP2701", time="21:06:55", side="BUY", offset="CLOSE")],
                author_low_tick_time=None, available_volume_at_low_ticks=None, author_action_at=None,
                capture_time_verified=False, author_action_samples=0, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("FG_BOUNDARY_PRICE_OUTPUT_EXISTS")
    try:
        report = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('FG_BOUNDARY_PRICE_') and code.isidentifier() else 'FG_BOUNDARY_PRICE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()

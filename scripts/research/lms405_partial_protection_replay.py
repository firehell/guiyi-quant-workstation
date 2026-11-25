"""Project conditional net exposure from frozen protection-leg origin counts."""

import argparse
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from lms405_protection_lot_origins import ORIGINS
from lms405_protection_lot_timing import verified_json
from lms_near405_replay import encoded

INPUT = Path("output/lms405-protection-lot-origins-20261126/scoped.json")
INPUT_SHA = "69643cf155a2b23eee1746db0fabe5c5a8a9f707e435000ef6daadeae890f4ac"
STRICT = "ONLY_COMPLETE_MINUTES_AFTER"
CHECKPOINTS = ("before_new_lots", "after_first_bucket", "after_middle_bucket", "at_terminal_quote_bound")
ORIGINAL_SCOPE = {
    "FG2701": "SHORT_SIZE_REFERENCE_FROM_MORNING_AND_CLOSE_ORIGINAL_ID_UNVERIFIED",
    "RU2701": "HYPOTHETICAL_CONTINUING_SHORT_NOT_SHOWN_IN_LATER_IMAGE",
    "SH2701": "UNCHANGED_SHORT_CONDITIONAL_ON_SAME_ACCOUNT",
}


def exposures(contract, base, counts, *, old_in_transit):
    """Project the two position bounds at each phase under a fixed original short."""
    if (type(base) is not int or base <= 0 or len(counts) != 4
            or any(type(n) is not int or n < 0 for n in counts) or sum(counts) != base
            or type(old_in_transit) is not int or not 0 <= old_in_transit <= base - counts[0]):
        raise ValueError("LMS_PARTIAL_PROTECTION_INVALID_COUNTS")
    retained, first, middle, _ = counts
    minimum_protection = (retained, retained + first, retained + first + middle, base)
    bounds = []
    for protection in minimum_protection:
        # Old units that will be replaced may still cover the short at a checkpoint.
        # The study assumes a protection cap equal to the original short size.
        upper = min(base, protection + old_in_transit)
        bounds.append((Position(contract, Decimal(protection), Decimal(base)),
                       Position(contract, Decimal(upper), Decimal(base))))
    return tuple(bounds)


def summarize(contract, base, allocations, *, removal_clock_unknown):
    if not allocations:
        return dict(compatible_allocation_count=0, checkpoints=None)
    paths = [exposures(contract, base, row, old_in_transit=base - row[0] if removal_clock_unknown else 0)
             for row in allocations]
    steps = {}
    for checkpoint, bounds in zip(CHECKPOINTS, zip(*paths, strict=True), strict=True):
        lower, upper = min(a.long for a, _ in bounds), max(b.long for _, b in bounds)
        original = Decimal(base)
        steps[checkpoint] = dict(protection_lots=[lower, upper], original_short_lots=original,
                                 net_lots=[lower - original, upper - original],
                                 gross_lots=[lower + original, upper + original])
    witnesses = {}
    for label, select, position_side in (("most_open_short", min, 0), ("least_open_short", max, 1)):
        # Each witness uses just one joint allocation and one timing convention for its whole path.
        allocation, path = select(zip(allocations, paths, strict=True), key=lambda pair: pair[1][2][position_side].long)
        witnesses[label] = dict(origin_counts=allocation, checkpoint_net_lots={
            clock: pair[position_side].long - pair[position_side].short
            for clock, pair in zip(CHECKPOINTS, path, strict=True)
        })
    return dict(compatible_allocation_count=len(allocations), checkpoints=steps,
                witnesses_at_end_of_middle_bucket=witnesses)


def scenario_sets(source):
    rows = source["summaries"][STRICT]["joint_counts_across_quotes"]
    return dict(
        retained_then_top_up=[row for row in rows if row[0] > 0 and row[1] == row[2] == 0 and row[3] > 0],
        full_rebuild=[row for row in rows if row[0] == 0],
        full_rebuild_only_after_second=[row for row in rows if row[0] == row[1] == row[2] == 0],
    )


def study(frozen):
    if frozen["origin_columns"] != list(ORIGINS):
        raise ValueError("LMS_PARTIAL_PROTECTION_COLUMNS_CHANGED")
    cases = {}
    for contract, source in frozen["cases"].items():
        scenarios = scenario_sets(source)
        amounts = {sum(row) for group in scenarios.values() for row in group}
        if amounts != {20}:
            raise ValueError("LMS_PARTIAL_PROTECTION_REFERENCE_SIZE_CHANGED")
        result = {
            name: dict(
                after_nonretained_lots_removed=summarize(contract, 20, rows, removal_clock_unknown=False),
                if_old_removal_time_unknown=summarize(contract, 20, rows, removal_clock_unknown=True),
            ) for name, rows in scenarios.items()
        }
        if "if_zero_at_morning_post" in source:
            early_zero = scenario_sets(source["if_zero_at_morning_post"])
            result["if_morning_long_is_zero"] = {
                name: summarize(contract, 20, rows, removal_clock_unknown=False)
                for name, rows in early_zero.items()
            }
        cases[contract] = dict(position_source_ids=source["position_source_ids"], gates=source["gates"],
                               original_short_scope=ORIGINAL_SCOPE[contract], trading_day=source["trading_day"],
                               terminal_bound_scope=source.get("later_quote_clock", "CONDITIONAL_QUOTE_MINUTE"),
                               cases=result)
    return dict(
        version="lms405-partial-protection-projection-v1", input_sha256=INPUT_SHA,
        scope="HYPOTHETICAL_FIXED_SHORT_QUANTITY_NO_TEMPORARY_LOTS_NO_OVERHEDGE",
        phase_clock=frozen["phase_clock"], checkpoint_order=CHECKPOINTS, checkpoints_are_marginal_ranges=True,
        max_protection_path_per_allocation="RETAIN_REPLACED_OLD_LOTS_UNTIL_CAP_REQUIRES_REMOVAL",
        old_protection_missing_row_implies_zero=False, cases=cases,
        author_action_samples=0, actual_positions=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = study(verified_json(INPUT, INPUT_SHA))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except FileExistsError:
        parser.exit(2, "LMS_PARTIAL_PROTECTION_OUTPUT_EXISTS\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "LMS_PARTIAL_PROTECTION_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

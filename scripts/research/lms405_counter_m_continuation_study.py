"""Compare same-quantity M continuation and exit with a conditional pre-extreme JM photo."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.portfolio_tasks import Book
from lms405_jm_early_counter_m_window import LEGS, price_window
from lms405_jm_m_leg_handoff import CLOSE, CONTRACT, LATER, OLD_PLAN
from lms405_plan_driven_replay import exit_candidate, local_market_case
from lms405_portfolio_task_policy import project_fixture
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_replay import display
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sh_protection_replacement import compatible_counts
from lms_near405_replay import encoded

DAY = date(2026, 10, 23)
STAGE = (Path("output/lms405-extreme-m-stage-20261128/verified.json"),
         "9c45506a37d3760f767b841c77724fbcef0bdfc2d067397428240dd9b9f9e0b9")
EARLY = (Path("output/lms405-jm-early-counter-m-20261128/final.json"),
         "7ba5ac4be6693929e1eddf4b9b2f8a2b4dc3adadb7c14f82ad47686240d4d967")


def first_rebuilt_envelope(minutes, *, after, cutoff, target_ticks, lots, tick):
    """Return when strictly eligible completed minutes first admit the whole displayed average."""
    envelope = None
    for bar in completed(minutes, after + US, cutoff):
        low, high = tick_bounds([bar], tick)
        envelope = (min(envelope[0], low), max(envelope[1], high)) if envelope else (low, high)
        if earlier_lot_counts(None, envelope, lots, target_ticks):
            return bar.end + US
    return None


def management(series, *, start, cutoff, ordinary, far):
    diagnostics = {}
    candidates = {}
    for label, edge in (("ordinary", ordinary), ("extreme", far)):
        for shape, confirm in VARIANTS:
            event, detail = exit_candidate(series, role="DIRECTIONAL_TARGET", side="LONG", plan_start=start,
                                           fresh_start=start, cutoff=cutoff, lower=edge, upper=edge,
                                           shape_period=shape, confirmation_period=confirm)
            name = f"{label}_{shape}m_to_{confirm}m"
            candidates[name] = event
            diagnostics[name] = detail
    # A post-extreme close back inside is a separate early-exit sensitivity, not a disclosed author trigger.
    extreme_touch = diagnostics["extreme_1m_to_1m"].get("target_known_at")
    if extreme_touch is not None:
        candidates["extreme_adverse_close"], diagnostics["extreme_adverse_close"] = exit_candidate(
            series, role="ADVERSE_EXIT", side="LONG", plan_start=start, fresh_start=extreme_touch + US,
            cutoff=cutoff, lower=far, upper=far, shape_period=1, confirmation_period=1,
        )
    return candidates, diagnostics


def study(session, market):
    stage = verified_json(*STAGE)["cases"][f"{CONTRACT}/{DAY}"]
    early = verified_json(*EARLY)
    records = verified_json(*LEGS)
    series = read_window(session, market, CONTRACT, DAY)
    identity = {f"{period}m": dict(count=len(rows), sha256=digest(rows)) for period, rows in series.items()}
    if identity != stage["inputs"]:
        raise ValueError("COUNTER_M_CONTINUATION_MARKET_CHANGED")
    far_at = datetime.fromisoformat(stage["extreme_far_reached_at"])
    ordinary, _, far = map(Decimal, stage["levels"])
    quote, = map(datetime.fromisoformat, records["anchors"][CLOSE])
    cutoff = quote - ONE + 2 * US  # Include prices only up to the start of the closing quote minute.
    lots = early["displayed_long_lots"]
    tick = Decimal(early["tick_size"])
    leg = records["visible"][LATER]["legs"]["long"]
    if leg != records["visible"][CLOSE]["legs"]["long"] or lots != leg["quantity"]:
        raise ValueError("COUNTER_M_CONTINUATION_POSITION_FIELDS_CHANGED")
    summed = displayed_tick_totals(Decimal(leg["opening_average"]), lots, tick)
    if list(summed) != early["ending_sum_ticks"]:
        raise ValueError("COUNTER_M_CONTINUATION_OPENING_AVERAGE_CHANGED")
    if any(stage["stages"]["near"]["candidates_before_next_reference"].values()) or any(
        stage["stages"]["far"]["candidates"].values()
    ):
        raise ValueError("COUNTER_M_CONTINUATION_INDEPENDENT_ENTRY_SCOPE_CHANGED")
    observations = {}
    checks = 0
    for displayed_quote in map(datetime.fromisoformat, records["anchors"][LATER]):
        if not displayed_quote + US < far_at:
            continue
        before = displayed_quote + US
        candidates, details = management(series, start=before + US, cutoff=cutoff, ordinary=ordinary, far=far)
        for name, event in candidates.items():
            if event is None:
                continue
            prefix, _ = management(series, start=before + US, cutoff=event["available_at"] + US,
                                   ordinary=ordinary, far=far)
            if prefix[name] != event:
                raise ValueError("COUNTER_M_CONTINUATION_PREFIX_MISMATCH")
            checks += 1

        seeded = Book(CONTRACT, f"{LATER}:CONDITIONAL_M:{display(displayed_quote)}", "SHORT", before,
                      counter_m=Decimal(lots), attempt=1)
        # A separate replacement cannot use prices before the corresponding hypothetical exit.
        exit_clocks = {name: event["available_at"] + 4 * US for name, event in candidates.items()
                       if event is not None and event["available_at"] + 4 * US < cutoff}
        rebuild_after_exit = {name: first_rebuilt_envelope(
            series[1], after=exit_at, cutoff=cutoff, target_ticks=summed,
            lots=lots, tick=tick,
        ) for name, exit_at in exit_clocks.items()}
        after_exit_ticks = {name: price_window(series[1], after=exit_at, through=quote - ONE, tick=tick)
                            for name, exit_at in exit_clocks.items()}
        clock = min(exit_clocks.values(), default=None)
        projections = dict(hold=dict(long=seeded.visible.long, matches_closing_size=seeded.visible.long == lots))
        if clock is not None:
            # One lot witnesses any positive reduction. It does not encode a recommended ratio.
            for name, quantity in (("reduce_one", Decimal(1)), ("exit_all", Decimal(lots))):
                projected = project_fixture(seeded, "EXIT_COUNTER_M", quantity, clock - US, plan=OLD_PLAN)
                remaining = projected["fixture"]["after"].visible.long
                projections[name] = dict(long=remaining, matches_closing_size=remaining == lots, projection=projected)

        carry = {}
        post_ticks = price_window(series[1], after=far_at, through=quote - ONE, tick=tick)
        for gate_name, gate in early["gates"].items():
            gate_at = datetime.fromisoformat(gate["known_at"])
            if gate_at >= before:
                continue
            pre_ticks = price_window(series[1], after=gate_at, through=displayed_quote - ONE, tick=tick)
            if not earlier_lot_counts(None, pre_ticks, lots, summed):
                continue
            allocations = compatible_counts(lots, summed, summed, pre_ticks, None, post_ticks)
            retained_after = {}
            for exit_name, replacement_ticks in after_exit_ticks.items():
                following = compatible_counts(lots, summed, summed, pre_ticks, None, replacement_ticks)
                retained_after[exit_name] = sorted({retained for retained, _, _ in following})
            carry[gate_name] = dict(pre_extreme_ticks=pre_ticks, post_extreme_ticks=post_ticks,
                                   surviving_earlier_lots=sorted({retained for retained, _, _ in allocations}),
                                   surviving_if_replacements_only_after_each_exit=retained_after)
        observations[display(displayed_quote)] = dict(conditional_m_book=seeded, candidates=candidates,
                                                     diagnostics=details, projections_without_new_open=projections,
                                                     replacement_price_bounds_after_extreme_price=carry,
                                                     first_full_rebuild_price_after_exit=rebuild_after_exit)

    return dict(version="lms405-counter-m-continuation-study-v1", contract=CONTRACT, inputs=identity,
                sources=[OLD_PLAN, LATER, CLOSE], strict_close_quote=quote, position_account_and_task_verified=False,
                post_extreme_rebuild_first_price_known_at=first_rebuilt_envelope(
                    series[1], after=far_at, cutoff=cutoff, target_ticks=summed, lots=lots, tick=tick,
                ), observations=observations, counter_m_reentry_permission=None, prefix_checks=checks,
                author_actions_scored=0, author_match_rate=None, fills=None, pnl=None, executable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("COUNTER_M_CONTINUATION_OUTPUT_EXISTS")
    try:
        result = local_market_case(args.env_file, case=lambda market_input: study(*market_input))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() else "COUNTER_M_CONTINUATION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

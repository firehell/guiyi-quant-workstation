"""Compare fresh shape evidence at ordinary and extreme M stages without granting entry."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_breakout_trial_study import price_states
from lms405_counter_m_segment_study import first_reference
from lms405_plan_driven_replay import local_market_case
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded


# Near and far edges are taken in trade direction. Select by published source and roles before market reads.
CASES = (
    ("JM2701", "2026-10-23", "LONG", "2026-10-22T18:19", ("1420", "1420.5", "1427.5"),
     ("A5356884629782554", "WRo0OCbeQG"), "4.0.5_SHORT_TACTIC_REPORTED_REENTRY_UNKNOWN"),
    ("SA2701", "2026-10-23", "LONG", "2026-10-22T18:19", ("945", "953", "957"),
     ("A5356884629782554", "WRo1n9FjvJ"), "EXTREME_M_RATING_REPORTED_PARTICIPATION_UNKNOWN"),
    ("FG2701", "2026-10-28", "LONG", "2026-10-27T17:38", ("844", "854", "857"),
     ("A5358686423089344", "S5359038701503531"), "NEAR_EDGE_FAILURE_REPORTED_PARTICIPATION_UNKNOWN"),
    ("RU2701", "2026-10-28", "LONG", "2026-10-27T17:39", ("19610", "19765", "19970"),
     ("A5358686695981271", "S5359046580243515"), "ORDINARY_M_REPORTED_PARTICIPATION_UNKNOWN"),
    ("JM2701", "2026-09-09", "SHORT", None, ("1657", "1627.5", "1619"),
     ("S5341270434121818",), "AUTHOR_SKIPPED_RETROSPECTIVE_EDGES_ONLY"),
)


def compare_stages(series, *, side, start, cutoff, ordinary, near, far):
    ordinary_known = first_reference(series[1], start, cutoff, ordinary, side)
    far_touched = first_reference(series[1], start, cutoff, far, side)
    result = dict(ordinary_target_known_at=ordinary_known, extreme_far_reached_at=far_touched,
                  ordinary_trade_succeeded=None, independent_extreme_permission=None, stages={})
    if ordinary_known is None:
        return result

    minutes = completed(series[1], start, cutoff)
    shapes = {(form, confirm): signals(
        series, form, confirm, side=side, start=ordinary_known + US, cut=cutoff,
    ) for form, confirm in VARIANTS}
    for name, edge in (("near", near), ("far", far)):
        paths = price_states(minutes, side, edge)
        crossing_times = [stamp + US for stamp, state in paths.items() if state["crossing"]]
        eligible = {}
        for (form, confirm), rows in shapes.items():
            candidates = []
            for row in rows:
                cross = paths[row["confirmed_at"]]["active_cross_at"]
                if cross is not None and ordinary_known < cross + US < row["shape_end"] - form * ONE:
                    candidates.append(row | {"cross_known_at": cross + US})
            eligible[f"{form}m_to_{confirm}m"] = candidates
        result["stages"][name] = dict(
            edge=edge, first_cross_after_ordinary_at=next((stamp for stamp in crossing_times if ordinary_known < stamp), None),
            same_minute_cross=ordinary_known in crossing_times, candidates=eligible,
            candidates_before_next_reference={clock: [
                row["confirmed_at"] for row in rows if far_touched is None or row["available_at"] < far_touched
            ] for clock, rows in eligible.items()} if name == "near" else None,
            next_reference=far if name == "near" else None,
        )
    return result


def study(session, market):
    from app.market_data.market_data_service import MarketDataError
    from app.market_data.session_clock import SessionClockError

    report = {}
    for contract, trading_day, side, plan_upper, levels, sources, scope in CASES:
        case = dict(contract=contract, trading_day=trading_day, side=side, levels=levels, sources=sources, scope=scope)
        report[f"{contract}/{trading_day}"] = case
        try:
            series = read_window(session, market, contract, date.fromisoformat(trading_day))
            start, cutoff = series[1][0].start, series[1][-1].end + 2 * US
            if plan_upper and not at(plan_upper) < start:
                raise ValueError("EXTREME_M_PLAN_NOT_KNOWN_BEFORE_WINDOW")
        except (ValueError, IndexError, MarketDataError, SessionClockError) as exc:
            code = getattr(exc, "code", str(exc))
            case.update(coverage=code if code.isidentifier() else "MARKET_INPUT_UNVERIFIED")
            continue
        ordinary, near, far = map(Decimal, levels)
        args = dict(side=side, start=start, ordinary=ordinary, near=near, far=far)
        result = compare_stages(series, cutoff=cutoff, **args)
        prefix_checks = 0
        for stage in result["stages"].values():
            for clock, rows in stage["candidates"].items():
                for row in rows:
                    known = row["available_at"]
                    prefix = compare_stages(series, cutoff=known + US, **args)
                    for stage_name, facts in result["stages"].items():
                        expected = [x for x in facts["candidates"][clock] if x["available_at"] <= known]
                        prefix_stage = prefix["stages"][stage_name]
                        if prefix_stage["candidates"][clock] != expected:
                            raise ValueError("EXTREME_M_PREFIX_MISMATCH")
                        permitted = facts["candidates_before_next_reference"]
                        if permitted is not None:
                            expected_times = [end for end in permitted[clock] if end + US <= known]
                            if prefix_stage["candidates_before_next_reference"][clock] != expected_times:
                                raise ValueError("EXTREME_M_TARGET_PREFIX_MISMATCH")
                    prefix_checks += 1
        case.update(coverage="COMPLETE", plan_publication_minute_upper=at(plan_upper) if plan_upper else None,
                    inputs={f"{period}m": dict(count=len(rows), sha256=digest(rows)) for period, rows in series.items()},
                    cutoff_exclusive=cutoff, prefix_checks=prefix_checks, **result)
    return dict(version="lms405-extreme-m-stage-study-v1", cases=report, author_actions_scored=0,
                author_match_rate=None, fills=None, pnl=None, executable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("EXTREME_M_STAGE_OUTPUT_EXISTS")
    try:
        result = local_market_case(args.env_file, case=lambda market_input: study(*market_input))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() else "EXTREME_M_STAGE_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

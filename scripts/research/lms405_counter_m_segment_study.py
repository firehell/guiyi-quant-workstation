"""Compare the lifetime of an interruption and a reached target in M research."""

import argparse
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_breakout_trial_study import beyond, price_states
from lms405_m_permission_study import read_pair
from lms405_oi_june_case import DAYS as OI_DAYS
from lms405_oi_m_band_study import market_digest
from lms405_plan_driven_replay import local_market_case
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import FIVE, LOCAL, US, at
from lms405_sh_lock_lifecycle import completed, signals
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

REFERENCE = "d86ef72649f64742c64ea8cd773060803cfe977468d9790f2ed8bae571405107"


@dataclass(frozen=True)
class Case:
    contract: str
    trading_day: str
    start_previous_night: str
    cutoff: str
    side: str
    levels: tuple[tuple[str, str], ...]
    target: str | None
    input_id: str
    source_ids: tuple[str, ...]
    evidence_scope: str


CASES = (
    Case("JM2701", "2026-10-23", "2026-10-22T21:00", "2026-10-23T15:00:00.000002", "LONG",
         (("published_interruption_far", "1397.5"),), "1420", "jm_trial",
         ("A5356884629782554", "WRnTlEfj1t", "WRo0OCbeQG"), "CURRENT_PRIOR_PLAN_TEXT_EDIT_HISTORY_UNKNOWN"),
    Case("JM2701", "2026-09-09", "2026-09-08T21:00", "2026-09-09T15:00:00.000002", "SHORT",
         (("m_near_proxy", "1663.5"),), "1657", "jm_skip", ("S5341270434121818",),
         "RETROSPECTIVE_ONLY_AUTHOR_SKIPPED"),
    Case("OI2609", "2026-06-05", "2026-06-04T21:00", "2026-06-05T10:26", "SHORT",
         (("published_protection_lower", "10273"), ("prior_day_low_proxy", "10230")), None, "oi",
         ("S5306128623993006", "S5306393997347489", "WR2IUYCQHj"), "AUTHOR_REPORTED_M_NEXT_REFERENCE_UNKNOWN"),
    Case("RU2701", "2026-10-28", "2026-10-27T21:00", "2026-10-28T15:00:00.000002", "LONG",
         (("m_near_proxy", "19515"),), "19610", "ru", ("S5359046580243515",),
         "RETROSPECTIVE_ONLY_ACTUAL_PARTICIPATION_UNKNOWN"),
)


def carried_breaks(paths):
    """Carry genuine breaks through gaps only while observed closes stay beyond."""
    latest = None
    carried = {}
    for stamp, state in paths.items():
        if state["crossing"]:
            latest = stamp
        elif not state["outside"]:
            latest = None
        carried[stamp] = latest
    return carried


def first_reference(series, start, cutoff, target, side, *, overlap_can_block=False):
    if target is None:
        return None
    # Only the decision guard can use a conservative overlap. Historical contact requires a full bar.
    for bar in series:
        in_window = start < bar.end if overlap_can_block else start <= bar.start
        reached = bar.high >= target if side == "LONG" else bar.low <= target
        if in_window and reached and bar.end + US < cutoff:
            return bar.end + US
    return None


def with_opening_cross(minutes, paths, side, edge, session_open):
    """Use only the completed opening minute of the verified session."""
    first = minutes[0] if minutes else None
    if first is None or first.start != session_open:
        return None, {stamp: state["active_cross_at"] for stamp, state in paths.items()}

    opens_outside = beyond(first.open, edge, side)
    closes_outside = paths[first.end]["outside"]
    if not closes_outside:
        origin = "CLOSE_NOT_OUTSIDE"
    elif opens_outside:
        origin = "OPEN_ALREADY_OUTSIDE"
    else:
        origin = "OPEN_TO_CLOSE_CROSS"
    opening = dict(start=first.start, end=first.end, known_at=first.end + US, open=first.open,
                   close=first.close, origin=origin)
    initial_cross = first.end if origin == "OPEN_TO_CLOSE_CROSS" else None
    expected_start = first.start
    active = {}
    for bar in minutes:
        state = paths[bar.end]
        if bar.start != expected_start or not state["outside"]:
            initial_cross = None
        active[bar.end] = state["active_cross_at"] or initial_cross
        expected_start = bar.end
    return opening, active


def compare(series, *, side, edge, target, history_start, start, cutoff, session_open=None):
    history = price_states(completed(series[1], history_start, cutoff), side, edge)
    minutes = completed(series[1], start, cutoff)
    fresh = price_states(minutes, side, edge)
    carried = carried_breaks(history)
    modes = ("fresh_segment", "carry_unbroken")
    opening, opening_crosses = None, {}
    if session_open is not None:
        opening, opening_crosses = with_opening_cross(minutes, fresh, side, edge, session_open)
        modes += ("fresh_segment_or_open_cross",)
    reached = {
        "decision_window": first_reference(series[1], start, cutoff, target, side, overlap_can_block=True),
        "same_trading_day": first_reference(series[1], history_start, cutoff, target, side),
    }
    events = {}
    for period in (1, 5):
        rows = []
        for candidate in signals(series, 5, period, side=side, start=start, cut=cutoff):
            stamp = candidate["confirmed_at"]
            available = candidate["available_at"]
            shape_start = candidate["shape_end"] - FIVE
            interruption = {"fresh_segment": fresh[stamp]["active_cross_at"], "carry_unbroken": carried[stamp]}
            if session_open is not None:
                interruption["fresh_segment_or_open_cross"] = opening_crosses[stamp]
            rows.append(candidate | dict(
                interruption_at=interruption,
                interruption_fresh={kind: when is not None and when + US < shape_start
                                    for kind, when in interruption.items()},
                reference_reached_at={kind: when if when is not None and when <= available else None
                                      for kind, when in reached.items()},
            ))
        events[period] = rows

    comparison = {}
    for period, rows in events.items():
        for interruption in modes:
            eligible = [r for r in rows if r["interruption_fresh"][interruption]]
            comparison[f"5m_to_{period}m/{interruption}"] = dict(
                before_target_filter=[row["confirmed_at"] for row in eligible],
                target_window={scope: None if target is None else [
                    row["confirmed_at"] for row in eligible if row["reference_reached_at"][scope] is None
                ] for scope in reached},
            )
    result = dict(first_interruption_at=next((stamp for stamp, state in history.items() if state["crossing"]), None),
                  first_decision_window_interruption_at=next((stamp for stamp, state in fresh.items()
                                                             if state["crossing"]), None),
                  first_reference_known_at=reached, events=events, comparison=comparison)
    if session_open is not None:
        result["opening_minute"] = opening
    return result


def checked_series(session, market, case, reference):
    days = OI_DAYS if case.input_id == "oi" else (date.fromisoformat(case.trading_day),)
    raw, bars = read_pair(session, market, case.contract, days)
    if case.input_id == "oi":
        identity = {f"{period}m": market_digest(rows) for period, rows in raw.items()}
    elif case.input_id == "ru":
        identity = {f"{period}m": dict(count=len(rows), ohlc_sha256=bars_sha(rows)) for period, rows in raw.items()}
    else:
        identity = dict(minute_count=len(raw[1]), five_count=len(raw[5]),
                        minute_sha256=bars_sha(raw[1]), five_sha256=bars_sha(raw[5]))
    if identity != reference["inputs"][case.input_id]:
        raise ValueError("COUNTER_M_SEGMENT_MARKET_INPUT_CHANGED")
    return bars, identity


def study(session, market, reference, *, include_opening=False):
    results = {}
    for case in CASES:
        bars, identity = checked_series(session, market, case, reference)
        start, cutoff = at(f"{case.trading_day}T09:00"), at(case.cutoff)
        session_open = None
        if include_opening:
            from app.market_data.session_clock import resolved_session_windows_for_trading_day

            symbol = case.contract[:-4].lower()
            sessions = resolved_session_windows_for_trading_day(
                session, exchange=market.catalog.exchange_for_symbol(symbol), symbol=symbol,
                trading_day=date.fromisoformat(case.trading_day),
            )
            session_open = min((item.window.start for item in sessions if not item.is_night), default=None)
            if session_open is None or session_open != start:
                raise ValueError("COUNTER_M_DAY_SESSION_OPEN_MISMATCH")
        histories = {"full_day": at(case.start_previous_night)}
        if case.input_id == "jm_trial":
            # The 22:10 post gives only a conditional pre-image. It is not a fill clock.
            histories["after_conditional_position_known"] = at("2026-10-22T22:11") + US
        windows = {}
        for label, edge in case.levels:
            for history, history_start in histories.items():
                args = dict(side=case.side, edge=Decimal(edge), target=Decimal(case.target) if case.target else None,
                            history_start=history_start, start=start, session_open=session_open)
                result = compare(bars, cutoff=cutoff, **args)
                prefix_checks = 0
                for period, rows in result["events"].items():
                    for row in rows:
                        prefix = compare(bars, cutoff=row["available_at"] + US, **args)["events"][period]
                        expected = [e for e in rows if e["available_at"] <= row["available_at"]]
                        if prefix != expected:
                            raise ValueError("COUNTER_M_SEGMENT_PREFIX_MISMATCH")
                        prefix_checks += 1
                windows[f"{label}/{history}"] = dict(edge=edge, target=case.target, history_start=history_start,
                                                     start=start, cutoff_exclusive=cutoff, prefix_checks=prefix_checks,
                                                     **result)
        results[case.input_id] = dict(contract=case.contract, trading_day=case.trading_day, side=case.side,
                                      scope=case.evidence_scope, source_ids=case.source_ids, inputs=identity,
                                      windows=windows)
    version = "lms405-counter-m-opening-cross-study-v1" if include_opening else "lms405-counter-m-segment-study-v1"
    return dict(version=version, frozen_reference_sha256=REFERENCE, cases=results,
                author_actions_scored=0, author_match_rate=None, fills=None, pnl=None, executable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-opening-cross", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("COUNTER_M_SEGMENT_OUTPUT_EXISTS")
    try:
        reference = verified_json(args.reference, REFERENCE)
        result = local_market_case(args.env_file, case=lambda market_input: study(
            *market_input, reference, include_opening=args.include_opening_cross,
        ))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result | {"timezone": str(LOCAL)}))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() else "COUNTER_M_SEGMENT_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

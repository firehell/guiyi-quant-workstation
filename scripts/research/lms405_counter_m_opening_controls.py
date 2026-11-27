"""Compare unchanged M interruption hypotheses on source-selected controls."""

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_segment_study import compare
from lms405_m_permission_study import read_pair
from lms405_plan_driven_replay import local_market_case
from lms405_right_side_study import LOCAL, US, at
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded

# Select by source and price role before reading the follow-up windows.
# Each row preserves the distinction between an activation level and a diagnostic price.
CASES = (
    ("OI2605", "2025-12-23", "LONG", "2025-12-22T17:02", "S5246699477926773",
     "PRIOR_LMS_OPTION_VERSION_AND_OUTCOME_UNKNOWN",
     (("breakout_far", "8814", None), ("breakout_near_sensitivity", "8738", None))),
    ("JM2609", "2026-05-21", "SHORT", "2026-05-20T17:25", "G02;F08",
     "RECAP_IDENTIFIES_ORIGINAL_SHORT_RECOVERY_NOT_NEW_SHORT_M",
     (("balance_lower_recovery_control", "1223", "1214.5"),)),
    ("SH2609", "2026-07-27", "LONG", None, "S5325329692361179",
     "RETROSPECTIVE_EXTREME_M_BOUNDARY_OUTCOME_UNKNOWN",
     (("extreme_m_far", "1911", None),)),
    ("RU2609", "2026-06-23", "SHORT", "2026-06-18T17:19", "S5311208706277938;S5313021782003245",
     "EARLIER_BEARISH_TARGET_APPLICABILITY_M_DIRECTION_AND_ACTION_UNKNOWN",
     (("bearish_target_edge_sensitivity", "17670", "17555"),)),
)

FIRST_SESSION_CASES = (
    ("OI2609", "2026-06-05", "SHORT", "2026-06-04T16:52", "S5306128623993006;WR2IUYCQHj",
     "LOCKED_PREVIOUS_DAY_M_REPORTED_WITHOUT_SIGNAL_TIME",
     (("published_protection_lower", "10273", None), ("prior_day_low_sensitivity", "10230", None))),
    ("JM2701", "2026-09-09", "SHORT", None, "S5341270434121818",
     "AUTHOR_SKIPPED_M_RETROSPECTIVE_BOUNDS",
     (("m_near_sensitivity", "1663.5", "1657"),)),
    ("JM2701", "2026-10-23", "LONG", "2026-10-22T18:19", "A5356884629782554;WRnTlEfj1t;WRo0OCbeQG",
     "CURRENT_PRIOR_PLAN_TEXT_EDIT_HISTORY_UNKNOWN",
     (("published_interruption_far", "1397.5", "1420"),)),
    ("SH2701", "2026-10-28", "LONG", "2026-10-27T17:39", "A5358686695981271;WRoLeVhPQ1",
     "CURRENT_PRIOR_PLAN_TEXT_COMBINATION_RECAP_PRODUCT_ACTION_UNKNOWN",
     (("published_interruption_far", "1501", "1523"),)),
    ("RU2701", "2026-10-28", "LONG", "2026-10-27T17:39", "A5358686695981271;S5359046580243515",
     "CURRENT_PRIOR_PLAN_TEXT_RECAP_PARTICIPATION_UNKNOWN",
     (("published_interruption_far", "19405", "19610"), ("m_near_sensitivity", "19515", "19610"))),
)


def study(session, market, *, first_session_only=False):
    from app.market_data.market_data_service import MarketDataError
    from app.market_data.session_clock import SessionClockError, resolved_session_windows_for_trading_day

    results = {}
    cases = CASES + FIRST_SESSION_CASES if first_session_only else CASES
    for contract, day, side, published, sources, scope, levels in cases:
        ref = dict(contract=contract, trading_day=day, side=side, sources=sources.split(";"), scope=scope,
                   publication_minute_upper=at(published) if published else None, author_actions_scored=0)
        results[f"{contract}/{day}" if first_session_only else contract] = ref
        trading_day = date.fromisoformat(day)
        symbol = contract[:-4].lower()
        try:
            sessions = resolved_session_windows_for_trading_day(
                session, exchange=market.catalog.exchange_for_symbol(symbol), symbol=symbol, trading_day=trading_day,
            )
            night = [entry.window for entry in sessions if entry.is_night]
            day_windows = [entry.window for entry in sessions if not entry.is_night]
            if not night or not day_windows:
                raise ValueError("DAY_OR_NIGHT_SESSION_MISSING")
            first_day_window = min(day_windows, key=lambda w: w.start)
            start = first_day_window.start
            history_start = min(w.start for w in night)
            end = first_day_window.end if first_session_only else max(w.end for w in day_windows)
            cutoff = end + 2 * US
            if published and not at(published) < history_start:
                raise ValueError("SOURCE_NOT_KNOWN_BEFORE_NIGHT_SESSION")
            raw, bars = read_pair(session, market, contract, (trading_day,))
        except (ValueError, MarketDataError, SessionClockError) as exc:
            code = getattr(exc, "code", str(exc))
            ref.update(coverage=code if code.isidentifier() else "MARKET_INPUT_UNVERIFIED", windows=None)
            continue
        ref.update(coverage="COMPLETE", day_open=start, night_open=history_start, cutoff_exclusive=cutoff,
                   inputs={key: dict(count=len(rows), sha256=bars_sha(rows)) for key, rows in raw.items()}, windows={})
        for name, edge, target in levels:
            args = dict(side=side, edge=Decimal(edge), target=Decimal(target) if target else None,
                        history_start=history_start, start=start, session_open=start)
            full = compare(bars, cutoff=cutoff, **args)
            checks = 0
            for period, events in full["events"].items():
                for event in events:
                    known_at = event["available_at"]
                    prefix = compare(bars, cutoff=known_at + US, **args)["events"][period]
                    if prefix != [e for e in events if e["available_at"] <= known_at]:
                        raise ValueError("COUNTER_M_OPENING_CONTROL_PREFIX_MISMATCH")
                    checks += 1
            ref["windows"][name] = dict(edge=edge, target=target, prefix_checks=checks, **full)
    version = "lms405-counter-m-first-day-session-v1" if first_session_only else "lms405-counter-m-opening-controls-v1"
    return dict(version=version, cases=results, author_actions_scored=0,
                author_match_rate=None, fills=None, pnl=None, executable=False, timezone=str(LOCAL))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first-day-session", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("COUNTER_M_OPENING_CONTROL_OUTPUT_EXISTS")
    try:
        result = local_market_case(args.env_file, case=lambda market_input: study(
            *market_input, first_session_only=args.first_day_session,
        ))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (ValueError, KeyError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() else "COUNTER_M_OPENING_CONTROL_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()

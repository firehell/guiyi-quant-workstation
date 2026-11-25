"""Compare recovery price and volatility clocks for JM2601 and a PVC negative case."""

import argparse
from datetime import date, datetime
from pathlib import Path

from lms405_explicit_near_recovery import REFERENCES, market_for
from lms405_jm1072_public_clock import DAY, EDGE, FAR, NIGHT, NOON_POST, OPEN
from lms405_jm_oct_recovery_clock import window_signals
from lms405_protection_lot_timing import verified_json
from lms405_pvc_recovery_carry import BAND as PVC_BAND
from lms405_recovery_confirmation_audit import beyond, strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_sh2609_recovery_context import contexts
from lms405_sh_lock_lifecycle import completed
from lms_near405_replay import encoded

VERSION = "lms405-jm1072-stability-v1"
PVC_DAY = date(2026, 4, 27)
PVC_SOURCE = "S5292358960155373"
CONTRACTION_SCOPES = ("trading_day", "continuous_session")
CONTRACTION_MOMENTS = ("before_shape", "before_confirmation")
CONTRACTION_TESTS = ("latest_narrower_than_opening", "strict_two_in_sequence")


def compare_eligibility(row):
    price = row["price"]
    eligible = price["strictly_beyond_near"] and price["earlier_near_close"] is not None
    outcomes = {
        "earlier_near_close_and_current_beyond": eligible,
        "same_run_known_before_shape_and_current_beyond": eligible and price["current_run_known_before_shape"],
        "earlier_far_close_and_current_beyond": price["strictly_beyond_far"] and price["earlier_far_close"] is not None,
    }
    for scope in CONTRACTION_SCOPES:
        for moment in CONTRACTION_MOMENTS:
            context = row[moment][scope]
            for test in CONTRACTION_TESTS:
                outcomes[f"near_and_{scope}_{moment}_{test}"] = (context[test] if context else None) if eligible else False
    return outcomes


def evaluate_context(event, series, sessions, *, start, side, band):
    when, shape_start = event["confirmed_at"], event["shape_start"]
    near, far = band if side == "LONG" else band[::-1]
    minutes = completed(series[1], start, event["available_at"] + US)
    earlier = [bar for bar in minutes if bar.end + US < event["available_at"]]
    run = strict_runs(minutes, near, side).get(when)
    run_count = run["close_count"] if run else 0
    run_start = when - (run_count - 1) * ONE if run_count else None
    price = dict(
        strictly_beyond_near=beyond(event["close"], near, side),
        strictly_beyond_far=beyond(event["close"], far, side),
        earlier_near_close=next((bar.end for bar in earlier if beyond(bar.close, near, side)), None),
        earlier_far_close=next((bar.end for bar in earlier if beyond(bar.close, far, side)), None),
        current_run_close_count=run_count,
        current_run_known_before_shape=bool(run_start and run_start + US < shape_start),
    )
    row = event | dict(price=price, before_shape=contexts(series[15], sessions, shape_start),
                       before_confirmation=contexts(series[15], sessions, when))
    return row | dict(eligible_as_hypothesis=compare_eligibility(row))


def inspect_candidates(series, sessions, *, start, cutoff, display_from, side, band):
    events, signal_checks = window_signals(series, start, cutoff, side)
    scope = dict(start=start, side=side, band=band)
    results = {}
    for clock, rows in events.items():
        results[clock] = []
        for event in rows:
            if event["confirmed_at"] <= display_from:
                continue
            row = evaluate_context(event, series, sessions, **scope)
            cut = event["available_at"] + US
            prefix = {p: [bar for bar in bars if bar.end + US < cut] for p, bars in series.items()}
            if evaluate_context(event, prefix, sessions, **scope) != row:
                raise ValueError("RECOVERY_STABILITY_CONTEXT_PREFIX_DIVERGED")
            results[clock].append(row)
    all_rows = [row for rows in results.values() for row in rows]
    first_by_test = {}
    if all_rows:
        for key in all_rows[0]["eligible_as_hypothesis"]:
            first_by_test[key] = min((row["confirmed_at"] for row in all_rows
                                      if row["eligible_as_hypothesis"][key] is True), default=None)
    return dict(candidates=results, first_by_test=first_by_test, signal_prefix_checks=signal_checks,
                context_prefix_checks=len(all_rows), window_start=start, observation_cutoff=cutoff,
                display_after=display_from, direction=side, band=band)


def session_bounds(session, market, symbol, day):
    from app.market_data.session_clock import resolved_session_windows_for_trading_day

    exchange = market.catalog.exchange_for_symbol(symbol)
    windows = resolved_session_windows_for_trading_day(session, exchange=exchange, symbol=symbol, trading_day=day)
    return [(row.window.start, row.window.end) for row in windows]


def study(session, market, refs):
    prior = refs["jm"]
    if not (datetime.fromisoformat(prior["noon_report_displayed_at"]) == NOON_POST
            < datetime.fromisoformat(prior["later_article_entry"])) or prior["historical_plan_verified"]:
        raise ValueError("JM1072_STABILITY_SOURCE_SCOPE_CHANGED")
    jm = market_for(session, market, prior["contract"], DAY, prior["market"], end_only=True)
    focal = inspect_candidates(jm, session_bounds(session, market, "jm", DAY), start=NIGHT, cutoff=NOON_POST,
                               display_from=OPEN, side="SHORT", band=(FAR, EDGE))
    prior_pvc = refs["pvc"]
    pvc_source = prior_pvc["sources"][PVC_SOURCE]
    pvc_cutoff = at("2026-04-27T15:01")
    if (prior_pvc["author_april27_report"] != "NO_LONG_UNLOCK"
            or datetime.fromisoformat(pvc_source["published_at"]) <= pvc_cutoff):
        raise ValueError("PVC_STABILITY_SOURCE_SCOPE_CHANGED")
    pvc_input = prior_pvc["days"][PVC_DAY.isoformat()]["market"]
    pvc = market_for(session, market, prior_pvc["contract"], PVC_DAY, pvc_input)
    pvc_start = pvc[1][0].start
    control = inspect_candidates(pvc, session_bounds(session, market, "v", PVC_DAY), start=pvc_start, cutoff=pvc_cutoff,
                                 display_from=pvc_start, side="LONG", band=PVC_BAND)
    return dict(version=VERSION, cases={
        "jm_noon_reported_unlock": focal | dict(contract=prior["contract"], market=prior["market"],
                                                 sources=prior["sources"], source_plan_before_cutoff_verified=False),
        "pvc_no_long_unlock": control | dict(contract=prior_pvc["contract"], market=pvc_input, source=pvc_source,
                                              band_role="REPORTED_STRONG_TARGET",
                                              source_plan_before_cutoff_verified=False),
    }, input_report_sha256={key: REFERENCES[key][1] for key in refs}, retrospective_comparison=True,
        author_actions_scored=0, author_action_at=None, author_stability_formula=None, author_match_rate=None,
        executable=False, fills=None, pnl=None)


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
        refs = {key: verified_json(Path("output") / REFERENCES[key][0], REFERENCES[key][1]) for key in ("jm", "pvc")}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), refs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "JM1072_STABILITY_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()

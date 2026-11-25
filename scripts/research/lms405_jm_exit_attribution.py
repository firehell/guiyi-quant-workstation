"""Explain the frozen JM2701 October model exit and absence of reentry."""

import argparse
from datetime import datetime
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_fg_sa_case import at
from lms405_hold_clock_study import compare
from lms405_locked_exit_audit import BASELINE_SHA256, exit_times, first_exit
from lms405_portfolio_replay import DAYS, FIVE, batch_fixture_transitions
from lms405_replay import display, ohlc, read_session_series
from lms_near405_replay import encoded, sha

CONTRACT = "JM2701"
DAY_OPEN = at("27T09:00")
DAY_END = at("27T15:01")
DIVIDER_REPORT_SHA256 = "cdaa0aa6b4996d8214aabd6755ee7a203445bfa9bd922a2cf04029557369c792"


def frozen_transitions(baseline, replay):
    expected = []
    for row in baseline["timeline"]:
        if row["layer"] != "FIXTURE_STATE_BATCH":
            continue
        expected.extend((row["time"], action) for action in row["payload"]["actions"]
                        if action["contract"] == CONTRACT)
    batches, _ = batch_fixture_transitions(replay["transitions"])
    actual = [(row["time"], action) for row in batches for action in row["payload"]["actions"]]
    if actual != expected:
        raise ValueError("JM_EXIT_FROZEN_TRANSITIONS_DIVERGED")


def retained_exit_boundaries(checks):
    """Compare fixed-plan condition times. These snapshots never advance states."""
    omissions = (
        (), ("RISK_INVALID",), ("RISK_INVALID", "REGIME_INVALID"),
        ("RISK_INVALID", "REGIME_INVALID", "PLAN_EXPIRED"),
    )
    results = []
    for excluded in omissions:
        time, reason = first_exit({name: time for name, time in checks.items() if name not in excluded})
        results.append(dict(omit_only_for_diagnosis=excluded, first_reason=reason, available_at=time))
    return results


def post_exit_signals(bars, replay, closing):
    close_known = datetime.fromisoformat(closing["known_at"])
    plan = closing["after"]["plan"]
    expires = plan["created_index"] + candidate.RULES["plan_lifetime_bars"]
    day_proposals = {p["generated_at"]: p["action"] for p in replay["proposals"]}
    rows = []
    for evaluation in replay["evaluations"]:
        index, direction = evaluation["index"], evaluation["signal_direction"]
        bar = bars[index]
        if not close_known < bar.end < DAY_END or not direction:
            continue
        signal, region = bars[index - 1], evaluation["region"]
        rows.append(dict(
            bar_end=display(bar.end), close=bar.close, signal=direction, environment=region["environment"],
            range=[region["lower"], region["upper"]], context_starts_at=region["window_start"],
            context_is_entirely_after_exit=datetime.fromisoformat(region["window_start"]) > close_known,
            old_plan_within_time=index < expires,
            new_plan_price_condition=candidate._entry_allowed(region, direction, signal, bar),
            proposed_action=day_proposals.get(evaluation["available_at"]),
        ))
    return rows


def study(bars, baseline, divider):
    if any(b.contract != CONTRACT for b in bars):
        raise ValueError("JM_EXIT_CONTRACT_BOUNDARY")
    market_hash = sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))] for b in bars]).encode())
    if market_hash != baseline["contract_summaries"][CONTRACT]["input_prefix_sha256"]:
        raise ValueError("JM_EXIT_FROZEN_MARKET_DIVERGED")
    if baseline["candidate_rule_hash"] != candidate.RULE_HASH:
        raise ValueError("JM_EXIT_FROZEN_RULE_CHANGED")
    full = compare(bars, None, as_of=datetime.fromisoformat(baseline["as_of"]))
    frozen_transitions(baseline, full)
    replay = candidate.replay(bars, as_of=DAY_END, timely_fixture=True)
    opening, closing = [row for row in replay["transitions"] if DAY_OPEN < datetime.fromisoformat(row["known_at"])]
    if ((opening["action"], closing["action"]) != ("ENTER_LONG", "CLEAR")
            or opening["after"]["cycle_id"] != closing["before"]["cycle_id"]):
        raise ValueError("JM_EXIT_BASELINE_CYCLE_CHANGED")
    entry_at, close_at = (datetime.fromisoformat(row["known_at"]) for row in (opening, closing))
    plan = opening["after"]["plan"]
    times = exit_times(bars, entry_at, DAY_END, opening["after"])
    when, why = first_exit(times)
    if when + candidate.US != close_at or why != closing["reason"]:
        raise ValueError("JM_EXIT_ATTRIBUTED_REASON_DIVERGED")
    quotes = {}
    for source, anchor in divider["anchors"].items():
        time = datetime.fromisoformat(anchor["time"])
        actual = candidate.replay(bars, as_of=time, timely_fixture=True)
        if actual["terminal_status"] != "FLAT" or anchor["baseline"]["last_action"]["at"] != closing["known_at"]:
            raise ValueError("JM_EXIT_QUOTE_ANCHOR_BASELINE_DIVERGED")
        quotes[source] = dict(quote_at=time, model_before_quote=actual["terminal_status"], legs=anchor["legs"],
                              source_binding=anchor["binding"])
    before_clear = candidate.replay(bars, as_of=close_at - 2 * candidate.US, timely_fixture=True)
    restarted = candidate.replay(bars, as_of=DAY_END, timely_fixture=True,
                                 checkpoint=json.loads(encoded(before_clear["checkpoint"])))
    if before_clear["terminal_status"] != "OPEN_DIRECTIONAL" or restarted != replay:
        raise ValueError("JM_EXIT_RESTART_OR_STRICT_BEFORE_DIVERGED")
    closes = {b.end: b.close for b in bars}
    return dict(
        version="lms405-jm-exit-attribution-v1", contract=CONTRACT, rule_hash=candidate.RULE_HASH,
        baseline_sha256=BASELINE_SHA256, market_5m_sha256=market_hash, bars=len(bars),
        divider_report_sha256=DIVIDER_REPORT_SHA256,
        opening=dict(known_at=entry_at, close=closes[entry_at - 2 * candidate.US], plan=plan),
        exit=dict(known_at=close_at, close=closes[close_at - 2 * candidate.US], reason=why,
                  risk_boundary=plan["lower"]),
        fixed_plan_exit_conditions={name: dict(available_at=when, close=closes[when - candidate.US])
                                    for name, when in times.items()},
        conditional_first_exits=retained_exit_boundaries(times),
        post_exit_5m_confirmations=post_exit_signals(bars, replay, closing),
        quote_comparison=quotes, restarted_before_exit_matches_full=True,
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--portfolio", type=Path, required=True)
    parser.add_argument("--divider-report", type=Path, required=True)
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
        baseline, divider = args.portfolio.read_bytes(), args.divider_report.read_bytes()
        if sha(baseline) != BASELINE_SHA256 or sha(divider) != DIVIDER_REPORT_SHA256:
            parser.exit(2, "JM_EXIT_FROZEN_REPORT_CHANGED\n")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            raw = read_session_series(session, build_market_data_service(session), "jm", CONTRACT, "5m", FIVE, DAYS)
        bars = [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw]
        result = study(bars, json.loads(baseline), json.loads(divider))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "JM_EXIT_BASELINE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()

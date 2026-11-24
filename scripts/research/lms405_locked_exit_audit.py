"""Compare the first post-lock action on frozen fixtures and separate public windows."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_keybar_approx import classify
from lms405_portfolio_replay import CONTRACTS, DAYS, FIVE, batch_fixture_transitions
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

ONE = timedelta(minutes=1)
BASELINE_SHA256 = "fba8faadaffb8fc5f54bc84588ad67e2256a4b113db270ed4285e4fe518ba856"
POLICY_VERSION = "lms405-locked-first-action-audit-v1"
PUBLIC_WINDOWS = (
    ("SH2701", "2026-10-27T11:30:00+08:00", "2026-10-27T15:00:00+08:00",
     ("WRoAkcEppg", "U03"), "QUOTE_ALIGNED_MIXED_POSTS", True),
    ("I2701", "2026-10-27T15:00:00+08:00", "2026-10-27T22:12:00+08:00",
     ("U03", "WRoEvasxQR"), "END_POST_PARTIAL_QUOTE_ALIGNMENT", False),
    ("FG2701", "2026-10-22T22:10:00+08:00", "2026-10-23T10:13:00+08:00",
     ("WRnTlEfj1t", "WRnY5bznUE"), "POST_BOUNDED_ACCOUNT_CONTINUITY_UNVERIFIED", False),
)
EXIT_REASONS = {"PLAN_EXPIRED", "REGIME_INVALID", "RANGE_TARGET"}


def confirmed_shapes(fives, minutes, *, start, through, side):
    """Evaluate each close on its own availability; formation is strictly after the seed."""
    one_by_end = {bar.bar_end: bar for bar in minutes if bar.bar_end <= through}
    five_by_end = {bar.end: bar for bar in fives if bar.end <= through}
    rows = []
    for index, shape in enumerate(fives):
        if not start < shape.end < through:
            continue
        frame = classify(fives[index - 1] if index else None, shape)
        if not (frame.ibar or frame.pinbar == side):
            continue
        boundary = shape.high if side == "LONG" else shape.low
        fast = None
        for step in range(1, 6):
            minute = one_by_end.get(shape.end + step * ONE)
            if minute is None:
                # A break invalidates this immediate confirmation window.
                break
            if beyond(minute.close, boundary, side):
                fast = minute.bar_end
                break
        following = five_by_end.get(shape.end + FIVE)
        slow = (following.end if following and following.start == shape.end
                and beyond(following.close, boundary, side) else None)
        if fast or slow:
            rows.append(dict(
                shape_at=shape.end.isoformat(), level=str(boundary),
                fast_at=fast.isoformat() if fast else None, slow_at=slow.isoformat() if slow else None,
            ))
    return rows


def beyond(price, level, side):
    return price > level if side == "LONG" else price < level


def first_confirmation(shapes, field):
    return min((datetime.fromisoformat(row[field]) + candidate.US
                for row in shapes if row[field]), default=None)


def hard_stop(fives, start, through, state):
    """Preserve frozen risk boundary and equality; only a completed 5m can stop."""
    long = state["original_side"] == "LONG"
    threshold = Decimal(state["plan"]["lower" if long else "upper"])
    return next(
        (bar.end + candidate.US for bar in fives
         if start < bar.end and bar.end + candidate.US <= through
         and (bar.close <= threshold if long else bar.close >= threshold)),
        None,
    )


def verify_aggregation(fives, minutes):
    one_by_end = {bar.bar_end: bar for bar in minutes}
    for bar in fives:
        parts = [one_by_end[bar.start + step * ONE] for step in range(1, 6)]
        rebuilt = (parts[0].open, max(b.high for b in parts), min(b.low for b in parts), parts[-1].close)
        if rebuilt != ohlc(bar):
            raise ValueError("MINUTE_AGGREGATE_DIVERGED")


def hypothetical_first_action(exit_at, recovery_at, side, *, as_of, exit_reason="RISK_INVALID"):
    if recovery_at is not None and recovery_at > as_of:
        recovery_at = None
    if exit_at is not None and exit_at > as_of:
        exit_at = None
    if exit_at is not None and (recovery_at is None or exit_at <= recovery_at):
        return dict(action="CLEAR", reason=exit_reason, at=exit_at.isoformat())
    if recovery_at is not None:
        return dict(action="UNLOCK_" + side, reason="ORIGINAL_DIRECTION_CONFIRMATION", at=recovery_at.isoformat())
    return dict(action=None, reason="NO_CONCLUSIVE_FIRST_ACTION_IN_WINDOW", at=None)


def exit_times(bars, start, through, state):
    """Measure all four frozen exit conditions from the known locked state."""
    plan = state["plan"]
    side = state["original_side"]
    target = Decimal(plan["upper" if side == "LONG" else "lower"])
    adverse = "DOWN" if side == "LONG" else "UP"
    expires = plan["created_index"] + candidate.RULES["plan_lifetime_bars"]
    times = {"RISK_INVALID": hard_stop(bars, start, through, state)}
    for index, bar in enumerate(bars):
        at = bar.end + candidate.US
        if not start < bar.end or at > through:
            continue
        environment = candidate.context(bars, index)
        target_reached = bar.close >= target if side == "LONG" else bar.close <= target
        for reason, applies in (
            ("PLAN_EXPIRED", index >= expires),
            ("REGIME_INVALID", environment is not None and environment["environment"] == adverse),
            ("RANGE_TARGET", plan["environment"] == "RANGE" and target_reached),
        ):
            if applies:
                times.setdefault(reason, at)
    return {reason: at for reason, at in times.items() if at is not None}


def first_exit(times, *, exclude=None):
    priority = candidate.RULES["priority"]
    return min(
        ((at, reason) for reason, at in times.items() if reason != exclude),
        key=lambda pair: (pair[0], priority.index(pair[1])),
        default=(None, None),
    )


def audit_fixture(contract, transitions, fives, minutes, *, as_of):
    outcomes = []
    for i, lock in enumerate(transitions):
        if lock["action"] != "LOCK":
            continue
        cycle_id = lock["after"]["cycle_id"]
        later = next((row for row in transitions[i + 1:] if row["before"]["cycle_id"] == cycle_id), None)
        if later is None or later["action"] != "CLEAR" or later["reason"] not in EXIT_REASONS:
            raise ValueError("FROZEN_LOCK_OUTCOME_DIVERGED")
        state = lock["after"]
        side = state["original_side"]
        open_at = datetime.fromisoformat(lock["known_at"])
        shapes = confirmed_shapes(fives, minutes, start=open_at, through=as_of, side=side)
        times = exit_times(fives, open_at, as_of, state)
        original_at, original_reason = first_exit(times)
        if (original_at is None or original_at + candidate.US != datetime.fromisoformat(later["known_at"])
                or original_reason != later["reason"]):
            raise ValueError("BASELINE_EXIT_CONDITIONS_DIVERGED")
        risk = times.get("RISK_INVALID")
        next_exit_at, next_reason = first_exit(times, exclude=original_reason)
        outcomes.append(dict(
            contract=contract, side=side, cycle_id=cycle_id, locked_at=open_at.isoformat(),
            baseline_clear_at=later["known_at"], baseline_clear_reason=later["reason"],
            price_risk_level=state["plan"]["lower" if side == "LONG" else "upper"],
            hard_stop_available_at=risk.isoformat() if risk else None,
            frozen_exit_condition_times={name: at.isoformat() for name, at in times.items()},
            only_baseline_first_exit_deferred={
                field: hypothetical_first_action(
                    next_exit_at, first_confirmation(shapes, field), side,
                    as_of=as_of, exit_reason=next_reason,
                )
                for field in ("fast_at", "slow_at")
            },
            soft_exits_deferred={
                field: hypothetical_first_action(risk, first_confirmation(shapes, field), side, as_of=as_of)
                for field in ("fast_at", "slow_at")
            },
            confirmation_windows=shapes,
        ))
    return outcomes


def compute(session, market, baseline):
    as_of = datetime.fromisoformat(baseline["as_of"])
    fives, transitions = {}, {}
    for contract in CONTRACTS:
        bars = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        series = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in bars]
        prefix_hash = sha(encoded([[b.end.isoformat(), *(str(p) for p in ohlc(b))] for b in series]).encode())
        if prefix_hash != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("FROZEN_INPUT_BAR_IDENTITY_DIVERGED")
        fives[contract] = series
        transitions[contract] = candidate.replay(
            series, as_of=as_of, timely_fixture=True,
        )["transitions"]
    batches, _ = batch_fixture_transitions(row for rows in transitions.values() for row in rows)
    if batches != [r for r in baseline["timeline"] if r["layer"] == "FIXTURE_STATE_BATCH"]:
        raise ValueError("FROZEN_PORTFOLIO_BASELINE_DIVERGED")

    needed = {contract for contract, rows in transitions.items() if any(r["action"] == "LOCK" for r in rows)}
    needed.update(contract for contract, *_ in PUBLIC_WINDOWS)
    minutes = {
        contract: read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, DAYS)
        for contract in sorted(needed)
    }
    for contract, series in minutes.items():
        verify_aggregation(fives[contract], series)
    fixtures = [
        row for contract in CONTRACTS if contract in minutes
        for row in audit_fixture(contract, transitions[contract], fives[contract], minutes[contract], as_of=as_of)
    ]
    public = []
    for contract, start, through, refs, confidence, end_is_quote_anchor in PUBLIC_WINDOWS:
        finish = datetime.fromisoformat(through)
        if not end_is_quote_anchor:
            # The post is only known to the minute, so exclude that entire minute's end.
            finish -= candidate.US
        shapes = confirmed_shapes(
            fives[contract], minutes[contract], start=datetime.fromisoformat(start),
            through=finish, side="SHORT",
        )
        public.append(dict(
            contract=contract, window=[start, through], side_hypothesis="SHORT", sources=refs,
            time_evidence=confidence, includes_end_bar=end_is_quote_anchor,
            hard_stop_available_at=None, author_action=None,
            risk_status="UNKNOWN_NO_BOUND_AUTHOR_RISK_REGION", confirmation_windows=shapes,
        ))
    # Both iron snapshots show the same two average prices and quantities.
    # Account continuity (and intermediate event history) is nevertheless unknown.
    first_display = datetime.fromisoformat("2026-10-27T11:30:00+08:00")
    second_display = datetime.fromisoformat("2026-10-27T15:00:00+08:00")
    observed_span = dict(
        contract="I2701", quote_times=[first_display.isoformat(), second_display.isoformat()],
        completed_5m_bars_between=sum(first_display < b.end <= second_display for b in fives["I2701"]),
        frozen_plan_lifetime_bars=candidate.RULES["plan_lifetime_bars"],
        sources=["WRoAkcEppg", "U03"], continuity_proven=False,
    )
    return dict(
        policy_version=POLICY_VERSION, frozen_portfolio_sha256=BASELINE_SHA256,
        as_of=as_of.isoformat(), hypothesis_scope="FIRST_ACTION_PER_INDEPENDENT_FROZEN_LOCK",
        matching_author_events=None, executable=False, fills=None, pnl=None,
        coverage={"five_minute": {c: len(b) for c, b in fives.items()},
                  "one_minute": {c: len(b) for c, b in minutes.items()}},
        minute_inputs_sha256={
            contract: sha(encoded([[bar.bar_end.isoformat(), *(str(p) for p in ohlc(bar))]
                                   for bar in series]).encode())
            for contract, series in minutes.items()
        },
        fixture_cases=sorted(fixtures, key=lambda r: datetime.fromisoformat(r["locked_at"])),
        public_comparisons=public, author_display_dwell_comparison=observed_span,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or not args.baseline.is_file() or args.output.exists():
        parser.error("INPUT_MISSING_OR_OUTPUT_EXISTS")
    raw = args.baseline.read_bytes()
    if sha(raw) != BASELINE_SHA256:
        parser.error("BASELINE_IDENTITY_MISMATCH")

    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = compute(session, build_market_data_service(session), json.loads(raw))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (ValueError, KeyError):
        parser.exit(2, "AUDIT_INPUT_OR_BASELINE_UNVERIFIED\n")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded(report))


if __name__ == "__main__":
    main()

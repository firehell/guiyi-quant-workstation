"""Complete deterministic near-LMS research candidate, never an execution engine.

All thresholds and combined rules are candidate assumptions. Old LMS versions
remain independent. Decimal prices, explicit human decisions, no fills/PnL.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from .lms405 import Position, Action, apply_action, timestamp
from .lms_keybar_approx import classify, VERSION as KEYBAR_VERSION
from .lms_confirmed_replay import fingerprint

VERSION = "lms-near405-v1"
RULES = dict(
    version=VERSION,
    keybar_version=KEYBAR_VERSION,
    context_bars=6,
    block_bars=3,
    plan_lifetime_bars=12,
    max_attempts=2,
    availability_microseconds=1,
    fixture_delay_microseconds=1,
    priority=[
        "RISK_INVALID",
        "PLAN_EXPIRED",
        "REGIME_INVALID",
        "RANGE_TARGET",
        "LOCK",
        "UNLOCK",
        "REENTER",
        "ENTER",
    ],
)
RULE_HASH = fingerprint(RULES)
US = timedelta(microseconds=1)


def _time(value):
    t = datetime.fromisoformat(value)
    timestamp(t)
    return t


def context(bars, index):
    """Exclude signal(index-1) and confirmation(index); no future pivot labels."""
    if index < 7:
        return None
    w = bars[index - 7 : index - 1]
    a, b = w[:3], w[3:]
    ah, al = max(x.high for x in a), min(x.low for x in a)
    bh, bl = max(x.high for x in b), min(x.low for x in b)
    env = "UP" if bh > ah and bl > al else "DOWN" if bh < ah and bl < al else "RANGE"
    lower, upper = min(x.low for x in w), max(x.high for x in w)
    return dict(
        environment=env,
        lower=str(lower),
        upper=str(upper),
        valid=lower < upper,
        window_start=w[0].end.isoformat(),
        window_end=w[-1].end.isoformat(),
        context_hash=fingerprint([asdict(x) for x in w]),
    )


def _direction(frame, following):
    direction = (
        "LONG"
        if following.close > frame.bar.high
        else "SHORT"
        if following.close < frame.bar.low
        else None
    )
    if direction and (frame.ibar is True or frame.pinbar == direction):
        return direction
    return None


def _entry_allowed(region, side, signal, following):
    lo, hi = Decimal(region["lower"]), Decimal(region["upper"])
    # Multiplication by 2 avoids midpoint rounding and a new indicator parameter.
    with localcontext() as ctx:
        values = (lo, hi, signal.low, signal.high)
        ctx.prec = max(
            28,
            max(x.adjusted() for x in values)
            - min(x.as_tuple().exponent for x in values)
            + 4,
        )
        near_high = signal.low <= hi and signal.high * 2 >= lo + hi
        near_low = signal.high >= lo and signal.low * 2 <= lo + hi
    env = region["environment"]
    c = following.close
    if side == "LONG":
        return (env == "UP" and near_high and c > hi) or (
            env == "RANGE" and near_low and lo < c < hi
        )
    return (env == "DOWN" and near_low and c < lo) or (
        env == "RANGE" and near_high and lo < c < hi
    )


def _invalid(state, bars, index):
    plan = state["plan"]
    side = state["original_side"]
    lo, hi = Decimal(plan["lower"]), Decimal(plan["upper"])
    # Persistent invalidation for this cycle: reveal history only, never heal a
    # breached plan while waiting for a human CLEAR. New reentry starts a cycle.
    for j in range(state["entry_index"] + 1, index + 1):
        found = set()
        c = bars[j].close
        if (side == "LONG" and c <= lo) or (side == "SHORT" and c >= hi):
            found.add("RISK_INVALID")
        if j >= plan["created_index"] + RULES["plan_lifetime_bars"]:
            found.add("PLAN_EXPIRED")
        env = context(bars, j)
        if env and env["environment"] == ("DOWN" if side == "LONG" else "UP"):
            found.add("REGIME_INVALID")
        if plan["environment"] == "RANGE" and (
            (side == "LONG" and c >= hi) or (side == "SHORT" and c <= lo)
        ):
            found.add("RANGE_TARGET")
        first = next((r for r in RULES["priority"][:4] if r in found), None)
        if first:
            return first
    return None


def initial_state(bars):
    seed = (bars[0].start - US).isoformat()
    return dict(
        contract=bars[0].contract,
        long="0",
        short="0",
        original_side=None,
        cycle_id=None,
        cycle_seq=0,
        plan=None,
        attempt=0,
        entry_index=None,
        since=seed,
        known_at=seed,
        last_exit_at=None,
        last_exit_reason=None,
    )


def evaluate(state, bars, index):
    """One revealed Bar, one possible proposal; state is never mutated here."""
    c = bars[index]
    t = c.end + US
    region = context(bars, index)
    frame = (
        classify(bars[index - 2] if index >= 2 else None, bars[index - 1])
        if index
        else None
    )
    direction = _direction(frame, c) if frame else None
    result = dict(
        index=index,
        bar_end=c.end.isoformat(),
        available_at=t.isoformat(),
        environment=region["environment"] if region else None,
        region=region,
        pattern=dict(
            ibar=frame.ibar,
            pinbar=frame.pinbar,
            signal_bar_end=frame.bar.end.isoformat(),
        )
        if frame
        else None,
        signal_direction=direction,
        status="WARMUP" if region is None else "HOLD",
        proposal=None,
    )
    if region is None:
        return result
    action = reason = plan = None
    held = Decimal(state["long"]) + Decimal(state["short"]) > 0
    signal_fresh = frame.bar.end > _time(state["since"])
    if held:
        reason = _invalid(state, bars, index)
        if reason:
            action = "CLEAR"
        elif direction and signal_fresh:
            locked = state["long"] == state["short"]
            if not locked and direction != state["original_side"]:
                action = "LOCK"
                reason = "OPPOSING_KEYBAR"
            elif locked and direction == state["original_side"]:
                action = "UNLOCK_" + direction
                reason = "ORIGINAL_DIRECTION_KEYBAR"
    elif direction and signal_fresh and region["valid"]:
        prior = state["plan"]
        if (
            prior
            and state["last_exit_reason"] == "RISK_INVALID"
            and state["attempt"] < RULES["max_attempts"]
            and index < prior["created_index"] + RULES["plan_lifetime_bars"]
            and direction == prior["side"]
            and region["environment"] != ("DOWN" if direction == "LONG" else "UP")
            and _entry_allowed(prior, direction, frame.bar, c)
        ):
            action = "REENTER_" + direction
            reason = "FRESH_SIGNAL_RETRY"
            plan = prior
        # A new plan requires an entire post-exit context, not merely a new id.
        elif (
            state["last_exit_at"] is None
            or _time(region["window_start"]) > _time(state["last_exit_at"])
        ) and _entry_allowed(region, direction, frame.bar, c):
            action = "ENTER_" + direction
            reason = "FRESH_PLAN_KEYBAR"
            plan = {
                k: region[k] for k in ("lower", "upper", "environment", "context_hash")
            }
            plan.update(side=direction, created_index=index, created_at=t.isoformat())
            plan["plan_id"] = fingerprint(
                dict(
                    rules=RULE_HASH,
                    contract=c.contract,
                    region=plan,
                    signal=asdict(frame.bar),
                    confirmation=asdict(c),
                )
            )
    if action:
        proposed_plan = plan or state["plan"]
        p = dict(
            version=VERSION,
            rule_hash=RULE_HASH,
            keybar_version=KEYBAR_VERSION,
            contract=c.contract,
            action=action,
            reason=reason,
            state_fingerprint=fingerprint(state),
            cycle_id=state["cycle_id"],
            plan_id=proposed_plan["plan_id"],
            signal_bar_end=frame.bar.end.isoformat(),
            generated_at=t.isoformat(),
            index=index,
            plan=proposed_plan,
            status="PENDING",
            executable=False,
        )
        p["proposal_id"] = fingerprint(p)
        result.update(status="PROPOSAL", proposal=p)
    elif not held:
        result["status"] = "NO_ENTRY" if region["valid"] else "DEGENERATE_REGION"
    elif direction and not signal_fresh:
        result["status"] = "STALE_SIGNAL"
    return result


def _apply(state, p, t):
    action = p["action"]
    before = Position(
        state["contract"], Decimal(state["long"]), Decimal(state["short"])
    )
    quantity = before.long + before.short if action == "CLEAR" else Decimal(1)
    pos = apply_action(before, Action(action, quantity))
    after = state | dict(
        long=str(pos.long),
        short=str(pos.short),
        since=t.isoformat(),
        known_at=t.isoformat(),
    )
    if action.startswith(("ENTER_", "REENTER_")):
        side = action.split("_")[-1]
        seq = state["cycle_seq"] + 1
        after.update(
            original_side=side,
            cycle_seq=seq,
            cycle_id=fingerprint(
                dict(version=VERSION, sequence=seq, proposal_id=p["proposal_id"])
            ),
            plan=p["plan"],
            attempt=state["attempt"] + 1 if action.startswith("REENTER_") else 1,
            entry_index=p["index"],
            last_exit_reason=None,
        )
    elif action == "CLEAR":
        after.update(
            last_exit_at=t.isoformat(),
            last_exit_reason=p["reason"],
            cycle_id=None,
            entry_index=None,
        )
    return after


def replay(bars, decisions=None, *, as_of, checkpoint=None, timely_fixture=False):
    """Append-only hypothesis replay; checkpoint recovery validates the entire prefix.

    Only explicit timely_fixture creates TEST_FIXTURE records. Human mode never
    generates decisions, and no accepted action is a broker or fill fact.
    """
    timestamp(as_of)
    if not isinstance(timely_fixture, bool):
        raise ValueError("BOOLEAN_MODE_REQUIRED")
    visible = [b for b in bars if b.end + US <= as_of]
    if not visible:
        raise ValueError("VISIBLE_BARS_REQUIRED")
    for i, b in enumerate(visible):
        classify(visible[i - 1] if i else None, b)
    state = initial_state(visible)
    supplied = list(decisions or [])
    if timely_fixture and supplied:
        raise ValueError("FIXTURE_MODE_DISALLOWS_EXTERNAL_DECISIONS")
    if checkpoint is not None:
        old = _time(checkpoint["as_of"])
        if old > as_of:
            raise ValueError("CHECKPOINT_TIME_REVERSED")
        prior = replay(
            bars,
            None if timely_fixture else checkpoint["decision_records"],
            as_of=old,
            timely_fixture=timely_fixture,
        )["checkpoint"]
        if prior != checkpoint:
            raise ValueError("CHECKPOINT_IDENTITY_MISMATCH")
        if not timely_fixture:
            for d in supplied:
                if d not in checkpoint["decision_records"]:
                    try:
                        late = _time(d["known_at"]) <= old
                    except (ValueError, TypeError, KeyError):
                        late = True
                    if late:
                        raise ValueError("LATE_DECISION_BEFORE_CHECKPOINT")
            supplied = checkpoint["decision_records"] + [
                d for d in supplied if d not in checkpoint["decision_records"]
            ]
    proposals = []
    evaluations = []
    outcomes = []
    transitions = []
    records = []
    groups = {}
    processed = {}
    for d in supplied:
        try:
            if not isinstance(d, dict):
                raise ValueError()
            t = _time(d["known_at"])
            if t > as_of:
                continue
            if not isinstance(d.get("decision_id"), str) or not d["decision_id"]:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            records.append(d)
            outcomes.append(dict(record=d, status="INVALID", reason="INVALID_DECISION"))
            continue
        if d not in records:
            records.append(d)
            groups.setdefault(t, []).append(d)
    events = [(b.end + US, 0, i) for i, b in enumerate(visible)] + [
        (t, 1, ds) for t, ds in groups.items()
    ]
    events.sort(key=lambda x: (x[0], x[1]))

    def process(ds, t):
        nonlocal state
        for d in sorted(ds, key=fingerprint):
            p = None
            reason = "INVALID_DECISION"
            try:
                if not all(
                    isinstance(d.get(k), str) and d[k]
                    for k in ("decision_id", "proposal_id", "state_fingerprint")
                ):
                    raise ValueError()
                decided = _time(d["decided_at"])
                if (
                    t < decided
                    or d["decision"] not in ("ACCEPT", "REJECT")
                    or d["record_kind"]
                    not in ("HUMAN_RESEARCH_DECISION", "TEST_FIXTURE")
                ):
                    raise ValueError()
                if "recorded_at" in d:
                    _time(d["recorded_at"])
                if d["decision_id"] in processed and processed[
                    d["decision_id"]
                ] != fingerprint(d):
                    reason = "DECISION_ID_CONTENT_CONFLICT"
                elif len(ds) > 1:
                    reason = "SAME_TIME_DECISION_CONFLICT"
                elif any(
                    d.get(k, v) != v
                    for k, v in dict(
                        version=VERSION,
                        rule_hash=RULE_HASH,
                        keybar_version=KEYBAR_VERSION,
                        contract=state["contract"],
                        cycle_id=state["cycle_id"],
                    ).items()
                ):
                    reason = "IDENTITY_MISMATCH"
                else:
                    p = next(
                        (p for p in proposals if p["proposal_id"] == d["proposal_id"]),
                        None,
                    )
                    if p is None:
                        reason = "UNKNOWN_PROPOSAL"
                    elif d.get("plan_id", p["plan_id"]) != p["plan_id"]:
                        reason = "IDENTITY_MISMATCH"
                    elif p["status"] != "PENDING":
                        reason = "PROPOSAL_NOT_PENDING"
                    elif d["state_fingerprint"] != p["state_fingerprint"] or d[
                        "state_fingerprint"
                    ] != fingerprint(state):
                        reason = "STATE_MISMATCH"
                    elif decided <= _time(p["generated_at"]) or t <= _time(
                        p["generated_at"]
                    ):
                        reason = "DECISION_NOT_AFTER_PROPOSAL"
                    elif d["decision"] == "REJECT":
                        p["status"] = "REJECTED"
                        reason = "REJECTED"
                    else:
                        before = state
                        state = _apply(state, p, t)
                        p["status"] = "ACCEPTED"
                        reason = "ACCEPTED"
                        transitions.append(
                            dict(
                                proposal_id=p["proposal_id"],
                                decision_id=d["decision_id"],
                                action=p["action"],
                                reason=p["reason"],
                                known_at=t.isoformat(),
                                before=before,
                                after=state,
                                record_kind=d["record_kind"],
                            )
                        )
            except (ValueError, TypeError, KeyError):
                reason = "INVALID_DECISION"
            processed.setdefault(d["decision_id"], fingerprint(d))
            outcomes.append(
                dict(
                    record=d,
                    status=reason if reason in ("ACCEPTED", "REJECTED") else "INVALID",
                    reason=reason,
                    confirmation_delay_seconds=str(
                        (t - _time(p["generated_at"])).total_seconds()
                    )
                    if p
                    else None,
                )
            )

    for t, kind, payload in events:
        if kind == 1:
            process(payload, t)
            continue
        for p in proposals:
            if p["status"] == "PENDING":
                p.update(status="EXPIRED", expired_at=t.isoformat())
        e = evaluate(state, visible, payload)
        evaluations.append({k: v for k, v in e.items() if k != "proposal"})
        if e["proposal"]:
            p = e["proposal"]
            proposals.append(p)
            ft = t + US
            if timely_fixture and ft <= as_of:
                d = dict(
                    decision_id="fixture-" + p["proposal_id"],
                    proposal_id=p["proposal_id"],
                    state_fingerprint=p["state_fingerprint"],
                    decision="ACCEPT",
                    decided_at=ft.isoformat(),
                    known_at=ft.isoformat(),
                    record_kind="TEST_FIXTURE",
                )
                records.append(d)
                process([d], ft)

    # Canonical chronological record order makes batch and resumed files identical.
    def record_key(record):
        try:
            return (1, _time(record["known_at"]), fingerprint(record))
        except (ValueError, TypeError, KeyError):
            return (0, as_of, fingerprint(record))

    records.sort(key=record_key)
    outcomes.sort(key=lambda outcome: record_key(outcome["record"]))
    cp = dict(
        version=VERSION,
        rule_hash=RULE_HASH,
        as_of=as_of.isoformat(),
        mode="TIMELY_TEST_FIXTURE" if timely_fixture else "HUMAN_CONFIRMATION",
        input_prefix_hash=fingerprint([asdict(b) for b in visible]),
        cursor=len(visible),
        initial_state=initial_state(visible),
        current_state=state,
        pending_proposals=[p for p in proposals if p["status"] == "PENDING"],
        decision_records=records,
        processed_decisions=[
            dict(
                decision_id=d.get("decision_id") if isinstance(d, dict) else None,
                content_hash=fingerprint(d),
            )
            for d in records
        ],
    )
    terminal = (
        "FLAT"
        if state["long"] == state["short"] == "0"
        else "OPEN_LOCKED"
        if state["long"] == state["short"]
        else "OPEN_DIRECTIONAL"
    )
    return dict(
        version=VERSION,
        rule_hash=RULE_HASH,
        rules=deepcopy(RULES),
        evaluations=evaluations,
        proposals=proposals,
        decisions=outcomes,
        transitions=transitions,
        current_state=state,
        terminal_status=terminal,
        checkpoint=cp,
        executable=False,
        fill=None,
        performance=None,
        cost=None,
        margin=None,
    )

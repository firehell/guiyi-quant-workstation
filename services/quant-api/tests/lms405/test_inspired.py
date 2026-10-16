from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_inspired import (
    State,
    batch,
    step,
    restore,
    snapshot,
    policy,
    features,
)
from dataclasses import replace


def bars(n=90):
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        Bar(
            "JM2701",
            start + timedelta(minutes=15 * (i + 1)),
            D(100 + i),
            D(102 + i),
            D(99 + i),
            D(101 + i),
            start=start + timedelta(minutes=15 * i),
        )
        for i in range(n)
    ]


def test_warmup_and_prefix_restart():
    xs = bars()
    state, frames = batch(State("JM2701"), xs)
    assert all(f["action"] is None for f in frames[:50])
    a, fa = batch(State("JM2701"), xs[:61])
    assert fa == frames[:61]
    b, fb = batch(restore(json.loads(json.dumps(snapshot(a)))), xs[61:])
    assert snapshot(b) == snapshot(state)
    assert fa + fb == frames


def test_contract_and_overlap_rejected():
    state, _ = step(State("JM2701"), bars()[0])
    with pytest.raises(ValueError, match="BAR_ORDER"):
        step(state, bars()[0])
    with pytest.raises(ValueError, match="CONTRACT"):
        step(State("FG2701"), bars()[0])


def test_restore_rejects_version():
    raw = snapshot(State("JM2701"))
    raw["version"] = "another-rule"
    with pytest.raises(ValueError, match="VERSION"):
        restore(raw)


def quote(close):
    return replace(
        bars()[0], open=D(close), high=D(close) + 1, low=D(close) - 1, close=D(close)
    )


def signal(**kwargs):
    return (
        dict(
            environment="TREND", a=D(2), long=False, short=False, bull=False, bear=False
        )
        | kwargs
    )


@pytest.mark.parametrize("side", [1, -1])
def test_enter_lock_restore_exit_reenter(side):
    up = side == 1
    entry = signal(long=up, short=not up)
    s, action, _ = policy(State("JM2701"), quote(100), entry)
    assert action == ("ENTER_LONG" if up else "ENTER_SHORT")
    s, action, _ = policy(s, quote(100 - side), signal(bear=up, bull=not up))
    assert action == "LOCK" and s.long == s.short == 1
    s = restore(json.loads(json.dumps(snapshot(s))))
    s, action, _ = policy(s, quote(100), entry)
    assert action == ("UNLOCK_LONG" if up else "UNLOCK_SHORT")
    assert (s.long, s.short) == ((D(1), D(0)) if up else (D(0), D(1)))
    s, action, reason = policy(s, quote(100 + 6 * side), signal())
    assert action == "CLEAR" and reason == "TARGET"
    for _ in range(2):
        s, action, reason = policy(s, quote(100), entry)
        assert action is None and reason == "COOLDOWN"
    s, action, _ = policy(s, quote(100), entry)
    assert action == ("REENTER_LONG" if up else "REENTER_SHORT")


@pytest.mark.parametrize(
    "price,env,reason", [("93", "TREND", "HARD_CLOSE_STOP"), ("100", "S", "EXTREME")]
)
def test_clear_precedes_lock(price, env, reason):
    s, _, _ = policy(State("JM2701"), quote(100), signal(long=True))
    s, action, why = policy(s, quote(price), signal(environment=env, bear=True))
    assert action == "CLEAR" and why == reason and s.long + s.short == 0


def test_lock_timeout_trailing_and_failed_reentry():
    s, _, _ = policy(State("JM2701"), quote(100), signal(long=True))
    s, _, _ = policy(s, quote(102), signal())
    _, action, why = policy(s, quote(98), signal())
    assert (action, why) == ("CLEAR", "TRAIL")
    s, _, _ = policy(State("JM2701", last_side=1), quote(100), signal(long=True))
    s, action, _ = policy(s, quote(97), signal())
    assert action == "LOCK"
    for _ in range(7):
        s, action, _ = policy(s, quote(97), signal())
        assert action is None
    s, action, why = policy(s, quote(97), signal(long=True))
    assert (action, why) == ("CLEAR", "LOCK_TIMEOUT")


def test_feature_background_and_extreme():
    xs = bars(60)
    f = features(xs[:50], xs[50])
    assert f["fast"] == D("140.5") and f["slow"] == D("125.5")
    assert f["a"] == 3 and f["er"] == 1
    assert f["upper"] == D("150.75")
    assert f["long"] is False  # Previous close=150 has not closed above shared anchor.
    current = replace(xs[50], high=D(180))
    extreme = features(xs[:50], current)
    assert extreme["environment"] == "S" and not extreme["long"]
    assert all(
        f[k] == extreme[k] for k in ("a", "fast", "slow", "er", "upper", "lower")
    )


def test_observation_and_zero_range():
    xs = [
        replace(b, open=D(100), high=D(100), low=D(100), close=D(100)) for b in bars()
    ]
    _, frames = batch(State("JM2701"), xs)
    assert frames[-1]["features"]["environment"] == "ZERO_VOLATILITY"
    assert not any(f["action"] for f in frames)
    s, _, _ = policy(State("JM2701"), quote(100), signal(long=True))
    with pytest.raises(ValueError, match="OBSERVE_ONLY"):
        step(s, bars()[0], observe_only=True)


def test_conflict_and_max_hold():
    _, action, reason = policy(
        State("JM2701"), quote(100), signal(long=True, short=True)
    )
    assert action is None and reason == "CONFLICT"
    s, _, _ = policy(State("JM2701"), quote(100), signal(long=True))
    s = replace(s, age=63)
    _, action, reason = policy(s, quote(100), signal())
    assert (action, reason) == ("CLEAR", "MAX_HOLD")


def test_decimal_context_and_incomplete_held_history():
    from decimal import localcontext, ROUND_FLOOR, ROUND_CEILING, Inexact

    xs = bars(60)
    xs[40] = replace(xs[40], high=xs[40].high + D(".1"))
    with localcontext() as ctx:
        ctx.rounding = ROUND_FLOOR
        a, fa = batch(State("JM2701"), xs)
    with localcontext() as ctx:
        ctx.rounding = ROUND_CEILING
        ctx.traps[Inexact] = True
        b, fb = batch(State("JM2701"), xs)
    assert fa == fb and snapshot(a) == snapshot(b)
    held, _, _ = policy(State("JM2701"), quote(100), signal(long=True))
    with pytest.raises(ValueError, match="HELD_HISTORY"):
        step(held, bars()[0])


def test_two_close_breakout_and_restart_with_actual_position():
    xs = bars(53)
    xs[50] = replace(xs[50], open=D(150), close=D(154), high=D(155), low=D(149))
    xs[51] = replace(xs[51], open=D(154), close=D(156), high=D(157), low=D(153))
    a, frames = batch(State("JM2701"), xs[:52])
    assert frames[50]["action"] is None
    assert frames[51]["action"] == "ENTER_LONG"
    assert frames[51]["effective_after"] == xs[51].end.isoformat()
    b, rest = batch(restore(json.loads(json.dumps(snapshot(a)))), xs[52:])
    full, full_frames = batch(State("JM2701"), xs)
    assert snapshot(b) == snapshot(full) and frames + rest == full_frames
    with pytest.raises(ValueError, match="15M"):
        step(State("JM2701"), replace(xs[0], start=xs[0].start - timedelta(minutes=1)))

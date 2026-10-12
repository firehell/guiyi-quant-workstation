"""Independent hypotheses, NOT the author's LMS formula. Decisions, never fills."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from .lms405 import Action, Bar, Position, apply_action, physical_contract

VERSION = "lms-inspired-v1.0"
D = Decimal
ZERO = D(0)


@dataclass(frozen=True)
class State:
    contract: str
    history: tuple[Bar, ...] = ()
    long: Decimal = ZERO
    short: Decimal = ZERO
    side: int = 0
    entry: Decimal = ZERO
    risk: Decimal = ZERO
    best: Decimal = ZERO
    lock_price: Decimal = ZERO
    age: int = 0
    lock_age: int = 0
    cooldown: int = 0
    last_side: int = 0

    def __post_init__(self):
        physical_contract(self.contract)
        for value in (
            self.long,
            self.short,
            self.entry,
            self.risk,
            self.best,
            self.lock_price,
        ):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("INVALID_STATE_DECIMAL")
        if self.long not in (ZERO, D(1)) or self.short not in (ZERO, D(1)):
            raise ValueError("UNIT_LEGS_REQUIRED")
        if self.side not in (-1, 0, 1) or self.last_side not in (-1, 0, 1):
            raise ValueError("INVALID_SIDE")
        for value in (self.age, self.lock_age, self.cooldown):
            if type(value) is not int or value < 0:
                raise ValueError("INVALID_COUNTER")
        held = bool(self.long or self.short)
        if held != bool(self.side) or (
            held and min(self.entry, self.risk, self.best) <= 0
        ):
            raise ValueError("INVALID_POSITION_METADATA")
        if held and not (self.long and self.short):
            if self.side != (1 if self.long else -1):
                raise ValueError("INVALID_POSITION_SIDE")
        if self.long and self.short and self.lock_price <= 0:
            raise ValueError("INVALID_LOCK_PRICE")
        if len(self.history) > 51:
            raise ValueError("HISTORY_LIMIT")
        for i, bar in enumerate(self.history):
            check_bar(self.contract, self.history[i - 1] if i else None, bar)


def check_bar(contract, previous, bar):
    if bar.contract != contract:
        raise ValueError("CONTRACT_BOUNDARY")
    if bar.start is None or bar.end - bar.start != timedelta(minutes=15):
        raise ValueError("COMPLETED_15M_REQUIRED")
    if previous and (bar.end <= previous.end or bar.start < previous.end):
        raise ValueError("BAR_ORDER")


def features(history, bar):
    """All background windows exclude current bar; shared anchor excludes previous."""
    closes = [b.close for b in history]
    f, g = sum(closes[-20:]) / D(20), sum(closes[-50:]) / D(50)
    path = sum(abs(b - a) for a, b in zip(closes[-21:-1], closes[-20:]))
    er = abs(closes[-1] - closes[-21]) / path if path else ZERO
    a = sum(
        max(
            history[i].high - history[i].low,
            abs(history[i].high - history[i - 1].close),
            abs(history[i].low - history[i - 1].close),
        )
        for i in range(len(history) - 14, len(history))
    ) / D(14)
    trend = (1 if f > g else -1 if f < g else 0) if er >= D(".30") else 0
    anchor = history[-21:-1]
    upper = max(b.high for b in anchor) + D(".25") * a
    lower = min(b.low for b in anchor) - D(".25") * a
    prev = history[-1]
    body, width = abs(bar.close - bar.open), bar.high - bar.low
    bull = bar.close > bar.open and (
        (
            min(bar.open, bar.close) - bar.low >= 2 * body
            and bar.close >= bar.low + width * D(2) / D(3)
        )
        or (
            prev.close < prev.open and bar.open <= prev.close and bar.close >= prev.open
        )
    )
    bear = bar.close < bar.open and (
        (
            bar.high - max(bar.open, bar.close) >= 2 * body
            and bar.close <= bar.low + width / D(3)
        )
        or (
            prev.close > prev.open and bar.open >= prev.close and bar.close <= prev.open
        )
    )
    direction = 1 if bar.close > bar.open else -1 if bar.close < bar.open else 0
    environment = (
        "ZERO_VOLATILITY"
        if not a
        else "S"
        if width >= 3 * a
        else "M"
        if trend and direction == -trend and body >= D("1.5") * a
        else "TREND"
        if trend
        else "L"
    )
    long = trend == 1 and (
        min(prev.close, bar.close) > upper
        or (bull and abs(bar.low - f) <= D(".5") * a and bar.close > f)
    )
    short = trend == -1 and (
        max(prev.close, bar.close) < lower
        or (bear and abs(bar.high - f) <= D(".5") * a and bar.close < f)
    )
    permitted = environment == "TREND"
    return dict(
        environment=environment,
        trend=trend,
        a=a,
        fast=f,
        slow=g,
        er=er,
        upper=upper,
        lower=lower,
        bull=bull,
        bear=bear,
        long=bool(long and permitted),
        short=bool(short and permitted),
    )


def policy(state, bar, f):
    """Fixed priority and unit suggested legs; no account state or execution."""
    held = bool(state.long or state.short)
    locked = bool(state.long and state.short)
    age = state.age + 1 if held else 0
    lock_age = state.lock_age + 1 if locked else 0
    best = (
        (max(state.best, bar.close) if state.side == 1 else min(state.best, bar.close))
        if held
        else ZERO
    )
    s = replace(
        state,
        age=age,
        lock_age=lock_age,
        best=best,
        cooldown=max(0, state.cooldown - 1),
    )
    kind, reason = None, "HOLD" if held else "NO_PERMISSION"
    if held:
        gain = D(s.side) * (bar.close - s.entry)
        retreat = D(s.side) * (s.best - bar.close)
        best_gain = D(s.side) * (s.best - s.entry)
        opposite = f["short"] if s.side == 1 else f["long"]
        clear = (
            "EXTREME"
            if f["environment"] == "S"
            else "OPPOSITE_PERMISSION"
            if opposite
            else "HARD_CLOSE_STOP"
            if gain <= -3 * s.risk
            else "MAX_HOLD"
            if age >= 64
            else "LOCK_TIMEOUT"
            if locked and lock_age >= 8
            else "TARGET"
            if not locked and gain >= 3 * s.risk
            else "TRAIL"
            if not locked and best_gain >= s.risk and retreat >= 2 * s.risk
            else None
        )
        if clear:
            kind, reason = "CLEAR", clear
        elif locked:
            original = f["long"] if s.side == 1 else f["short"]
            if original and D(s.side) * (bar.close - s.lock_price) >= D(".25") * s.risk:
                kind, reason = (
                    "UNLOCK_LONG" if s.side == 1 else "UNLOCK_SHORT",
                    "RESTORE_PERMISSION",
                )
        elif (
            (f["bear"] if s.side == 1 else f["bull"])
            or f["environment"] == "M"
            or gain <= -D("1.5") * s.risk
        ):
            kind, reason = "LOCK", "ADVERSE_PROTECTION"
    elif state.cooldown:
        reason = "COOLDOWN"
    elif f["long"] and f["short"]:
        reason = "CONFLICT"
    elif f["long"] or f["short"]:
        side = 1 if f["long"] else -1
        kind = ("REENTER_" if s.last_side == side else "ENTER_") + (
            "LONG" if side == 1 else "SHORT"
        )
        reason = "TREND_PERMISSION"
        s = replace(
            s,
            side=side,
            entry=bar.close,
            risk=f["a"],
            best=bar.close,
            long=D(1) if side == 1 else ZERO,
            short=D(1) if side == -1 else ZERO,
        )
        return s, kind, reason
    if kind:
        quantity = s.long + s.short if kind == "CLEAR" else D(1)
        p = apply_action(Position(s.contract, s.long, s.short), Action(kind, quantity))
        if kind == "CLEAR":
            s = State(s.contract, s.history, cooldown=2, last_side=s.side)
        else:
            s = replace(
                s,
                long=p.long,
                short=p.short,
                lock_price=bar.close if kind == "LOCK" else ZERO,
                lock_age=0,
            )
    return s, kind, reason


def step(state: State, bar: Bar, *, observe_only=False):
    """Decision known at bar.end, execution must be strictly later. No intrabar claims."""
    check_bar(state.contract, state.history[-1] if state.history else None, bar)
    if observe_only and (state.long or state.short):
        raise ValueError("OBSERVE_ONLY_REQUIRES_FLAT")
    if (state.long or state.short) and len(state.history) < 50:
        raise ValueError("HELD_HISTORY_INSUFFICIENT")
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        if len(state.history) < 50:
            f, kind, reason = {}, None, "WARMUP"
            s = state
        else:
            f = features(state.history, bar)
            if observe_only:
                s, kind, reason = state, None, "PREFIX_OBSERVATION"
            else:
                s, kind, reason = policy(state, bar, f)
        s = replace(s, history=(state.history + (bar,))[-51:])
        frame = dict(
            version=VERSION,
            contract=bar.contract,
            known_at=bar.end.isoformat(),
            effective_after=bar.end.isoformat(),
            action=kind,
            reason=reason,
            reference_close=str(bar.close),
            long=str(s.long),
            short=str(s.short),
            features={k: str(v) if isinstance(v, Decimal) else v for k, v in f.items()},
            fill=None,
            performance=None,
            executable=False,
            original_formula=False,
        )
        return s, frame


def batch(state, bars, *, observe_only=False):
    frames = []
    for bar in bars:
        state, frame = step(state, bar, observe_only=observe_only)
        frames.append(frame)
    return state, frames


def snapshot(state):
    return dict(
        version=VERSION,
        contract=state.contract,
        history=[
            [
                b.start.isoformat(),
                b.end.isoformat(),
                str(b.open),
                str(b.high),
                str(b.low),
                str(b.close),
            ]
            for b in state.history
        ],
        **{
            k: str(getattr(state, k))
            for k in ("long", "short", "entry", "risk", "best", "lock_price")
        },
        **{
            k: getattr(state, k)
            for k in ("side", "age", "lock_age", "cooldown", "last_side")
        },
    )


def restore(raw):
    data = dict(raw)
    if data.pop("version") != VERSION:
        raise ValueError("CHECKPOINT_VERSION")
    data["history"] = tuple(
        Bar(
            data["contract"],
            datetime.fromisoformat(r[1]),
            *map(D, r[2:]),
            start=datetime.fromisoformat(r[0]),
        )
        for r in data["history"]
    )
    for k in ("long", "short", "entry", "risk", "best", "lock_price"):
        data[k] = D(data[k])
    return State(**data)

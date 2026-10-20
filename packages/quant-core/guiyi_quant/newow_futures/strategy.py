"""Deterministic bidirectional strategy intents; fills and quantities live elsewhere."""
from __future__ import annotations

from dataclasses import replace
from decimal import (Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
                     ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext)
from typing import Mapping

from .contracts import Decision, Feature, LADDERS, Position, Profile, Variant

D = Decimal
_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                           capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])
_OSC = {Variant.OSCILLATION, Variant.TEST1, Variant.TEST2, Variant.TEST3, Variant.TEST4}


def _round(value: Decimal, tick: Decimal, *, up: bool) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick


def _known(feature: Feature | None, base: Feature, frequency: str) -> Feature | None:
    if (feature is None or feature.bar.frequency != frequency or feature.bar.owner != base.bar.owner
            or feature.bar.product != base.bar.product
            or feature.bar.bar_end >= base.bar.confirmed_at
            or feature.bar.confirmed_at >= base.bar.confirmed_at):
        return None
    return feature


def _available(feature: Feature | None) -> bool:
    return feature is not None and feature.regime is not None and feature.atr is not None and feature.atr > 0


def _osc_side(f: Feature) -> int:
    if f.regime != 0 or f.upper is None or f.lower is None or f.atr is None:
        return 0
    b = f.bar
    if f.upper - f.lower < 2 * f.atr or not f.lower < b.close < f.upper:
        return 0
    if b.low <= f.lower and b.close > b.open:
        return 1
    if b.high >= f.upper and b.close < b.open:
        return -1
    return 0


def _entry(profile: Profile, base: Feature, higher: Mapping[str, Feature | None], tick: Decimal) -> Decision:
    side = 0
    branch = ""
    variant = profile.variant
    b = base.bar
    if variant == Variant.MAIN_RISE:
        if any(x is None for x in (base.ma35, base.ma45, base.ma45_prev3, base.high11, base.low11)):
            return Decision("WAIT", 0, "INPUT_UNAVAILABLE", None)
        for direction in (1, -1):
            if (direction * (base.ma35 - base.ma45) >= base.atr / 4
                    and direction * (base.ma45 - base.ma45_prev3) > 0
                    and direction * (b.close - (base.high11 if direction == 1 else base.low11)) > 0):
                side, branch = direction, "main_rise"
    elif variant == Variant.TREND or (variant == Variant.DUAL and base.regime != 0):
        if base.regime == 1 and base.high3 is not None and b.close > base.high3:
            side = 1
        elif base.regime == -1 and base.low3 is not None and b.close < base.low3:
            side = -1
        branch = "trend"
    elif variant in _OSC or variant == Variant.DUAL:
        side, branch = _osc_side(base), "oscillation"
        if variant == Variant.TEST3:
            ladder = LADDERS[profile.frequency]
            if not ladder:
                return Decision("WAIT", 0, "NOT_APPLICABLE", None)
            next_f = _known(higher.get(ladder[0]), base, ladder[0])
            if not _available(next_f):
                return Decision("WAIT", 0, "INPUT_UNAVAILABLE", None)
            if next_f.regime != side:
                side = 0
    if not side:
        return Decision("WAIT", 0, "NO_ENTRY", None)
    distance = base.atr * (D("1.5") if variant == Variant.TEST1 else 2)
    stop = _round(b.close - side * distance, tick, up=side == -1)
    if stop <= 0 or (b.close - stop) * side <= 0:
        return Decision("WAIT", 0, "INVALID_PROTECTIVE_PRICE", None)
    target = (base.upper if side == 1 else base.lower) if branch == "oscillation" else None
    pos = Position(side, b.close, stop, stop, abs(b.close - stop), b.confirmed_at, b.confirmed_at,
                   profile.frequency, branch, target, b.close)
    return Decision("ENTER", side, "ENTRY_" + branch.upper(), pos)


def _protect(p: Position, holding: Feature, mark: Decimal, tick: Decimal, cost: Decimal,
             *, reset: bool = False) -> Position:
    earned = p.earned_r or p.side * (mark - p.entry) >= p.r
    favorable = mark if reset or p.favorable_close is None else p.favorable_close
    if not reset and (p.last_holding_bar is None or holding.bar.bar_end > p.last_holding_bar):
        favorable = max(favorable, holding.bar.close) if p.side == 1 else min(favorable, holding.bar.close)
    stop = p.stop
    if earned:
        # A fee-covering stop rounds toward profit; a trailing stop rounds outward.
        cover = _round(p.entry + p.side * cost, tick, up=p.side == 1)
        trail = _round(favorable - p.side * 3 * holding.atr, tick, up=p.side == -1)
        stop = max(stop, cover, trail) if p.side == 1 else min(stop, cover, trail)
    return replace(p, stop=stop, favorable_close=favorable, earned_r=earned)


def _evaluate(profile: Profile, base: Feature, higher: Mapping[str, Feature | None],
             position: Position | None, *, tick: Decimal,
             close_cost_per_unit: Decimal = D(0)) -> Decision:
    """Evaluate one completed base Bar; caller resolves session/account gates and fills.

    WAIT carries state updates. ADD/REDUCE do not pretend to have filled: the caller
    updates adds/reduced only after applying an actual or reference fill.
    """
    if (type(tick) is not Decimal or not tick.is_finite() or tick <= 0
            or type(close_cost_per_unit) is not Decimal or not close_cost_per_unit.is_finite()
            or close_cost_per_unit < 0):
        raise ValueError("FUTURES_STRATEGY_PRICE_INVALID")
    if base.bar.frequency != profile.frequency:
        raise ValueError("FUTURES_STRATEGY_FREQUENCY_MISMATCH")
    if position is None and profile.variant == Variant.TEST3 and not LADDERS[profile.frequency]:
        return Decision("WAIT", 0, "NOT_APPLICABLE", None)
    if not _available(base):
        return Decision("WAIT", position.side if position else 0, "INPUT_UNAVAILABLE", position)
    if position is None:
        if not base.bar.observation_eligible:
            return Decision("WAIT", 0, "OBSERVATION_INELIGIBLE", None)
        return _entry(profile, base, higher, tick)
    p = position
    if p.side not in (-1, 1) or p.r <= 0:
        raise ValueError("FUTURES_STRATEGY_POSITION_INVALID")
    holding = base if p.holding_frequency == profile.frequency else _known(higher.get(p.holding_frequency), base, p.holding_frequency)
    if not _available(holding):
        return Decision("WAIT", p.side, "INPUT_UNAVAILABLE", p)
    daily = base if profile.frequency == "1d" else _known(higher.get("1d"), base, "1d")
    p = _protect(p, holding, base.bar.close, tick, close_cost_per_unit)
    overnight = (profile.frequency in ("1d", "1w") or
                 (p.holding_frequency in ("60m", "1d", "1w") and p.earned_r
                  and _available(daily) and daily.regime != -p.side))
    p = replace(p, overnight_eligible=overnight)
    new_holding = holding.bar.bar_end > p.entry_at and (
        p.last_holding_bar is None or holding.bar.bar_end > p.last_holding_bar)
    if new_holding:
        line = holding.slow if p.upgrades or p.branch == "trend" else (
            holding.ma45 if p.branch == "main_rise" else None)
        if (p.upgrades or p.branch in ("trend", "main_rise")) and line is None:
            return Decision("WAIT", p.side, "INPUT_UNAVAILABLE", p)
        invalid = p.invalid_closes + 1 if line is not None and p.side * (holding.bar.close - line) < 0 else 0
        p = replace(p, invalid_closes=invalid, last_holding_bar=holding.bar.bar_end)
        if invalid >= 2:
            return Decision("CLOSE", p.side, "HOLDING_TREND_EXIT", p)
    # Upgrade is deliberately one ladder step, with a fresh higher-period snapshot.
    ladder = LADDERS[profile.frequency]
    next_index = ladder.index(p.holding_frequency) + 1 if p.holding_frequency in ladder else 0
    next_f = _known(higher.get(ladder[next_index]), base, ladder[next_index]) if next_index < len(ladder) else None
    upgraded = False
    boundary_broken = (p.branch != "oscillation" or
                       (p.entry_target is not None and p.side * (base.bar.close - p.entry_target) > 0))
    if (p.earned_r and boundary_broken and _available(next_f) and next_f.regime == p.side
            and next_f.bar.bar_end > p.stage_at):
        p = replace(p, holding_frequency=next_f.bar.frequency, stage_at=base.bar.confirmed_at,
                    upgrades=p.upgrades + 1, invalid_closes=0, last_holding_bar=next_f.bar.bar_end)
        p = _protect(p, next_f, base.bar.close, tick, close_cost_per_unit, reset=True)
        upgraded = True
        overnight = (profile.frequency in ("1d", "1w") or
                     (p.holding_frequency in ("60m", "1d", "1w") and p.earned_r
                      and _available(daily) and daily.regime != -p.side))
        p = replace(p, overnight_eligible=overnight)
    if not p.upgrades and p.branch == "oscillation":
        target = p.entry_target if profile.variant == Variant.TEST2 else (base.upper if p.side == 1 else base.lower)
        if target is None:
            return Decision("WAIT", p.side, "INPUT_UNAVAILABLE", p)
        if profile.variant == Variant.TEST4:
            if p.confirm_reference is not None:
                if base.bar.bar_end > p.confirm_at and p.side * (base.bar.close - p.confirm_reference) < 0:
                    return Decision("CLOSE", p.side, "OSC_CONFIRM_REVERSAL", p)
                if p.side * (base.bar.close - p.confirm_reference) > 0:
                    p = replace(p, confirm_reference=base.bar.close, confirm_at=base.bar.bar_end)
            elif p.side * (base.bar.close - target) >= 0:
                p = replace(p, confirm_reference=base.bar.close, confirm_at=base.bar.bar_end)
        elif p.side * (base.bar.close - target) >= 0:
            return Decision("CLOSE", p.side, "OSC_TARGET", p)
    # The entry-period crossing trims layers after an upgrade; ordinary fluctuation
    # on the wrong side without a new crossing does not repeatedly trim the core.
    crossed = (base.slow is not None and base.previous_slow is not None and base.previous_close is not None
               and p.side * (base.bar.close - base.slow) < 0
               and p.side * (base.previous_close - base.previous_slow) >= 0)
    if p.upgrades and crossed:
        return Decision("REDUCE", p.side, "BASE_TREND_REDUCTION", p, upgraded)
    profit = p.side * (base.bar.close - p.entry)
    if upgraded and not p.reduced and p.adds < 2 and profit >= (p.adds + 1) * p.r and profit > 0:
        return Decision("ADD", p.side, "UPGRADE_ADD", p, True)
    return Decision("WAIT", p.side, "HOLD", p, upgraded)


def evaluate(profile: Profile, base: Feature, higher: Mapping[str, Feature | None],
             position: Position | None, *, tick: Decimal,
             close_cost_per_unit: Decimal = D(0)) -> Decision:
    """Return a deterministic intent under the frozen precision, rounding, and traps.

    WAIT carries state updates. The caller resolves session/account gates and fills,
    and updates adds/reduced only after an actual or reference fill.
    """
    with localcontext(_DECIMAL_CONTEXT):
        return _evaluate(profile, base, higher, position, tick=tick,
                         close_cost_per_unit=close_cost_per_unit)

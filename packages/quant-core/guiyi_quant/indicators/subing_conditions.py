"""Research-only condition explanations. No position, action, order or fill."""
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime

VERSION = 'subing_joint_conditions_window5_v3'


def _positive(value):
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def exit_facts(*, close, previous_low, ema21, high_death):
    """Strict level comparisons; equality is not a break, repeats are allowed."""
    return dict(
        previous_low=previous_low if _positive(previous_low) else None,
        below_previous_low=(close < previous_low) if _positive(close) and _positive(previous_low) else None,
        below_ema=(close < ema21) if _positive(close) and _positive(ema21) else None,
        high_death=high_death if type(high_death) is bool else None,
    )


def entry_conditions(*, daily_direction, minute_angle, above_ema, golden_window, volume_effective):
    """Price, slope and volume gates refer to this completed bar; D1 is strict-before upstream.

    UNKNOWN is retained even with another failed gate, never silently accepted.
    This is an entry setup, not permission to open: position/risk/cooldown omitted.
    """
    checks = dict(
        daily_allows_long=(daily_direction != 'DOWN') if daily_direction in ('UP', 'NEUTRAL', 'DOWN') else None,
        minute_positive=(minute_angle > 0) if isinstance(minute_angle, Decimal) and minute_angle.is_finite() else None,
        above_ema=above_ema if type(above_ema) is bool else None,
        golden_window=golden_window if type(golden_window) is bool else None,
        volume_expanded=volume_effective if type(volume_effective) is bool else None,
    )
    missing = [key for key, value in checks.items() if value is None]
    failed = [key for key, value in checks.items() if value is False]
    return dict(checks=checks, missing=missing, failed=failed,
                met=None if missing else not failed,
                status='UNKNOWN' if missing else 'NOT_MET' if failed else 'MET')


@dataclass(frozen=True)
class EntryWindow:
    contract: str
    last_end: datetime | None = None
    source_end: datetime | None = None
    age: int | None = None


def observe_entry(state, *, contract, bar_end, near_zero_golden, daily_direction,
                  minute_angle, above_ema, volume_effective, max_age=5):
    """One research opportunity per near-axis cross; default ages 0..5 inclusive.

    max_age 4/6 is for explicitly identified research profiles only.

    Caller supplies complete, validated consecutive physical 30m bars. Session
    breaks do not count as bars. No unapproved early price/volume/death-cross gate.
    """
    if type(max_age) is not int or max_age not in (4, 5, 6):
        raise ValueError('ENTRY_RESEARCH_WINDOW_INVALID')
    if not contract or state.contract != contract:
        raise ValueError('ENTRY_IDENTITY_CHANGED')
    if bar_end.tzinfo is None or bar_end.utcoffset() is None or (state.last_end is not None and bar_end <= state.last_end):
        raise ValueError('ENTRY_TIME_INVALID')
    source, age = state.source_end, state.age
    if source is not None:
        age += 1
    replaced = False
    if type(near_zero_golden) is not bool:
        source, age = None, None
        valid = None
    else:
        if near_zero_golden:
            replaced = source is not None and age <= max_age
            source, age = bar_end, 0
        if source is not None and age > max_age:
            source, age = None, None
        valid = source is not None
    result = entry_conditions(daily_direction=daily_direction, minute_angle=minute_angle,
        above_ema=above_ema, golden_window=valid, volume_effective=volume_effective)
    consumed = result['met'] is True
    expired = valid is True and age == max_age and not consumed
    result['window'] = dict(source_end=source, age=age, remaining=max_age-age if age is not None else None,
        consumed=consumed, replaced=replaced, expired_after_bar=expired,
        reason='MACD_UNKNOWN' if valid is None else None)
    if consumed or expired:
        source, age = None, None
    return EntryWindow(contract, bar_end, source, age), result

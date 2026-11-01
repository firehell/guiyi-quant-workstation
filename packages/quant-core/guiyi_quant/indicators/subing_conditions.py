"""Research-only condition explanations. No position, action, order or fill."""
from decimal import Decimal

VERSION = 'subing_joint_conditions_v2'


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


def entry_conditions(*, daily_direction, minute_angle, above_ema, near_zero_golden, volume_effective):
    """All minute gates refer to this completed bar; D1 is strict-before upstream.

    UNKNOWN is retained even with another failed gate, never silently accepted.
    This is an entry setup, not permission to open: position/risk/cooldown omitted.
    """
    checks = dict(
        daily_allows_long=(daily_direction != 'DOWN') if daily_direction in ('UP', 'NEUTRAL', 'DOWN') else None,
        minute_positive=(minute_angle > 0) if isinstance(minute_angle, Decimal) and minute_angle.is_finite() else None,
        above_ema=above_ema if type(above_ema) is bool else None,
        new_near_zero_golden=near_zero_golden if type(near_zero_golden) is bool else None,
        volume_expanded=volume_effective if type(volume_effective) is bool else None,
    )
    missing = [key for key, value in checks.items() if value is None]
    failed = [key for key, value in checks.items() if value is False]
    return dict(checks=checks, missing=missing, failed=failed,
                met=None if missing else not failed,
                status='UNKNOWN' if missing else 'NOT_MET' if failed else 'MET')

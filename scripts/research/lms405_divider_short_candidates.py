"""Source-scoped short probes in a published two-sided divider."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import signals


@dataclass(frozen=True)
class DividerShortPlan:
    contract: str
    revision: str
    known_at: datetime
    start: datetime
    through: datetime
    lower: Decimal
    upper: Decimal
    mode: str


def divider_short_events(series, plan, cutoff):
    """Issue the first eligible research probe per plan using completed minutes."""
    cut = min(cutoff, plan.through)
    if not series[1] or cut <= plan.start:
        return []
    if (plan.contract != series[1][0].contract or not plan.known_at < plan.start < plan.through
            or not plan.lower < plan.upper):
        raise ValueError("DIVIDER_SHORT_SCOPE_INVALID")
    matches = []
    if plan.mode == "INSIDE_KEYBAR":
        for signal in signals(series, 1, 1, side="SHORT", start=plan.start, cut=cut):
            if plan.lower <= signal["close"] <= plan.upper:
                matches.append((signal["confirmed_at"], signal["shape_end"] - ONE, signal["close"], signal))
    elif plan.mode == "FIRST_FAR_CLOSE":
        for previous, bar in zip(series[1], series[1][1:]):
            if (plan.start <= previous.start and previous.end == bar.start and bar.end + US < cut
                    and bar.close < plan.lower <= previous.close <= plan.upper):
                matches.append((bar.end, previous.start, bar.close, None))
                break
    else:
        raise ValueError("DIVIDER_SHORT_MODE_UNKNOWN")
    for confirmed, setup_start, close, signal in matches[:1]:
        ready = confirmed + 9 * US
        if ready < cut:
            return [dict(at=ready, known_at=confirmed + US, setup_start=setup_start, close=close,
                         signal=signal, plan=plan)]
    return []

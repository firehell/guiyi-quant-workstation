"""Futures display policy over the unchanged mirror primitive; never a trade signal."""
from dataclasses import dataclass

from .models import NewowDailyBar
from .subplots import calculate_zhaoyao_mirror, mirror_peak_structure

CAUTION_DISPLAY_VERSION = "guiyi_caution_completed_anchor_v1"
DETAIL_MAX_AGE = 10
HOME_MAX_AGE = 1


@dataclass(frozen=True, slots=True)
class CautionDisplayPoint:
    event_index: int
    peak_index: int
    first_visible_index: int
    confirmed_index: int | None
    age_bars: int


def caution_display_points(bars: tuple[NewowDailyBar, ...]) -> tuple[CautionDisplayPoint, ...]:
    """Rebuild first eligible completed observations in O(n), no persisted clock/latch."""
    if any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:])):
        raise ValueError('NEWOW_CAUTION_DISPLAY_NON_MONOTONIC')
    mirror = calculate_zhaoyao_mirror(bars)  # validates owner and chronological inputs
    if mirror is None:
        return ()
    _, confirmed, trend, candidate, first_seen, known = mirror_peak_structure(bars)
    points = []
    for peak, confirmation in confirmed:
        if mirror.caution[peak] != 50:
            continue  # nearby peaks absorbed by the original 10-bar window
        first = known[peak]
        anchor = first if first is not None else peak
        if not bars[anchor].observation_eligible:
            continue
        points.append(CautionDisplayPoint(anchor, peak, first if first is not None else max(19, confirmation),
                                          confirmation, len(bars)-1-anchor))
    if trend >= 0 and first_seen is not None and len(bars)-1-first_seen <= DETAIL_MAX_AGE:
        points.append(CautionDisplayPoint(first_seen, candidate, first_seen, None, len(bars)-1-first_seen))
    return tuple(points)

"""Completed-bar snapshots and frozen setup evidence for new_subing_v1."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from guiyi_quant.new_subing_common import (
    Snapshot,
    build_snapshots as _build_snapshots,
    divergence_events as _divergence_events,
)

from . import Profile, StrategyBar

D = Decimal


def build_snapshots(bars: Sequence[StrategyBar], profile: Profile | None = None) -> list[Snapshot]:
    """Delegate shared computation with this strategy's independent defaults."""
    return _build_snapshots(bars, profile or Profile())


def direction(s: Snapshot) -> int:
    if s.ma is None or not s.slope:
        return 0
    return s.slope if (s.bar.close - s.ma) * s.slope > 0 else 0


def setup_evidence(snapshots: Sequence[Snapshot], index: int, side: int,
                   profile: Profile | None = None) -> dict[str, object] | None:
    p = profile or Profile()
    s = snapshots[index]
    if side not in (-1, 1) or direction(s) != side or s.atr is None or s.atr <= 0 or s.ma is None:
        return None
    if s.chop or abs(s.bar.close - s.ma) / s.atr > p.max_ma_distance_atr:
        return None
    recent = [x for x in snapshots[max(0, index-p.trigger_window+1):index+1]
              if x.bar.physical_contract == s.bar.physical_contract]
    macd_triggers = [x for x in recent if x.macd_cross == side and x.atr and x.atr > 0 and
                     x.dif is not None and x.dea is not None and
                     max(abs(x.dif), abs(x.dea)) / x.atr <= p.macd_zero_axis_atr]
    previous_hist = snapshots[index-1].histogram if index >= 1 else None
    hist_ok = (s.histogram is not None and previous_hist is not None and
               s.histogram * side > 0 and previous_hist * side > 0 and
               abs(s.histogram) > abs(previous_hist))
    ma_triggers = [x for x in recent if x.ma_cross == side]
    boll_triggers = [x for x in recent if x.boll_cross == side]
    breakout_triggers = [x for x in recent if x.breakout == side and x.breakout_level is not None and
                         (s.bar.close - x.breakout_level) * side > 0]
    votes = {'trend': True, 'macd': bool(macd_triggers and hist_ok),
             'boll': bool(boll_triggers and (s.bar.close - s.ma) * side > 0),
             'volume': any(x.volume_spike for x in recent), 'breakout': bool(breakout_triggers)}
    if sum(votes.values()) < p.votes_required:
        return None
    if breakout_triggers:
        trigger, chosen = 'BREAKOUT', breakout_triggers[-1]
        level = chosen.breakout_level
    elif ma_triggers:
        trigger, chosen = 'MA_CROSS', ma_triggers[-1]
        level = chosen.ma
    elif macd_triggers:
        trigger, chosen = 'MACD_CROSS', macd_triggers[-1]
        level = chosen.ma
    else:
        return None
    return {'trigger': trigger, 'trigger_at': chosen.bar.bar_end.isoformat(),
            'trigger_source': chosen.bar.source_identity, 'level': level,
            'votes': votes, 'all_triggers': [k for k, v in
                                           (('BREAKOUT', breakout_triggers),
                                            ('MA_CROSS', ma_triggers), ('MACD_CROSS', macd_triggers)) if v]}


def divergence_events(snapshots: Sequence[Snapshot], side: int,
                      profile: Profile | None = None) -> list[tuple[int, int] | None]:
    return _divergence_events(snapshots, side, profile or Profile())


def confirmed_divergence(snapshots: Sequence[Snapshot], index: int, side: int) -> tuple[int, int] | None:
    return divergence_events(snapshots[:index+1], side)[-1] if index >= 0 else None

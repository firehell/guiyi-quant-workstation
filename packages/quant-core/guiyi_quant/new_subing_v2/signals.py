"""Prefix-only shared indicators with V2 source-stage setup interpretation."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence, cast

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
    if s.ma is None:
        return 0
    return (s.bar.close > s.ma) - (s.bar.close < s.ma)


def setup_evidence(snapshots: Sequence[Snapshot], index: int, side: int,
                   profile: Profile | None = None) -> dict[str, object] | None:
    p = profile or Profile()
    s = snapshots[index]
    if side not in (-1, 1) or direction(s) != side or s.atr is None or s.atr <= 0 or s.ma is None:
        return None
    recent = [x for x in snapshots[max(0, index-p.trigger_window+1):index+1]
              if x.bar.physical_contract == s.bar.physical_contract]
    macd_triggers = []
    for x in recent:
        j = snapshots.index(x)
        if j == 0 or x.dif is None or snapshots[j-1].dif is None:
            continue
        if (cast(D, snapshots[j-1].dif) * side <= 0 < x.dif * side and
            any(y.macd_cross == side for y in recent)):
            macd_triggers.append(x)
    previous_hist = snapshots[index-1].histogram if index >= 1 else None
    hist_ok = (s.histogram is not None and previous_hist is not None and
               s.histogram * side > 0 and previous_hist * side > 0 and
               abs(s.histogram) > abs(previous_hist))
    ma_triggers = [x for x in recent if x.ma_cross == side]

    def volume_above_at(j: int) -> bool:
        if j < p.volume_window:
            return False
        candidate = snapshots[j]
        prior = snapshots[j-p.volume_window:j]
        if any(x.bar.physical_contract != candidate.bar.physical_contract for x in prior):
            return False
        mean = sum((x.bar.volume for x in prior), D('0')) / p.volume_window
        return candidate.bar.volume > mean and candidate.bar.volume > snapshots[j-1].bar.volume

    def boll_valid_at(j: int) -> bool:
        candidate = snapshots[j]
        if j < max(3, p.volume_window) or candidate.boll_cross != side or \
           candidate.ma is None or (candidate.bar.close - candidate.ma) * side <= 0 or \
           not volume_above_at(j):
            return False
        before = snapshots[j-3:j]
        if any(x.bar.physical_contract != candidate.bar.physical_contract or
               x.boll_upper is None or x.boll_lower is None for x in before):
            return False
        widths = [cast(D, x.boll_upper) - cast(D, x.boll_lower) for x in before]
        if not widths[0] >= widths[1] >= widths[2]:
            return False
        ma_earlier, ma_prior = snapshots[j-2].ma, snapshots[j-1].ma
        if ma_earlier is None or ma_prior is None:
            return False
        return abs(candidate.ma - ma_prior) <= abs(ma_prior - ma_earlier)

    recent_indices = range(max(0, index-p.trigger_window+1), index+1)
    volume_above = any(snapshots[j].bar.physical_contract == s.bar.physical_contract and
                       volume_above_at(j) for j in recent_indices)
    boll_triggers = [snapshots[j] for j in recent_indices
                     if snapshots[j].bar.physical_contract == s.bar.physical_contract and boll_valid_at(j)]
    breakout_triggers = [x for x in recent if x.breakout == side and x.breakout_level is not None and
                         (s.bar.close - x.breakout_level) * side > 0]
    votes = {'trend': direction(s) == side, 'macd': bool(macd_triggers and hist_ok),
             'boll': bool(boll_triggers and (s.bar.close - s.ma) * side > 0),
             'volume': volume_above,
             'breakout': bool(breakout_triggers and any(x.volume_spike for x in breakout_triggers))}
    if sum(votes.values()) < p.votes_required:
        return None
    if s.chop and not votes['breakout']:
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

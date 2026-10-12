"""Completed-bar snapshots and frozen setup evidence for new_subing_v1."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from guiyi_quant.indicators.atr import initial_atr_state, step_atr
from guiyi_quant.indicators.macd import initial_macd_state, step_macd

from . import Profile, StrategyBar

D = Decimal


@dataclass(frozen=True)
class Snapshot:
    bar: StrategyBar
    ma: Decimal | None
    boll_upper: Decimal | None
    boll_lower: Decimal | None
    atr: Decimal | None
    dif: Decimal | None
    dea: Decimal | None
    histogram: Decimal | None
    slope: int
    ma_cross: int
    macd_cross: int
    boll_cross: int
    breakout: int
    breakout_level: Decimal | None
    volume_spike: bool
    chop: bool


def _point(value: object) -> Decimal | None:
    if not getattr(value, 'ready') or not getattr(value, 'valid') or getattr(value, 'value') is None:
        return None
    return D(str(getattr(value, 'value')))


def build_snapshots(bars: Sequence[StrategyBar], profile: Profile | None = None) -> list[Snapshot]:
    """Each output depends only on its own physical-contract prefix."""
    p = profile or Profile()
    out: list[Snapshot] = []
    segment: list[StrategyBar] = []
    closes: list[Decimal] = []
    atr_state = initial_atr_state(p.atr_period, smoothing_policy='wilder_sma_seed', round_digits=p.macd_round_digits)
    macd_state = initial_macd_state(p.macd_fast, p.macd_slow, p.macd_signal,
                                    ema_seed_policy='sma_window',
                                    histogram_scale=p.macd_histogram_scale, round_digits=p.macd_round_digits)
    for bar in bars:
        if segment and bar.physical_contract != segment[-1].physical_contract:
            segment = []
            closes = []
            atr_state = initial_atr_state(p.atr_period, smoothing_policy='wilder_sma_seed', round_digits=p.macd_round_digits)
            macd_state = initial_macd_state(p.macd_fast, p.macd_slow, p.macd_signal,
                                            ema_seed_policy='sma_window',
                                            histogram_scale=p.macd_histogram_scale, round_digits=p.macd_round_digits)
        segment.append(bar)
        closes.append(bar.close)
        i = len(segment) - 1
        w = p.ma_window
        ma = sum(closes[-w:], D('0')) / w if len(closes) >= w else None
        prior_ma = sum(closes[-w-3:-3], D('0')) / w if len(closes) >= w + 3 else None
        slope = 0 if ma is None or prior_ma is None else (ma > prior_ma) - (ma < prior_ma)
        prev_ma = sum(closes[-w-1:-1], D('0')) / w if len(closes) >= w + 1 else None
        ma_cross = 0
        if ma is not None and prev_ma is not None:
            if closes[-2] <= prev_ma and bar.close > ma:
                ma_cross = 1
            elif closes[-2] >= prev_ma and bar.close < ma:
                ma_cross = -1
        upper = lower = None
        if ma is not None:
            variance = sum(((v - ma) ** 2 for v in closes[-w:]), D('0')) / w
            width = p.boll_sigma * variance.sqrt()
            upper, lower = ma + width, ma - width
        atr_state, atr_point = step_atr(atr_state, high=float(bar.high), low=float(bar.low),
                                        close=float(bar.close), bar_end=bar.bar_end.isoformat())
        atr = _point(atr_point)
        macd_state, macd_points = step_macd(macd_state, float(bar.close), bar_end=bar.bar_end.isoformat())
        dif, dea, hist = (_point(x) for x in macd_points)
        prev_dif = out[-1].dif if i else None
        prev_dea = out[-1].dea if i else None
        macd_cross = 0
        if dif is not None and dea is not None and prev_dif is not None and prev_dea is not None:
            if prev_dif <= prev_dea and dif > dea:
                macd_cross = 1
            elif prev_dif >= prev_dea and dif < dea:
                macd_cross = -1
        boll_cross = ma_cross
        breakout = 0
        breakout_level = None
        if i >= p.breakout_window:
            upper_level = max(b.high for b in segment[-p.breakout_window-1:-1])
            lower_level = min(b.low for b in segment[-p.breakout_window-1:-1])
            if bar.close > upper_level:
                breakout, breakout_level = 1, upper_level
            elif bar.close < lower_level:
                breakout, breakout_level = -1, lower_level
        volume_spike = False
        if i >= p.volume_window:
            mean = sum((b.volume for b in segment[-p.volume_window-1:-1]), D('0')) / p.volume_window
            volume_spike = mean > 0 and bar.volume >= mean * p.volume_multiple
        chop = False
        if len(segment) >= p.noise_window and len(out) >= p.noise_window - 1:
            signs: list[int] = []
            for previous in out[-p.noise_window+1:]:
                if previous.bar.physical_contract != bar.physical_contract or previous.ma is None:
                    continue
                signs.append((previous.bar.close > previous.ma) - (previous.bar.close < previous.ma))
            if ma is not None:
                signs.append((bar.close > ma) - (bar.close < ma))
            nonzero = [x for x in signs if x]
            chop = sum(a != b for a, b in zip(nonzero, nonzero[1:])) >= p.noise_switches
        out.append(Snapshot(bar, ma, upper, lower, atr, dif, dea, hist, slope,
                            ma_cross, macd_cross, boll_cross, breakout, breakout_level,
                            volume_spike, chop))
    return out


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
    """Linear prefix scan; pivot j first appears at j+right, never at j."""
    p = profile or Profile()
    pivots: list[int] = []
    result: list[tuple[int, int] | None] = []
    for index in range(len(snapshots)):
        centre_index = index - p.pivot_right
        if centre_index >= p.pivot_left:
            window = snapshots[centre_index-p.pivot_left:index+1]
            centre = snapshots[centre_index]
            if centre.dif is not None and all(x.bar.physical_contract == centre.bar.physical_contract for x in window):
                neighbors = [x for k, x in enumerate(window) if k != p.pivot_left]
                if side > 0 and centre.bar.high > max(x.bar.high for x in neighbors):
                    pivots.append(centre_index)
                elif side < 0 and centre.bar.low < min(x.bar.low for x in neighbors):
                    pivots.append(centre_index)
        pair = None
        if len(pivots) >= 2:
            a, b = pivots[-2:]
            x, y = snapshots[a], snapshots[b]
            if side > 0 and x.dif is not None and y.dif is not None and y.bar.high > x.bar.high and y.dif < x.dif:
                pair = (a, b)
            elif side < 0 and x.dif is not None and y.dif is not None and y.bar.low < x.bar.low and y.dif > x.dif:
                pair = (a, b)
        result.append(pair)
    return result


def confirmed_divergence(snapshots: Sequence[Snapshot], index: int, side: int) -> tuple[int, int] | None:
    return divergence_events(snapshots[:index+1], side)[-1] if index >= 0 else None

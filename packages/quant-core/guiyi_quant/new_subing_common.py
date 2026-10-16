"""Stable shared research calculations for the independent new SuBing versions.

Profiles, setup interpretation, execution and account state belong to each strategy.
This module has no strategy defaults. Shared DTOs retain their existing V1 import
identity; importing them does not import a strategy engine or choose a profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal, Mapping, Protocol, Sequence

from guiyi_quant.indicators.atr import initial_atr_state, step_atr
from guiyi_quant.indicators.macd import initial_macd_state, step_macd
from guiyi_quant.new_subing import ExecutionBar, StrategyBar

# Implementation contract, independent of either strategy's formula/profile identity.
COMPUTATION_VERSION = 'new_subing_common_v1'
D = Decimal


class SnapshotProfile(Protocol):
    """Only the frozen indicator parameters consumed by this calculation version."""

    @property
    def ma_window(self) -> int: ...

    @property
    def boll_sigma(self) -> Decimal: ...

    @property
    def atr_period(self) -> int: ...

    @property
    def macd_fast(self) -> int: ...

    @property
    def macd_slow(self) -> int: ...

    @property
    def macd_signal(self) -> int: ...

    @property
    def macd_histogram_scale(self) -> Literal[2]: ...

    @property
    def macd_round_digits(self) -> int: ...

    @property
    def breakout_window(self) -> int: ...

    @property
    def volume_window(self) -> int: ...

    @property
    def volume_multiple(self) -> Decimal: ...

    @property
    def noise_window(self) -> int: ...

    @property
    def noise_switches(self) -> int: ...

    @property
    def pivot_left(self) -> int: ...

    @property
    def pivot_right(self) -> int: ...


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


def build_snapshots(bars: Sequence[StrategyBar], profile: SnapshotProfile) -> list[Snapshot]:
    """Each output depends only on its own physical-contract prefix."""
    p = profile
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


def divergence_events(snapshots: Sequence[Snapshot], side: int,
                      profile: SnapshotProfile) -> list[tuple[int, int] | None]:
    """Linear prefix scan; pivot j first appears at j+right, never at j."""
    p = profile
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


def validate_inputs(bars_by_frequency: Mapping[str, Sequence[StrategyBar]],
                     execution_bars: Sequence[ExecutionBar], scenario: str,
                     since: date, through: date) -> None:
    if scenario not in ('baseline', 'double_commission', 'double_slippage'):
        raise ValueError('unsupported scenario')
    if type(since) is not date or type(through) is not date or since > through:
        raise ValueError('invalid requested window')
    if not isinstance(bars_by_frequency, Mapping) or not isinstance(execution_bars, Sequence):
        raise ValueError('invalid research inputs')
    if not {'1m', '5m', '15m', '1d'}.issubset(bars_by_frequency):
        raise ValueError('1m, 5m, 15m and 1d histories required')
    products: set[str] = set()
    for frequency, bars in bars_by_frequency.items():
        if frequency not in ('1m', '5m', '15m', '1d', '1w') or not isinstance(bars, Sequence):
            raise ValueError('invalid frequency history')
        keys: set[tuple[str, datetime]] = set()
        previous: tuple[datetime, str] | None = None
        confirmations: dict[str, datetime] = {}
        for bar in bars:
            if type(bar) is not StrategyBar or bar.frequency != frequency:
                raise ValueError('bar frequency mismatch')
            if re.fullmatch(r'[A-Za-z]{1,3}\d{3,4}(?:\.[A-Za-z]+)?', bar.physical_contract) is None:
                raise ValueError('physical monthly contract required')
            products.add(bar.product.upper())
            key = (bar.physical_contract, bar.bar_end)
            if key in keys or (previous and (bar.bar_end, bar.physical_contract) < previous):
                raise ValueError('duplicate or unordered history')
            keys.add(key)
            previous = (bar.bar_end, bar.physical_contract)
            if bar.physical_contract in confirmations and bar.confirmed_at < confirmations[bar.physical_contract]:
                raise ValueError('out-of-order confirmation within physical history')
            confirmations[bar.physical_contract] = bar.confirmed_at
    if len(products) > 1:
        raise ValueError('one product per research account')
    one_minute = {(b.physical_contract, b.bar_end): b for b in bars_by_frequency['1m']}
    previous_time: datetime | None = None
    previous_confirmed: datetime | None = None
    seen: set[datetime] = set()
    for execution in execution_bars:
        if type(execution) is not ExecutionBar or execution.bar.product.upper() not in products:
            raise ValueError('execution product mismatch')
        bar = execution.bar
        if one_minute.get((bar.physical_contract, bar.bar_end)) != bar:
            raise ValueError('execution bar differs from 1m history')
        if not bar.observation_eligible or not since <= bar.trading_day <= through:
            raise ValueError('execution must be eligible owner within requested window')
        if previous_time and bar.bar_end <= previous_time or bar.bar_end in seen:
            raise ValueError('execution bars must be strictly ordered')
        if previous_confirmed and bar.confirmed_at < previous_confirmed:
            raise ValueError('execution confirmation must be ordered')
        previous_time = bar.bar_end
        previous_confirmed = bar.confirmed_at
        seen.add(bar.bar_end)

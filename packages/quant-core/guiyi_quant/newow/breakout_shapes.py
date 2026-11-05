"""Public detail 3.4.49 geometry. Display facts only; no strategy decisions.

Display ATR uses TR[0]=H-L and prefix SMA, unlike position_kernel 1.1.1.
Output order is all two-bar events followed by all wick events, as in source.
"""
from dataclasses import dataclass
from .models import NewowDailyBar

FORMULA_VERSION = 'newow_breakout_shapes_detail3449_v1'
SOURCE_SHA256 = '685a44629ad938bcc427fbc790e4fa57b5ee7a9a6d0b327a15795c12590430bb'


@dataclass(frozen=True, slots=True)
class BreakoutShape:
    kind: str
    index: int
    occur: int
    side: str
    level: float
    buffer: float
    volume_ratio: float | None
    volume_ok: bool
    doubt: bool
    regime: str


def _mean(values):
    total = 0.0
    for value in values:
        total += value
    return total / len(values)


def compute_breakout_shapes(bars: tuple[NewowDailyBar, ...]) -> tuple[BreakoutShape, ...]:
    if len({(b.product, b.physical_contract, b.segment_id) for b in bars}) > 1:
        raise ValueError('NEWOW_BREAKOUT_MIXED_OWNER')
    n = len(bars)
    if n < 12:
        return ()
    high, low, close = ([float(getattr(b, key)) for b in bars] for key in ('high', 'low', 'close'))
    tr = [max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1])) if i else high[i]-low[i] for i in range(n)]
    atr = [_mean(tr[max(0, i-13):i+1]) for i in range(n)]
    upper = [max(high[max(0, i-10):i]) if i else high[0] for i in range(n)]
    lower = [min(low[max(0, i-10):i]) if i else low[0] for i in range(n)]
    buffer = [max(.0015 * low[i], min(.3 * atr[i], .02 * low[i])) for i in range(n)]
    ma = [_mean(close[i-19:i+1]) if i >= 19 else None for i in range(n)]
    regimes = ['unknown'] * n
    for i in range(25, n):
        if atr[i] > 0:
            drift = (ma[i] - ma[i-5]) / atr[i]
            regimes[i] = 'up' if drift >= .5 else 'down' if drift <= -.5 else 'osc'

    def event(kind, index, occur, side, doubt=False):
        prior = bars[max(0, occur-5):occur]
        average = _mean([b.volume for b in prior]) if prior else 0
        ratio = bars[occur].volume / average if average > 0 else None
        return BreakoutShape(kind, index, occur, side,
                             upper[occur] if side == 'up' else lower[occur],
                             buffer[occur], ratio,
                             bars[occur].volume >= 1.5 * average if average > 0 else True,
                             doubt, regimes[occur])

    result = []
    for i in range(10, n):
        up = close[i-1] <= upper[i-1]+buffer[i-1] and close[i] > upper[i]+buffer[i]
        down = close[i-1] >= lower[i-1]-buffer[i-1] and close[i] < lower[i]-buffer[i]
        if not (up or down):
            continue
        side = 'up' if up else 'down'
        kind = ('true_up' if close[i+1] > upper[i]+buffer[i] else 'false_up') if up and i+1 < n else ('true_down' if close[i+1] < lower[i]-buffer[i] else 'false_down') if i+1 < n else 'pending'
        result.append(event(kind, min(i+1, n-1), i, side))
    for i in range(10, n):
        if high[i] > upper[i]+buffer[i] and close[i] <= upper[i]+buffer[i]:
            result.append(event('fake_up_ib', i, i, 'up', upper[i] < close[i] <= upper[i]+buffer[i]))
        if low[i] < lower[i]-buffer[i] and close[i] >= lower[i]-buffer[i]:
            result.append(event('fake_dn_ib', i, i, 'down', lower[i]-buffer[i] <= close[i] < lower[i]))
    return tuple(result)

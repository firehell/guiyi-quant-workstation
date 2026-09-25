"""Page-parity WR20 / MA120 trend reversal display over one trusted owner segment."""

from __future__ import annotations

from dataclasses import dataclass

from .models import NewowDailyBar


TREND_REVERSAL_FORMULA_VERSION = "newow_trend_reversal_core_1_0_0_futures_segment_v1"


@dataclass(frozen=True, slots=True)
class TrendReversalResult:
    wr1: tuple[float, ...]
    wr2: tuple[float, ...]
    bias: tuple[float, ...]
    rebound: tuple[float, ...]
    adjust: tuple[float, ...]
    ma120: tuple[float, ...]
    hhv: tuple[float, ...]
    llv: tuple[float, ...]
    enough: bool
    bar_count: int
    formula_version: str = TREND_REVERSAL_FORMULA_VERSION


def calculate_trend_reversal(
    bars: tuple[NewowDailyBar, ...],
) -> TrendReversalResult | None:
    """Match the public 1.0.0 kernel; quality/owner segmentation happens upstream."""

    if not bars:
        return None
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    closes = [float(bar.close) for bar in bars]
    wr1: list[float] = []
    wr2: list[float] = []
    bias: list[float] = []
    rebound: list[float] = []
    adjust: list[float] = []
    ma120: list[float] = []
    hhv: list[float] = []
    llv: list[float] = []
    close_sum = 0.0
    for index, close in enumerate(closes):
        if index >= 120:
            close_sum -= closes[index - 120]
        close_sum += close
        average = close_sum / min(index + 1, 120)
        highest = max(highs[max(0, index - 19):index + 1])
        lowest = min(lows[max(0, index - 19):index + 1])
        denominator = highest - lowest
        position = 100 * (highest - close) / denominator if denominator > 0 else 50.0
        high_position = 100 * (highest - highs[index]) / denominator if denominator > 0 else 50.0
        deviation = (close / average - 1) * 100
        hhv.append(highest)
        llv.append(lowest)
        ma120.append(average)
        wr1.append(position)
        wr2.append(high_position)
        bias.append(deviation)
        rebound.append(deviation if position > 97 else 0.0)
        adjust.append(deviation if position < 3 else 0.0)
    return TrendReversalResult(
        tuple(wr1), tuple(wr2), tuple(bias), tuple(rebound), tuple(adjust),
        tuple(ma120), tuple(hhv), tuple(llv), len(bars) >= 120, len(bars),
    )

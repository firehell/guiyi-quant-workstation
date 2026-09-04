"""Pure Newow subplot primitives, including an explicitly repainting mirror."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import NewowDailyBar


MAIN_FORCE_CONTROL_FORMULA_VERSION = "newow_main_force_control_page_v1"
ZHAOYAO_MIRROR_FORMULA_VERSION = "newow_zhaoyao_mirror_repainting_page_v1"
UP_DOWN_ENERGY_FORMULA_VERSION = "newow_up_down_energy_page_v1"


class MainForceStatus(StrEnum):
    NO_CONTROL = "无庄控盘"
    CONTROL_STARTED = "开始控盘"
    CONTROLLED = "有庄控盘"
    HIGH_CONTROL = "高度控盘"
    DISTRIBUTION = "主力出货"
    HIGH_CONTROL_DISTRIBUTION = "高控+出货"


@dataclass(frozen=True, slots=True)
class MainForceControlResult:
    kongpan: tuple[float, ...]
    status: tuple[MainForceStatus, ...]
    current_status: MainForceStatus
    formula_version: str = MAIN_FORCE_CONTROL_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class ZhaoyaoMirrorResult:
    entry: tuple[float, ...]
    wash: tuple[float, ...]
    distribution: tuple[float, ...]
    markup: tuple[float, ...]
    exit: tuple[float, ...]
    inducement: tuple[float, ...]
    peaks: tuple[int, ...]
    caution: tuple[int, ...]
    repainting: bool = True
    formal_signal_eligible: bool = False
    formula_version: str = ZHAOYAO_MIRROR_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class UpDownEnergyResult:
    var4: tuple[float | None, ...]
    ma10: tuple[float, ...]
    band_entry: tuple[int, ...]
    rebound_entry: tuple[int, ...]
    oversold_entry: tuple[int, ...]
    var3: tuple[float, ...]
    ma120: tuple[float, ...]
    formula_version: str = UP_DOWN_ENERGY_FORMULA_VERSION


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1.0 - alpha))
    return result


def _sma_cn(values: list[float], period: int) -> list[float]:
    result = [values[0]]
    for value in values[1:]:
        result.append((value + (period - 1) * result[-1]) / period)
    return result


def _partial_sma(values: list[float], period: int) -> list[float]:
    result: list[float] = []
    for index in range(len(values)):
        total = 0.0
        count = 0
        for offset in range(period):
            source = index - offset
            if source < 0:
                break
            total += values[source]
            count += 1
        result.append(total / count)
    return result


def _rolling(values: list[float], period: int, index: int, *, highest: bool) -> float:
    window = values[max(0, index - period + 1) : index + 1]
    return max(window) if highest else min(window)


def calculate_main_force_control(
    bars: tuple[NewowDailyBar, ...],
) -> MainForceControlResult | None:
    if len(bars) < 10:
        return None
    closes = [float(bar.close) for bar in bars]
    var1 = _ema(_ema(closes, 9), 9)
    kongpan = [0.0]
    for index in range(1, len(bars)):
        previous = var1[index - 1]
        kongpan.append(
            0.0 if previous == 0 else (var1[index] - previous) / previous * 1000.0
        )
    ema50 = _ema(closes, 50)
    status = [MainForceStatus.NO_CONTROL]
    for index in range(1, len(bars)):
        current = kongpan[index]
        previous = kongpan[index - 1]
        if previous <= 0 < current:
            value = MainForceStatus.CONTROL_STARTED
        elif current > 0 and current > previous:
            value = MainForceStatus.CONTROLLED
        elif current > 0 and closes[index] > ema50[index] and current < previous:
            value = MainForceStatus.HIGH_CONTROL_DISTRIBUTION
        elif current > 0 and closes[index] > ema50[index]:
            value = MainForceStatus.HIGH_CONTROL
        elif current > 0 and current < previous:
            value = MainForceStatus.DISTRIBUTION
        elif current < 0:
            value = MainForceStatus.NO_CONTROL
        else:
            value = status[-1]
        status.append(value)
    return MainForceControlResult(tuple(kongpan), tuple(status), status[-1])


def calculate_zhaoyao_mirror(
    bars: tuple[NewowDailyBar, ...],
) -> ZhaoyaoMirrorResult | None:
    """Reproduce the page overlay, including its documented future repaint."""

    if len(bars) < 20:
        return None
    size = len(bars)
    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    quarters = [float(bar.low + bar.open + bar.close + bar.high) / 4.0 for bar in bars]
    var1 = [quarters[0], *quarters[:-1]]

    abs_low = [abs(value - prior) for value, prior in zip(lows, var1, strict=True)]
    max_low = [max(value - prior, 0.0) for value, prior in zip(lows, var1, strict=True)]
    low_num, low_den = _sma_cn(abs_low, 13), _sma_cn(max_low, 10)
    var2 = [num / (den or 1.0) for num, den in zip(low_num, low_den, strict=True)]
    var3 = _ema(var2, 10)
    var4 = [_rolling(lows, 10, index, highest=False) for index in range(size)]
    var5 = _ema(
        [var3[index] if lows[index] <= var4[index] else 0.0 for index in range(size)], 3
    )
    entry = [
        0.0 if index == 0 or var5[index] <= var5[index - 1] else var5[index]
        for index in range(size)
    ]
    wash = [
        0.0 if index == 0 or var5[index] >= var5[index - 1] else var5[index]
        for index in range(size)
    ]

    abs_high = [abs(value - prior) for value, prior in zip(highs, var1, strict=True)]
    min_high = [
        abs(min(value - prior, 0.0)) for value, prior in zip(highs, var1, strict=True)
    ]
    high_num, high_den = _sma_cn(abs_high, 13), _sma_cn(min_high, 10)
    var21 = [num / (den or 1.0) for num, den in zip(high_num, high_den, strict=True)]
    var31 = _ema(var21, 10)
    var41 = [_rolling(highs, 10, index, highest=True) for index in range(size)]
    var51 = _ema(
        [
            var31[index] if highs[index] >= var41[index] else 0.0
            for index in range(size)
        ],
        3,
    )
    distribution = [
        0.0 if index == 0 or var51[index] <= var51[index - 1] else var51[index]
        for index in range(size)
    ]
    markup = [
        0.0 if index == 0 or var51[index] >= var51[index - 1] else var51[index]
        for index in range(size)
    ]

    var55 = _ema(
        [var3[index] if highs[index] >= var41[index] else 0.0 for index in range(size)],
        3,
    )
    exit_values = [
        0.0 if index == 0 or var55[index] <= var55[index - 1] else var55[index]
        for index in range(size)
    ]
    inducement = [
        0.0 if index == 0 or var55[index] >= var55[index - 1] else var55[index]
        for index in range(size)
    ]

    confirmed_peaks: list[int] = []
    trend = 1
    candidate_peak = candidate_trough = 0
    peak_value = trough_value = closes[0]
    for index in range(1, size):
        if trend >= 0:
            if closes[index] > peak_value:
                peak_value, candidate_peak = closes[index], index
            elif closes[index] <= peak_value * 0.95:
                confirmed_peaks.append(candidate_peak)
                trend, candidate_trough, trough_value = -1, index, closes[index]
        elif closes[index] < trough_value:
            trough_value, candidate_trough = closes[index], index
        elif closes[index] >= trough_value * 1.05:
            trend, candidate_peak, peak_value = 1, index, closes[index]
    del candidate_trough
    all_peaks = list(confirmed_peaks)
    if trend >= 0 and candidate_peak not in all_peaks:
        all_peaks.append(candidate_peak)
    peaks = [0] * size
    for index in all_peaks:
        peaks[index] = 1
    ding = [0] * size
    pointer = 0
    current_peak = -1
    for index in range(size):
        while pointer < len(all_peaks) and all_peaks[pointer] <= index:
            current_peak = all_peaks[pointer]
            pointer += 1
        if current_peak >= 0 and index - current_peak < 10:
            ding[index] = 2
    caution = [
        50 if (value == 2 if index == 0 else value > ding[index - 1]) else 0
        for index, value in enumerate(ding)
    ]
    caution[-1] = 0
    return ZhaoyaoMirrorResult(
        tuple(entry),
        tuple(wash),
        tuple(distribution),
        tuple(markup),
        tuple(exit_values),
        tuple(inducement),
        tuple(peaks),
        tuple(caution),
    )


def calculate_up_down_energy(
    bars: tuple[NewowDailyBar, ...],
) -> UpDownEnergyResult | None:
    if len(bars) < 15:
        return None
    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    ma120 = _partial_sma(closes, 120)
    ma5 = _partial_sma(closes, 5)
    ma10 = _partial_sma(closes, 10)
    var3 = [
        (fast - slow) / slow if slow != 0 else 0.0
        for fast, slow in zip(ma5, ma120, strict=True)
    ]
    raw: list[float | None] = [None] * len(bars)
    for index in range(9, len(bars)):
        low = min(lows[index - 9 : index + 1])
        high = max(highs[index - 9 : index + 1])
        raw[index] = (
            50.0 if high - low <= 0 else (closes[index] - low) / (high - low) * 100.0
        )
    var4: list[float | None] = [None] * len(bars)
    for index in range(2, len(bars)):
        values = raw[index - 2 : index + 1]
        if all(value is not None for value in values):
            var4[index] = sum(value for value in values if value is not None) / 3.0
    band = [50] * len(bars)
    rebound = [50] * len(bars)
    oversold = [50] * len(bars)
    for index in range(3, len(bars)):
        current, previous, prior = var4[index], var4[index - 1], var4[index - 2]
        if current is None or previous is None or prior is None:
            continue
        band[index] = (
            80
            if closes[index] > ma120[index]
            and previous < 30
            and current > previous
            and previous < prior
            else 50
        )
        rebound[index] = (
            80
            if previous < 5
            and current > previous
            and previous < prior
            and var3[index] < -0.3
            else 50
        )
        oversold[index] = (
            80 if previous <= 5 and current > 5 and var3[index] < -0.4 else 50
        )
    return UpDownEnergyResult(
        tuple(var4),
        tuple(ma10),
        tuple(band),
        tuple(rebound),
        tuple(oversold),
        tuple(var3),
        tuple(ma120),
    )

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass(frozen=True)
class AuditBar:
    high: float
    low: float
    close: float


def test_macd_seed_policy_diff_is_material_for_current_implementations() -> None:
    closes = [100.0, 101.5, 99.0, 104.0, 106.5, 103.0, 108.0, 111.0, 107.0, 112.5]

    web = _macd_web_style(closes, fast=3, slow=5, signal=3)
    first_value = _macd_first_value_style(closes, fast=3, slow=5, signal=3)

    assert web["dif"][6] is not None
    assert first_value["dif"][6] is not None
    assert web["dif"][6] != first_value["dif"][6]
    assert web["dea"][6] != first_value["dea"][6]


def test_macd_histogram_scale_diff_is_explicit() -> None:
    closes = [100.0, 102.0, 101.0, 105.0, 107.0, 103.0, 109.0, 112.0, 108.0, 113.0]

    web = _macd_web_style(closes, fast=3, slow=5, signal=3)
    strategy = _macd_first_value_style(closes, fast=3, slow=5, signal=3)

    web_index = _last_ready_index(web["histogram"])
    strategy_index = _last_ready_index(strategy["histogram"])

    assert abs(web["histogram"][web_index] - _round((web["dif"][web_index] - web["dea"][web_index]) * 2)) <= 0.000002
    assert (
        abs(
            strategy["histogram"][strategy_index]
            - _round(strategy["dif"][strategy_index] - strategy["dea"][strategy_index])
        )
        <= 0.000002
    )
    assert web["histogram"][web_index] != _round(web["dif"][web_index] - web["dea"][web_index])


def test_atr_seed_and_smoothing_diff_is_material() -> None:
    bars = [
        AuditBar(high=102.0, low=99.0, close=100.0),
        AuditBar(high=105.0, low=100.0, close=104.0),
        AuditBar(high=106.0, low=98.0, close=99.0),
        AuditBar(high=110.0, low=101.0, close=108.0),
        AuditBar(high=112.0, low=104.0, close=105.0),
        AuditBar(high=109.0, low=97.0, close=100.0),
    ]

    web = _atr_wilder_sma_seed(bars, period=3)
    api_strategy = _atr_wilder_first_tr(bars, period=3)
    quant_core_strategy = _atr_ema_first_tr(bars, period=3)

    assert web[2] is not None
    assert web[2] != api_strategy[2]
    assert api_strategy[2] != quant_core_strategy[2]
    assert web[-1] != quant_core_strategy[-1]


def test_macd_and_atr_tail_perturbation_does_not_repaint_past_values() -> None:
    closes = [100.0, 101.0, 103.0, 102.0, 105.0, 107.0, 106.0, 108.0]
    changed_closes = [*closes[:6], 500.0, 600.0]
    original_macd = _macd_web_style(closes, fast=3, slow=5, signal=3)
    changed_macd = _macd_web_style(changed_closes, fast=3, slow=5, signal=3)

    assert original_macd["dif"][5] == changed_macd["dif"][5]
    assert original_macd["dea"][5] == changed_macd["dea"][5]

    bars = [
        AuditBar(high=102.0, low=99.0, close=100.0),
        AuditBar(high=104.0, low=100.0, close=103.0),
        AuditBar(high=107.0, low=101.0, close=106.0),
        AuditBar(high=108.0, low=104.0, close=105.0),
        AuditBar(high=109.0, low=103.0, close=107.0),
        AuditBar(high=111.0, low=105.0, close=110.0),
    ]
    changed_bars = [*bars[:4], AuditBar(high=800.0, low=100.0, close=500.0), AuditBar(high=900.0, low=200.0, close=600.0)]

    assert _atr_wilder_sma_seed(bars, 3)[3] == _atr_wilder_sma_seed(changed_bars, 3)[3]
    assert _atr_wilder_first_tr(bars, 3)[3] == _atr_wilder_first_tr(changed_bars, 3)[3]


def test_macd_and_atr_are_not_validated_registry_entries_yet() -> None:
    from guiyi_quant.indicators import indicator_registry

    assert "macd" not in indicator_registry
    assert "atr" not in indicator_registry
    assert "ema21" in indicator_registry
    assert indicator_registry["huo_tian_da_you"].status == "observation_only"


def _macd_web_style(closes: list[float], fast: int, slow: int, signal: int) -> dict[str, list[float | None]]:
    fast_series = _ema_sma_window(closes, fast)
    slow_series = _ema_sma_window(closes, slow)
    dif_values: list[float] = []
    dif_indexes: list[int] = []
    for index, (fast_value, slow_value) in enumerate(zip(fast_series, slow_series, strict=True)):
        if fast_value is None or slow_value is None:
            continue
        dif_indexes.append(index)
        dif_values.append(fast_value - slow_value)

    dea_local = _ema_sma_window(dif_values, signal)
    dif = _empty_series(len(closes))
    dea = _empty_series(len(closes))
    histogram = _empty_series(len(closes))
    for local_index, dea_value in enumerate(dea_local):
        if dea_value is None:
            continue
        source_index = dif_indexes[local_index]
        dif[source_index] = _round(dif_values[local_index])
        dea[source_index] = _round(dea_value)
        histogram[source_index] = _round((dif_values[local_index] - dea_value) * 2)
    return {"dif": dif, "dea": dea, "histogram": histogram}


def _macd_first_value_style(closes: list[float], fast: int, slow: int, signal: int) -> dict[str, list[float | None]]:
    fast_series = _ema_first_value(closes, fast)
    slow_series = _ema_first_value(closes, slow)
    dif = [fast_value - slow_value for fast_value, slow_value in zip(fast_series, slow_series, strict=True)]
    dea = _ema_first_value(dif, signal)
    histogram = [_round(diff - dea_value) for diff, dea_value in zip(dif, dea, strict=True)]
    return {
        "dif": [_round(value) for value in dif],
        "dea": [_round(value) for value in dea],
        "histogram": histogram,
    }


def _ema_sma_window(values: list[float], period: int) -> list[float | None]:
    result = _empty_series(len(values))
    if period <= 0 or len(values) < period:
        return result
    alpha = 2 / (period + 1)
    previous = sum(values[:period]) / period
    result[period - 1] = previous
    for index in range(period, len(values)):
        previous = (values[index] - previous) * alpha + previous
        result[index] = previous
    return result


def _ema_first_value(values: list[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def _atr_wilder_sma_seed(bars: list[AuditBar], period: int) -> list[float | None]:
    true_ranges = _true_ranges(bars)
    result = _empty_series(len(bars))
    if period <= 0 or len(true_ranges) < period:
        return result
    previous = sum(true_ranges[:period]) / period
    result[period - 1] = _round(previous)
    for index in range(period, len(true_ranges)):
        previous = (previous * (period - 1) + true_ranges[index]) / period
        result[index] = _round(previous)
    return result


def _atr_wilder_first_tr(bars: list[AuditBar], period: int) -> list[float]:
    true_ranges = _true_ranges(bars)
    result = [true_ranges[0]]
    for value in true_ranges[1:]:
        result.append(_round((result[-1] * (period - 1) + value) / period))
    return result


def _atr_ema_first_tr(bars: list[AuditBar], period: int) -> list[float]:
    return [_round(value) for value in _ema_first_value(_true_ranges(bars), period)]


def _true_ranges(bars: list[AuditBar]) -> list[float]:
    result = [bars[0].high - bars[0].low]
    for index in range(1, len(bars)):
        previous_close = bars[index - 1].close
        result.append(
            max(
                bars[index].high - bars[index].low,
                abs(bars[index].high - previous_close),
                abs(bars[index].low - previous_close),
            )
        )
    return result


def _empty_series(length: int) -> list[float | None]:
    return [None] * length


def _last_ready_index(values: list[float | None]) -> int:
    return max(index for index, value in enumerate(values) if value is not None)


def _round(value: float) -> float:
    return round(value, 6)

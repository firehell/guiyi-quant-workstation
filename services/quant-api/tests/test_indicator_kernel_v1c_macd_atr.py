from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass(frozen=True)
class AuditBar:
    high: float
    low: float
    close: float


def test_macd_series_replicates_web_sma_window_histogram_scale_2() -> None:
    from guiyi_quant.indicators import macd_series

    closes = [100.0, 102.0, 101.0, 105.0, 107.0, 103.0, 109.0, 112.0, 108.0, 113.0]
    result = macd_series(closes, 3, 5, 3, ema_seed_policy="sma_window", histogram_scale=2)
    expected = _macd_web_style(closes, fast=3, slow=5, signal=3)

    assert result.indicator_code == "macd"
    assert result.indicator_version == "v1-draft"
    assert result.parameters["ema_seed_policy"] == "sma_window"
    assert result.parameters["histogram_scale"] == 2
    assert len(result.dif.points) == len(closes)
    assert len(result.dea.points) == len(closes)
    assert len(result.histogram.points) == len(closes)
    assert result.dif.points[4].ready is True
    assert result.dea.points[4].ready is False

    for index, expected_dea in enumerate(expected["dea"]):
        if expected_dea is None:
            continue
        assert result.dif.points[index].value == expected["dif"][index]
        assert result.dea.points[index].value == expected_dea
        assert result.histogram.points[index].value == expected["histogram"][index]


def test_macd_series_replicates_python_strategy_first_value_histogram_scale_1() -> None:
    from guiyi_quant.indicators import macd_series

    closes = [100.0, 101.5, 99.0, 104.0, 106.5, 103.0, 108.0, 111.0]
    result = macd_series(closes, 3, 5, 3, ema_seed_policy="first_value", histogram_scale=1)
    expected = _macd_first_value_style(closes, fast=3, slow=5, signal=3)

    assert [point.ready for point in result.dif.points] == [True] * len(closes)
    assert [point.valid for point in result.histogram.points] == [True] * len(closes)
    assert _values(result.dif.points) == expected["dif"]
    assert _values(result.dea.points) == expected["dea"]
    assert _values(result.histogram.points) == expected["histogram"]


def test_atr_series_replicates_web_wilder_sma_seed() -> None:
    from guiyi_quant.indicators import atr_series

    bars = _atr_bars()
    result = atr_series(
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
        3,
        smoothing_policy="wilder_sma_seed",
    )

    assert result.indicator_code == "atr"
    assert result.indicator_version == "v1-draft"
    assert result.points[0].ready is False
    assert result.points[1].ready is False
    assert _values(result.points) == _atr_wilder_sma_seed(bars, 3)


def test_atr_series_replicates_fastapi_wilder_first_tr_seed() -> None:
    from guiyi_quant.indicators import atr_series

    bars = _atr_bars()
    result = atr_series(
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
        3,
        smoothing_policy="wilder_first_tr",
    )

    assert result.points[0].ready is True
    assert _values(result.points) == _atr_wilder_first_tr(bars, 3)


def test_atr_series_replicates_quant_core_ema_first_tr_seed() -> None:
    from guiyi_quant.indicators import atr_series

    bars = _atr_bars()
    result = atr_series(
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
        3,
        smoothing_policy="ema_first_tr",
    )

    assert result.points[0].ready is True
    assert _values(result.points) == _atr_ema_first_tr(bars, 3)


def test_invalid_inputs_are_marked_invalid_without_zero_fill() -> None:
    from guiyi_quant.indicators import atr_series, macd_series

    macd = macd_series([10.0, 11.0, math.nan, 13.0, 14.0, 15.0, 16.0], 2, 3, 2, ema_seed_policy="sma_window", histogram_scale=2)

    assert macd.dif.points[2].valid is False
    assert macd.dif.points[2].value is None
    assert macd.dif.points[2].reason == "input_invalid"
    assert macd.histogram.points[2].value is None
    assert macd.histogram.points[6].valid is True
    assert macd.histogram.points[6].value is not None

    atr = atr_series(
        [10.0, 11.0, math.nan, 13.0, 14.0, 15.0],
        [8.0, 9.0, 10.0, 11.0, 12.0, 13.0],
        [9.0, 10.0, 10.5, 12.0, 13.0, 14.0],
        3,
        smoothing_policy="wilder_sma_seed",
    )

    assert atr.points[2].valid is False
    assert atr.points[2].value is None
    assert atr.points[2].reason == "input_invalid"
    assert atr.points[5].valid is True
    assert atr.points[5].value != 0


def test_invalid_parameters_raise_clear_errors() -> None:
    from guiyi_quant.indicators import atr_series, macd_series

    with pytest.raises(ValueError, match="fast period"):
        macd_series([1.0, 2.0], 5, 3, 2, ema_seed_policy="sma_window", histogram_scale=2)
    with pytest.raises(ValueError, match="histogram_scale"):
        macd_series([1.0, 2.0], 2, 3, 2, ema_seed_policy="sma_window", histogram_scale=3)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ema_seed_policy"):
        macd_series([1.0, 2.0], 2, 3, 2, ema_seed_policy="bad", histogram_scale=2)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="bar_ends"):
        macd_series([1.0, 2.0], 2, 3, 2, ema_seed_policy="sma_window", histogram_scale=2, bar_ends=["x"])

    with pytest.raises(ValueError, match="length"):
        atr_series([1.0], [0.5, 0.6], [0.8], 3, smoothing_policy="wilder_sma_seed")
    with pytest.raises(ValueError, match="smoothing_policy"):
        atr_series([1.0], [0.5], [0.8], 3, smoothing_policy="bad")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="round_digits"):
        atr_series([1.0], [0.5], [0.8], 3, smoothing_policy="wilder_sma_seed", round_digits=-1)


def test_future_tail_perturbation_does_not_repaint_past_outputs() -> None:
    from guiyi_quant.indicators import atr_series, macd_series

    closes = [100.0, 101.0, 103.0, 102.0, 105.0, 107.0, 106.0, 108.0]
    changed_closes = [*closes[:6], 500.0, 600.0]
    original_macd = macd_series(closes, 3, 5, 3, ema_seed_policy="sma_window", histogram_scale=2)
    changed_macd = macd_series(changed_closes, 3, 5, 3, ema_seed_policy="sma_window", histogram_scale=2)

    assert _values(original_macd.dif.points[:6]) == _values(changed_macd.dif.points[:6])
    assert _values(original_macd.dea.points[:6]) == _values(changed_macd.dea.points[:6])
    assert _values(original_macd.histogram.points[:6]) == _values(changed_macd.histogram.points[:6])

    bars = _atr_bars()
    changed_bars = [*bars[:4], AuditBar(high=800.0, low=100.0, close=500.0), AuditBar(high=900.0, low=200.0, close=600.0)]
    original_atr = atr_series(
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
        3,
        smoothing_policy="wilder_sma_seed",
    )
    changed_atr = atr_series(
        [bar.high for bar in changed_bars],
        [bar.low for bar in changed_bars],
        [bar.close for bar in changed_bars],
        3,
        smoothing_policy="wilder_sma_seed",
    )

    assert _values(original_atr.points[:4]) == _values(changed_atr.points[:4])


def test_macd_and_atr_are_public_functions_but_not_validated_registry_entries() -> None:
    from guiyi_quant.indicators import atr_series, indicator_registry, macd_series

    assert callable(macd_series)
    assert callable(atr_series)
    assert indicator_registry["macd"].status == "compatibility_validated"
    assert indicator_registry["atr"].status == "compatibility_validated"
    assert indicator_registry["ema21"].status == "validated"


def test_indicator_kernel_does_not_modify_forbidden_strategy_live_or_data_files() -> None:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--",
            "packages/quant-core/guiyi_quant/strategies",
            "services/quant-api/app/services/live_signal_evaluator.py",
            "services/quant-api/app/signal",
            "data",
            ".env",
            ".env.example",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == ""


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
    histogram = [diff - dea_value for diff, dea_value in zip(dif, dea, strict=True)]
    return {
        "dif": [_round(value) for value in dif],
        "dea": [_round(value) for value in dea],
        "histogram": [_round(value) for value in histogram],
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
        result.append((value - result[-1]) * alpha + result[-1])
    return result


def _atr_bars() -> list[AuditBar]:
    return [
        AuditBar(high=102.0, low=99.0, close=100.0),
        AuditBar(high=105.0, low=100.0, close=104.0),
        AuditBar(high=106.0, low=98.0, close=99.0),
        AuditBar(high=110.0, low=101.0, close=108.0),
        AuditBar(high=112.0, low=104.0, close=105.0),
        AuditBar(high=109.0, low=97.0, close=100.0),
    ]


def _atr_wilder_sma_seed(bars: list[AuditBar], period: int) -> list[float | None]:
    true_ranges = _true_ranges(bars)
    result = _empty_series(len(bars))
    previous = sum(true_ranges[:period]) / period
    result[period - 1] = _round(previous)
    for index in range(period, len(true_ranges)):
        previous = (previous * (period - 1) + true_ranges[index]) / period
        result[index] = _round(previous)
    return result


def _atr_wilder_first_tr(bars: list[AuditBar], period: int) -> list[float | None]:
    true_ranges = _true_ranges(bars)
    result: list[float | None] = []
    previous = true_ranges[0]
    result.append(_round(previous))
    for value in true_ranges[1:]:
        previous = (previous * (period - 1) + value) / period
        result.append(_round(previous))
    return result


def _atr_ema_first_tr(bars: list[AuditBar], period: int) -> list[float | None]:
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


def _values(points: list[object]) -> list[float | None]:
    return [getattr(point, "value") for point in points]


def _round(value: float) -> float:
    return round(value, 6)

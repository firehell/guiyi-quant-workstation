from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = REPO_ROOT / "services" / "quant-api"
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

for path in (SERVICE_ROOT, QUANT_CORE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@dataclass(frozen=True)
class VnpyBar:
    datetime: datetime
    trading_day: date
    open: float
    high: float
    low: float
    close: float
    volume: float



def test_quant_core_su_bing_ema21_vectors_match_kernel_policies() -> None:
    from guiyi_quant.indicators import atr_series, ema_series, macd_series
    from guiyi_quant.strategies.su_bing_ema21.config_schema import validate_params
    from guiyi_quant.strategies.su_bing_ema21.vnpy_strategy import SuBingEma21VnpyStrategy, _atr_series, _ema_series

    bars = _synthetic_bars(36)
    params = validate_params({"ema_period": 5, "macd_fast": 3, "macd_slow": 6, "macd_signal": 4, "atr_period": 5})
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]

    legacy_ema = _ema_series(closes, params.ema_period)
    legacy_fast = _ema_series(closes, params.macd_fast)
    legacy_slow = _ema_series(closes, params.macd_slow)
    legacy_dif = [fast - slow for fast, slow in zip(legacy_fast, legacy_slow, strict=True)]
    legacy_dea = _ema_series(legacy_dif, params.macd_signal)
    legacy_atr = _atr_series(highs, lows, closes, params.atr_period)
    legacy_snapshot = SuBingEma21VnpyStrategy._calculate_indicators(bars, params)

    kernel_ema = ema_series(closes, params.ema_period, seed_policy="first_value")
    kernel_macd = macd_series(
        closes,
        params.macd_fast,
        params.macd_slow,
        params.macd_signal,
        ema_seed_policy="first_value",
        histogram_scale=1,
    )
    kernel_atr = atr_series(highs, lows, closes, params.atr_period, smoothing_policy="ema_first_tr")

    assert _round_series(legacy_ema) == _point_values(kernel_ema.points)
    assert _round_series(legacy_dif) == _point_values(kernel_macd.dif.points)
    assert _round_series(legacy_dea) == _point_values(kernel_macd.dea.points)
    assert _round_series(legacy_atr) == _point_values(kernel_atr.points)
    assert round(legacy_snapshot.ema, 6) == _point_values(kernel_ema.points)[-1]
    assert round(legacy_snapshot.dif, 6) == _point_values(kernel_macd.dif.points)[-1]
    assert round(legacy_snapshot.dea, 6) == _point_values(kernel_macd.dea.points)[-1]
    assert round(legacy_snapshot.atr, 6) == _point_values(kernel_atr.points)[-1]


def test_jm_v1b_entry_and_daily_vectors_match_kernel_policies() -> None:
    from guiyi_quant.indicators import atr_series, ema_series, macd_series
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.config_schema import validate_params
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy import (
        _atr_series,
        _ema_series,
        calculate_indicators,
        confirmed_daily_direction_snapshot,
    )

    params = validate_params(
        {
            "ema_period": 5,
            "macd_fast": 3,
            "macd_slow": 6,
            "macd_signal": 4,
            "atr_period": 5,
            "daily_ema_period": 6,
            "daily_macd_fast": 3,
            "daily_macd_slow": 7,
            "daily_macd_signal": 4,
            "daily_atr_period": 6,
            "daily_ema_slope_lookback": 2,
            "submit_vnpy_orders": False,
        }
    )
    entry_bars = _synthetic_bars(36, minutes=15)
    daily_bars = _synthetic_bars(40, start=date(2026, 5, 1), minutes=24 * 60)

    entry_snapshot = calculate_indicators(entry_bars, params)
    _assert_legacy_series_match_kernel(
        entry_bars,
        ema_period=params.ema_period,
        macd_fast=params.macd_fast,
        macd_slow=params.macd_slow,
        macd_signal=params.macd_signal,
        atr_period=params.atr_period,
        legacy_ema=_ema_series,
        legacy_atr=_atr_series,
    )
    entry_closes = [bar.close for bar in entry_bars]
    entry_kernel_ema = ema_series(entry_closes, params.ema_period, seed_policy="first_value")
    entry_kernel_macd = macd_series(
        entry_closes,
        params.macd_fast,
        params.macd_slow,
        params.macd_signal,
        ema_seed_policy="first_value",
        histogram_scale=1,
    )
    entry_kernel_atr = atr_series(
        [bar.high for bar in entry_bars],
        [bar.low for bar in entry_bars],
        entry_closes,
        params.atr_period,
        smoothing_policy="ema_first_tr",
    )

    assert round(entry_snapshot.ema, 6) == _point_values(entry_kernel_ema.points)[-1]
    assert round(entry_snapshot.dif, 6) == _point_values(entry_kernel_macd.dif.points)[-1]
    assert round(entry_snapshot.dea, 6) == _point_values(entry_kernel_macd.dea.points)[-1]
    assert round(entry_snapshot.atr, 6) == _point_values(entry_kernel_atr.points)[-1]

    current_bar = VnpyBar(
        datetime=datetime.combine(date(2026, 6, 20), datetime.min.time()).replace(hour=9),
        trading_day=date(2026, 6, 20),
        open=130.0,
        high=132.0,
        low=129.0,
        close=131.0,
        volume=1000.0,
    )
    daily_snapshot = confirmed_daily_direction_snapshot(current_bar=current_bar, daily_bars=daily_bars, params=params)
    daily_confirmed = [bar for bar in daily_bars if bar.trading_day < current_bar.trading_day]
    _assert_legacy_series_match_kernel(
        daily_confirmed,
        ema_period=params.daily_ema_period,
        macd_fast=params.daily_macd_fast,
        macd_slow=params.daily_macd_slow,
        macd_signal=params.daily_macd_signal,
        atr_period=params.daily_atr_period,
        legacy_ema=_ema_series,
        legacy_atr=_atr_series,
    )
    daily_closes = [bar.close for bar in daily_confirmed]
    daily_kernel_ema = ema_series(daily_closes, params.daily_ema_period, seed_policy="first_value")
    daily_kernel_macd = macd_series(
        daily_closes,
        params.daily_macd_fast,
        params.daily_macd_slow,
        params.daily_macd_signal,
        ema_seed_policy="first_value",
        histogram_scale=1,
    )
    daily_kernel_atr = atr_series(
        [bar.high for bar in daily_confirmed],
        [bar.low for bar in daily_confirmed],
        daily_closes,
        params.daily_atr_period,
        smoothing_policy="ema_first_tr",
    )

    assert daily_snapshot.ema is not None
    assert daily_snapshot.dif is not None
    assert daily_snapshot.dea is not None
    assert daily_snapshot.atr is not None
    assert round(daily_snapshot.ema, 6) == _point_values(daily_kernel_ema.points)[-1]
    assert round(daily_snapshot.dif, 6) == _point_values(daily_kernel_macd.dif.points)[-1]
    assert round(daily_snapshot.dea, 6) == _point_values(daily_kernel_macd.dea.points)[-1]
    assert round(daily_snapshot.atr, 6) == _point_values(daily_kernel_atr.points)[-1]


def test_daily_macd_volume_and_score_variants_match_kernel_first_value_policy() -> None:
    from guiyi_quant.indicators import ema_series, macd_series
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.config_schema import (
        validate_params as validate_macd_volume_params,
    )
    from guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.vnpy_strategy import (
        calculate_indicators as calculate_macd_volume_indicators,
    )
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4.config_schema import (
        validate_params as validate_score2_params,
    )
    from guiyi_quant.strategies.su_bing_jm_daily_score2of4.vnpy_strategy import (
        calculate_indicators as calculate_score2_indicators,
    )
    from guiyi_quant.strategies.su_bing_jm_daily_trend_cross_score2.vnpy_strategy import (
        calculate_indicators as calculate_trend_cross_indicators,
    )

    bars = _synthetic_bars(40, start=date(2026, 4, 1), minutes=24 * 60)
    closes = [bar.close for bar in bars]
    macd_volume_params = validate_macd_volume_params()
    score2_params = validate_score2_params()

    kernel_ema = ema_series(closes, macd_volume_params.ema_period, seed_policy="first_value")
    kernel_macd = macd_series(
        closes,
        macd_volume_params.macd_fast,
        macd_volume_params.macd_slow,
        macd_volume_params.macd_signal,
        ema_seed_policy="first_value",
        histogram_scale=1,
    )
    macd_volume = calculate_macd_volume_indicators(bars, macd_volume_params)
    score2 = calculate_score2_indicators(bars, score2_params)
    trend_cross = calculate_trend_cross_indicators(bars, score2_params)

    for snapshot in (macd_volume, score2, trend_cross):
        assert round(snapshot.ema21, 6) == _point_values(kernel_ema.points)[-1]
        assert round(snapshot.fast_ema, 6) == _point_values(
            ema_series(closes, macd_volume_params.macd_fast, seed_policy="first_value").points
        )[-1]
        assert round(snapshot.slow_ema, 6) == _point_values(
            ema_series(closes, macd_volume_params.macd_slow, seed_policy="first_value").points
        )[-1]
        assert round(snapshot.dif, 6) == _point_values(kernel_macd.dif.points)[-1]
        assert round(snapshot.dea, 6) == _point_values(kernel_macd.dea.points)[-1]
        assert round(snapshot.histogram, 6) == _point_values(kernel_macd.histogram.points)[-1]
        assert round(snapshot.previous_dif, 6) == _point_values(kernel_macd.dif.points)[-2]
        assert round(snapshot.previous_dea, 6) == _point_values(kernel_macd.dea.points)[-2]


def test_macd_and_atr_remain_unregistered_and_business_paths_unchanged() -> None:
    from guiyi_quant.indicators import indicator_registry

    assert indicator_registry["macd"].status == "compatibility_validated"
    assert indicator_registry["atr"].status == "compatibility_validated"
    assert indicator_registry["ema21"].status == "validated"


def _assert_legacy_series_match_kernel(
    bars: list[VnpyBar],
    *,
    ema_period: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
    atr_period: int,
    legacy_ema: Any,
    legacy_atr: Any,
) -> None:
    from guiyi_quant.indicators import atr_series, ema_series, macd_series

    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    legacy_fast = legacy_ema(closes, macd_fast)
    legacy_slow = legacy_ema(closes, macd_slow)
    legacy_dif = [fast - slow for fast, slow in zip(legacy_fast, legacy_slow, strict=True)]
    legacy_dea = legacy_ema(legacy_dif, macd_signal)

    assert _round_series(legacy_ema(closes, ema_period)) == _point_values(
        ema_series(closes, ema_period, seed_policy="first_value").points
    )
    kernel_macd = macd_series(
        closes,
        macd_fast,
        macd_slow,
        macd_signal,
        ema_seed_policy="first_value",
        histogram_scale=1,
    )
    assert _round_series(legacy_dif) == _point_values(kernel_macd.dif.points)
    assert _round_series(legacy_dea) == _point_values(kernel_macd.dea.points)
    assert _round_series(legacy_atr(highs, lows, closes, atr_period)) == _point_values(
        atr_series(highs, lows, closes, atr_period, smoothing_policy="ema_first_tr").points
    )


def _synthetic_bars(
    count: int,
    *,
    start: date = date(2026, 7, 1),
    minutes: int = 15,
) -> list[VnpyBar]:
    bars: list[VnpyBar] = []
    start_dt = datetime.combine(start, datetime.min.time()).replace(hour=9)
    for index in range(count):
        close = 100.0 + index * 0.65 + ((index % 5) - 2) * 0.35
        moment = start_dt + timedelta(minutes=index * minutes)
        trading_day = start + timedelta(days=index) if minutes >= 24 * 60 else start
        bars.append(
            VnpyBar(
                datetime=moment,
                trading_day=trading_day,
                open=close - 0.4,
                high=close + 1.2 + (index % 3) * 0.1,
                low=close - 1.1 - (index % 4) * 0.05,
                close=close,
                volume=1000.0 + index * 10,
            )
        )
    return bars


def _point_values(points: Any) -> list[float | None]:
    return [point.value for point in points]


def _round_series(values: list[float]) -> list[float]:
    return [round(value, 6) for value in values]

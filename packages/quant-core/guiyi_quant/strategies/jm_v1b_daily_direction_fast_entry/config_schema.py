from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


DAILY_DIRECTION_EFFECTIVE_POLICY = "confirmed_daily_bar_effective_next_trading_day"
FILL_POLICY = "signal_on_close_fill_next_bar_open"

DEFAULT_PARAMS: dict[str, Any] = {
    "entry_interval": "15m",
    "fixed_size": 1,
    "ema_period": 21,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14,
    "volume_window": 20,
    "volume_multiplier_15m": 1.0,
    "volume_multiplier_5m": 1.1,
    "pullback_lookback_bars": 3,
    "pullback_touch_ema_atr": 0.35,
    "max_ema_distance_atr_15m": 1.2,
    "max_ema_distance_atr_5m": 1.0,
    "max_hold_bars_min": 5,
    "max_hold_bars_max": 8,
    "stop_loss_atr_multiple": 1.5,
    "structure_stop_lookback_bars": 3,
    "stop_buffer_ticks": 2,
    "pricetick": 1.0,
    "allow_long": True,
    "allow_short": True,
    "submit_vnpy_orders": True,
    "order_price_chase_ticks": 20,
    "daily_ema_period": 21,
    "daily_ema_slope_lookback": 3,
    "daily_ema_slope_min_atr": 0.1,
    "daily_macd_fast": 12,
    "daily_macd_slow": 26,
    "daily_macd_signal": 9,
    "daily_atr_period": 14,
    "daily_neutral_ema_band_atr": 0.3,
    "daily_max_ema_distance_atr": 2.5,
    "daily_effective_policy": DAILY_DIRECTION_EFFECTIVE_POLICY,
    "fill_policy": FILL_POLICY,
}


@dataclass(frozen=True)
class JmV1bFastEntryParams:
    entry_interval: str = "15m"
    fixed_size: int = 1
    ema_period: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    volume_window: int = 20
    volume_multiplier_15m: float = 1.0
    volume_multiplier_5m: float = 1.1
    pullback_lookback_bars: int = 3
    pullback_touch_ema_atr: float = 0.35
    max_ema_distance_atr_15m: float = 1.2
    max_ema_distance_atr_5m: float = 1.0
    max_hold_bars_min: int = 5
    max_hold_bars_max: int = 8
    stop_loss_atr_multiple: float = 1.5
    structure_stop_lookback_bars: int = 3
    stop_buffer_ticks: int = 2
    pricetick: float = 1.0
    allow_long: bool = True
    allow_short: bool = True
    submit_vnpy_orders: bool = True
    order_price_chase_ticks: int = 20
    daily_ema_period: int = 21
    daily_ema_slope_lookback: int = 3
    daily_ema_slope_min_atr: float = 0.1
    daily_macd_fast: int = 12
    daily_macd_slow: int = 26
    daily_macd_signal: int = 9
    daily_atr_period: int = 14
    daily_neutral_ema_band_atr: float = 0.3
    daily_max_ema_distance_atr: float = 2.5
    daily_effective_policy: str = DAILY_DIRECTION_EFFECTIVE_POLICY
    fill_policy: str = FILL_POLICY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def volume_multiplier(self) -> float:
        if self.entry_interval == "5m":
            return self.volume_multiplier_5m
        return self.volume_multiplier_15m

    @property
    def max_ema_distance_atr(self) -> float:
        if self.entry_interval == "5m":
            return self.max_ema_distance_atr_5m
        return self.max_ema_distance_atr_15m


def validate_params(raw_params: Mapping[str, Any] | None = None) -> JmV1bFastEntryParams:
    params = dict(DEFAULT_PARAMS)
    params.update(raw_params or {})
    validated = JmV1bFastEntryParams(**params)

    if validated.entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")
    _validate_positive_int("fixed_size", validated.fixed_size)
    _validate_positive_int("ema_period", validated.ema_period)
    _validate_positive_int("macd_fast", validated.macd_fast)
    _validate_positive_int("macd_slow", validated.macd_slow)
    _validate_positive_int("macd_signal", validated.macd_signal)
    _validate_positive_int("atr_period", validated.atr_period)
    _validate_positive_int("volume_window", validated.volume_window)
    _validate_positive_int("pullback_lookback_bars", validated.pullback_lookback_bars)
    _validate_positive_int("structure_stop_lookback_bars", validated.structure_stop_lookback_bars)
    _validate_positive_int("daily_ema_period", validated.daily_ema_period)
    _validate_positive_int("daily_ema_slope_lookback", validated.daily_ema_slope_lookback)
    _validate_positive_int("daily_macd_fast", validated.daily_macd_fast)
    _validate_positive_int("daily_macd_slow", validated.daily_macd_slow)
    _validate_positive_int("daily_macd_signal", validated.daily_macd_signal)
    _validate_positive_int("daily_atr_period", validated.daily_atr_period)
    _validate_positive_float("volume_multiplier_15m", validated.volume_multiplier_15m)
    _validate_positive_float("volume_multiplier_5m", validated.volume_multiplier_5m)
    _validate_positive_float("pullback_touch_ema_atr", validated.pullback_touch_ema_atr)
    _validate_positive_float("max_ema_distance_atr_15m", validated.max_ema_distance_atr_15m)
    _validate_positive_float("max_ema_distance_atr_5m", validated.max_ema_distance_atr_5m)
    _validate_positive_float("stop_loss_atr_multiple", validated.stop_loss_atr_multiple)
    _validate_positive_float("pricetick", validated.pricetick)
    _validate_positive_float("daily_ema_slope_min_atr", validated.daily_ema_slope_min_atr)
    _validate_positive_float("daily_neutral_ema_band_atr", validated.daily_neutral_ema_band_atr)
    _validate_positive_float("daily_max_ema_distance_atr", validated.daily_max_ema_distance_atr)

    if validated.macd_fast >= validated.macd_slow:
        raise ValueError("macd_fast must be less than macd_slow")
    if validated.daily_macd_fast >= validated.daily_macd_slow:
        raise ValueError("daily_macd_fast must be less than daily_macd_slow")
    if validated.max_hold_bars_min != 5:
        raise ValueError("max_hold_bars_min must be 5 for V1-B")
    if validated.max_hold_bars_max != 8:
        raise ValueError("max_hold_bars_max must be 8 for V1-B")
    if validated.stop_buffer_ticks < 0:
        raise ValueError("stop_buffer_ticks cannot be negative")
    if validated.order_price_chase_ticks < 0:
        raise ValueError("order_price_chase_ticks cannot be negative")
    if not validated.allow_long and not validated.allow_short:
        raise ValueError("at least one of allow_long or allow_short must be enabled")
    if validated.daily_effective_policy != DAILY_DIRECTION_EFFECTIVE_POLICY:
        raise ValueError(f"daily_effective_policy must be {DAILY_DIRECTION_EFFECTIVE_POLICY}")
    if validated.fill_policy != FILL_POLICY:
        raise ValueError(f"fill_policy must be {FILL_POLICY}")
    if not isinstance(validated.submit_vnpy_orders, bool):
        raise ValueError("submit_vnpy_orders must be a boolean")
    return validated


def _validate_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_positive_float(name: str, value: float) -> None:
    if not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be a positive number")

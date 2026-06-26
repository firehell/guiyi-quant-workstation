from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


DEFAULT_PARAMS = {
    "ema_period": 21,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_window": 20,
    "volume_multiplier": 1.2,
    "atr_period": 14,
    "stop_atr_multiple": 2.0,
    "take_profit_r_multiple": 2.5,
    "max_ema_deviation_atr": 1.5,
    "allow_long": True,
    "allow_short": True,
}


@dataclass(frozen=True)
class SuBingEma21Params:
    ema_period: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_window: int = 20
    volume_multiplier: float = 1.2
    atr_period: int = 14
    stop_atr_multiple: float = 2.0
    take_profit_r_multiple: float = 2.5
    max_ema_deviation_atr: float = 1.5
    allow_long: bool = True
    allow_short: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_params(raw_params: Mapping[str, Any] | None = None) -> SuBingEma21Params:
    params = dict(DEFAULT_PARAMS)
    params.update(raw_params or {})
    validated = SuBingEma21Params(**params)
    _validate_positive_int("ema_period", validated.ema_period)
    _validate_positive_int("macd_fast", validated.macd_fast)
    _validate_positive_int("macd_slow", validated.macd_slow)
    _validate_positive_int("macd_signal", validated.macd_signal)
    _validate_positive_int("volume_window", validated.volume_window)
    _validate_positive_int("atr_period", validated.atr_period)
    _validate_positive_float("volume_multiplier", validated.volume_multiplier)
    _validate_positive_float("stop_atr_multiple", validated.stop_atr_multiple)
    _validate_positive_float("take_profit_r_multiple", validated.take_profit_r_multiple)
    _validate_positive_float("max_ema_deviation_atr", validated.max_ema_deviation_atr)
    if validated.macd_fast >= validated.macd_slow:
        raise ValueError("macd_fast must be less than macd_slow")
    if not validated.allow_long and not validated.allow_short:
        raise ValueError("at least one of allow_long or allow_short must be enabled")
    return validated


def _validate_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_positive_float(name: str, value: float) -> None:
    if not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} must be a positive number")

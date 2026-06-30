from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping


STRATEGY_CODE = "su_bing_jm_daily_ema21_macd_volume"
STRATEGY_VERSION = "v0.3.0-daily-score2of4"
FILL_POLICY = "daily_close_signal_next_daily_open_fill"
REVERSE_POLICY = "no_same_daily_bar_reverse"


DEFAULT_PARAMS: dict[str, Any] = {
    "strategy_code": STRATEGY_CODE,
    "strategy_version": STRATEGY_VERSION,
    "interval": "1d",
    "product": "JM",
    "ema_period": 21,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "macd_zero_threshold": 25,
    "min_entry_score": 2,
    "require_directional_anchor": True,
    "ambiguous_tie_action": "reject",
    "emit_skill_tags": True,
    "maximum_position": 1,
    "allow_long": True,
    "allow_short": True,
    "slippage_ticks": 1,
    "stop_loss_enabled": False,
    "take_profit_enabled": False,
    "time_exit_enabled": False,
    "submit_vnpy_orders": False,
    "live_trading_enabled": False,
    "auto_order_enabled": False,
    "price_tick": None,
    "contract_multiplier": None,
    "commission_rate": None,
    "commission_per_contract": None,
    "margin_rate": None,
    "fill_policy": FILL_POLICY,
    "reverse_policy": REVERSE_POLICY,
}


@dataclass(frozen=True)
class SuBingJmDailyScore2Of4Params:
    strategy_code: str = STRATEGY_CODE
    strategy_version: str = STRATEGY_VERSION
    interval: str = "1d"
    product: str = "JM"
    ema_period: int = 21
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_zero_threshold: float = 25
    min_entry_score: int = 2
    require_directional_anchor: bool = True
    ambiguous_tie_action: str = "reject"
    emit_skill_tags: bool = True
    maximum_position: int = 1
    allow_long: bool = True
    allow_short: bool = True
    slippage_ticks: int = 1
    stop_loss_enabled: bool = False
    take_profit_enabled: bool = False
    time_exit_enabled: bool = False
    submit_vnpy_orders: bool = False
    live_trading_enabled: bool = False
    auto_order_enabled: bool = False
    price_tick: float | None = None
    contract_multiplier: int | None = None
    commission_rate: float | None = None
    commission_per_contract: float | None = None
    margin_rate: float | None = None
    fill_policy: str = FILL_POLICY
    reverse_policy: str = REVERSE_POLICY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_params(raw_params: Mapping[str, Any] | None = None) -> SuBingJmDailyScore2Of4Params:
    allowed = {field.name for field in fields(SuBingJmDailyScore2Of4Params)}
    params = dict(DEFAULT_PARAMS)
    params.update({key: value for key, value in dict(raw_params or {}).items() if key in allowed})
    validated = SuBingJmDailyScore2Of4Params(**params)

    if validated.strategy_code != STRATEGY_CODE:
        raise ValueError(f"strategy_code must be {STRATEGY_CODE}")
    if validated.strategy_version != STRATEGY_VERSION:
        raise ValueError(f"strategy_version must be {STRATEGY_VERSION}")
    if validated.interval != "1d":
        raise ValueError("interval must be 1d")
    if validated.product != "JM":
        raise ValueError("product must be JM")
    _validate_exact_int("ema_period", validated.ema_period, 21)
    _validate_exact_int("macd_fast", validated.macd_fast, 12)
    _validate_exact_int("macd_slow", validated.macd_slow, 26)
    _validate_exact_int("macd_signal", validated.macd_signal, 9)
    _validate_positive_number("macd_zero_threshold", validated.macd_zero_threshold)
    if validated.macd_fast >= validated.macd_slow:
        raise ValueError("macd_fast must be less than macd_slow")
    if not isinstance(validated.min_entry_score, int) or not 1 <= validated.min_entry_score <= 4:
        raise ValueError("min_entry_score must be an integer from 1 to 4")
    if validated.require_directional_anchor is not True:
        raise ValueError("require_directional_anchor must stay true")
    if validated.ambiguous_tie_action != "reject":
        raise ValueError("ambiguous_tie_action must be reject")
    if validated.emit_skill_tags is not True:
        raise ValueError("emit_skill_tags must stay true")
    _validate_exact_int("maximum_position", validated.maximum_position, 1)
    _validate_exact_int("slippage_ticks", validated.slippage_ticks, 1)
    if not validated.allow_long and not validated.allow_short:
        raise ValueError("at least one of allow_long or allow_short must be enabled")
    if validated.stop_loss_enabled:
        raise ValueError("stop_loss_enabled must stay false")
    if validated.take_profit_enabled:
        raise ValueError("take_profit_enabled must stay false")
    if validated.time_exit_enabled:
        raise ValueError("time_exit_enabled must stay false")
    if validated.submit_vnpy_orders:
        raise ValueError("submit_vnpy_orders must stay false")
    if validated.live_trading_enabled:
        raise ValueError("live_trading_enabled must stay false")
    if validated.auto_order_enabled:
        raise ValueError("auto_order_enabled must stay false")
    if validated.fill_policy != FILL_POLICY:
        raise ValueError(f"fill_policy must be {FILL_POLICY}")
    if validated.reverse_policy != REVERSE_POLICY:
        raise ValueError(f"reverse_policy must be {REVERSE_POLICY}")
    _validate_optional_positive_float("price_tick", validated.price_tick)
    _validate_optional_positive_int("contract_multiplier", validated.contract_multiplier)
    _validate_optional_non_negative_float("commission_rate", validated.commission_rate)
    _validate_optional_non_negative_float("commission_per_contract", validated.commission_per_contract)
    _validate_optional_positive_float("margin_rate", validated.margin_rate)
    return validated


def _validate_exact_int(name: str, value: int, expected: int) -> None:
    if not isinstance(value, int) or value != expected:
        raise ValueError(f"{name} must be {expected}")


def _validate_positive_number(name: str, value: float) -> None:
    if not isinstance(value, int | float) or float(value) <= 0:
        raise ValueError(f"{name} must be a positive number")


def _validate_optional_positive_int(name: str, value: int | None) -> None:
    if value is not None and (not isinstance(value, int) or value <= 0):
        raise ValueError(f"{name} must be a positive integer when provided")


def _validate_optional_positive_float(name: str, value: float | None) -> None:
    if value is not None and (not isinstance(value, int | float) or value <= 0):
        raise ValueError(f"{name} must be a positive number when provided")


def _validate_optional_non_negative_float(name: str, value: float | None) -> None:
    if value is not None and (not isinstance(value, int | float) or value < 0):
        raise ValueError(f"{name} must be a non-negative number when provided")

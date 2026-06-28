from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping


STRATEGY_CODE = "su_bing_jm_v1b_short_hold"
STRATEGY_VERSION = "v0.1.1-spec"
FILL_POLICY = "signal_on_close_fill_next_bar_open"
DAILY_EFFECTIVE_POLICY = "confirmed_daily_bar_effective_next_trading_day"


DEFAULT_PARAMS: dict[str, Any] = {
    "strategy_code": STRATEGY_CODE,
    "strategy_version": STRATEGY_VERSION,
    "entry_interval": "15m",
    "ema_period": 21,
    "daily_ema_period": 21,
    "pullback_lookback_bars": 3,
    "pullback_interaction_ticks": 1,
    "max_entry_ema_distance_ticks": 8,
    "stop_buffer_ticks": 1,
    "max_initial_stop_distance_ticks": 30,
    "take_profit_enabled": True,
    "take_profit_r_multiple": 1.5,
    "planned_time_exit_bars": 8,
    "slippage_ticks": 1,
    "initial_capital": 1_000_000,
    "risk_per_trade_ratio": 0.005,
    "maximum_position": 1,
    "max_entries_per_trading_day_per_interval": 2,
    "allow_long": True,
    "allow_short": True,
    "breakout_breakdown_enabled": False,
    "volume_confirmation_enabled": False,
    "macd_usage": "record_only_not_filter",
    "price_tick": None,
    "contract_multiplier": None,
    "commission_rate": None,
    "commission_per_contract": None,
    "margin_rate": None,
    "submit_vnpy_orders": False,
    "fill_policy": FILL_POLICY,
    "daily_effective_policy": DAILY_EFFECTIVE_POLICY,
}


@dataclass(frozen=True)
class SuBingJmV1bShortHoldParams:
    strategy_code: str = STRATEGY_CODE
    strategy_version: str = STRATEGY_VERSION
    entry_interval: str = "15m"
    ema_period: int = 21
    daily_ema_period: int = 21
    pullback_lookback_bars: int = 3
    pullback_interaction_ticks: int = 1
    max_entry_ema_distance_ticks: int = 8
    stop_buffer_ticks: int = 1
    max_initial_stop_distance_ticks: int = 30
    take_profit_enabled: bool = True
    take_profit_r_multiple: float = 1.5
    planned_time_exit_bars: int = 8
    slippage_ticks: int = 1
    initial_capital: int = 1_000_000
    risk_per_trade_ratio: float = 0.005
    maximum_position: int = 1
    max_entries_per_trading_day_per_interval: int = 2
    allow_long: bool = True
    allow_short: bool = True
    breakout_breakdown_enabled: bool = False
    volume_confirmation_enabled: bool = False
    macd_usage: str = "record_only_not_filter"
    price_tick: float | None = None
    contract_multiplier: int | None = None
    commission_rate: float | None = None
    commission_per_contract: float | None = None
    margin_rate: float | None = None
    submit_vnpy_orders: bool = False
    fill_policy: str = FILL_POLICY
    daily_effective_policy: str = DAILY_EFFECTIVE_POLICY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_params(raw_params: Mapping[str, Any] | None = None) -> SuBingJmV1bShortHoldParams:
    allowed = {field.name for field in fields(SuBingJmV1bShortHoldParams)}
    params = dict(DEFAULT_PARAMS)
    params.update({key: value for key, value in dict(raw_params or {}).items() if key in allowed})
    validated = SuBingJmV1bShortHoldParams(**params)

    if validated.strategy_code != STRATEGY_CODE:
        raise ValueError(f"strategy_code must be {STRATEGY_CODE}")
    if validated.strategy_version != STRATEGY_VERSION:
        raise ValueError(f"strategy_version must be {STRATEGY_VERSION}")
    if validated.entry_interval not in {"15m", "5m"}:
        raise ValueError("entry_interval must be one of: 15m, 5m")
    _validate_positive_int("ema_period", validated.ema_period)
    _validate_positive_int("daily_ema_period", validated.daily_ema_period)
    _validate_exact("pullback_lookback_bars", validated.pullback_lookback_bars, 3)
    _validate_exact("pullback_interaction_ticks", validated.pullback_interaction_ticks, 1)
    _validate_exact("max_entry_ema_distance_ticks", validated.max_entry_ema_distance_ticks, 8)
    _validate_exact("stop_buffer_ticks", validated.stop_buffer_ticks, 1)
    _validate_exact("max_initial_stop_distance_ticks", validated.max_initial_stop_distance_ticks, 30)
    if validated.take_profit_enabled is not True:
        raise ValueError("take_profit_enabled must stay true for v0.1.1")
    if validated.take_profit_r_multiple != 1.5:
        raise ValueError("take_profit_r_multiple must be 1.5 for v0.1.1")
    _validate_exact("planned_time_exit_bars", validated.planned_time_exit_bars, 8)
    _validate_exact("slippage_ticks", validated.slippage_ticks, 1)
    _validate_exact("initial_capital", validated.initial_capital, 1_000_000)
    if validated.risk_per_trade_ratio != 0.005:
        raise ValueError("risk_per_trade_ratio must be 0.005 for v0.1.1")
    _validate_exact("maximum_position", validated.maximum_position, 1)
    _validate_exact(
        "max_entries_per_trading_day_per_interval",
        validated.max_entries_per_trading_day_per_interval,
        2,
    )
    if not validated.allow_long and not validated.allow_short:
        raise ValueError("at least one of allow_long or allow_short must be enabled")
    if validated.breakout_breakdown_enabled:
        raise ValueError("breakout_breakdown_enabled must stay false for v0.1.1")
    if validated.volume_confirmation_enabled:
        raise ValueError("volume_confirmation_enabled must stay false for v0.1.1")
    if validated.macd_usage != "record_only_not_filter":
        raise ValueError("macd_usage must be record_only_not_filter for v0.1.1")
    if validated.fill_policy != FILL_POLICY:
        raise ValueError(f"fill_policy must be {FILL_POLICY}")
    if validated.daily_effective_policy != DAILY_EFFECTIVE_POLICY:
        raise ValueError(f"daily_effective_policy must be {DAILY_EFFECTIVE_POLICY}")
    if not isinstance(validated.submit_vnpy_orders, bool):
        raise ValueError("submit_vnpy_orders must be a boolean")
    _validate_optional_positive_float("price_tick", validated.price_tick)
    _validate_optional_positive_int("contract_multiplier", validated.contract_multiplier)
    _validate_optional_non_negative_float("commission_rate", validated.commission_rate)
    _validate_optional_non_negative_float("commission_per_contract", validated.commission_per_contract)
    _validate_optional_positive_float("margin_rate", validated.margin_rate)
    return validated


def _validate_exact(name: str, value: int, expected: int) -> None:
    if value != expected:
        raise ValueError(f"{name} must be {expected} for v0.1.1")


def _validate_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_optional_positive_int(name: str, value: int | None) -> None:
    if value is not None and (not isinstance(value, int) or value <= 0):
        raise ValueError(f"{name} must be a positive integer when provided")


def _validate_optional_positive_float(name: str, value: float | None) -> None:
    if value is not None and (not isinstance(value, int | float) or value <= 0):
        raise ValueError(f"{name} must be a positive number when provided")


def _validate_optional_non_negative_float(name: str, value: float | None) -> None:
    if value is not None and (not isinstance(value, int | float) or value < 0):
        raise ValueError(f"{name} must be a non-negative number when provided")

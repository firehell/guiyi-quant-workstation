from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping


INDICATOR_VERSION = "huotian_dayou_strict_v1"
STRATEGY_CODE = "huotian_dayou_strict"
STRATEGY_VERSION = "v0.1.0-backtest-candidate"
CANDIDATE_POLICY = "strict_v1_15m_formal_candidate_v0"
FILL_POLICY = "signal_on_close_fill_next_bar_open"
EXECUTION_SCOPE = "formal_backtest_candidate"
COST_MODEL_VERSION = "cost_model_v1_rate_slippage_size"
RESEARCH_STATUS = "backtest_candidate"
EXECUTION_TIMING = "next_bar_open"
INDICATOR_VERSIONS = (INDICATOR_VERSION,)
FORMAL_POLICY_IDS = (INDICATOR_VERSION,)


DEFAULT_PARAMS: dict[str, Any] = {
    "indicator_version": INDICATOR_VERSION,
    "indicator_versions": list(INDICATOR_VERSIONS),
    "formal_policy_ids": list(FORMAL_POLICY_IDS),
    "confirmed_only": True,
    "execution_timing": EXECUTION_TIMING,
    "cost_model_version": COST_MODEL_VERSION,
    "research_status": RESEARCH_STATUS,
    "strategy_code": STRATEGY_CODE,
    "strategy_version": STRATEGY_VERSION,
    "candidate_policy": CANDIDATE_POLICY,
    "execution_scope": EXECUTION_SCOPE,
    "entry_interval": "15m",
    "channel_period": 25,
    "var23_period": 6,
    "stop_buffer_ticks": 1,
    "take_profit_r_multiple": 1.5,
    "planned_time_exit_bars": 8,
    "min_hold_bars": 5,
    "slippage_ticks": 1,
    "initial_capital": 1_000_000,
    "risk_per_trade_ratio": 0.005,
    "maximum_position": 1,
    "allow_long": True,
    "allow_short": True,
    "price_tick": None,
    "contract_multiplier": None,
    "commission_rate": None,
    "commission_per_contract": None,
    "margin_rate": None,
    "submit_vnpy_orders": False,
    "fill_policy": FILL_POLICY,
    "reverse_policy": "close_first_no_same_bar_reverse",
    "conflict_policy": "skip_conflict_candidate",
    "same_bar_exit_priority": "stop_loss_before_take_profit",
}


@dataclass(frozen=True)
class HuoTianDaYouStrictParams:
    indicator_version: str = INDICATOR_VERSION
    indicator_versions: tuple[str, ...] | list[str] = INDICATOR_VERSIONS
    formal_policy_ids: tuple[str, ...] | list[str] = FORMAL_POLICY_IDS
    confirmed_only: bool = True
    execution_timing: str = EXECUTION_TIMING
    cost_model_version: str = COST_MODEL_VERSION
    research_status: str = RESEARCH_STATUS
    strategy_code: str = STRATEGY_CODE
    strategy_version: str = STRATEGY_VERSION
    candidate_policy: str = CANDIDATE_POLICY
    execution_scope: str = EXECUTION_SCOPE
    entry_interval: str = "15m"
    channel_period: int = 25
    var23_period: int = 6
    stop_buffer_ticks: int = 1
    take_profit_r_multiple: float = 1.5
    planned_time_exit_bars: int = 8
    min_hold_bars: int = 5
    slippage_ticks: int = 1
    initial_capital: int = 1_000_000
    risk_per_trade_ratio: float = 0.005
    maximum_position: int = 1
    allow_long: bool = True
    allow_short: bool = True
    price_tick: float | None = None
    contract_multiplier: int | None = None
    commission_rate: float | None = None
    commission_per_contract: float | None = None
    margin_rate: float | None = None
    submit_vnpy_orders: bool = False
    fill_policy: str = FILL_POLICY
    reverse_policy: str = "close_first_no_same_bar_reverse"
    conflict_policy: str = "skip_conflict_candidate"
    same_bar_exit_priority: str = "stop_loss_before_take_profit"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_params(raw_params: Mapping[str, Any] | None = None) -> HuoTianDaYouStrictParams:
    allowed = {field.name for field in fields(HuoTianDaYouStrictParams)}
    params = dict(DEFAULT_PARAMS)
    params.update({key: value for key, value in dict(raw_params or {}).items() if key in allowed})
    validated = HuoTianDaYouStrictParams(**params)

    _validate_exact("indicator_version", validated.indicator_version, INDICATOR_VERSION)
    _validate_exact("strategy_code", validated.strategy_code, STRATEGY_CODE)
    _validate_exact("strategy_version", validated.strategy_version, STRATEGY_VERSION)
    _validate_exact("candidate_policy", validated.candidate_policy, CANDIDATE_POLICY)
    _validate_exact("execution_scope", validated.execution_scope, EXECUTION_SCOPE)
    _validate_exact("entry_interval", validated.entry_interval, "15m")
    _validate_exact("execution_timing", validated.execution_timing, EXECUTION_TIMING)
    _validate_exact("cost_model_version", validated.cost_model_version, COST_MODEL_VERSION)
    _validate_exact("research_status", validated.research_status, RESEARCH_STATUS)
    if validated.confirmed_only is not True:
        raise ValueError("confirmed_only must be true for HTDY strict candidate")
    indicator_versions = tuple(validated.indicator_versions)
    formal_policy_ids = tuple(validated.formal_policy_ids)
    if indicator_versions != INDICATOR_VERSIONS:
        raise ValueError(f"indicator_versions must be {list(INDICATOR_VERSIONS)!r}")
    if formal_policy_ids != FORMAL_POLICY_IDS:
        raise ValueError(f"formal_policy_ids must be {list(FORMAL_POLICY_IDS)!r}")
    forbidden = {"huotian_dayou_original_v0", "huo_tian_da_you"}
    if forbidden.intersection(indicator_versions) or forbidden.intersection(formal_policy_ids):
        raise ValueError("huotian_dayou_strict cannot bind original_v0")
    _validate_positive_int("channel_period", validated.channel_period)
    _validate_positive_int("var23_period", validated.var23_period)
    _validate_exact("stop_buffer_ticks", validated.stop_buffer_ticks, 1)
    _validate_exact_float("take_profit_r_multiple", validated.take_profit_r_multiple, 1.5)
    _validate_exact("min_hold_bars", validated.min_hold_bars, 5)
    _validate_exact("planned_time_exit_bars", validated.planned_time_exit_bars, 8)
    _validate_exact("slippage_ticks", validated.slippage_ticks, 1)
    _validate_exact("initial_capital", validated.initial_capital, 1_000_000)
    _validate_exact_float("risk_per_trade_ratio", validated.risk_per_trade_ratio, 0.005)
    _validate_exact("maximum_position", validated.maximum_position, 1)
    if not validated.allow_long and not validated.allow_short:
        raise ValueError("at least one of allow_long or allow_short must be enabled")
    if validated.submit_vnpy_orders is not False:
        raise ValueError("submit_vnpy_orders must stay false for HTDY v0.1.0 candidate")
    _validate_exact("fill_policy", validated.fill_policy, FILL_POLICY)
    _validate_exact("reverse_policy", validated.reverse_policy, "close_first_no_same_bar_reverse")
    _validate_exact("conflict_policy", validated.conflict_policy, "skip_conflict_candidate")
    _validate_exact("same_bar_exit_priority", validated.same_bar_exit_priority, "stop_loss_before_take_profit")
    _validate_optional_positive_float("price_tick", validated.price_tick)
    _validate_optional_positive_int("contract_multiplier", validated.contract_multiplier)
    _validate_optional_non_negative_float("commission_rate", validated.commission_rate)
    _validate_optional_non_negative_float("commission_per_contract", validated.commission_per_contract)
    _validate_optional_positive_float("margin_rate", validated.margin_rate)
    return validated


def _validate_exact(name: str, value: Any, expected: Any) -> None:
    if value != expected:
        raise ValueError(f"{name} must be {expected!r} for {STRATEGY_VERSION}")


def _validate_exact_float(name: str, value: float, expected: float) -> None:
    if float(value) != expected:
        raise ValueError(f"{name} must be {expected} for {STRATEGY_VERSION}")


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

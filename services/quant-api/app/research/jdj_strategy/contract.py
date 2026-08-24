"""Strict, research-only JDJ V1 strategy profile contract."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.env import PROJECT_ROOT
from app.core.exact_json_contract import load_exact_json
from app.market_data.domain import BarFrequency


JDJ_V1_PROFILE_PATH = PROJECT_ROOT / "data/strategy_profiles/jdj_v1.json"
_DEFAULT_PROFILE_ID = "jdj_active60_1m_v1"
_EXPECTED_PAYLOAD: dict[str, Any] = {
    "schema_version": 2,
    "strategy_id": "jdj_intraday_futures_v1",
    "core_rules": {
        "minimum_reward_risk": "2.0",
        "max_planned_trade_risk_fraction": "0.01",
        "require_profit_before_add": True,
        "require_partial_profit_before_add": True,
        "add_fraction_of_current_qty": "0.25",
        "max_add_count": 2,
        "losing_position_add_forbidden": True,
        "daily_pause_drawdown_fraction": "0.005",
        "daily_pause_bars": 15,
        "daily_stop_drawdown_fraction": "0.01",
    },
    "profiles": {
        _DEFAULT_PROFILE_ID: {
            "product_scope_source": "active_products",
            "series_kind": "actual_dominant",
            "execution_frequency": "1m",
            "trend_context_frequency": "5m",
            "base_risk_fraction": "0.005",
            "first_profit_take_fraction": "0.40",
            "historical_reference_start_equity": "1000000",
            "entry_limit_valid_bars": 1,
            "terminal_flatten_lead_bars": 1,
        }
    },
}


class JdjStrategyContractError(ValueError):
    code = "JDJ_STRATEGY_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjCoreRules:
    minimum_reward_risk: Decimal
    max_planned_trade_risk_fraction: Decimal
    require_profit_before_add: bool
    require_partial_profit_before_add: bool
    add_fraction_of_current_qty: Decimal
    max_add_count: int
    losing_position_add_forbidden: bool
    daily_pause_drawdown_fraction: Decimal
    daily_pause_bars: int
    daily_stop_drawdown_fraction: Decimal


@dataclass(frozen=True, slots=True)
class JdjStrategyProfile:
    profile_id: str
    product_scope_source: str
    series_kind: str
    execution_frequency: BarFrequency
    trend_context_frequency: BarFrequency
    base_risk_fraction: Decimal
    first_profit_take_fraction: Decimal
    historical_reference_start_equity: Decimal
    entry_limit_valid_bars: int
    terminal_flatten_lead_bars: int


@dataclass(frozen=True, slots=True)
class JdjV1Config:
    strategy_id: str
    core: JdjCoreRules
    profile: JdjStrategyProfile


def load_jdj_v1_config(profile_id: str = _DEFAULT_PROFILE_ID) -> JdjV1Config:
    """Load the one frozen JDJ V1 profile, rejecting all shape or value drift."""

    if type(profile_id) is not str or profile_id != _DEFAULT_PROFILE_ID:
        raise JdjStrategyContractError()
    payload = load_exact_json(
        JDJ_V1_PROFILE_PATH,
        _EXPECTED_PAYLOAD,
        JdjStrategyContractError,
    )
    core_rules = payload["core_rules"]
    profile = payload["profiles"][profile_id]

    return JdjV1Config(
        strategy_id=payload["strategy_id"],
        core=JdjCoreRules(
            minimum_reward_risk=Decimal(core_rules["minimum_reward_risk"]),
            max_planned_trade_risk_fraction=Decimal(
                core_rules["max_planned_trade_risk_fraction"]
            ),
            require_profit_before_add=core_rules["require_profit_before_add"],
            require_partial_profit_before_add=core_rules[
                "require_partial_profit_before_add"
            ],
            add_fraction_of_current_qty=Decimal(
                core_rules["add_fraction_of_current_qty"]
            ),
            max_add_count=core_rules["max_add_count"],
            losing_position_add_forbidden=core_rules[
                "losing_position_add_forbidden"
            ],
            daily_pause_drawdown_fraction=Decimal(
                core_rules["daily_pause_drawdown_fraction"]
            ),
            daily_pause_bars=core_rules["daily_pause_bars"],
            daily_stop_drawdown_fraction=Decimal(
                core_rules["daily_stop_drawdown_fraction"]
            ),
        ),
        profile=JdjStrategyProfile(
            profile_id=profile_id,
            product_scope_source=profile["product_scope_source"],
            series_kind=profile["series_kind"],
            execution_frequency=BarFrequency(profile["execution_frequency"]),
            trend_context_frequency=BarFrequency(profile["trend_context_frequency"]),
            base_risk_fraction=Decimal(profile["base_risk_fraction"]),
            first_profit_take_fraction=Decimal(profile["first_profit_take_fraction"]),
            historical_reference_start_equity=Decimal(
                profile["historical_reference_start_equity"]
            ),
            entry_limit_valid_bars=profile["entry_limit_valid_bars"],
            terminal_flatten_lead_bars=profile["terminal_flatten_lead_bars"],
        ),
    )

from __future__ import annotations

import importlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.domain import BarFrequency


def _contract_module():
    module_name = "app.research.jdj_strategy.contract"
    assert importlib.util.find_spec(module_name) is not None
    return importlib.import_module(module_name)


def test_active_products_profile_loads_the_frozen_decimal_contract() -> None:
    contract = _contract_module()

    config = contract.load_jdj_v1_config()

    assert config.strategy_id == "jdj_intraday_futures_v1"
    assert config.core.minimum_reward_risk == Decimal("2.0")
    assert config.core.max_planned_trade_risk_fraction == Decimal("0.01")
    assert config.core.require_profit_before_add is True
    assert config.core.require_partial_profit_before_add is True
    assert config.core.add_fraction_of_current_qty == Decimal("0.25")
    assert config.core.max_add_count == 2
    assert config.core.losing_position_add_forbidden is True
    assert config.core.daily_pause_drawdown_fraction == Decimal("0.005")
    assert config.core.daily_pause_bars == 15
    assert config.core.daily_stop_drawdown_fraction == Decimal("0.01")
    assert config.profile.profile_id == "jdj_active60_1m_v1"
    assert config.profile.product_scope_source == "active_products"
    assert not hasattr(config.profile, "symbol")
    assert config.profile.series_kind == "actual_dominant"
    assert config.profile.execution_frequency is BarFrequency.M1
    assert config.profile.trend_context_frequency is BarFrequency.M5
    assert config.profile.base_risk_fraction == Decimal("0.005")
    assert config.profile.first_profit_take_fraction == Decimal("0.40")
    assert config.profile.historical_reference_start_equity == Decimal("1000000")
    assert config.profile.entry_limit_valid_bars == 1
    assert config.profile.terminal_flatten_lead_bars == 1


def test_unknown_profile_fails_closed() -> None:
    contract = _contract_module()

    with pytest.raises(contract.JdjStrategyContractError):
        contract.load_jdj_v1_config("unknown")


@pytest.mark.parametrize(
    ("mutation", "description"),
    (
        (
            lambda payload: payload["core_rules"].pop("max_add_count"),
            "missing field",
        ),
        (
            lambda payload: payload["profiles"]["jdj_active60_1m_v1"].update(
                unexpected_knob=True
            ),
            "extra field",
        ),
        (
            lambda payload: payload["core_rules"].update(
                minimum_reward_risk="1.5"
            ),
            "drifted field",
        ),
        (
            lambda payload: payload["profiles"]["jdj_active60_1m_v1"].update(
                product_scope_source="all_products"
            ),
            "unsupported product scope",
        ),
        (
            lambda payload: payload["profiles"]["jdj_active60_1m_v1"].update(
                per_product_overrides={"jm": {}}
            ),
            "per-product override",
        ),
        (
            lambda payload: payload.update(schema_version=1),
            "old schema version",
        ),
    ),
)
def test_malformed_or_drifted_profile_contract_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: object,
    description: str,
) -> None:
    contract = _contract_module()
    payload = json.loads(contract.JDJ_V1_PROFILE_PATH.read_text(encoding="utf-8"))
    assert callable(mutation), description
    mutation(payload)
    path = tmp_path / "jdj_v1.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(contract, "JDJ_V1_PROFILE_PATH", path)

    with pytest.raises(contract.JdjStrategyContractError):
        contract.load_jdj_v1_config()

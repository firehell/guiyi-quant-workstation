from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from guiyi_quant.indicators import ema_series, get_indicator, require_formal_policy

from app.live_review_loop.contracts import (
    APPROVED_INDICATOR_CODE,
    APPROVED_INDICATOR_VERSION,
    APPROVED_PARAMETERS,
    APPROVED_POLICY_ID,
    APPROVED_RECIPE_VERSION,
    APPROVED_STRATEGY_CODE,
    APPROVED_STRATEGY_VERSION,
    FINGERPRINT_RECIPE_VERSION,
    PARAMETER_SCHEMA_VERSION,
    StrategyInputSchema,
    canonical_digest,
)
from app.models.live_review_loop import SignalDecision


class ApprovedEma21DirectionEvaluator:
    """The single Task06 evaluator: confirmed JM 15m close versus causal EMA21."""

    def evaluate_schema(self, strategy_input: StrategyInputSchema) -> Mapping[str, Any]:
        _validate_schema_contract(strategy_input)
        return _evaluate_snapshot(strategy_input.snapshot)

    def __call__(
        self,
        decision: SignalDecision,
        snapshot: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        _validate_snapshot_contract(snapshot)
        strategy = snapshot["strategy"]
        mapping = snapshot["mapping"]
        expected_parameter_digest = canonical_digest(
            {
                "schema_version": PARAMETER_SCHEMA_VERSION,
                "parameters": strategy["parameters"],
            }
        )
        expected_fingerprint = canonical_digest(
            {
                "fingerprint_recipe_version": FINGERPRINT_RECIPE_VERSION,
                "input_digest": decision.input_digest,
                "strategy_code": APPROVED_STRATEGY_CODE,
                "strategy_version": APPROVED_STRATEGY_VERSION,
                "policy_id": APPROVED_POLICY_ID,
                "parameter_digest": expected_parameter_digest,
                "recipe_version": APPROVED_RECIPE_VERSION,
            }
        )
        if (
            decision.strategy_code != APPROVED_STRATEGY_CODE
            or decision.strategy_version != APPROVED_STRATEGY_VERSION
            or decision.policy_id != APPROVED_POLICY_ID
            or decision.parameter_digest != expected_parameter_digest
            or decision.fingerprint != expected_fingerprint
            or decision.actual_contract != mapping.get("actual_contract")
            or decision.trading_day.isoformat() != mapping.get("trading_day")
        ):
            raise ValueError("EMA21_EVALUATOR_CONTRACT_INVALID")
        return _evaluate_snapshot(snapshot)


def _validate_schema_contract(strategy_input: StrategyInputSchema) -> None:
    expected = (
        APPROVED_STRATEGY_CODE,
        APPROVED_STRATEGY_VERSION,
        APPROVED_INDICATOR_CODE,
        APPROVED_INDICATOR_VERSION,
        APPROVED_POLICY_ID,
        APPROVED_RECIPE_VERSION,
    )
    actual = (
        strategy_input.strategy_code,
        strategy_input.strategy_version,
        strategy_input.indicator_code,
        strategy_input.indicator_version,
        strategy_input.policy_id,
        strategy_input.recipe_version,
    )
    if actual != expected:
        raise ValueError("EMA21_EVALUATOR_CONTRACT_INVALID")
    _validate_snapshot_contract(strategy_input.snapshot)
    if canonical_digest(strategy_input.snapshot) != strategy_input.input_digest:
        raise ValueError("EMA21_EVALUATOR_INPUT_DIGEST_INVALID")
    strategy = strategy_input.snapshot["strategy"]
    mapping = strategy_input.snapshot["mapping"]
    expected_parameter_digest = canonical_digest(
        {
            "schema_version": PARAMETER_SCHEMA_VERSION,
            "parameters": strategy["parameters"],
        }
    )
    if (
        strategy_input.parameter_digest != expected_parameter_digest
        or strategy.get("parameter_digest") != expected_parameter_digest
        or strategy_input.trading_day.isoformat() != mapping.get("trading_day")
        or strategy_input.actual_contract != mapping.get("actual_contract")
    ):
        raise ValueError("EMA21_EVALUATOR_CONTRACT_INVALID")
    expected_fingerprint = canonical_digest(
        {
            "fingerprint_recipe_version": FINGERPRINT_RECIPE_VERSION,
            "input_digest": strategy_input.input_digest,
            "strategy_code": APPROVED_STRATEGY_CODE,
            "strategy_version": APPROVED_STRATEGY_VERSION,
            "policy_id": APPROVED_POLICY_ID,
            "parameter_digest": expected_parameter_digest,
            "recipe_version": APPROVED_RECIPE_VERSION,
        }
    )
    if strategy_input.fingerprint != expected_fingerprint:
        raise ValueError("EMA21_EVALUATOR_FINGERPRINT_INVALID")


def _validate_snapshot_contract(snapshot: Mapping[str, Any]) -> None:
    strategy = snapshot.get("strategy")
    decision_bar = snapshot.get("decision_bar")
    historical = snapshot.get("historical_input")
    mapping = snapshot.get("mapping")
    live_inputs = snapshot.get("live_inputs")
    if (
        not isinstance(strategy, Mapping)
        or not isinstance(decision_bar, Mapping)
        or not isinstance(historical, Mapping)
        or not isinstance(mapping, Mapping)
        or not isinstance(live_inputs, list)
    ):
        raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")
    expected_strategy = {
        "code": APPROVED_STRATEGY_CODE,
        "version": APPROVED_STRATEGY_VERSION,
        "indicator_code": APPROVED_INDICATOR_CODE,
        "indicator_version": APPROVED_INDICATOR_VERSION,
        "policy_id": APPROVED_POLICY_ID,
        "parameters": APPROVED_PARAMETERS,
        "recipe_version": APPROVED_RECIPE_VERSION,
        "purpose": "observation_only",
        "future_looking": False,
        "repainting_accepted": False,
        "historical_backtest_allowed": False,
        "auto_order": False,
    }
    if any(strategy.get(key) != value for key, value in expected_strategy.items()):
        raise ValueError("EMA21_EVALUATOR_CONTRACT_INVALID")
    bars = historical.get("bars")
    actual_contract = str(mapping.get("actual_contract", ""))
    trading_day = mapping.get("trading_day")
    dataset_key = historical.get("dataset_key")
    if (
        snapshot.get("trigger") != "confirmed_15m_close"
        or mapping.get("provider") != "rqdata"
        or mapping.get("product") != "jm"
        or mapping.get("rank") != 1
        or not actual_contract.startswith("JM")
        or actual_contract.endswith(".MAIN")
        or not isinstance(dataset_key, Mapping)
        or dataset_key.get("provider") != "rqdata"
        or dataset_key.get("dataset_kind") != "actual_dominant"
        or dataset_key.get("symbol") != "jm"
        or dataset_key.get("contract_or_series") != actual_contract
        or dataset_key.get("frequency") != "1m"
        or dataset_key.get("adjustment") != "none"
        or dataset_key.get("schema_version") != "canonical-bar-v1"
        or historical.get("data_role") != "primary"
        or historical.get("quality_status") != "passed"
        or historical.get("aggregation_recipe") != "trading_session_15m_v1"
        or decision_bar.get("provider") != "rqdata"
        or decision_bar.get("source_mode") != "session_aggregate_15m_v2"
        or decision_bar.get("product") != "jm"
        or decision_bar.get("actual_contract") != actual_contract
        or decision_bar.get("trading_day") != trading_day
        or decision_bar.get("confirmed") is not True
        or decision_bar.get("period") != "15m"
        or not isinstance(bars, list)
        or len(bars) != 128
        or len(live_inputs) != 15
    ):
        raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")

    decision_start = _datetime(decision_bar.get("source_start"))
    decision_end = _datetime(decision_bar.get("bar_end"))
    if _datetime(decision_bar.get("source_end")) != decision_end:
        raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")
    historical_ends = []
    for bar in bars:
        if not isinstance(bar, Mapping) or bar.get("period") != "15m":
            raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")
        _decimal(bar.get("close"))
        historical_ends.append(_datetime(bar.get("bar_end")))
    if (
        historical_ends != sorted(historical_ends)
        or len(set(historical_ends)) != 128
        or historical_ends[-1] > decision_start
    ):
        raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")

    live_ends = []
    live_starts = []
    for item in live_inputs:
        if (
            not isinstance(item, Mapping)
            or item.get("provider") != "rqdata"
            or item.get("source_mode") != "rqdata_live_1m_v2"
            or item.get("product") != "jm"
            or item.get("actual_contract") != actual_contract
            or item.get("trading_day") != trading_day
            or item.get("confirmed") is not True
            or item.get("period") != "1m"
        ):
            raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")
        live_end = _datetime(item.get("bar_end"))
        live_start = _datetime(item.get("source_start"))
        if _datetime(item.get("source_end")) != live_end or live_end - live_start != timedelta(minutes=1):
            raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")
        live_ends.append(live_end)
        live_starts.append(live_start)
    if (
        live_ends != [live_ends[0] + timedelta(minutes=index) for index in range(15)]
        or live_starts[0] != decision_start
        or live_ends[-1] != decision_end
        or any(value > decision_end for value in live_ends)
    ):
        raise ValueError("EMA21_EVALUATOR_INPUT_INVALID")


def _evaluate_snapshot(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate_snapshot_contract(snapshot)
    definition = get_indicator(APPROVED_INDICATOR_CODE)
    policy = require_formal_policy(APPROVED_POLICY_ID, consumer="live_confirmed")
    if (
        definition.indicator_version != APPROVED_INDICATOR_VERSION
        or definition.formal_policy_id != APPROVED_POLICY_ID
        or not definition.live_capable
        or not definition.confirmed_only
        or definition.repainting_risk != "none"
        or policy.seed_policy != APPROVED_PARAMETERS["seed_policy"]
    ):
        raise ValueError("EMA21_EVALUATOR_REGISTRY_CONTRACT_INVALID")

    historical = snapshot["historical_input"]
    decision_bar = snapshot["decision_bar"]
    bars = [*historical["bars"], decision_bar]
    closes = [_decimal(bar.get("close")) for bar in bars]
    bar_ends = [_bar_end(bar.get("bar_end")) for bar in bars]
    series = ema_series(
        [float(value) for value in closes],
        period=21,
        bar_ends=bar_ends,
        seed_policy="sma_window",
        indicator_code=APPROVED_INDICATOR_CODE,
        round_digits=6,
    )
    point = series.points[-1]
    if (
        len(series.points) != 129
        or not point.ready
        or not point.valid
        or point.value is None
        or point.bar_end != bar_ends[-1]
    ):
        raise ValueError("EMA21_EVALUATOR_OUTPUT_INVALID")

    decision_close = closes[-1]
    ema_value = Decimal(str(point.value))
    direction = "long" if decision_close > ema_value else "short" if decision_close < ema_value else None
    result_kind = "signal" if direction is not None else "no_signal"
    payload = {
        "comparison": "confirmed_close_vs_ema21",
        "decision_close": format(decision_close, "f"),
        "ema21": format(ema_value, "f"),
        "direction": direction,
        "indicator_code": APPROVED_INDICATOR_CODE,
        "indicator_version": APPROVED_INDICATOR_VERSION,
        "policy_id": APPROVED_POLICY_ID,
        "recipe_version": APPROVED_RECIPE_VERSION,
        "input_series_digest": canonical_digest(
            {"bar_ends": bar_ends, "closes": closes}
        ),
        "observation_only": True,
        "historical_backtest_allowed": False,
        "auto_order": False,
    }
    return {"result_kind": result_kind, "direction": direction, "payload": payload}


def _decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("EMA21_EVALUATOR_CLOSE_INVALID") from exc
    if not parsed.is_finite():
        raise ValueError("EMA21_EVALUATOR_CLOSE_INVALID")
    return parsed


def _bar_end(value: object) -> str:
    return _datetime(value).isoformat().replace("+00:00", "Z")


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("EMA21_EVALUATOR_BAR_END_INVALID") from exc
    else:
        raise ValueError("EMA21_EVALUATOR_BAR_END_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("EMA21_EVALUATOR_BAR_END_INVALID")
    return parsed.astimezone(UTC)

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


STRATEGY_INPUT_SCHEMA_VERSION = "strategy_input_v1"
FINGERPRINT_RECIPE_VERSION = "strategy_fingerprint_v1"
PARAMETER_SCHEMA_VERSION = "strategy_parameters_v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_FORBIDDEN_FUTURE_LOOKING_IDENTITIES = {
    "htdy_original_realtime_first_seen",
    "htdy_original_xma_15m_first_seen_v1",
    "htdy_original_xma_15m_close_first_seen_v1",
    "huotian_dayou_original_v0",
}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CANONICAL_DATETIME_TIMEZONE_REQUIRED")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("CANONICAL_MAPPING_STRING_KEYS_REQUIRED")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("CANONICAL_FLOAT_FINITE_REQUIRED")
        return format(Decimal(str(value)), "f")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError(f"CANONICAL_VALUE_UNSUPPORTED:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StrategyInputSchema:
    snapshot: dict[str, Any]
    input_digest: str
    fingerprint: str
    strategy_code: str
    strategy_version: str
    indicator_code: str
    indicator_version: str
    policy_id: str
    parameter_digest: str
    recipe_version: str
    trading_day: date
    actual_contract: str

    @classmethod
    def build(
        cls,
        *,
        strategy_code: str,
        strategy_version: str,
        indicator_code: str,
        indicator_version: str,
        policy_id: str,
        parameters: Mapping[str, Any],
        recipe_version: str,
        trading_day: date,
        actual_contract: str,
        decision_bar: Mapping[str, Any],
        historical_input: Mapping[str, Any],
        live_inputs: Sequence[Mapping[str, Any]],
    ) -> StrategyInputSchema:
        if not isinstance(parameters, Mapping):
            raise ValueError("STRATEGY_PARAMETERS_MAPPING_REQUIRED")
        normalized_parameters = _canonical_value(dict(parameters))
        parameter_digest = canonical_digest(
            {
                "schema_version": PARAMETER_SCHEMA_VERSION,
                "parameters": normalized_parameters,
            }
        )
        normalized_contract = actual_contract.strip().upper()
        if not normalized_contract.startswith("JM") or normalized_contract.endswith(
            ".MAIN"
        ):
            raise ValueError("STRATEGY_ACTUAL_CONTRACT_REQUIRED")
        _validate_decision_bar(
            decision_bar,
            trading_day=trading_day,
            actual_contract=normalized_contract,
        )
        _validate_strategy_contract(
            strategy_code=strategy_code,
            strategy_version=strategy_version,
            indicator_code=indicator_code,
            indicator_version=indicator_version,
            policy_id=policy_id,
            recipe_version=recipe_version,
        )
        _validate_historical_input(
            historical_input,
            actual_contract=normalized_contract,
            decision_bar=decision_bar,
        )
        _validate_live_inputs(
            live_inputs,
            decision_bar=decision_bar,
            trading_day=trading_day,
            actual_contract=normalized_contract,
        )
        snapshot = _canonical_value(
            {
                "schema_version": STRATEGY_INPUT_SCHEMA_VERSION,
                "trigger": "confirmed_15m_close",
                "strategy": {
                    "code": strategy_code,
                    "version": strategy_version,
                    "indicator_code": indicator_code,
                    "indicator_version": indicator_version,
                    "policy_id": policy_id,
                    "parameters_schema_version": PARAMETER_SCHEMA_VERSION,
                    "parameters": normalized_parameters,
                    "parameter_digest": parameter_digest,
                    "recipe_version": recipe_version,
                    "purpose": "observation_only",
                    "future_looking": False,
                    "repainting_accepted": False,
                    "historical_backtest_allowed": False,
                    "auto_order": False,
                },
                "mapping": {
                    "provider": "rqdata",
                    "product": "jm",
                    "trading_day": trading_day,
                    "actual_contract": normalized_contract,
                    "rank": 1,
                },
                "decision_bar": decision_bar,
                "historical_input": historical_input,
                "live_inputs": list(live_inputs),
            }
        )
        input_digest = canonical_digest(snapshot)
        fingerprint = canonical_digest(
            {
                "fingerprint_recipe_version": FINGERPRINT_RECIPE_VERSION,
                "input_digest": input_digest,
                "strategy_code": strategy_code,
                "strategy_version": strategy_version,
                "policy_id": policy_id,
                "parameter_digest": parameter_digest,
                "recipe_version": recipe_version,
            }
        )
        return cls(
            snapshot=snapshot,
            input_digest=input_digest,
            fingerprint=fingerprint,
            strategy_code=strategy_code,
            strategy_version=strategy_version,
            indicator_code=indicator_code,
            indicator_version=indicator_version,
            policy_id=policy_id,
            parameter_digest=parameter_digest,
            recipe_version=recipe_version,
            trading_day=trading_day,
            actual_contract=normalized_contract,
        )


def _validate_decision_bar(
    decision_bar: Mapping[str, Any],
    *,
    trading_day: date,
    actual_contract: str,
) -> None:
    bar_end = decision_bar.get("bar_end")
    bar_trading_day = decision_bar.get("trading_day")
    if isinstance(bar_trading_day, str):
        try:
            bar_trading_day = date.fromisoformat(bar_trading_day)
        except ValueError:
            bar_trading_day = None
    if (
        decision_bar.get("provider") != "rqdata"
        or decision_bar.get("product") != "jm"
        or decision_bar.get("source_mode") != "session_aggregate_15m_v2"
        or decision_bar.get("period") != "15m"
        or decision_bar.get("confirmed") is not True
        or not isinstance(decision_bar.get("revision"), int)
        or decision_bar.get("revision", -1) < 0
        or decision_bar.get("source_bar_count") != 15
        or decision_bar.get("expected_bar_count") != 15
        or str(decision_bar.get("actual_contract", "")).strip().upper()
        != actual_contract
        or bar_trading_day != trading_day
        or not isinstance(bar_end, datetime)
        or bar_end.tzinfo is None
        or bar_end.utcoffset() is None
    ):
        raise ValueError("STRATEGY_DECISION_BAR_CONFIRMED_15M_REQUIRED")


def _validate_strategy_contract(
    *,
    strategy_code: str,
    strategy_version: str,
    indicator_code: str,
    indicator_version: str,
    policy_id: str,
    recipe_version: str,
) -> None:
    identities = (
        strategy_code,
        strategy_version,
        indicator_code,
        indicator_version,
        policy_id,
        recipe_version,
    )
    if any(
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value.strip()) is None
        or value.strip() in _FORBIDDEN_FUTURE_LOOKING_IDENTITIES
        for value in identities
    ):
        raise ValueError("STRATEGY_POLICY_CONTRACT_INVALID")


def _validate_historical_input(
    historical_input: Mapping[str, Any],
    *,
    actual_contract: str,
    decision_bar: Mapping[str, Any],
) -> None:
    dataset_key = historical_input.get("dataset_key")
    manifest_digest = historical_input.get("manifest_digest")
    bars = historical_input.get("bars")
    if (
        not isinstance(dataset_key, Mapping)
        or dataset_key.get("provider") != "rqdata"
        or dataset_key.get("dataset_kind") != "actual_dominant"
        or dataset_key.get("symbol") != "jm"
        or str(dataset_key.get("contract_or_series", "")).strip().upper()
        != actual_contract
        or dataset_key.get("frequency") != "1m"
        or dataset_key.get("adjustment") != "none"
        or dataset_key.get("schema_version") != "canonical-bar-v1"
        or not isinstance(manifest_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest_digest) is None
        or historical_input.get("data_role") != "primary"
        or historical_input.get("quality_status") != "passed"
        or historical_input.get("aggregation_recipe") != "trading_session_15m_v1"
        or not isinstance(bars, Sequence)
        or isinstance(bars, (str, bytes))
        or len(bars) != 128
    ):
        raise ValueError("STRATEGY_HISTORICAL_INPUT_INVALID")
    ends: list[datetime] = []
    for bar in bars:
        if not isinstance(bar, Mapping):
            raise ValueError("STRATEGY_HISTORICAL_INPUT_INVALID")
        bar_end = bar.get("bar_end")
        try:
            open_value = Decimal(str(bar["open"]))
            high_value = Decimal(str(bar["high"]))
            low_value = Decimal(str(bar["low"]))
            close_value = Decimal(str(bar["close"]))
            volume_value = Decimal(str(bar["volume"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError("STRATEGY_HISTORICAL_INPUT_INVALID") from exc
        if (
            bar.get("period") != "15m"
            or not isinstance(bar_end, datetime)
            or bar_end.tzinfo is None
            or bar_end.utcoffset() is None
            or not (low_value <= open_value <= high_value)
            or not (low_value <= close_value <= high_value)
            or volume_value < 0
        ):
            raise ValueError("STRATEGY_HISTORICAL_INPUT_INVALID")
        ends.append(bar_end)
    decision_start = decision_bar.get("source_start")
    if (
        ends != sorted(ends)
        or len(set(ends)) != len(ends)
        or not isinstance(decision_start, datetime)
        or ends[-1] > decision_start
    ):
        raise ValueError("STRATEGY_HISTORICAL_INPUT_INVALID")


def _validate_live_inputs(
    live_inputs: Sequence[Mapping[str, Any]],
    *,
    decision_bar: Mapping[str, Any],
    trading_day: date,
    actual_contract: str,
) -> None:
    if len(live_inputs) != 15:
        raise ValueError("STRATEGY_LIVE_INPUTS_CONFIRMED_1M_REQUIRED")
    ends: list[datetime] = []
    starts: list[datetime] = []
    for item in live_inputs:
        if not isinstance(item, Mapping):
            raise ValueError("STRATEGY_LIVE_INPUTS_CONFIRMED_1M_REQUIRED")
        bar_end = item.get("bar_end")
        source_start = item.get("source_start")
        source_end = item.get("source_end")
        if (
            item.get("provider") != "rqdata"
            or item.get("source_mode") != "rqdata_live_1m_v2"
            or item.get("product") != "jm"
            or str(item.get("actual_contract", "")).strip().upper() != actual_contract
            or item.get("trading_day") != trading_day
            or item.get("period") != "1m"
            or item.get("confirmed") is not True
            or not isinstance(item.get("revision"), int)
            or item.get("revision", -1) < 0
            or item.get("source_bar_count") != 1
            or item.get("expected_bar_count") != 1
            or not isinstance(bar_end, datetime)
            or bar_end.tzinfo is None
            or bar_end.utcoffset() is None
            or not isinstance(source_start, datetime)
            or source_start.tzinfo is None
            or source_start.utcoffset() is None
            or not isinstance(source_end, datetime)
            or source_end.tzinfo is None
            or source_end.utcoffset() is None
            or source_end != bar_end
            or bar_end - source_start != timedelta(minutes=1)
        ):
            raise ValueError("STRATEGY_LIVE_INPUTS_CONFIRMED_1M_REQUIRED")
        ends.append(bar_end)
        starts.append(source_start)
    decision_end = decision_bar["bar_end"]
    decision_start = decision_bar.get("source_start")
    expected_ends = [ends[0] + timedelta(minutes=index) for index in range(15)]
    if (
        ends != sorted(ends)
        or ends != expected_ends
        or len(set(ends)) != 15
        or ends[-1] != decision_end
        or starts[0] != decision_start
        or any(value > decision_end for value in ends)
    ):
        raise ValueError("STRATEGY_LIVE_INPUTS_CONFIRMED_1M_REQUIRED")

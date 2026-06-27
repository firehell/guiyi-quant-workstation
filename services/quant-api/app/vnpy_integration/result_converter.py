from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import math
from typing import Any, Mapping


def convert_vnpy_result(raw_result: Any) -> dict[str, Any]:
    payload = _to_mapping(raw_result)
    statistics = _normalize_mapping(_pick(payload, "statistics", "stats", "summary") or {})
    vnpy_trades = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "trades", "trade_results"))]
    strategy_trades = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "strategy_trades"))]
    trades = strategy_trades or vnpy_trades
    orders = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "orders"))]
    daily_results = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "daily_results", "daily"))]
    equity_curve = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "equity_curve", "balance_curve"))]
    drawdown_curve = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "drawdown_curve"))]

    return {
        "engine": "vnpy_cta_backtesting",
        "source": "vnpy",
        "summary": statistics,
        "trades": trades,
        "orders": orders,
        "daily_results": daily_results,
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "warnings": list(_as_sequence(_pick(payload, "warnings"))) or [],
        "metadata": {
            "converted_by": "guiyi.vnpy_integration.result_converter",
            "raw_type": type(raw_result).__name__,
            "research_only": True,
            "vnpy_trade_count": len(vnpy_trades),
            "strategy_trade_count": len(strategy_trades),
        },
    }


def _pick(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _to_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return vars(value)
    return {"value": value}


def _normalize_mapping(value: Any) -> dict[str, Any]:
    mapping = _to_mapping(value)
    return {str(key): _json_safe(item) for key, item in mapping.items() if not str(key).startswith("_")}


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, list | tuple | set):
        return list(value)
    return [value]


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and callable(value.item):
        return _json_safe(value.item())
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize_mapping(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return value

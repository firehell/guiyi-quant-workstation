from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
import math
from typing import Any, Mapping

from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.equity_curve_generator import generate_equity_curve
from app.backtest.report_metrics import compute_report_metrics


SCHEMA_VERSION = "backtest_result.v1.0"
DERIVED_CURVE_KEYS = ("daily_results", "drawdown_curve", "equity_curve", "balance_curve")


def convert_vnpy_result(raw_result: Any) -> dict[str, Any]:
    payload = _to_mapping(raw_result)
    statistics = _normalize_mapping(_pick(payload, "statistics", "stats", "summary") or {})
    vnpy_trades = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "trades", "trade_results"))]
    strategy_trades = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "strategy_trades"))]
    prepared = _normalize_mapping(_pick(payload, "prepared") or {})
    trades = _normalize_trade_list(strategy_trades or vnpy_trades, prepared=prepared)
    orders = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "orders"))]
    strategy_execution_events = [
        _normalize_mapping(item) for item in _as_sequence(_pick(payload, "strategy_execution_events"))
    ]
    signal_candidates = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "signal_candidates"))]
    rejected_signals = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "rejected_signals"))]
    initial_capital = _initial_capital(statistics, prepared)
    equity_curve = generate_equity_curve(trades, initial_capital=initial_capital)
    drawdown_result = generate_drawdown_curve(equity_curve)
    drawdown_curve = drawdown_result["drawdown_curve"]
    start, end = _result_window(trades, prepared=prepared)
    report = _report_from_trades(
        trades=trades,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        initial_capital=initial_capital,
        start=start,
        end=end,
        payload=payload,
        prepared=prepared,
    )
    generated_at = datetime.now(UTC).isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "engine": "vnpy_cta_backtesting",
        "source": "vnpy",
        "report": report,
        "summary": report,
        "trades": trades,
        "orders": orders,
        "strategy_execution_events": strategy_execution_events,
        "signal_candidates": signal_candidates,
        "rejected_signals": rejected_signals,
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "warnings": list(_as_sequence(_pick(payload, "warnings"))) or [],
        "metadata": {
            "converted_by": "guiyi.vnpy_integration.result_converter",
            "raw_type": type(raw_result).__name__,
            "research_only": True,
            "vnpy_trade_count": len(vnpy_trades),
            "strategy_trade_count": len(strategy_trades),
            "ignored_raw_curve_fields": [key for key in DERIVED_CURVE_KEYS if key in payload],
        },
    }


def _normalize_trade_list(raw_trades: list[dict[str, Any]], *, prepared: dict[str, Any]) -> list[dict[str, Any]]:
    return [_normalize_trade(trade, index=index, prepared=prepared) for index, trade in enumerate(raw_trades)]


def _normalize_trade(trade: dict[str, Any], *, index: int, prepared: dict[str, Any]) -> dict[str, Any]:
    sequence = int(_number_or_default(_pick(trade, "sequence"), index + 1))
    trade_id = str(_pick(trade, "trade_id", "tradeid", "trade_no", "vt_tradeid") or f"VN-T-{sequence}")
    entry_time = _trade_time(trade, "entry_time", "entry_datetime", "open_time", "datetime", "close_time", "exit_datetime", "exit_time")
    exit_time = _trade_time(trade, "exit_time", "exit_datetime", "close_time", "datetime", "entry_time", "entry_datetime", "open_time")
    direction = _normalize_direction(_pick(trade, "direction"))
    entry_price = _first_number(trade, "entry_price", "open_price", "price", "exit_price", "close_price", default=0.0)
    exit_price = _first_number(trade, "exit_price", "close_price", "price", "entry_price", "open_price", default=entry_price)
    volume = max(1, int(_first_number(trade, "volume", default=1.0)))
    contract_multiplier = max(1, int(_first_number(trade, "contract_multiplier", "size", default=_prepared_number(prepared, "size", default=1.0))))
    price_tick = _first_number(trade, "price_tick", "pricetick", default=_prepared_number(prepared, "pricetick", default=1.0))
    commission = _first_number(trade, "commission", default=0.0)
    slippage = _first_number(trade, "slippage", default=0.0)
    explicit_gross_pnl = _optional_number(_pick(trade, "gross_pnl"))
    gross_pnl = explicit_gross_pnl if explicit_gross_pnl is not None else _gross_pnl(direction, entry_price, exit_price, volume, contract_multiplier)
    explicit_net_pnl = _optional_number(_pick(trade, "net_pnl"))
    net_pnl = explicit_net_pnl if explicit_net_pnl is not None else gross_pnl - commission - slippage
    symbol = str(_pick(trade, "symbol", "contract", "contract_code") or _prepared_symbol(prepared) or "")
    exchange = str(_pick(trade, "exchange") or _prepared_exchange(prepared) or "")
    normalized = dict(trade)
    normalized.update(
        {
            "trade_id": trade_id,
            "tradeid": trade_id,
            "sequence": sequence,
            "symbol": symbol,
            "exchange": exchange,
            "direction": direction,
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "entry_datetime": entry_time.isoformat(),
            "exit_datetime": exit_time.isoformat(),
            "open_time": entry_time.isoformat(),
            "close_time": exit_time.isoformat(),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "open_price": entry_price,
            "close_price": exit_price,
            "volume": volume,
            "contract_multiplier": contract_multiplier,
            "size": contract_multiplier,
            "price_tick": price_tick,
            "pricetick": price_tick,
            "gross_pnl": gross_pnl,
            "commission": commission,
            "slippage": slippage,
            "net_pnl": net_pnl,
            "margin_required": _first_number(trade, "margin_required", default=0.0),
            "margin_ratio": _first_number(trade, "margin_ratio", default=0.0),
            "holding_bars": int(_first_number(trade, "holding_bars", "hold_bars", default=0.0)),
            "entry_reason": str(_pick(trade, "entry_reason", "reason") or "vnpy_trade"),
            "exit_reason": str(_pick(trade, "exit_reason") or "vnpy_trade"),
            "rollover_forced_exit": bool(_pick(trade, "rollover_forced_exit") or False),
            "delivery_risk_exit": bool(_pick(trade, "delivery_risk_exit") or False),
        }
    )
    return normalized


def _report_from_trades(
    *,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    drawdown_curve: list[dict[str, Any]],
    initial_capital: float,
    start: datetime,
    end: datetime,
    payload: Mapping[str, Any],
    prepared: dict[str, Any],
) -> dict[str, Any]:
    metrics = compute_report_metrics(
        summary={"initial_capital": initial_capital},
        trades=trades,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        start=start,
        end=end,
        default_initial_capital=initial_capital,
    )
    metrics["status"] = str(_pick(payload, "status") or "success")
    metrics["engine_type"] = "vnpy"
    metrics["engine_version"] = _pick(payload, "engine_version")
    metrics["symbol"] = _prepared_symbol(prepared)
    metrics["exchange"] = _prepared_exchange(prepared)
    metrics["timeframe"] = prepared.get("interval")
    metrics["start"] = start.isoformat()
    metrics["end"] = end.isoformat()
    metrics["total_gross_pnl"] = sum(_first_number(trade, "gross_pnl", default=0.0) for trade in trades)
    metrics["total_net_pnl"] = sum(_first_number(trade, "net_pnl", default=0.0) for trade in trades)
    metrics["max_drawdown"] = metrics["max_drawdown_pct"]
    return metrics


def _initial_capital(statistics: dict[str, Any], prepared: dict[str, Any]) -> float:
    statistic_value = _optional_number(_pick(statistics, "initial_capital", "capital"))
    if statistic_value is not None and statistic_value > 0:
        return statistic_value
    return _prepared_number(prepared, "capital", default=100000.0)


def _result_window(trades: list[dict[str, Any]], *, prepared: dict[str, Any]) -> tuple[datetime, datetime]:
    prepared_start = _parse_optional_datetime(prepared.get("start"))
    prepared_end = _parse_optional_datetime(prepared.get("end"))
    trade_times = [
        parsed
        for trade in trades
        for parsed in (_parse_optional_datetime(trade.get("entry_time")), _parse_optional_datetime(trade.get("exit_time")))
        if parsed is not None
    ]
    start = prepared_start or (min(trade_times) if trade_times else datetime.now(UTC))
    end = prepared_end or (max(trade_times) if trade_times else start + timedelta(days=1))
    if end <= start:
        end = start + timedelta(days=1)
    return start, end


def _trade_time(trade: Mapping[str, Any], *keys: str) -> datetime:
    for key in keys:
        parsed = _parse_optional_datetime(trade.get(key))
        if parsed is not None:
            return parsed
    return datetime.now(UTC)


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _prepared_symbol(prepared: Mapping[str, Any]) -> str | None:
    vt_symbol = str(prepared.get("vt_symbol") or "")
    if vt_symbol:
        return vt_symbol.rsplit(".", 1)[0]
    return None


def _prepared_exchange(prepared: Mapping[str, Any]) -> str | None:
    vt_symbol = str(prepared.get("vt_symbol") or "")
    if "." in vt_symbol:
        return vt_symbol.rsplit(".", 1)[1]
    return None


def _prepared_number(prepared: Mapping[str, Any], key: str, *, default: float) -> float:
    return _number_or_default(prepared.get(key), default)


def _first_number(mapping: Mapping[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = _optional_number(mapping.get(key))
        if value is not None:
            return value
    return default


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _number_or_default(value: Any, default: float) -> float:
    number = _optional_number(value)
    return default if number is None else number


def _normalize_direction(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"long", "buy", "多", "direction.long"}:
        return "long"
    if normalized in {"short", "sell", "空", "direction.short"}:
        return "short"
    return normalized or "unknown"


def _gross_pnl(direction: str, entry_price: float, exit_price: float, volume: int, contract_multiplier: int) -> float:
    if direction == "long":
        return (exit_price - entry_price) * volume * contract_multiplier
    if direction == "short":
        return (entry_price - exit_price) * volume * contract_multiplier
    return 0.0


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

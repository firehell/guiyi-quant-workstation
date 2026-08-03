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
    lineage = apply_backtest_lineage_mapping(
        trades=trades,
        orders=orders,
        strategy_execution_events=strategy_execution_events,
    )
    trades = lineage["trades"]
    orders = lineage["orders"]
    signal_candidates = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "signal_candidates"))]
    rejected_signals = [_normalize_mapping(item) for item in _as_sequence(_pick(payload, "rejected_signals"))]
    contract_roll_cancellations = [
        _normalize_mapping(item)
        for item in _as_sequence(_pick(payload, "contract_roll_cancellations"))
    ]
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
    report["lineage_summary"] = lineage["lineage_summary"]
    generated_at = datetime.now(UTC).isoformat()

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "engine": "vnpy_cta_backtesting",
        "source": "vnpy",
        "report": report,
        "summary": report,
        "trades": trades,
        "orders": orders,
        "lineage_summary": lineage["lineage_summary"],
        "strategy_execution_events": strategy_execution_events,
        "signal_candidates": signal_candidates,
        "rejected_signals": rejected_signals,
        "contract_roll_cancellations": contract_roll_cancellations,
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
    return _json_numeric_boundary(result)


def _json_numeric_boundary(value: Any) -> Any:
    """Serialize exact derived numerics only after all metric derivation is complete."""
    if isinstance(value, dict):
        return {str(key): _json_numeric_boundary(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_numeric_boundary(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


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


def apply_backtest_lineage_mapping(
    *,
    trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    strategy_execution_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach explicit signal/order lineage without inferring from bar interval."""
    mapped_orders = [dict(order) for order in orders]
    mapped_trades: list[dict[str, Any]] = []
    events = [dict(event) for event in strategy_execution_events or []]
    has_orders = bool(mapped_orders)
    order_indexes_by_no = {_order_no(order, index): index for index, order in enumerate(mapped_orders)}
    summary = {
        "trade_count": len(trades),
        "order_count": len(mapped_orders),
        "mapped_trades": 0,
        "partial_trades": 0,
        "missing_trades": 0,
        "ambiguous_trades": 0,
        "mapped_orders": 0,
        "unmapped_orders": 0,
        "ambiguous_orders": 0,
        "lineage_sources": [],
    }
    lineage_sources: set[str] = set()
    used_order_nos: set[str] = set()

    for index, trade in enumerate(trades):
        row = dict(trade)
        trade_no = _trade_no(row, index)
        entry_result = _ensure_signal_time(
            row,
            signal_key="entry_signal_time",
            alias_keys=("signal_datetime", "signal_time"),
            fill_keys=("entry_datetime", "entry_time", "open_time", "fill_datetime"),
            events=events,
            event_actions=("open_long", "open_short"),
            direction=row.get("direction"),
            source_key="entry_signal_source",
        )
        exit_result = _ensure_signal_time(
            row,
            signal_key="exit_signal_time",
            alias_keys=("exit_signal_datetime",),
            fill_keys=("exit_datetime", "exit_time", "close_time", "exit_fill_datetime"),
            events=events,
            event_actions=("close",),
            direction=row.get("direction"),
            source_key="exit_signal_source",
        )
        order_statuses: list[str] = []
        for leg, field_name in (("entry", "entry_order_no"), ("exit", "exit_order_no")):
            match = _match_order_for_trade(mapped_orders, row, leg=leg, used_order_nos=used_order_nos)
            if match["status"] == "mapped":
                order_no = match["order_no"]
                source = str(match.get("lineage_source") or "order_time_direction_offset")
                if order_no:
                    row[field_name] = order_no
                    used_order_nos.add(str(order_no))
                    order_index = order_indexes_by_no.get(str(order_no))
                    if order_index is not None:
                        mapped_order = mapped_orders[order_index]
                        mapped_order["trade_no"] = trade_no
                        mapped_order["leg"] = leg
                        mapped_order["lineage_source"] = source
                        mapped_order["mapping_status"] = "mapped"
                elif leg == "exit":
                    row["exit_signal_source"] = row.get("exit_signal_source") or source
            elif match["status"] == "ambiguous":
                order_statuses.append("ambiguous")
            elif has_orders:
                order_statuses.append("missing")

        for source in (row.get("entry_signal_source"), row.get("exit_signal_source")):
            if source:
                lineage_sources.add(str(source))

        status = _trade_lineage_status(
            entry_status=entry_result,
            exit_status=exit_result,
            order_statuses=order_statuses,
            has_orders=has_orders,
        )
        row["lineage_status"] = status
        summary[f"{status}_trades"] += 1
        mapped_trades.append(row)

    for order in mapped_orders:
        if not order.get("mapping_status"):
            order["mapping_status"] = "missing"
            order["lineage_source"] = "unmapped_vnpy_order"
    summary["mapped_orders"] = sum(1 for order in mapped_orders if order.get("mapping_status") == "mapped")
    summary["unmapped_orders"] = sum(1 for order in mapped_orders if order.get("mapping_status") == "missing")
    summary["ambiguous_orders"] = sum(1 for order in mapped_orders if order.get("mapping_status") == "ambiguous")
    summary["lineage_sources"] = sorted(lineage_sources)
    return {"trades": mapped_trades, "orders": mapped_orders, "lineage_summary": summary}


def _ensure_signal_time(
    row: dict[str, Any],
    *,
    signal_key: str,
    alias_keys: tuple[str, ...],
    fill_keys: tuple[str, ...],
    events: list[dict[str, Any]],
    event_actions: tuple[str, ...],
    direction: Any,
    source_key: str,
) -> str:
    if row.get(signal_key):
        row[source_key] = row.get(source_key) or "trade_field"
        return "mapped"
    for alias_key in alias_keys:
        if row.get(alias_key):
            row[signal_key] = row[alias_key]
            row[source_key] = row.get(source_key) or f"trade_{alias_key}"
            return "mapped"
    fill_key = _first_time_key(row, *fill_keys)
    if fill_key is None:
        return "missing"
    candidates = [
        event
        for event in events
        if _event_action_matches(event, actions=event_actions, direction=direction)
        and _datetime_key(_first_value(event, "fill_datetime", "exit_datetime")) == fill_key
        and _first_value(event, "signal_datetime", "entry_signal_time", "exit_signal_time") is not None
    ]
    if len(candidates) == 1:
        row[signal_key] = _first_value(candidates[0], "signal_datetime", "entry_signal_time", "exit_signal_time")
        row[source_key] = "strategy_execution_event"
        return "mapped"
    if len(candidates) > 1:
        row[source_key] = "ambiguous_strategy_execution_event"
        return "ambiguous"
    return "missing"


def _match_order_for_trade(
    orders: list[dict[str, Any]],
    trade: dict[str, Any],
    *,
    leg: str,
    used_order_nos: set[str] | None = None,
) -> dict[str, Any]:
    if not orders:
        return {"status": "missing", "order_no": None}
    used = used_order_nos or set()
    explicit_order_no = _first_value(trade, "entry_order_no" if leg == "entry" else "exit_order_no")
    if explicit_order_no:
        explicit = str(explicit_order_no)
        for index, order in enumerate(orders):
            if _order_no(order, index) == explicit and explicit not in used:
                return {"status": "mapped", "order_no": explicit, "lineage_source": "trade_order_field"}
        return {"status": "missing", "order_no": None}

    if leg == "entry":
        return _match_entry_order_for_trade(orders, trade, used_order_nos=used)
    return _match_exit_order_for_trade(orders, trade, used_order_nos=used)


def _match_entry_order_for_trade(
    orders: list[dict[str, Any]],
    trade: dict[str, Any],
    *,
    used_order_nos: set[str],
) -> dict[str, Any]:
    signal_time = _first_time_key(trade, "entry_signal_time", "signal_datetime", "signal_time")
    match = _match_order_at_time(
        orders,
        trade,
        leg="entry",
        order_time=signal_time,
        used_order_nos=used_order_nos,
        lineage_source="order_submission_signal_time",
    )
    if match["status"] != "missing":
        return match

    fill_time = _first_time_key(trade, "entry_datetime", "entry_time", "open_time", "fill_datetime")
    return _match_order_at_time(
        orders,
        trade,
        leg="entry",
        order_time=fill_time,
        used_order_nos=used_order_nos,
        lineage_source="order_time_direction_offset",
    )


def _match_exit_order_for_trade(
    orders: list[dict[str, Any]],
    trade: dict[str, Any],
    *,
    used_order_nos: set[str],
) -> dict[str, Any]:
    signal_time = _first_time_key(trade, "exit_signal_time", "exit_signal_datetime")
    match = _match_order_at_time(
        orders,
        trade,
        leg="exit",
        order_time=signal_time,
        used_order_nos=used_order_nos,
        lineage_source="exit_signal_order_time",
    )
    if match["status"] != "missing":
        return match

    range_match = _match_single_exit_order_in_trade_window(orders, trade, used_order_nos=used_order_nos)
    if range_match["status"] != "missing":
        return range_match

    fill_time = _first_time_key(trade, "exit_datetime", "exit_time", "close_time", "exit_fill_datetime")
    match = _match_order_at_time(
        orders,
        trade,
        leg="exit",
        order_time=fill_time,
        used_order_nos=used_order_nos,
        lineage_source="order_time_direction_offset",
    )
    if match["status"] != "missing":
        return match

    if _is_strategy_direct_exit(trade):
        return {"status": "mapped", "order_no": None, "lineage_source": "strategy_trade_direct_exit"}
    return {"status": "missing", "order_no": None}


def _match_order_at_time(
    orders: list[dict[str, Any]],
    trade: dict[str, Any],
    *,
    leg: str,
    order_time: str | None,
    used_order_nos: set[str],
    lineage_source: str,
) -> dict[str, Any]:
    if order_time is None:
        return {"status": "missing", "order_no": None}
    candidates = [
        (index, order)
        for index, order in enumerate(orders)
        if _order_no(order, index) not in used_order_nos
        and _datetime_key(_first_value(order, "datetime", "order_time")) == order_time
        and _order_leg_matches(order, leg=leg)
        and _order_direction_matches(order, trade_direction=trade.get("direction"), leg=leg)
    ]
    return _order_match_result(candidates, lineage_source=lineage_source)


def _match_single_exit_order_in_trade_window(
    orders: list[dict[str, Any]],
    trade: dict[str, Any],
    *,
    used_order_nos: set[str],
) -> dict[str, Any]:
    entry_time = _first_time_key(trade, "entry_datetime", "entry_time", "open_time", "fill_datetime")
    exit_time = _first_time_key(trade, "exit_datetime", "exit_time", "close_time", "exit_fill_datetime")
    if entry_time is None or exit_time is None:
        return {"status": "missing", "order_no": None}
    candidates = [
        (index, order)
        for index, order in enumerate(orders)
        if _order_no(order, index) not in used_order_nos
        and (order_time := _datetime_key(_first_value(order, "datetime", "order_time"))) is not None
        and entry_time <= order_time <= exit_time
        and _order_leg_matches(order, leg="exit")
        and _order_direction_matches(order, trade_direction=trade.get("direction"), leg="exit")
    ]
    return _order_match_result(candidates, lineage_source="single_position_exit_order_range")


def _order_match_result(candidates: list[tuple[int, dict[str, Any]]], *, lineage_source: str) -> dict[str, Any]:
    if len(candidates) == 1:
        index, order = candidates[0]
        return {"status": "mapped", "order_no": _order_no(order, index), "lineage_source": lineage_source}
    if len(candidates) > 1:
        for _, order in candidates:
            order["mapping_status"] = "ambiguous"
            order["lineage_source"] = f"ambiguous_{lineage_source}"
        return {"status": "ambiguous", "order_no": None}
    return {"status": "missing", "order_no": None}


def _is_strategy_direct_exit(trade: Mapping[str, Any]) -> bool:
    exit_reason = str(_first_value(trade, "exit_reason") or "").strip().lower()
    if exit_reason != "stop_loss_atr_or_structure":
        return False
    return (
        _first_time_key(trade, "exit_datetime", "exit_time", "close_time", "exit_fill_datetime") is not None
        and _first_number(trade, "exit_price", "close_price", default=0.0) > 0
    )


def _trade_lineage_status(
    *,
    entry_status: str,
    exit_status: str,
    order_statuses: list[str],
    has_orders: bool,
) -> str:
    if entry_status == "ambiguous" or exit_status == "ambiguous" or "ambiguous" in order_statuses:
        return "ambiguous"
    if entry_status != "mapped":
        return "missing"
    if has_orders and "missing" in order_statuses:
        return "partial"
    return "mapped"


def _event_action_matches(event: dict[str, Any], *, actions: tuple[str, ...], direction: Any) -> bool:
    action = str(event.get("action") or "").strip().lower()
    if action not in actions:
        return False
    normalized_direction = _normalize_direction(direction)
    if action == "open_long":
        return normalized_direction in {"", "long"}
    if action == "open_short":
        return normalized_direction in {"", "short"}
    return True


def _order_leg_matches(order: dict[str, Any], *, leg: str) -> bool:
    explicit_leg = str(order.get("leg") or "").strip().lower()
    if explicit_leg:
        return explicit_leg == leg
    offset = str(order.get("offset") or "").strip().lower()
    if leg == "entry":
        return offset in {"", "open", "开", "offset.open"}
    return offset in {"", "close", "closetoday", "closeyesterday", "平", "平今", "平昨", "offset.close"}


def _order_direction_matches(order: dict[str, Any], *, trade_direction: Any, leg: str) -> bool:
    order_direction = _normalize_order_direction(order.get("direction"))
    if not order_direction:
        return True
    normalized_trade = _normalize_direction(trade_direction)
    if not normalized_trade:
        return True
    if leg == "entry":
        return order_direction == normalized_trade
    return order_direction != normalized_trade


def _normalize_order_direction(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"long", "buy", "cover", "多", "direction.long"}:
        return "long"
    if normalized in {"short", "sell", "空", "direction.short"}:
        return "short"
    return ""


def _first_time_key(mapping: Mapping[str, Any], *keys: str) -> str | None:
    return _datetime_key(_first_value(mapping, *keys))


def _datetime_key(value: Any) -> str | None:
    parsed = _parse_optional_datetime(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=None).isoformat()


def _first_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _trade_no(trade: Mapping[str, Any], index: int) -> str:
    return str(_first_value(trade, "tradeid", "trade_id", "trade_no") or f"VN-T-{index + 1}")


def _order_no(order: Mapping[str, Any], index: int) -> str:
    return str(_first_value(order, "orderid", "order_id", "order_no") or f"VN-O-{index + 1}")


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

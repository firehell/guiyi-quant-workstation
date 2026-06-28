from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any


METRIC_UNITS: dict[str, str] = {
    "initial_capital": "CNY",
    "final_equity": "CNY",
    "total_return": "ratio",
    "annual_return": "ratio",
    "max_drawdown": "ratio",
    "max_drawdown_amount": "CNY",
    "max_drawdown_pct": "ratio",
    "win_rate": "ratio",
    "profit_loss_ratio": "ratio",
    "trade_count": "count",
    "max_consecutive_losses": "count",
    "total_commission": "CNY",
    "total_slippage": "CNY",
    "max_margin_required": "CNY",
    "max_margin_usage_pct": "ratio",
    "rollover_exit_count": "count",
    "delivery_risk_exit_count": "count",
    "average_hold_bars": "bars",
}


def compute_report_metrics(
    *,
    summary: dict[str, Any],
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    drawdown_curve: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    default_initial_capital: float,
) -> dict[str, Any]:
    initial_capital = _first_number(summary, "initial_capital", "capital", default=default_initial_capital)
    trade_count = len(trades)
    explicit_trade_net_pnl = any(_has_value(trade.get("net_pnl")) for trade in trades)
    total_net_pnl = sum(_trade_net_pnl(trade) for trade in trades) if explicit_trade_net_pnl else _first_number(summary, "total_net_pnl", default=0.0)
    final_equity = _final_equity(
        summary=summary,
        equity_curve=equity_curve,
        initial_capital=initial_capital,
        total_net_pnl=total_net_pnl,
        prefer_trade_net_pnl=explicit_trade_net_pnl,
    )
    total_return = (final_equity - initial_capital) / initial_capital if initial_capital else 0.0
    annual_return = _annual_return(initial_capital=initial_capital, final_equity=final_equity, start=start, end=end)
    max_drawdown_amount, max_drawdown_pct = _drawdown_metrics(equity_curve=equity_curve, drawdown_curve=drawdown_curve, initial_capital=initial_capital)

    wins = [_trade_net_pnl(trade) for trade in trades if _trade_net_pnl(trade) > 0]
    losses = [_trade_net_pnl(trade) for trade in trades if _trade_net_pnl(trade) < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    hold_bars = [_trade_hold_bars(trade) for trade in trades if _trade_hold_bars(trade) is not None]
    max_margin_required = max((_safe_float(trade.get("margin_required")) for trade in trades if _has_value(trade.get("margin_required"))), default=0.0)

    return {
        "initial_capital": initial_capital,
        "capital": initial_capital,
        "final_equity": final_equity,
        "end_balance": final_equity,
        "ending_equity": final_equity,
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown_pct,
        "max_drawdown_amount": max_drawdown_amount,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate": len(wins) / trade_count if trade_count else 0.0,
        "profit_loss_ratio": average_win / average_loss if average_loss else 0.0,
        "profit_loss_ratio_defined": bool(average_loss),
        "expectancy": sum(_trade_net_pnl(trade) for trade in trades) / trade_count if trade_count else 0.0,
        "trade_count": trade_count,
        "total_trade_count": trade_count,
        "total_trades": trade_count,
        "max_consecutive_losses": _max_consecutive_losses(trades),
        "total_commission": sum(_safe_float(trade.get("commission")) for trade in trades),
        "total_slippage": sum(_safe_float(trade.get("slippage")) for trade in trades),
        "total_net_pnl": total_net_pnl if explicit_trade_net_pnl else final_equity - initial_capital,
        "max_margin_required": max_margin_required,
        "max_margin_usage_pct": max_margin_required / initial_capital if initial_capital else 0.0,
        "rollover_exit_count": sum(1 for trade in trades if trade.get("rollover_forced_exit")),
        "delivery_risk_exit_count": sum(1 for trade in trades if trade.get("delivery_risk_exit")),
        "average_hold_bars": sum(hold_bars) / len(hold_bars) if hold_bars else None,
        "metric_units": dict(METRIC_UNITS),
    }


def _final_equity(
    *,
    summary: dict[str, Any],
    equity_curve: list[dict[str, Any]],
    initial_capital: float,
    total_net_pnl: float,
    prefer_trade_net_pnl: bool,
) -> float:
    if prefer_trade_net_pnl:
        return initial_capital + total_net_pnl
    curve_value = _curve_final_equity(equity_curve)
    if curve_value is not None:
        return curve_value
    return _first_number(summary, "final_equity", "end_balance", "ending_equity", "balance", default=initial_capital + total_net_pnl)


def _curve_final_equity(equity_curve: list[dict[str, Any]]) -> float | None:
    for point in reversed(equity_curve):
        value = point.get("equity") if point.get("equity") is not None else point.get("balance")
        if _has_value(value):
            return _safe_float(value)
    return None


def _annual_return(*, initial_capital: float, final_equity: float, start: datetime, end: datetime) -> float:
    if initial_capital <= 0:
        return 0.0
    if final_equity <= 0:
        return -1.0
    elapsed_days = max((end - start).total_seconds() / 86400, 1.0)
    return (final_equity / initial_capital) ** (365 / elapsed_days) - 1


def _drawdown_metrics(
    *,
    equity_curve: list[dict[str, Any]],
    drawdown_curve: list[dict[str, Any]],
    initial_capital: float,
) -> tuple[float, float]:
    equities = [_safe_float(point.get("equity") if point.get("equity") is not None else point.get("balance")) for point in equity_curve]
    equities = [equity for equity in equities if equity > 0]
    if equities:
        peak = initial_capital if initial_capital > 0 else equities[0]
        max_amount = 0.0
        max_pct = 0.0
        for equity in equities:
            peak = max(peak, equity)
            drawdown = max(peak - equity, 0.0)
            max_amount = max(max_amount, drawdown)
            max_pct = max(max_pct, drawdown / peak if peak else 0.0)
        return max_amount, max_pct

    amounts: list[float] = []
    pct_values: list[float] = []
    for point in drawdown_curve:
        if _has_value(point.get("drawdown")):
            amounts.append(abs(_safe_float(point.get("drawdown"))))
        pct_value = point.get("drawdown_pct") if point.get("drawdown_pct") is not None else point.get("ddpercent")
        if _has_value(pct_value):
            pct_values.append(abs(_safe_float(pct_value)))
    return (max(amounts) if amounts else 0.0, max(pct_values) if pct_values else 0.0)


def _max_consecutive_losses(trades: list[dict[str, Any]]) -> int:
    current = 0
    maximum = 0
    for trade in sorted(trades, key=_trade_close_sort_key):
        if _trade_net_pnl(trade) < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _trade_close_sort_key(trade: dict[str, Any]) -> tuple[datetime, str]:
    close_time = _parse_optional_time(trade.get("exit_datetime") or trade.get("close_time") or trade.get("datetime") or trade.get("open_time"))
    trade_no = str(trade.get("tradeid") or trade.get("trade_id") or trade.get("trade_no") or "")
    return close_time or datetime.min.replace(tzinfo=UTC), trade_no


def _trade_net_pnl(trade: dict[str, Any]) -> float:
    if _has_value(trade.get("net_pnl")):
        return _safe_float(trade.get("net_pnl"))
    if _has_value(trade.get("gross_pnl")):
        return _safe_float(trade.get("gross_pnl")) - _safe_float(trade.get("commission")) - _safe_float(trade.get("slippage"))
    direction = str(trade.get("direction") or "")
    open_price = _safe_float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"))
    close_price = _safe_float(trade.get("exit_price") or trade.get("close_price") or trade.get("price"))
    volume = int(_safe_float(trade.get("volume"), 1.0))
    size = int(_safe_float(trade.get("contract_multiplier") or trade.get("size"), 1.0))
    gross_pnl = _gross_pnl(direction, open_price, close_price, volume, size)
    return gross_pnl - _safe_float(trade.get("commission")) - _safe_float(trade.get("slippage"))


def _trade_hold_bars(trade: dict[str, Any]) -> float | None:
    for key in ("holding_bars", "hold_bars"):
        if _has_value(trade.get(key)):
            return _safe_float(trade.get(key))
    raw_payload = trade.get("raw_payload")
    if isinstance(raw_payload, dict):
        for key in ("holding_bars", "hold_bars"):
            if _has_value(raw_payload.get(key)):
                return _safe_float(raw_payload.get(key))
    return None


def _gross_pnl(direction: str, open_price: float, close_price: float, volume: int, size: int) -> float:
    normalized = direction.lower()
    if normalized in {"short", "空", "short_direction", "sell"}:
        return (open_price - close_price) * volume * size
    if normalized in {"long", "多", "long_direction", "buy"}:
        return (close_price - open_price) * volume * size
    return 0.0


def _first_number(summary: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = summary.get(key)
        if _has_value(value):
            return _safe_float(value, default)
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if not _has_value(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _parse_optional_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

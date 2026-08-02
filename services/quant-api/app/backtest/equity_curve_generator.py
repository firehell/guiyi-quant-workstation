from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


Number = Decimal | float | int

_EXIT_TIME_KEYS = ("exit_time", "exit_datetime", "close_time")
_TRADE_ID_KEYS = ("trade_id", "trade_no", "id")


def generate_equity_curve(
    trades: Sequence[Mapping[str, Any]],
    *,
    initial_capital: Number,
) -> list[dict[str, Any]]:
    """Generate a realized equity curve from closed trades only."""
    equity = _to_decimal(initial_capital, field="initial_capital")
    curve: list[dict[str, Any]] = [
        {"point_index": 0, "time": None, "equity": equity, "source": "initial_capital"}
    ]

    for point_index, prepared in enumerate(sorted(_prepare_trades(trades), key=_sort_key), start=1):
        equity += prepared["net_pnl"]
        curve.append(
            {
                "point_index": point_index,
                "time": prepared["exit_time"].isoformat(),
                "trade_id": prepared["trade_id"],
                "sequence": prepared["sequence"],
                "gross_pnl": prepared["gross_pnl"],
                "commission": prepared["commission"],
                "slippage": prepared["slippage"],
                "net_pnl": prepared["net_pnl"],
                "equity": equity,
            }
        )

    return curve


def _prepare_trades(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for original_index, trade in enumerate(trades):
        exit_time = _trade_exit_time(trade, original_index)
        sequence = _trade_sequence(trade, original_index)
        trade_id = _trade_id(trade, original_index)
        gross_pnl = _optional_decimal(trade.get("gross_pnl"), field="gross_pnl", original_index=original_index)
        commission = _optional_decimal(trade.get("commission"), field="commission", original_index=original_index) or Decimal("0")
        slippage = _optional_decimal(trade.get("slippage"), field="slippage", original_index=original_index) or Decimal("0")
        net_pnl = _trade_net_pnl(
            trade,
            gross_pnl=gross_pnl,
            commission=commission,
            slippage=slippage,
            original_index=original_index,
        )
        prepared.append(
            {
                "exit_time": exit_time,
                "sequence": sequence,
                "trade_id": trade_id,
                "gross_pnl": gross_pnl,
                "commission": commission,
                "slippage": slippage,
                "net_pnl": net_pnl,
            }
        )
    return prepared


def _sort_key(prepared_trade: dict[str, Any]) -> tuple[datetime, int, str]:
    return prepared_trade["exit_time"], prepared_trade["sequence"], prepared_trade["trade_id"]


def _trade_exit_time(trade: Mapping[str, Any], original_index: int) -> datetime:
    for key in _EXIT_TIME_KEYS:
        value = trade.get(key)
        if _has_value(value):
            return _parse_time(value, field=key, original_index=original_index)
    raise ValueError(f"trade[{original_index}] missing required exit_time")


def _trade_sequence(trade: Mapping[str, Any], original_index: int) -> int:
    value = trade.get("sequence")
    if not _has_value(value):
        return original_index
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trade[{original_index}] sequence must be an integer") from exc


def _trade_id(trade: Mapping[str, Any], original_index: int) -> str:
    for key in _TRADE_ID_KEYS:
        value = trade.get(key)
        if _has_value(value):
            return str(value)
    return str(original_index)


def _trade_net_pnl(
    trade: Mapping[str, Any],
    *,
    gross_pnl: Decimal | None,
    commission: Decimal,
    slippage: Decimal,
    original_index: int,
) -> Decimal:
    if _has_value(trade.get("net_pnl")):
        return _to_decimal(trade.get("net_pnl"), field="net_pnl", original_index=original_index)
    if gross_pnl is not None:
        return gross_pnl - commission - slippage
    raise ValueError(f"trade[{original_index}] requires net_pnl or gross_pnl")


def _parse_time(value: Any, *, field: str, original_index: int) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=UTC)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"trade[{original_index}] {field} must be ISO datetime compatible") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _optional_decimal(value: Any, *, field: str, original_index: int) -> Decimal | None:
    if not _has_value(value):
        return None
    return _to_decimal(value, field=field, original_index=original_index)


def _to_decimal(value: Any, *, field: str, original_index: int | None = None) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        prefix = f"trade[{original_index}] " if original_index is not None else ""
        raise ValueError(f"{prefix}{field} must be numeric") from exc


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


__all__ = ["generate_equity_curve"]

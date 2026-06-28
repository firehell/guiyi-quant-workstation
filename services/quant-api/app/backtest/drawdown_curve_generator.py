from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


def generate_drawdown_curve(equity_curve: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Generate drawdown points and max drawdown metrics from an equity curve."""
    if not equity_curve:
        return _empty_result()

    peak: Decimal | None = None
    max_drawdown_amount = Decimal("0")
    max_drawdown_pct = Decimal("0")
    drawdown_curve: list[dict[str, Any]] = []

    for original_index, point in enumerate(equity_curve):
        equity = _point_equity(point, original_index)
        peak = equity if peak is None else max(peak, equity)
        drawdown = max(peak - equity, Decimal("0"))
        drawdown_pct = drawdown / peak if peak > 0 else Decimal("0")
        max_drawdown_amount = max(max_drawdown_amount, drawdown)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        drawdown_curve.append(
            {
                "point_index": point.get("point_index", original_index),
                "time": point.get("time"),
                "equity": float(equity),
                "peak_equity": float(peak),
                "drawdown": float(drawdown),
                "drawdown_pct": float(drawdown_pct),
                "source_trade_id": point.get("trade_id") if _has_value(point.get("trade_id")) else None,
            }
        )

    return {
        "drawdown_curve": drawdown_curve,
        "max_drawdown": float(max_drawdown_pct),
        "max_drawdown_amount": float(max_drawdown_amount),
        "max_drawdown_pct": float(max_drawdown_pct),
    }


def _empty_result() -> dict[str, Any]:
    return {
        "drawdown_curve": [],
        "max_drawdown": 0.0,
        "max_drawdown_amount": 0.0,
        "max_drawdown_pct": 0.0,
    }


def _point_equity(point: Mapping[str, Any], original_index: int) -> Decimal:
    if not _has_value(point.get("equity")):
        raise ValueError(f"equity_curve[{original_index}] missing required equity")
    return _to_decimal(point.get("equity"), field="equity", original_index=original_index)


def _to_decimal(value: Any, *, field: str, original_index: int) -> Decimal:
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"equity_curve[{original_index}] {field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"equity_curve[{original_index}] {field} must be finite")
    return number


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


__all__ = ["generate_drawdown_curve"]

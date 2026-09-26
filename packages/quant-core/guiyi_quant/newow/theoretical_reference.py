"""Non-executable hindsight display over already paired closed reference trades."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .product_contracts import ProductBar, ProductStrategy
from .reference_trades import ReferenceTrade, ReferenceTradeStatus

THEORETICAL_MODEL_VERSION = "newow_hindsight_peak_reference_v1"


def theoretical_reference(trades: tuple[ReferenceTrade, ...], bars: tuple[ProductBar, ...]) -> dict[str, object] | None:
    """Keep pairing/entry price; trend/main-rise exit at peak close, oscillation at peak high.

    Never crosses an owner/calculation segment or forces open/interrupted trades closed.
    The peak is retrospective and cannot be an executable price.
    """
    rows: list[dict[str, str]] = []
    returns: list[Decimal] = []
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        for trade in trades:
            if trade.status is not ReferenceTradeStatus.CLOSED or trade.exit_bar_end is None:
                return None
            owned = [item for item in bars if item.bar.product == trade.product
                     and item.frequency == trade.frequency
                     and item.bar.physical_contract == trade.physical_contract
                     and item.bar.segment_id == trade.segment_id
                     and item.calculation_segment_id == (trade.calculation_segment_id or trade.segment_id)
                     and trade.entry_bar_end <= item.bar.bar_end <= trade.exit_bar_end]
            times = [item.bar.bar_end for item in owned]
            if (not owned or len(owned) != trade.holding_bars + 1 or len(set(times)) != len(times)
                or min(times) != trade.entry_bar_end or max(times) != trade.exit_bar_end
                or any(not item.bar.observation_eligible for item in owned)):
                return None
            peak = max(item.bar.high if trade.strategy_code is ProductStrategy.OSCILLATION else item.bar.close for item in owned)
            result = (peak / trade.entry_reference_price - Decimal(1)) * Decimal(100)
            returns.append(result)
            rows.append({"reference_trade_id": trade.reference_trade_id, "return_pct": str(result), "ideal_exit_price": str(peak)})
        count = len(returns)
        total = sum(returns, Decimal(0))
        return {"model_version": THEORETICAL_MODEL_VERSION, "hindsight": True, "executable": False,
                "returns": rows, "sum_return_percentage_points": str(total),
                "win_rate_pct": str(Decimal(sum(value > 0 for value in returns)) / Decimal(count) * Decimal(100)) if count else None,
                "mean_return_pct": str(total / Decimal(count)) if count else None}

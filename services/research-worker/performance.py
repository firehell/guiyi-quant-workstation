"""Statistics for a verified, cash-flow-free trading-day settlement window."""

from decimal import Decimal
from math import isfinite

import pandas as pd
from quantstats import stats


def daily_returns(days, settlements, initial_equity, *, external_cash_flow):
    """Bind the exact trading calendar and refuse unknown cash flows or gaps."""
    if external_cash_flow != 0:
        raise ValueError("CASH_FLOW_ADJUSTED_SERIES_REQUIRED")
    index = pd.DatetimeIndex(days)
    if (
        not len(days) or len(index) != len(settlements) or index.hasnans
        or not index.is_unique or not index.is_monotonic_increasing
        or list(settlements) != list(days)
    ):
        raise ValueError("SETTLEMENT_COVERAGE_MISMATCH")
    equity = [Decimal(initial_equity), *(Decimal(settlements[day]) for day in days)]
    if any(not value.is_finite() or value <= 0 for value in equity):
        raise ValueError("SETTLEMENT_EQUITY_INVALID")
    return pd.Series(
        [float(after / before - 1) for before, after in zip(equity, equity[1:])],
        index=index, dtype="float64",
    )


def drawdown_span(path):
    """Max-drawdown episode, from previous peak through recovery or cutoff."""
    valley = int(path.argmin())
    if path.iloc[valley] >= 0:
        return {"trading_days": 0, "ongoing": False}
    peaks = [i for i in range(valley) if path.iloc[i] >= 0]
    peak = peaks[-1] if peaks else -1
    recovery = next((i for i in range(valley + 1, len(path)) if path.iloc[i] >= 0), None)
    end = recovery if recovery is not None else len(path) - 1
    return {"trading_days": end - peak, "ongoing": recovery is None}


def calculate(returns, *, periods=252):
    if returns.empty or not returns.map(isfinite).all() or (returns <= -1).any():
        raise ValueError("DAILY_RETURNS_INVALID")
    # QuantStats may treat a nonnegative series above 1 as prices in its
    # internal return preparation. Keep that unsupported case explicit.
    if returns.min() >= 0 and returns.max() >= 1:
        raise ValueError("QUANTSTATS_RETURN_INPUT_AMBIGUOUS")
    drawdown = stats.to_drawdown_series(returns)
    depth = max(0.0, -float(stats.max_drawdown(returns)))
    annual = float(stats.cagr(returns, rf=0.0, compounded=True, periods=periods))
    ratios = {
        "sharpe": stats.sharpe(returns, rf=0.0, periods=periods, annualize=True, smart=False)
        if len(returns) >= 2 and returns.std(ddof=1) > 0 else None,
        "sortino": stats.sortino(returns, rf=0.0, periods=periods, annualize=True, smart=False)
        if len(returns) >= 2 and returns.min() < 0 else None,
        "calmar": stats.calmar(returns, prepare_returns=False, periods=periods)
        if len(returns) >= 2 and depth > 0 else None,
    }
    return {
        "sessions": len(returns),
        "annual_periods": periods,
        "annual_risk_free_rate": 0,
        "cumulative": float(stats.comp(returns)),
        "annualized": annual,
        "max_drawdown": depth,
        "drawdown_span": drawdown_span(drawdown),
        "daily_win_rate": float((returns > 0).mean()),
        "monthly": {
            str(month): float(stats.comp(group))
            for month, group in returns.groupby(returns.index.to_period("M"))
        },
        **{name: float(value) if value is not None and isfinite(value) else None
           for name, value in ratios.items()},
    }

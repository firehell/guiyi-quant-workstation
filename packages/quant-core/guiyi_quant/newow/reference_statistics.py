"""Pure closed-reference statistics for an explicit performance window."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .product_identity import utc_timestamp
from .reference_trades import (
    ReferenceProjection,
    ReferenceTrade,
    ReferenceTradeStatus,
)


STATISTICS_MEMBERSHIP_POLICY = "entry_in_window_v1"
INITIAL_MEMBERSHIP = "initial_before_window"


def _price(value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= Decimal("0")
    ):
        raise ValueError("NEWOW_STATISTICS_INVALID_PRICE")
    return value


def reference_return_pct(entry: Decimal, exit_: Decimal) -> Decimal:
    """Return long/flat zero-cost performance in percentage points."""

    entry = _price(entry)
    exit_ = _price(exit_)
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        return (exit_ / entry - Decimal("1")) * Decimal("100")


@dataclass(frozen=True, slots=True)
class PerformanceWindow:
    since: date
    through: date
    cutoff: datetime

    def __post_init__(self) -> None:
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("NEWOW_STATISTICS_INVALID_WINDOW")
        try:
            cutoff = utc_timestamp(self.cutoff)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_STATISTICS_INVALID_WINDOW") from error
        object.__setattr__(self, "cutoff", cutoff)


@dataclass(frozen=True, slots=True)
class ReferenceSummary:
    window: PerformanceWindow
    membership_policy: str
    closed_count: int
    win_count: int
    loss_count: int
    flat_count: int
    win_rate_pct: Decimal | None
    mean_return_pct: Decimal | None
    sum_return_percentage_points: Decimal | None
    open_count: int
    interrupted_count: int
    initial_count: int
    closed_trades: tuple[ReferenceTrade, ...]
    open_trades: tuple[ReferenceTrade, ...]
    interrupted_trades: tuple[ReferenceTrade, ...]
    initial_trades: tuple[ReferenceTrade, ...]


def _identity(trade: ReferenceTrade) -> tuple[object, ...]:
    return (
        trade.product,
        trade.strategy_code,
        trade.frequency,
        trade.formula_versions,
        trade.reference_model_version,
        trade.futures_adaptation_version,
    )


def _validate_projection(projection: ReferenceProjection, window: PerformanceWindow) -> None:
    if not isinstance(projection, ReferenceProjection):
        raise ValueError("NEWOW_STATISTICS_INVALID_PROJECTION")
    if projection.as_of > window.cutoff:
        raise ValueError("NEWOW_STATISTICS_LATER_PROJECTION")

    identity: tuple[object, ...] | None = None
    trade_ids: set[str] = set()
    for trade in projection.trades:
        if not isinstance(trade, ReferenceTrade):
            raise ValueError("NEWOW_STATISTICS_INVALID_PROJECTION")
        if trade.reference_trade_id in trade_ids:
            raise ValueError("NEWOW_STATISTICS_DUPLICATE_TRADE")
        trade_ids.add(trade.reference_trade_id)
        current_identity = _identity(trade)
        if identity is None:
            identity = current_identity
        elif current_identity != identity:
            raise ValueError("NEWOW_STATISTICS_MIXED_IDENTITY")
        timestamps = (
            trade.entry_bar_end,
            trade.exit_bar_end,
            trade.mark_bar_end,
            trade.interrupted_at,
        )
        if any(value is not None and value > projection.as_of for value in timestamps):
            raise ValueError("NEWOW_STATISTICS_INVALID_PROJECTION")


def _closed_metrics(
    trades: tuple[ReferenceTrade, ...],
) -> tuple[int, int, int, Decimal | None, Decimal | None, Decimal | None]:
    if not trades:
        return 0, 0, 0, None, None, None

    returns: list[Decimal] = []
    for trade in trades:
        if (
            trade.exit_reference_price is None
            or trade.reference_return_pct is None
        ):
            raise ValueError("NEWOW_STATISTICS_INVALID_PROJECTION")
        calculated = reference_return_pct(
            trade.entry_reference_price, trade.exit_reference_price
        )
        if calculated != trade.reference_return_pct:
            raise ValueError("NEWOW_STATISTICS_INVALID_PROJECTION")
        returns.append(calculated)

    win_count = sum(value > Decimal("0") for value in returns)
    loss_count = sum(value < Decimal("0") for value in returns)
    flat_count = len(returns) - win_count - loss_count
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        total = sum(returns, Decimal("0"))
        mean = total / Decimal(len(returns))
        win_rate = Decimal(win_count) / Decimal(len(returns)) * Decimal("100")
    return win_count, loss_count, flat_count, win_rate, mean, total


def summarize_reference(
    projection: ReferenceProjection, window: PerformanceWindow
) -> ReferenceSummary:
    """Summarize one product/strategy/frequency projection without account math."""

    if not isinstance(window, PerformanceWindow):
        raise ValueError("NEWOW_STATISTICS_INVALID_WINDOW")
    _validate_projection(projection, window)

    closed: list[ReferenceTrade] = []
    open_: list[ReferenceTrade] = []
    interrupted: list[ReferenceTrade] = []
    initial: list[ReferenceTrade] = []
    for trade in projection.trades:
        if trade.entry_trading_day < window.since:
            initial.append(replace(trade, statistics_membership=INITIAL_MEMBERSHIP))
            continue
        if trade.entry_trading_day > window.through:
            continue
        member = replace(
            trade, statistics_membership=STATISTICS_MEMBERSHIP_POLICY
        )
        if trade.status is ReferenceTradeStatus.CLOSED:
            closed.append(member)
        elif trade.status is ReferenceTradeStatus.OPEN:
            open_.append(member)
        elif trade.status is ReferenceTradeStatus.ROLLOVER_INTERRUPTED:
            interrupted.append(member)
        else:  # pragma: no cover - enum construction rejects unknown statuses
            raise ValueError("NEWOW_STATISTICS_INVALID_PROJECTION")

    closed_trades = tuple(closed)
    (
        win_count,
        loss_count,
        flat_count,
        win_rate,
        mean_return,
        sum_return,
    ) = _closed_metrics(closed_trades)
    return ReferenceSummary(
        window=window,
        membership_policy=STATISTICS_MEMBERSHIP_POLICY,
        closed_count=len(closed_trades),
        win_count=win_count,
        loss_count=loss_count,
        flat_count=flat_count,
        win_rate_pct=win_rate,
        mean_return_pct=mean_return,
        sum_return_percentage_points=sum_return,
        open_count=len(open_),
        interrupted_count=len(interrupted),
        initial_count=len(initial),
        closed_trades=closed_trades,
        open_trades=tuple(open_),
        interrupted_trades=tuple(interrupted),
        initial_trades=tuple(initial),
    )

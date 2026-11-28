"""Decimal checks over Plus's native trade callbacks and settlement account."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from math import isfinite

from .errors import BacktestError
from .plus_inputs import Day, Minute, finite

ZERO = Decimal(0)
QUANTUM = Decimal("0.00000001")
ACCOUNT_BINARY_TOLERANCE = Decimal("0.00001")
MONEY_POLICY = "cny_8_half_even_plus_account_binary_tolerance_v1"


def text(value: Decimal) -> str:
    return format(value, "f")


def money(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) >= Decimal("1e20"):
        raise BacktestError("PLUS_AMOUNT_OUT_OF_RANGE")
    return value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def raw_money(expected: Decimal, actual: float, *, account: bool = False) -> dict:
    value = float(actual)
    if not isfinite(value):
        raise BacktestError("PLUS_DECIMAL_RECONCILIATION_FAILED")
    exact = Decimal.from_float(value)
    delta = exact - expected
    accepted = abs(delta) <= ACCOUNT_BINARY_TOLERANCE if account else money(exact) == money(expected)
    if not accepted:
        raise BacktestError("PLUS_DECIMAL_RECONCILIATION_FAILED")
    return {"repr": repr(value), "hex": value.hex(), "binary_delta": text(delta)}


def parse_rates(raw) -> dict:
    if raw is None:
        raise BacktestError("PLUS_NATIVE_COMMISSION_OR_MARGIN_UNAVAILABLE")
    try:
        scheme = raw.commission_type.name
        rates = {
            "scheme": scheme,
            "OPEN": finite(raw.open_commission_ratio),
            "CLOSE": finite(raw.close_commission_ratio),
            "CLOSE_TODAY": finite(raw.close_commission_today_ratio),
            "margin": finite(raw.long_margin_ratio, positive=True),
            "short_margin": finite(raw.short_margin_ratio, positive=True),
        }
    except (AttributeError, ValueError, ArithmeticError):
        raise BacktestError("PLUS_NATIVE_COMMISSION_OR_MARGIN_UNAVAILABLE") from None
    if scheme not in {"BY_MONEY", "BY_VOLUME"} or rates["margin"] > 1 or rates["short_margin"] > 1:
        raise BacktestError("PLUS_NATIVE_COMMISSION_OR_MARGIN_UNAVAILABLE")
    return rates


def candidate_quote(
    candidate: Minute, daily: Day, tick: Decimal, slippage: int, *, buying: bool,
) -> tuple[Decimal, str | None]:
    price = candidate.open + tick * slippage * (1 if buying else -1)
    if candidate.volume < 1:
        return price, "FIRST_CANDIDATE_ZERO_VOLUME"
    if (buying and candidate.open >= daily.limit_up) or (not buying and candidate.open <= daily.limit_down):
        return price, "FIRST_CANDIDATE_AT_LIMIT"
    if not daily.limit_down <= price <= daily.limit_up:
        return price, "FIRST_CANDIDATE_SLIPPAGE_LIMIT"
    return price, None


def trade_amounts(
    rates: dict, effect: str, candidate: Minute, daily: Day, tick: Decimal, multiplier: int, *,
    slippage: int, commission_multiplier: Decimal,
) -> tuple[Decimal, Decimal]:
    price, blocked = candidate_quote(candidate, daily, tick, slippage, buying=effect == "OPEN")
    if blocked or price % tick != 0:
        raise BacktestError("PLUS_NATIVE_INELIGIBLE_FILL")
    fee = rates[effect] * commission_multiplier
    if rates["scheme"] == "BY_MONEY":
        fee *= price * multiplier
    return price, fee


class AccountWitness:
    def __init__(self, capital: Decimal, contract: str, multiplier: int):
        self.cash_basis = capital
        self.contract = contract
        self.multiplier = multiplier
        self.open_fill: dict | None = None
        self.settlement_basis: Decimal | None = None
        self.trades: list[dict] = []

    def trade(self, row: dict, day: date, price: Decimal, fee: Decimal) -> None:
        self.cash_basis -= fee
        if row["position_effect"] == "OPEN":
            if self.open_fill is not None:
                raise BacktestError("PLUS_NATIVE_UNEXPECTED_OPEN")
            self.open_fill = {**row, "economic_price": price, "economic_fee": fee, "day": day}
            self.settlement_basis = price
            return
        entry = self.open_fill
        if entry is None:
            raise BacktestError("PLUS_NATIVE_UNMATCHED_EXIT")
        gross = (price - entry["economic_price"]) * self.multiplier
        costs = entry["economic_fee"] + fee
        self.cash_basis += gross
        self.trades.append({
            **self._entry_fields(entry), "status": "CLOSED", "exit_at": row["modeled_fill_at"],
            "exit_price": text(price), "native_exit_id": row["native_trade_id"],
            "exit_signal_id": row["signal_id"], "fees": text(money(costs)), "net_pnl": text(money(gross - costs)),
            "unrealized_pnl": None,
        })
        self.open_fill = self.settlement_basis = None

    def account(self, actual, day: date, mark: Decimal, margin_rate: Decimal, *, settled: bool) -> tuple[dict, Decimal]:
        positions = tuple(position for position in actual.get_positions() if position.quantity)
        entry = self.open_fill
        if len(positions) != int(entry is not None):
            raise BacktestError("PLUS_NATIVE_POSITION_RECONCILIATION_FAILED")
        margin = position_pnl = unrealized = ZERO
        position_witness = None
        if entry is not None:
            position, = positions
            today = int(day == entry["day"])
            if (
                position.order_book_id != self.contract or position.direction.name != "LONG"
                or position.quantity != 1 or position.today_quantity != today or position.old_quantity != 1 - today
            ):
                raise BacktestError("PLUS_NATIVE_POSITION_RECONCILIATION_FAILED")
            unrealized = (mark - entry["economic_price"]) * self.multiplier
            margin = mark * self.multiplier * margin_rate
            basis = mark if settled else self.settlement_basis
            position_pnl = (mark - basis) * self.multiplier
            position_witness = {
                "last_price": raw_money(mark, position.last_price),
                "basis": raw_money(basis, position.avg_price),
                "equity": raw_money(position_pnl, position.equity, account=True),
            }
            if settled:
                self.settlement_basis = mark
        equity = self.cash_basis + unrealized
        cash = equity - position_pnl - margin
        return {
            "native_cash": raw_money(cash, actual.cash, account=True),
            "native_equity": raw_money(equity, actual.total_value, account=True),
            "native_margin": raw_money(margin, actual.margin, account=True),
            "native_frozen_cash": raw_money(ZERO, actual.frozen_cash),
            "native_position": position_witness,
        }, money(equity)

    def terminal(self, at: datetime, mark: Decimal, *, expired: bool = False) -> dict | None:
        if self.open_fill is None:
            return None
        entry = self.open_fill
        model_pnl = money((mark - entry["economic_price"]) * self.multiplier)
        result = {
            **self._entry_fields(entry), "marked_at": at.isoformat(), "mark_price": text(mark),
            "status": "ROLLOVER_INTERRUPTED" if expired else "OPEN", "exit_at": None, "exit_price": None,
            "fees": text(money(entry["economic_fee"])), "net_pnl": None, "unrealized_pnl": text(model_pnl),
        }
        self.trades.append(result)
        return result

    def _entry_fields(self, entry: dict) -> dict:
        return {
            "trade_id": entry["native_trade_id"], "native_entry_id": entry["native_trade_id"],
            "entry_signal_id": entry["signal_id"], "contract": self.contract, "direction": "LONG",
            "entry_at": entry["modeled_fill_at"], "entry_price": entry["price"], "quantity": 1,
        }


def metric(value, definition: str, unavailable: str | None = None) -> dict:
    return {
        "value": text(value) if isinstance(value, Decimal) else value,
        "source": "reconciled_RQAlpha_Plus",
        "definition": definition,
        "reason": unavailable if value is None else None,
    }


def metrics(curve: list[dict], all_trades: list[dict], capital: Decimal) -> dict:
    closed = [Decimal(row["net_pnl"]) for row in all_trades if row["status"] == "CLOSED"]
    wins = [pnl for pnl in closed if pnl > 0]
    losses = [-pnl for pnl in closed if pnl < 0]
    no_loss = "NO_LOSS_TRADES" if closed else "NO_CLOSED_TRADES"
    return {
        "net_return": metric(Decimal(curve[-1]["equity"]) / capital - 1,
                             "最终结算权益 / 初始资金 − 1，含手续费及未平仓结算估值"),
        "max_drawdown": metric(max(Decimal(row["drawdown"]) for row in curve),
                               "含初始资金的日结权益峰值至当日权益的最大百分比回撤"),
        "trade_count": metric(len(closed), "按同一物理合约开平配对的已平仓交易次数"),
        "win_rate": metric(Decimal(len(wins)) / len(closed) if closed else None,
                           "净盈亏大于零的已平交易占比", "NO_CLOSED_TRADES"),
        "profit_loss_ratio": metric(
            (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else None,
            "平均正净盈亏 / 平均负净盈亏绝对值", "NO_WIN_TRADES" if losses else no_loss,
        ),
        "profit_factor": metric(sum(wins, ZERO) / sum(losses) if losses else None,
                                "正净盈亏之和 / 负净盈亏之和绝对值", no_loss),
    }

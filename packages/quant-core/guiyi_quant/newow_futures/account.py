"""Decimal, integer-lot research account. No persistence, external orders or runtime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from hashlib import sha256

from .contracts import ExecutionFacts

D = Decimal
ZERO = D(0)


@dataclass(slots=True)
class Layer:
    layer_id: str
    qty: int
    entry_price: Decimal
    entry_day: date
    entry_at: datetime
    open_fee: Decimal
    stop: Decimal
    added: bool


class Account:
    def __init__(self) -> None:
        self.initial_cash = D("100000")
        self.cash = self.initial_cash
        self.side = 0
        self.contract: str | None = None
        self.layers: list[Layer] = []
        self.fills: list[dict] = []
        self.closed_trades: list[dict] = []
        self.total_fees = ZERO
        self.round_reduced = False
        self.adds = 0
        self.initial_risk_budget = ZERO
        self.initial_margin_budget = ZERO
        self.round_start_cash = self.cash
        self.round_entry_at: datetime | None = None
        self.round_entry_day: date | None = None
        self.round_entry_price = ZERO
        self.round_total_qty = 0
        self.round_id = 0

    @property
    def qty(self) -> int:
        return sum(layer.qty for layer in self.layers)

    @property
    def entry_price(self) -> Decimal:
        return (sum((layer.entry_price * layer.qty for layer in self.layers), ZERO) / self.qty
                if self.qty else ZERO)

    def equity(self, mark: Decimal, facts: ExecutionFacts) -> Decimal:
        if self.qty and self.contract != facts.physical_contract:
            raise ValueError("FUTURES_CROSS_CONTRACT_MARK")
        return self.cash + sum(((mark - layer.entry_price) * layer.qty * self.side * facts.multiplier
                                for layer in self.layers), ZERO)

    def margin(self, mark: Decimal, facts: ExecutionFacts) -> Decimal:
        ratio = facts.long_margin_ratio if self.side > 0 else facts.short_margin_ratio
        return self.qty * max(mark, facts.prev_settlement) * facts.multiplier * ratio

    @staticmethod
    def close_cost_per_unit(price: Decimal, facts: ExecutionFacts, *, slippage: int = 1) -> Decimal:
        return (max(facts.fees.amount("close", price, facts.multiplier),
                    facts.fees.amount("close_today", price, facts.multiplier)) / facts.multiplier
                + slippage * facts.tick_size)

    def open_quantity(self, side: int, price: Decimal, stop: Decimal, facts: ExecutionFacts,
                      *, add: bool = False, slippage: int = 1) -> int:
        if side not in (-1, 1) or (price - stop) * side <= 0 or stop <= 0:
            return 0
        if self.qty and (side != self.side or self.contract != facts.physical_contract):
            return 0
        if add and (not self.qty or self.round_reduced or self.adds >= 2):
            return 0
        if not add and self.qty:
            return 0
        equity = self.equity(price, facts)
        if equity <= 0:
            return 0
        factor = D(2) / 3 if self.adds == 0 else D(1) / 3
        risk_budget = self.initial_risk_budget * factor if add else equity * D(".005")
        margin_budget = self.initial_margin_budget * factor if add else equity * D(".10")
        open_fee = facts.fees.amount("open", price, facts.multiplier)
        close_fee = max(facts.fees.amount("close", stop, facts.multiplier),
                        facts.fees.amount("close_today", stop, facts.multiplier))
        per_risk = abs(price - stop) * facts.multiplier + open_fee + close_fee + 2 * slippage * facts.tick_size * facts.multiplier
        held_risk = sum((max(ZERO, (layer.entry_price - layer.stop) * self.side) * facts.multiplier * layer.qty
                         + layer.qty * (close_fee + slippage * facts.tick_size * facts.multiplier)
                         for layer in self.layers), ZERO)
        ratio = facts.long_margin_ratio if side > 0 else facts.short_margin_ratio
        per_margin = max(price, facts.prev_settlement) * facts.multiplier * ratio
        held_margin = self.margin(price, facts)
        capacity = min(risk_budget / per_risk,
                       max(ZERO, equity * D(".01") - held_risk) / per_risk,
                       margin_budget / per_margin,
                       max(ZERO, equity * D(".30") - held_margin) / (per_margin + open_fee),
                       max(ZERO, equity - held_margin) / (per_margin + open_fee))
        return max(0, int(capacity.to_integral_value(rounding=ROUND_FLOOR)))

    def tighten(self, stop: Decimal) -> None:
        for layer in self.layers:
            layer.stop = max(layer.stop, stop) if self.side > 0 else min(layer.stop, stop)

    def open(self, side: int, qty: int, price: Decimal, facts: ExecutionFacts, at: datetime,
             stop: Decimal, *, action: str, slippage: int = 1) -> None:
        add = action == "ADD"
        if action not in ("ENTER", "ADD") or type(qty) is not int or qty < 1:
            raise ValueError("FUTURES_OPEN_INVALID")
        if qty > self.open_quantity(side, price, stop, facts, add=add, slippage=slippage):
            raise ValueError("FUTURES_OPEN_RISK_REJECTED")
        if not self.qty:
            self.round_id += 1
            self.round_start_cash = self.cash
            self.initial_risk_budget = self.cash * D(".005")
            self.initial_margin_budget = self.cash * D(".10")
            self.round_entry_at = at
            self.round_entry_day = facts.trading_day
            self.round_entry_price = price
            self.round_total_qty = 0
            self.side, self.contract = side, facts.physical_contract
            self.round_reduced, self.adds = False, 0
        fee = qty * facts.fees.amount("open", price, facts.multiplier)
        layer_id = sha256(f"{self.contract}|{self.round_id}|{len(self.fills)}|{at.isoformat()}".encode()).hexdigest()
        self.layers.append(Layer(layer_id, qty, price, facts.trading_day, at, fee, stop, add))
        self.round_total_qty += qty
        self.cash -= fee
        self.total_fees += fee
        if add:
            self.adds += 1
        self.fills.append({"at": at.isoformat(), "action": "ADD" if add else "OPEN",
                           "side": "LONG" if side > 0 else "SHORT", "qty": qty,
                           "price": str(price), "fee": str(fee), "physical_contract": self.contract,
                           "layer_id": layer_id, "facts_id": facts.source_id})

    def reduce_quantity(self) -> int:
        if not self.qty:
            return 0
        added = [layer for layer in self.layers if layer.added]
        if added:
            return added[-1].qty
        return min(self.qty - 1, int((D(self.qty) * D(".20")).to_integral_value(rounding=ROUND_CEILING)))

    def close(self, qty: int, price: Decimal, facts: ExecutionFacts, at: datetime,
              *, reason: str, reduce: bool = False) -> None:
        if (type(qty) is not int or not 0 < qty <= self.qty
                or self.contract != facts.physical_contract):
            raise ValueError("FUTURES_CLOSE_INVALID")
        side, contract, remaining = self.side, self.contract, qty
        gross, fee, allocated_open = ZERO, ZERO, ZERO
        closed_layers = []
        for layer in reversed(self.layers):
            if remaining == 0:
                break
            taken = min(layer.qty, remaining)
            allocated = layer.open_fee * taken / layer.qty
            action = "close_today" if layer.entry_day == facts.trading_day else "close"
            fee += taken * facts.fees.amount(action, price, facts.multiplier)
            gross += (price - layer.entry_price) * side * facts.multiplier * taken
            allocated_open += allocated
            closed_layers.append({"layer_id": layer.layer_id, "qty": taken})
            layer.qty -= taken
            layer.open_fee -= allocated
            remaining -= taken
        self.layers = [layer for layer in self.layers if layer.qty]
        self.cash += gross - fee
        self.total_fees += fee
        self.round_reduced = self.round_reduced or reduce
        self.fills.append({"at": at.isoformat(), "action": "REDUCE" if reduce else "CLOSE",
                           "side": "LONG" if side > 0 else "SHORT", "qty": qty, "price": str(price),
                           "fee": str(fee), "gross_pnl": str(gross),
                           "net_pnl": str(gross - fee - allocated_open), "reason": reason,
                           "physical_contract": contract, "layers": closed_layers, "facts_id": facts.source_id})
        if not self.layers:
            self.closed_trades.append({
                "trade_id": sha256(f"{contract}|{self.round_id}|{self.round_entry_at}".encode()).hexdigest(),
                "side": "LONG" if side > 0 else "SHORT", "physical_contract": contract,
                "entry_at": self.round_entry_at.isoformat(), "exit_at": at.isoformat(),
                "entry_price": str(self.round_entry_price), "exit_price": str(price),
                "qty": self.round_total_qty, "net_pnl": str(self.cash - self.round_start_cash),
                "status": "CLOSED", "reason": reason, "added": self.adds > 0,
                "overnight": self.round_entry_day != facts.trading_day,
            })
            self.side, self.contract = 0, None

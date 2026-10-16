"""Replayable in-memory net account with individually protected entry layers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from guiyi_quant.new_subing import ExecutionFacts

D = Decimal
ZERO = D('0')


@dataclass
class Layer:
    layer_id: str
    entry_at: datetime
    trading_day: date
    entry_price: D
    qty: int
    original_qty: int
    open_fee: D
    stop: D
    atr: D
    frozen_level: D
    stage: str


class LayerAccount:
    def __init__(self, initial_cash: D, day_loss_fraction: D = D('.02')) -> None:
        if type(initial_cash) is not D or not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError('positive finite Decimal initial_cash required')
        self.initial_cash = initial_cash
        self.day_loss_fraction = day_loss_fraction
        self.cash = initial_cash
        self.layers: list[Layer] = []
        self._side = 0
        self.contract: str | None = None
        self.trading_day: date | None = None
        self.day_start_equity = initial_cash
        self.daily_halt = False
        self.total_fees = ZERO
        self.closed_trades: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []
        self.closed_loss_streak = 0
        self.opening_direction: int | None = None
        self._round_start_cash = initial_cash
        self._round_entry_at: datetime | None = None
        self._round_entry_qty = 0
        self._round_id = 0
        self._mark: D | None = None
        self._mark_facts: ExecutionFacts | None = None

    @property
    def qty(self) -> int:
        return self._side * sum(layer.qty for layer in self.layers)

    @property
    def side(self) -> int:
        return self._side if self.layers else 0

    @property
    def average_price(self) -> D:
        quantity = sum(layer.qty for layer in self.layers)
        return sum((layer.entry_price * layer.qty for layer in self.layers), ZERO) / quantity if quantity else ZERO

    def equity(self, mark: D | None = None, facts: ExecutionFacts | None = None) -> D:
        if not self.qty:
            return self.cash
        if mark is None:
            mark, facts = self._mark, self._mark_facts
        if mark is None or facts is None or facts.physical_contract != self.contract:
            raise ValueError('held physical contract mark/facts required')
        return self.cash + sum(((mark - layer.entry_price) * layer.qty * self.side * facts.multiplier
                                for layer in self.layers), ZERO)

    def begin_day(self, day: date, mark: D | None, facts: ExecutionFacts | None = None,
                  *, can_reset: bool = True) -> None:
        if self.trading_day == day:
            return
        self.day_start_equity = self.equity(mark, facts) if self.qty else self.cash
        self.trading_day = day
        self.closed_loss_streak = 0
        if can_reset and not self.qty:
            self.daily_halt = False
        self.opening_direction = None

    def mark(self, mark: D, facts: ExecutionFacts) -> D:
        if self.qty and facts.physical_contract != self.contract:
            raise ValueError('wrong physical contract')
        self._mark, self._mark_facts = mark, facts
        value = self.equity(mark, facts)
        if value <= self.day_start_equity * (1 - self.day_loss_fraction):
            self.daily_halt = True
        return value

    def open(self, side: int, qty: int, price: D, facts: ExecutionFacts, at: datetime,
             stop: D, atr: D, frozen_level: D, stage: str = 'TRIAL') -> dict[str, Any]:
        if side not in (-1, 1) or type(qty) is not int or qty < 1:
            raise ValueError('integer positive lots and side required')
        if self.qty and (self.side != side or self.contract != facts.physical_contract):
            raise ValueError('net account cannot lock or silently roll')
        if self.trading_day != facts.trading_day:
            self.begin_day(facts.trading_day, self._mark, self._mark_facts)
        if self.daily_halt or self.opening_direction not in (None, side):
            raise ValueError('opening halt or same-day reversal')
        if not self.qty:
            self._round_id += 1
            self._round_start_cash = self.cash
            self._round_entry_at = at
            self._round_entry_qty = side * qty
            self.contract = facts.physical_contract
            self._side = side
            self.opening_direction = side
        fee = facts.fees.amount('open', price, facts.multiplier) * qty
        layer_id = sha256(f'{self.contract}|{self._round_id}|{len(self.fills)}|{at.isoformat()}'.encode()).hexdigest()[:24]
        self.layers.append(Layer(layer_id, at, facts.trading_day, price, qty, qty, fee, stop, atr,
                                 frozen_level, stage))
        self.cash -= fee
        self.total_fees += fee
        fill = {'at': at.isoformat(), 'action': 'OPEN', 'side': 'LONG' if side > 0 else 'SHORT',
                'qty': qty, 'price': str(price), 'fee': str(fee), 'physical_contract': self.contract,
                'facts_id': facts.source_id, 'layer_id': layer_id, 'stop': str(stop),
                'atr': str(atr), 'frozen_level': str(frozen_level), 'stage': stage}
        self.fills.append(fill)
        self._mark, self._mark_facts = price, facts
        return fill

    def close(self, qty: int, price: D, facts: ExecutionFacts, at: datetime,
              *, layer_id: str | None = None) -> dict[str, Any]:
        if type(qty) is not int or qty < 1 or qty > abs(self.qty):
            raise ValueError('invalid close quantity')
        if facts.physical_contract != self.contract:
            raise ValueError('wrong physical contract')
        side = self.side
        available = [layer for layer in self.layers if layer_id is None or layer.layer_id == layer_id]
        if sum(layer.qty for layer in available) < qty:
            raise ValueError('named layer lacks close quantity')
        remaining = qty
        today_closed = yesterday_closed = 0
        fee = gross = ZERO
        layer_closes: list[dict[str, object]] = []
        for layer in available:
            if not remaining:
                break
            closed = min(remaining, layer.qty)
            same_day = layer.trading_day == facts.trading_day
            layer_fee = facts.fees.amount('close_today' if same_day else 'close', price, facts.multiplier) * closed
            layer_gross = (price - layer.entry_price) * side * facts.multiplier * closed
            fee += layer_fee
            gross += layer_gross
            today_closed += closed if same_day else 0
            yesterday_closed += 0 if same_day else closed
            layer.qty -= closed
            remaining -= closed
            layer_closes.append({'layer_id': layer.layer_id, 'qty': closed,
                                 'entry_price': str(layer.entry_price), 'entry_day': layer.trading_day.isoformat(),
                                 'gross_pnl': str(layer_gross), 'fee': str(layer_fee)})
        self.layers = [layer for layer in self.layers if layer.qty]
        self.cash += gross - fee
        self.total_fees += fee
        fill = {'at': at.isoformat(), 'action': 'CLOSE', 'side': 'LONG' if side > 0 else 'SHORT',
                'qty': qty, 'price': str(price), 'fee': str(fee), 'realized_pnl': str(gross),
                'close_today_qty': today_closed, 'close_yesterday_qty': yesterday_closed,
                'physical_contract': facts.physical_contract, 'facts_id': facts.source_id,
                'layer_closes': layer_closes, 'named_layer_id': layer_id}
        self.fills.append(fill)
        if not self.layers:
            net = self.cash - self._round_start_cash
            identity = f'{self.contract}|{self._round_entry_at}|{at}|{self._round_entry_qty}'
            self.closed_trades.append({'trade_id': sha256(identity.encode()).hexdigest()[:24],
                                       'side': 'LONG' if self._round_entry_qty > 0 else 'SHORT',
                                       'entry_at': self._round_entry_at.isoformat() if self._round_entry_at else None,
                                       'exit_at': at.isoformat(), 'net_pnl': str(net), 'status': 'CLOSED',
                                       'physical_contract': self.contract})
            self.closed_loss_streak = self.closed_loss_streak + 1 if net < 0 else 0
            self._side = 0
            self.contract = None
            self._mark = None
            self._mark_facts = None
        else:
            self._mark, self._mark_facts = price, facts
        return fill

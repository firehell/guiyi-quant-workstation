"""In-memory, deterministic net futures research account; never a broker ledger."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from functools import wraps
from hashlib import sha256
from typing import Any

ZERO = Decimal('0')


def _fixed_context(function):
    @wraps(function)
    def call(*args, **kwargs):
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            return function(*args, **kwargs)
    return call


class ResearchAccount:
    def __init__(self, initial_cash: Decimal, day_loss_fraction: Decimal = Decimal('.02')) -> None:
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError('initial_cash must be finite and positive')
        if not day_loss_fraction.is_finite() or not ZERO < day_loss_fraction < 1:
            raise ValueError('day_loss_fraction must be in (0, 1)')
        self.initial_cash = initial_cash
        self.day_loss_fraction = day_loss_fraction
        self.cash = initial_cash
        self.qty = 0
        self.average_price = ZERO
        self.contract: str | None = None
        self.today_qty = 0
        self.trading_day: date | None = None
        self.day_start_equity = initial_cash
        self.daily_halt = False
        self.total_fees = ZERO
        self.closed_trades: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []
        self._round_start_cash = initial_cash
        self._round_entry_at: datetime | None = None
        self._round_entry_qty = 0
        self._round_id = 0
        self._mark: Decimal | None = None
        self._mark_facts: Any = None
        self.closed_loss_streak = 0
        self.opening_direction: int | None = None

    @property
    def side(self) -> int:
        return (self.qty > 0) - (self.qty < 0)

    @_fixed_context
    def equity(self, mark: Decimal | None = None, facts: Any = None) -> Decimal:
        if self.qty == 0:
            return self.cash
        if mark is None:
            mark, facts = self._mark, self._mark_facts
        if mark is None or facts is None or facts.physical_contract != self.contract:
            raise ValueError('current physical-contract mark and facts required')
        return self.cash + Decimal(self.qty) * (mark - self.average_price) * facts.multiplier

    @_fixed_context
    def begin_day(self, day: date, mark: Decimal | None, facts: Any = None,
                  *, can_reset: bool = True) -> None:
        if self.trading_day == day:
            return
        if self.qty and (mark is None or facts is None or facts.physical_contract != self.contract):
            raise ValueError('day opening mark requires held contract')
        self.day_start_equity = self.equity(mark, facts) if self.qty else self.cash
        self.trading_day = day
        self.today_qty = 0
        self.closed_loss_streak = 0
        if can_reset and self.qty == 0:
            self.daily_halt = False
        self.opening_direction = None

    @_fixed_context
    def mark(self, mark: Decimal, facts: Any) -> Decimal:
        if facts.physical_contract != self.contract and self.qty:
            raise ValueError('mark contract differs from held contract')
        self._mark, self._mark_facts = mark, facts
        value = self.equity(mark, facts)
        if value <= self.day_start_equity * (1 - self.day_loss_fraction):
            self.daily_halt = True
        return value

    @_fixed_context
    def open(self, side: int, qty: int, price: Decimal, facts: Any, at: datetime,
             stop: Decimal, atr: Decimal, frozen_level: Decimal) -> dict[str, Any]:
        if side not in (-1, 1) or type(qty) is not int or qty < 1:
            raise ValueError('invalid opening side or quantity')
        if self.qty and (self.side != side or self.contract != facts.physical_contract):
            raise ValueError('net account cannot lock or silently roll')
        if self.trading_day is None:
            self.begin_day(facts.trading_day, None)
        if self.trading_day != facts.trading_day:
            self.begin_day(facts.trading_day, self._mark, self._mark_facts)
        if self.daily_halt:
            raise ValueError('daily halt blocks opening')
        if self.opening_direction is not None and self.opening_direction != side:
            raise ValueError('same-day reversal blocked')
        if self.qty == 0:
            self._round_id += 1
            self._round_start_cash = self.cash
            self._round_entry_at = at
            self._round_entry_qty = side * qty
            self.contract = facts.physical_contract
            self.average_price = price
            self.opening_direction = side
        else:
            old = abs(self.qty)
            self.average_price = (self.average_price * old + price * qty) / (old + qty)
        fee = facts.fees.amount('open', price, facts.multiplier) * qty
        self.cash -= fee
        self.total_fees += fee
        self.qty += side * qty
        self.today_qty += qty
        fill = {'at': at.isoformat(), 'action': 'OPEN', 'side': 'LONG' if side > 0 else 'SHORT',
                'qty': qty, 'price': str(price), 'fee': str(fee),
                'physical_contract': facts.physical_contract, 'facts_id': facts.source_id,
                'stop': str(stop), 'atr': str(atr), 'frozen_level': str(frozen_level)}
        self.fills.append(fill)
        self._mark, self._mark_facts = price, facts
        return fill

    @_fixed_context
    def close(self, qty: int, price: Decimal, facts: Any, at: datetime) -> dict[str, Any]:
        if type(qty) is not int or qty < 1 or qty > abs(self.qty):
            raise ValueError('invalid close quantity')
        if facts.physical_contract != self.contract:
            raise ValueError('close contract differs from held contract')
        side = self.side
        prior_qty = abs(self.qty) - self.today_qty
        prior_closed = min(prior_qty, qty)
        today_closed = qty - prior_closed
        fee = (facts.fees.amount('close', price, facts.multiplier) * prior_closed +
               facts.fees.amount('close_today', price, facts.multiplier) * today_closed)
        realized = (price - self.average_price) * facts.multiplier * side * qty
        self.cash += realized - fee
        self.total_fees += fee
        self.qty -= side * qty
        self.today_qty -= today_closed
        fill = {'at': at.isoformat(), 'action': 'CLOSE',
                'side': 'LONG' if side > 0 else 'SHORT',
                'qty': qty, 'price': str(price), 'fee': str(fee), 'realized_pnl': str(realized),
                'close_today_qty': today_closed, 'close_yesterday_qty': prior_closed,
                'physical_contract': facts.physical_contract, 'facts_id': facts.source_id}
        self.fills.append(fill)
        if self.qty == 0:
            net = self.cash - self._round_start_cash
            trade_identity = f'{self.contract}|{self._round_entry_at.isoformat() if self._round_entry_at else ""}|{at.isoformat()}|{self._round_entry_qty}'
            trade = {'trade_id': sha256(trade_identity.encode()).hexdigest()[:24],
                     'side': 'LONG' if self._round_entry_qty > 0 else 'SHORT',
                     'entry_at': self._round_entry_at.isoformat() if self._round_entry_at else None,
                     'exit_at': at.isoformat(), 'net_pnl': str(net), 'status': 'CLOSED',
                     'physical_contract': self.contract}
            self.closed_trades.append(trade)
            self.closed_loss_streak = self.closed_loss_streak + 1 if net < 0 else 0
            self.contract = None
            self.average_price = ZERO
            self.today_qty = 0
            self._mark = None
            self._mark_facts = None
        else:
            self._mark, self._mark_facts = price, facts
        return fill

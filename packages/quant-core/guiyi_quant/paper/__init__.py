"""Deterministic, local-only JM Paper model. No broker or data-provider I/O.

Execution is a historical next-1m-open model. A completed bar is observed at its
end; an eligible order is priced at that bar's open and recorded at observation.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from hashlib import sha256
import json
import re
from typing import Any


ZERO = Decimal('0')
ONE = Decimal('1')


def _positive(value: Decimal, name: str, *, allow_zero: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite() or (value < 0 if allow_zero else value <= 0):
        raise ValueError(f'{name} must be a finite positive Decimal')


def _time(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name} must be timezone-aware')


def _str(value: str, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')



def _physical_contract(value: str) -> None:
    _str(value, 'physical_contract')
    if re.fullmatch(r'JM\d{4}(?:\.DCE)?', value) is None:
        raise ValueError('JM Paper requires a physical JM contract, not an actual-dominant series')


def _qty(value: int, name: str, maximum: int = 1) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'{name} must be an integer from 0 to {maximum}')


@dataclass(frozen=True)
class PaperProfile:
    profile_id: str
    strategy_version: str
    product: str = 'jm'
    frequency: str = '5m'
    initial_cash: Decimal = Decimal('50000')
    daily_loss_fraction: Decimal = Decimal('0.02')

    def __post_init__(self) -> None:
        for name in ('profile_id', 'strategy_version', 'product', 'frequency'):
            _str(getattr(self, name), name)
        _positive(self.initial_cash, 'initial_cash')
        _positive(self.daily_loss_fraction, 'daily_loss_fraction')
        if (self.product.lower() != 'jm' or self.frequency != '5m' or
            self.daily_loss_fraction != Decimal('0.02') or self.initial_cash != Decimal('50000')):
            raise ValueError('this Paper profile is limited to JM 5m with a 2% daily loss stop')


@dataclass(frozen=True)
class FeeSchedule:
    open_rate: Decimal
    open_per_contract: Decimal
    close_rate: Decimal
    close_per_contract: Decimal
    close_today_rate: Decimal
    close_today_per_contract: Decimal
    source_id: str

    def __post_init__(self) -> None:
        for name in ('open_rate', 'open_per_contract', 'close_rate', 'close_per_contract', 'close_today_rate', 'close_today_per_contract'):
            _positive(getattr(self, name), name, allow_zero=True)
        _str(self.source_id, 'source_id')

    def amount(self, kind: str, price: Decimal, multiplier: Decimal) -> Decimal:
        if kind not in ('open', 'close', 'close_today'):
            raise ValueError('unknown fee kind')
        return price * multiplier * getattr(self, f'{kind}_rate') + getattr(self, f'{kind}_per_contract')


@dataclass(frozen=True)
class Initialize:
    command_id: str
    at: datetime
    profile: PaperProfile

    def __post_init__(self) -> None:
        _str(self.command_id, 'command_id')
        _time(self.at, 'at')
        if type(self.profile) is not PaperProfile:
            raise TypeError('profile must be PaperProfile')


@dataclass(frozen=True)
class BeginTradingDay:
    command_id: str
    at: datetime
    trading_day: str
    reconciled_qty: int
    reconciled_contract: str | None
    reconciliation_fact_id: str

    def __post_init__(self) -> None:
        _str(self.command_id, 'command_id')
        _time(self.at, 'at')
        _str(self.trading_day, 'trading_day')
        if date.fromisoformat(self.trading_day).isoformat() != self.trading_day:
            raise ValueError('trading_day must be ISO date')
        _qty(self.reconciled_qty, 'reconciled_qty')
        if self.reconciled_contract is not None:
            _physical_contract(self.reconciled_contract)
        _str(self.reconciliation_fact_id, 'reconciliation_fact_id')
        if (self.reconciled_qty == 0) != (self.reconciled_contract is None):
            raise ValueError('reconciled quantity and contract mismatch')


@dataclass(frozen=True)
class ObserveDecision:
    command_id: str
    at: datetime
    decision_id: str
    source_hash: str
    action: str
    signal_bar_end: datetime
    effective_after: datetime
    trading_day: str
    physical_contract: str
    limit_price: Decimal | None
    profile_id: str
    strategy_version: str
    frequency: str

    def __post_init__(self) -> None:
        for name in ('command_id', 'decision_id', 'source_hash', 'trading_day', 'physical_contract', 'profile_id', 'strategy_version', 'frequency'):
            _str(getattr(self, name), name)
        for name in ('at', 'signal_bar_end', 'effective_after'):
            _time(getattr(self, name), name)
        _physical_contract(self.physical_contract)
        if self.action not in ('BUILD', 'CLEAR', 'HOLD'):
            raise ValueError('invalid action')
        if self.at < self.signal_bar_end or self.effective_after < self.signal_bar_end:
            raise ValueError('decision cannot precede completed signal')
        if self.limit_price is not None:
            _positive(self.limit_price, 'limit_price')


@dataclass(frozen=True)
class ObserveExecutionBar:
    command_id: str
    observed_at: datetime
    trading_day: str
    physical_contract: str
    bar_start: datetime
    bar_end: datetime
    completed: bool
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    session_open: bool
    limit_up: Decimal
    limit_down: Decimal
    tick_size: Decimal
    slippage_ticks: int
    multiplier: Decimal
    fees: FeeSchedule
    margin_per_contract: Decimal
    market_fact_id: str
    cost_fact_id: str
    limit_fact_id: str
    margin_fact_id: str

    def __post_init__(self) -> None:
        for name in ('command_id', 'trading_day', 'physical_contract', 'market_fact_id', 'cost_fact_id', 'limit_fact_id', 'margin_fact_id'):
            _str(getattr(self, name), name)
        _physical_contract(self.physical_contract)
        for name in ('observed_at', 'bar_start', 'bar_end'):
            _time(getattr(self, name), name)
        if self.bar_end - self.bar_start != timedelta(minutes=1) or self.observed_at < self.bar_end:
            raise ValueError('bar must be observed after its end')
        if type(self.completed) is not bool or type(self.session_open) is not bool:
            raise TypeError('bar flags must be bool')
        for name in ('open', 'high', 'low', 'close', 'limit_up', 'limit_down', 'tick_size', 'multiplier'):
            _positive(getattr(self, name), name)
        _positive(self.margin_per_contract, 'margin_per_contract', allow_zero=True)
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError('invalid OHLC range')
        if self.limit_down >= self.limit_up:
            raise ValueError('invalid exchange limits')
        if type(self.volume) is not int or self.volume < 0 or type(self.slippage_ticks) is not int or self.slippage_ticks < 0:
            raise ValueError('volume and slippage ticks must be nonnegative integers')
        if type(self.fees) is not FeeSchedule:
            raise TypeError('fees must be FeeSchedule')


@dataclass(frozen=True)
class ResolveOrder:
    command_id: str
    at: datetime
    order_id: str
    outcome: str
    reconciliation_fact_id: str

    def __post_init__(self) -> None:
        _str(self.command_id, 'command_id')
        _time(self.at, 'at')
        _str(self.order_id, 'order_id')
        _str(self.reconciliation_fact_id, 'reconciliation_fact_id')
        if self.outcome not in ('CANCELLED', 'REJECTED', 'UNKNOWN'):
            raise ValueError('resolution cannot inject a fill')


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    decision_id: str
    side: str
    contract: str
    created_at: datetime
    effective_after: datetime
    limit_price: Decimal | None
    status: str = 'PENDING'
    qty: int = 1


@dataclass(frozen=True)
class PaperFill:
    fill_id: str
    order_id: str
    side: str
    contract: str
    fill_at: datetime
    recorded_at: datetime
    price: Decimal
    fee: Decimal
    fee_source_id: str
    market_fact_id: str
    cost_fact_id: str
    margin_fact_id: str
    qty: int = 1


@dataclass(frozen=True)
class PaperState:
    profile: PaperProfile
    cash: Decimal
    equity: Decimal
    trading_day: str | None = None
    day_start_equity: Decimal | None = None
    daily_halt: bool = False
    rollover_halt: bool = False
    position_qty: int = 0
    position_contract: str | None = None
    entry_price: Decimal | None = None
    entry_trading_day: str | None = None
    position_multiplier: Decimal | None = None
    mark_price: Decimal | None = None
    mark_at: datetime | None = None
    orders: tuple[PaperOrder, ...] = ()
    fills: tuple[PaperFill, ...] = ()
    decisions: tuple[tuple[str, str], ...] = ()
    last_command_id: str | None = None
    last_command_hash: str | None = None
    last_event_id: str | None = None
    last_bar_end: datetime | None = None


@dataclass(frozen=True)
class PaperEvent:
    event_id: str
    command_id: str
    command_hash: str
    kind: str
    at: datetime
    previous_event_id: str | None
    command: dict[str, Any]
    changes: dict[str, Any]


_TYPES = {t.__name__: t for t in (PaperProfile, FeeSchedule, Initialize, BeginTradingDay,
    ObserveDecision, ObserveExecutionBar, ResolveOrder, PaperOrder, PaperFill, PaperState, PaperEvent)}
_COMMAND_TYPES = (Initialize, BeginTradingDay, ObserveDecision, ObserveExecutionBar, ResolveOrder)


def _encode(value: Any) -> Any:
    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError('nonfinite Decimal')
        return {'$decimal': str(value)}
    if type(value) is datetime:
        _time(value, 'datetime')
        return {'$datetime': value.isoformat()}
    if type(value) is tuple:
        return {'$tuple': [_encode(v) for v in value]}
    if type(value) is list:
        return [_encode(v) for v in value]
    if hasattr(value, '__dataclass_fields__'):
        return {'$type': type(value).__name__, **{f.name: _encode(getattr(value, f.name)) for f in fields(value)}}
    if type(value) is dict:
        return {k: _encode(v) for k, v in value.items()}
    if value is None or type(value) in (str, int, bool):
        return value
    raise TypeError('unsupported serialized type')


def _decode(value: Any) -> Any:
    if type(value) is list:
        return [_decode(v) for v in value]
    if type(value) is dict:
        if '$decimal' in value:
            if set(value) != {'$decimal'} or type(value['$decimal']) is not str:
                raise ValueError('invalid Decimal encoding')
            result = Decimal(value['$decimal'])
            if not result.is_finite():
                raise ValueError('nonfinite Decimal')
            return result
        if '$datetime' in value:
            if set(value) != {'$datetime'} or type(value['$datetime']) is not str:
                raise ValueError('invalid datetime encoding')
            time_value = datetime.fromisoformat(value['$datetime'])
            _time(time_value, 'datetime')
            return time_value
        if '$tuple' in value:
            if set(value) != {'$tuple'} or type(value['$tuple']) is not list:
                raise ValueError('invalid tuple encoding')
            return tuple(_decode(v) for v in value['$tuple'])
        if '$type' in value:
            name = value['$type']
            if name not in _TYPES:
                raise ValueError('unknown serialized type')
            cls = _TYPES[name]
            expected = {f.name for f in fields(cls)} | {'$type'}
            if set(value) != expected:
                raise ValueError('serialized fields mismatch')
            if cls is PaperEvent:
                return cls(**{f.name: value[f.name] if f.name in ('command', 'changes') else _decode(value[f.name]) for f in fields(cls)})
            return cls(**{f.name: _decode(value[f.name]) for f in fields(cls)})
        return {k: _decode(v) for k, v in value.items()}
    if value is None or type(value) in (str, int, bool):
        return value
    raise TypeError('invalid serialized value')


def command_to_dict(command: Any) -> dict[str, Any]:
    if type(command) not in _COMMAND_TYPES:
        raise TypeError('unknown Paper command')
    return _encode(command)


def command_from_dict(value: dict[str, Any]) -> Any:
    result = _decode(value)
    if type(result) not in _COMMAND_TYPES:
        raise TypeError('unknown Paper command')
    return result


def event_to_dict(event: PaperEvent) -> dict[str, Any]:
    if type(event) is not PaperEvent:
        raise TypeError('expected PaperEvent')
    return _encode(event)


def event_from_dict(value: dict[str, Any]) -> PaperEvent:
    result = _decode(value)
    if type(result) is not PaperEvent:
        raise TypeError('expected PaperEvent')
    return result


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _order_id(decision_id: str, side: str) -> str:
    return _hash({'decision_id': decision_id, 'side': side})[:32]


def _mark(state: PaperState, price: Decimal, at: datetime) -> PaperState:
    if state.position_qty:
        assert state.entry_price is not None and state.position_multiplier is not None
        equity = state.cash + (price - state.entry_price) * state.position_multiplier
        return replace(state, equity=equity, mark_price=price, mark_at=at)
    return replace(state, equity=state.cash, mark_price=price, mark_at=at)


def _active_order(state: PaperState, side: str) -> bool:
    return any(o.side == side and o.status in ('PENDING', 'CANCEL_REQUESTED', 'UNKNOWN') for o in state.orders)


def _add_order(state: PaperState, *, decision_id: str, side: str, contract: str,
               at: datetime, effective_after: datetime, limit_price: Decimal | None) -> PaperState:
    if _active_order(state, side):
        return state
    order = PaperOrder(_order_id(decision_id, side), decision_id, side, contract, at, effective_after, limit_price)
    return replace(state, orders=(*state.orders, order))


def _halt(state: PaperState, at: datetime) -> PaperState:
    orders = tuple(replace(o, status='CANCEL_REQUESTED') if o.status == 'PENDING'
                   and (o.side == 'OPEN' or (o.side == 'CLOSE' and o.limit_price is not None)) else o
                   for o in state.orders)
    state = replace(state, daily_halt=True, orders=orders)
    if state.position_qty and not _active_order(state, 'CLOSE'):
        assert state.position_contract is not None
        state = _add_order(state, decision_id=f'daily-halt:{state.trading_day}', side='CLOSE',
                           contract=state.position_contract, at=at, effective_after=at, limit_price=None)
    return state


def _fill_price(order: PaperOrder, bar: ObserveExecutionBar) -> Decimal | None:
    if bar.volume == 0 or not bar.session_open or bar.open < bar.limit_down or bar.open > bar.limit_up:
        return None
    if order.side == 'OPEN':
        if bar.open >= bar.limit_up:
            return None
        raw = bar.open + bar.tick_size * bar.slippage_ticks
        price = (raw / bar.tick_size).to_integral_value(rounding=ROUND_CEILING) * bar.tick_size
        if price > bar.limit_up or (order.limit_price is not None and price > order.limit_price):
            return None
    else:
        if bar.open <= bar.limit_down:
            return None
        raw = bar.open - bar.tick_size * bar.slippage_ticks
        price = (raw / bar.tick_size).to_integral_value(rounding=ROUND_FLOOR) * bar.tick_size
        if price < bar.limit_down or (order.limit_price is not None and price < order.limit_price):
            return None
    return price


def _on_bar(state: PaperState, bar: ObserveExecutionBar) -> PaperState:
    if not bar.completed:
        return state
    if state.last_bar_end is not None and bar.bar_start < state.last_bar_end:
        raise ValueError('overlapping or backward execution bar')
    if bar.trading_day != state.trading_day:
        raise ValueError('execution bar trading day does not match active day')
    state = replace(state, last_bar_end=bar.bar_end)
    old_exposure = (state.position_qty and bar.physical_contract != state.position_contract) or any(
        o.side == 'OPEN' and o.status == 'PENDING' and o.contract != bar.physical_contract for o in state.orders)
    if old_exposure:
        state = replace(state, rollover_halt=True,
            orders=tuple(replace(o, status='CANCEL_REQUESTED') if o.side == 'OPEN' and o.status == 'PENDING' else o for o in state.orders))
        if state.position_qty and not _active_order(state, 'CLOSE'):
            assert state.position_contract is not None
            state = _add_order(state, decision_id=f'rollover:{state.trading_day}:{state.position_contract}',
                side='CLOSE', contract=state.position_contract, at=bar.bar_end,
                effective_after=bar.bar_end, limit_price=None)
        return state
    for order in state.orders:
        if order.status != 'PENDING' or order.contract != bar.physical_contract:
            continue
        if bar.bar_start <= order.created_at or bar.bar_start <= order.effective_after:
            continue
        price = _fill_price(order, bar)
        if price is None:
            continue
        if order.side == 'OPEN':
            if state.daily_halt or state.rollover_halt or state.position_qty or _active_order(state, 'CLOSE'):
                continue
            fee = bar.fees.amount('open', price, bar.multiplier)
            if state.cash < bar.margin_per_contract + fee:
                continue
            state = replace(state, cash=state.cash-fee, position_qty=1,
                position_contract=order.contract, entry_price=price,
                entry_trading_day=bar.trading_day, position_multiplier=bar.multiplier)
        else:
            if state.position_qty != 1 or state.position_contract != order.contract:
                continue
            assert state.entry_price is not None and state.position_multiplier is not None
            fee_kind = 'close_today' if state.entry_trading_day == bar.trading_day else 'close'
            fee = bar.fees.amount(fee_kind, price, bar.multiplier)
            state = replace(state, cash=state.cash+(price-state.entry_price)*state.position_multiplier-fee,
                position_qty=0, position_contract=None, entry_price=None, entry_trading_day=None,
                position_multiplier=None)
        fill = PaperFill(_hash({'order_id': order.order_id, 'market_fact_id': bar.market_fact_id})[:32],
            order.order_id, order.side, order.contract, bar.bar_start, bar.observed_at, price, fee,
            bar.fees.source_id, bar.market_fact_id, bar.cost_fact_id, bar.margin_fact_id)
        state = replace(state, orders=tuple(replace(o, status='FILLED') if o.order_id == order.order_id else o for o in state.orders),
            fills=(*state.fills, fill))
    state = _mark(state, bar.close, bar.bar_end)
    if not state.daily_halt and state.day_start_equity is not None:
        if state.equity <= state.day_start_equity * (ONE-state.profile.daily_loss_fraction):
            state = _halt(state, bar.bar_end)
    if state.position_qty and state.equity < bar.margin_per_contract and not state.daily_halt:
        state = _halt(state, bar.bar_end)
    return state


def apply_command(state: PaperState | None, command: Any) -> tuple[PaperEvent, ...]:
    data = command_to_dict(command)
    command_hash = _hash(data)
    if state is not None:
        if state.last_command_id == command.command_id:
            if state.last_command_hash == command_hash:
                return ()
            raise ValueError('command id reused with changed payload')
    if type(command) is Initialize:
        if state is not None:
            raise ValueError('Paper account already initialized')
        new = PaperState(command.profile, command.profile.initial_cash, command.profile.initial_cash)
        at = command.at
    else:
        if state is None:
            raise ValueError('Paper account must be initialized')
        if type(command) is BeginTradingDay:
            if state.last_bar_end is not None and command.at < state.last_bar_end:
                raise ValueError('new trading day cannot precede previous observation')
            if state.trading_day is not None and command.trading_day <= state.trading_day:
                raise ValueError('trading day must advance')
            if command.reconciled_qty != state.position_qty or command.reconciled_contract != state.position_contract:
                raise ValueError('position reconciliation mismatch')
            unresolved = any(o.status in ('PENDING', 'CANCEL_REQUESTED', 'UNKNOWN') for o in state.orders)
            may_reset_halts = state.position_qty == 0 and not unresolved
            new = replace(state, trading_day=command.trading_day, day_start_equity=state.equity,
                daily_halt=state.daily_halt and not may_reset_halts,
                rollover_halt=state.rollover_halt and not may_reset_halts,
                last_bar_end=None)
            at = command.at
        elif type(command) is ObserveDecision:
            if (command.profile_id, command.strategy_version, command.frequency) != (
                state.profile.profile_id, state.profile.strategy_version, state.profile.frequency):
                raise ValueError('decision identity does not match Paper profile')
            if command.trading_day != state.trading_day:
                raise ValueError('decision trading day mismatch')
            if state.last_bar_end is not None and command.at < state.last_bar_end:
                raise ValueError('decision arrived behind completed execution bars')
            decision_data = dict(data)
            decision_data.pop('command_id')
            decision_hash = _hash(decision_data)
            prior = dict(state.decisions).get(command.decision_id)
            if prior is not None and prior != decision_hash:
                raise ValueError('decision id reused with changed payload')
            new = state
            if prior is None:
                new = replace(new, decisions=(*new.decisions, (command.decision_id, decision_hash)))
                if command.action == 'BUILD':
                    if (not new.daily_halt and not new.rollover_halt and new.position_qty == 0 and
                        not _active_order(new, 'OPEN') and not _active_order(new, 'CLOSE') and
                        all(o.status != 'UNKNOWN' for o in new.orders)):
                        new = _add_order(new, decision_id=command.decision_id, side='OPEN',
                            contract=command.physical_contract, at=command.at,
                            effective_after=command.effective_after, limit_price=command.limit_price)
                    elif new.position_qty and command.physical_contract != new.position_contract:
                        new = replace(new, rollover_halt=True)
                        if not _active_order(new, 'CLOSE'):
                            assert new.position_contract is not None
                            new = _add_order(new, decision_id=f'rollover:{new.trading_day}:{new.position_contract}',
                                side='CLOSE', contract=new.position_contract, at=command.at,
                                effective_after=command.effective_after, limit_price=None)
                elif command.action == 'CLEAR':
                    if new.position_qty and not _active_order(new, 'CLOSE'):
                        if command.physical_contract != new.position_contract:
                            raise ValueError('cannot close old position with new physical contract')
                        new = _add_order(new, decision_id=command.decision_id, side='CLOSE',
                            contract=command.physical_contract, at=command.at,
                            effective_after=command.effective_after, limit_price=command.limit_price)
                    elif new.position_qty == 0:
                        new = replace(new, orders=tuple(
                            replace(o, status='CANCEL_REQUESTED') if o.side == 'OPEN' and o.status == 'PENDING' else o
                            for o in new.orders))
            at = command.at
        elif type(command) is ObserveExecutionBar:
            new = _on_bar(state, command)
            at = command.observed_at
        elif type(command) is ResolveOrder:
            matches = [o for o in state.orders if o.order_id == command.order_id]
            if len(matches) != 1 or matches[0].status not in ('PENDING', 'CANCEL_REQUESTED', 'UNKNOWN'):
                raise ValueError('order is not unresolved')
            if command.at < matches[0].created_at:
                raise ValueError('order cannot be resolved before creation')
            new = replace(state, orders=tuple(replace(o, status=command.outcome) if o.order_id == command.order_id else o for o in state.orders))
            if (command.outcome in ('CANCELLED', 'REJECTED') and matches[0].side == 'CLOSE' and
                new.position_qty and (new.daily_halt or new.rollover_halt) and not _active_order(new, 'CLOSE')):
                assert new.position_contract is not None
                new = _add_order(new, decision_id=f'forced-reissue:{matches[0].order_id}:{command.command_id}',
                    side='CLOSE', contract=new.position_contract, at=command.at,
                    effective_after=command.at, limit_price=None)
            at = command.at
        else:
            raise TypeError('unknown Paper command')
    old_event_id = None if state is None else state.last_event_id
    old_fields = {} if state is None else {f.name: getattr(state, f.name) for f in fields(PaperState)}
    changes = {f.name: _encode(getattr(new, f.name)) for f in fields(PaperState)
               if f.name not in ('last_command_id', 'last_command_hash', 'last_event_id',
                                 'decisions', 'orders', 'fills')
               and (state is None or getattr(new, f.name) != old_fields[f.name])}
    if state is None:
        changes.update({name: _encode(getattr(new, name)) for name in ('decisions', 'orders', 'fills')})
    else:
        for name in ('decisions', 'fills'):
            before = getattr(state, name)
            after = getattr(new, name)
            if after[:len(before)] != before:
                raise ValueError(f'{name} ledger cannot be rewritten')
            if len(after) > len(before):
                changes[f'{name}_append'] = _encode(after[len(before):])
        before_orders = state.orders
        after_orders = new.orders
        if len(after_orders) < len(before_orders) or any(
            old.order_id != updated.order_id for old, updated in zip(before_orders, after_orders)):
            raise ValueError('order ledger cannot be reordered or deleted')
        updates = tuple(updated for old, updated in zip(before_orders, after_orders) if old != updated)
        if updates:
            changes['orders_update'] = _encode(updates)
        if len(after_orders) > len(before_orders):
            changes['orders_append'] = _encode(after_orders[len(before_orders):])
    event_id = _hash({'command_id': command.command_id, 'command_hash': command_hash,
                      'previous_event_id': old_event_id, 'command': data, 'changes': changes})
    return (PaperEvent(event_id, command.command_id, command_hash, type(command).__name__, at, old_event_id, data, changes),)


def apply_events(state: PaperState | None, events: tuple[PaperEvent, ...] | list[PaperEvent]) -> PaperState:
    """Apply a bounded event batch without replaying earlier history."""
    for event in events:
        if type(event) is not PaperEvent:
            raise TypeError('expected PaperEvent')
        expected = _hash({'command_id': event.command_id, 'command_hash': event.command_hash,
                          'previous_event_id': event.previous_event_id, 'command': event.command,
                          'changes': event.changes})
        if event.event_id != expected or _hash(event.command) != event.command_hash:
            raise ValueError('event identity mismatch')
        command = command_from_dict(event.command)
        if type(command).__name__ != event.kind or command.command_id != event.command_id:
            raise ValueError('event command type mismatch')
        if state is not None and state.last_command_id == event.command_id:
            if state.last_command_hash == event.command_hash and state.last_event_id == event.event_id:
                continue
            raise ValueError('command id reused with changed payload')
        if event.previous_event_id != (None if state is None else state.last_event_id):
            raise ValueError('event chain mismatch')
        if apply_command(state, command) != (event,):
            raise ValueError('event transition mismatch')
        if state is None:
            if event.kind != 'Initialize':
                raise ValueError('first Paper event must initialize')
            required = {'profile', 'cash', 'equity'}
            if not required.issubset(event.changes):
                raise ValueError('incomplete initialization event')
            state = PaperState(**{key: _decode(value) for key, value in event.changes.items()})
        else:
            delta_names = {'decisions_append', 'fills_append', 'orders_append', 'orders_update'}
            allowed = ({f.name for f in fields(PaperState)} -
                       {'last_command_id', 'last_command_hash', 'last_event_id', 'decisions', 'orders', 'fills'}) | delta_names
            if not set(event.changes) <= allowed:
                raise ValueError('unexpected Paper event field')
            scalar = {key: _decode(value) for key, value in event.changes.items() if key not in delta_names}
            state = replace(state, **scalar)
            if 'decisions_append' in event.changes:
                state = replace(state, decisions=state.decisions + _decode(event.changes['decisions_append']))
            if 'fills_append' in event.changes:
                state = replace(state, fills=state.fills + _decode(event.changes['fills_append']))
            if 'orders_update' in event.changes:
                updates = {order.order_id: order for order in _decode(event.changes['orders_update'])}
                state = replace(state, orders=tuple(updates.get(order.order_id, order) for order in state.orders))
            if 'orders_append' in event.changes:
                state = replace(state, orders=state.orders + _decode(event.changes['orders_append']))
        state = replace(state, last_command_id=event.command_id,
                        last_command_hash=event.command_hash, last_event_id=event.event_id)
    if state is None:
        raise ValueError('Paper event stream is empty')
    return state


def replay(events: tuple[PaperEvent, ...] | list[PaperEvent]) -> PaperState:
    """Reconstruct account state from its ordered immutable Paper events."""
    return apply_events(None, events)


__all__ = ['PaperProfile', 'FeeSchedule', 'Initialize', 'BeginTradingDay', 'ObserveDecision',
           'ObserveExecutionBar', 'ResolveOrder', 'PaperOrder', 'PaperFill', 'PaperState', 'PaperEvent',
           'apply_command', 'apply_events', 'replay', 'command_to_dict', 'command_from_dict',
           'event_to_dict', 'event_from_dict']

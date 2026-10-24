"""Frozen JM D1 fixed-one-lot offline model. No I/O, broker, Paper or Runtime."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from hashlib import sha256
import json
from typing import Sequence

from .indicators.subing_ths import SubingThs15mKernel
from .new_subing import ExecutionFacts, StrategyBar
from .paper import FeeSchedule

D = Decimal
VERSIONS = {'strategy_code': 'subing_jm_d1_fixed1_v1', 'formula_version': 'subing_ths_1d_v1',
    'profile_id': 'subing_jm_d1_100k_fixed1_v1', 'decision_policy_version': 'subing_jm_d1_decision_v1',
    'risk_profile_version': 'subing_jm_d1_risk_v1', 'execution_profile_version': 'subing_jm_d1_next_1m_v1',
    'account_model_version': 'subing_jm_d1_account_v1'}
RANK = {'1m': 0, '1d': 1, '15m': 2}
PRIORITY = {'DAILY_LOSS_HALT': 0, 'MARGIN_HALT': 1, 'ROLLOVER_INTERRUPTED': 2,
            'PROTECTIVE_STOP': 3, 'EMA_EXIT': 4}


def wire(value):
    if isinstance(value, (Decimal, date, datetime)):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    if isinstance(value, dict):
        return {str(k): wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    return value


def digest(value):
    return sha256(json.dumps(wire(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def entry_risk(side, price, stop, facts, equity, *, slippage_ticks=1):
    """One authority for admission and its numerical explanation; baseline unchanged."""
    with localcontext(Context(prec=28)):
        values = {'equity': equity, 'risk_budget': equity*D('.02'), 'price': price,
                  'stop': stop, 'estimated_risk': None, 'reason': None}
        if stop <= 0 or (price-stop)*side <= 0:
            return {**values, 'reason': 'STOP_NOT_PROTECTIVE'}
        fee = facts.fees.amount('open', price, facts.multiplier)
        exit_price = max(facts.tick_size, stop-side*slippage_ticks*facts.tick_size)
        close_fee = max(facts.fees.amount('close', exit_price, facts.multiplier),
                        facts.fees.amount('close_today', exit_price, facts.multiplier))
        slip_cost = slippage_ticks*facts.tick_size*facts.multiplier
        risk = abs(price-stop)*facts.multiplier + fee + close_fee + slip_cost
        ratio = facts.long_margin_ratio if side == 1 else facts.short_margin_ratio
        margin = max(price, facts.prev_settlement)*facts.multiplier*ratio
        reason = ('TRADE_RISK_EXCEEDED' if risk > values['risk_budget'] else
                  'INSUFFICIENT_MARGIN' if margin+fee > equity else None)
        return {**values, 'estimated_risk': risk, 'open_fee': fee, 'estimated_close_fee': close_fee,
                'exit_slippage_cost': slip_cost, 'required_margin': margin, 'reason': reason}


@dataclass(frozen=True)
class Event:
    kind: str
    bar: StrategyBar
    facts: ExecutionFacts | None = None
    ema: Decimal | None = None
    cross: int = 0

    def __post_init__(self):
        b = self.bar
        if type(b) is not StrategyBar:
            raise ValueError('JM_BAR_TYPE_INVALID')
        if (self.kind not in RANK or b.frequency != self.kind or b.product != 'jm'
                or not b.physical_contract.startswith('JM') or b.confirmed_at != b.bar_end
                or type(self.cross) is not int or self.cross not in (-1, 0, 1)):
            raise ValueError('JM_EVENT_IDENTITY_INVALID')
        if self.ema is not None and (type(self.ema) is not D or not self.ema.is_finite() or self.ema <= 0):
            raise ValueError('JM_EMA_INVALID')
        if self.kind == '1m':
            if (type(self.facts) is not ExecutionFacts or self.facts.physical_contract != b.physical_contract
                    or self.facts.trading_day != b.trading_day or b.session_open_at is None
                    or b.session_close_at is None or b.bar_end-timedelta(minutes=1) < b.session_open_at):
                raise ValueError('JM_EXECUTION_FACTS_MISSING')
        elif self.cross and (self.kind != '1d' or self.ema is None):
            raise ValueError('JM_CROSS_INVALID')
        if self.cross and (b.close-self.ema)*self.cross <= 0:
            raise ValueError('JM_CROSS_EMA_FILTER_INVALID')


def daily_frames(bars: Sequence[StrategyBar]) -> tuple[Event, ...]:
    """Use the original shared kernel, with a full physical prefix per contract."""
    kernel, state, contract, previous_end = SubingThs15mKernel(), None, None, None
    frames = []
    for b in bars:
        if b.frequency != '1d':
            raise ValueError('JM_DAILY_INPUT_INVALID')
        if b.physical_contract != contract:
            state, contract, previous_end = kernel.initial_state(), b.physical_contract, None
        if previous_end is not None and b.bar_end <= previous_end:
            raise ValueError('JM_DAILY_ORDER_INVALID')
        had_previous = state.previous_dif is not None and state.previous_dea is not None
        state, frame = kernel.step(state, float(b.close), bar_end=b.bar_end.isoformat())
        previous_end = b.bar_end
        evaluable = frame.valid and frame.ready and had_previous
        cross = 1 if 'buy' in frame.result_codes else -1 if 'sell' in frame.result_codes else 0
        frames.append(Event('1d', b, ema=D(str(frame.ema21)) if evaluable else None,
                            cross=cross if evaluable else 0))
    return tuple(frames)


@dataclass
class Position:
    side: int
    contract: str
    entry_price: Decimal
    entry_day: date
    entry_at: datetime
    stop: Decimal
    multiplier: Decimal
    open_fee: Decimal


@dataclass
class Pending:
    action: str
    side: int
    contract: str
    at: datetime
    reason: str
    stop: Decimal
    causes: list[str]


class DailyModel:
    slippage_ticks = 1

    def __init__(self):
        self.cash = D('100000')
        self.total_fees = D(0)
        self.position: Position | None = None
        self.pending: Pending | None = None
        self.owner: str | None = None
        self.day: date | None = None
        self.day_start_equity = self.cash
        self.daily_halt = False
        self.status = 'ACTIVE'
        self.last_mark: Decimal | None = None
        self.last_facts: ExecutionFacts | None = None
        self.last_clock = None
        self.last_flat_at: datetime | None = None
        self.peak = self.cash
        self.max_drawdown = D(0)
        self.decisions, self.fills, self.trades, self.curve = [], [], [], []
        self.seen = {}

    @property
    def equity(self):
        p = self.position
        with localcontext(Context(prec=28)):
            return self.cash + ((self.last_mark-p.entry_price)*p.side*p.multiplier if p else D(0))

    def _record(self, at, action, reason, **extra):
        self.decisions.append({'id': digest([str(at), action, reason, len(self.decisions)]),
            'at': at.isoformat(), 'action': action, 'reason': reason, **wire(extra)})

    @staticmethod
    def _stop(ema, side, tick):
        raw = ema-D(12)*side
        return (raw/tick).to_integral_value(rounding=ROUND_CEILING if side == 1 else ROUND_FLOOR)*tick

    def _queue_close(self, at, reason):
        if not self.position:
            if self.pending:
                self._record(at, 'CANCEL', reason, contract=self.pending.contract)
                self.pending = None
            return
        p = self.position
        if self.pending and self.pending.action == 'CLOSE':
            if reason not in self.pending.causes:
                self.pending.causes.append(reason)
            if PRIORITY[reason] < PRIORITY[self.pending.reason]:
                self.pending.reason = reason
            return
        self.pending = Pending('CLOSE', p.side, p.contract, at, reason, p.stop, [reason])
        self._record(at, 'CLOSE_INTENT', reason, contract=p.contract, side=p.side)

    def _halt_check(self, at):
        if self.equity <= self.day_start_equity*D('.95'):
            if not self.daily_halt:
                self._record(at, 'HALT', 'DAILY_LOSS_HALT', equity=self.equity)
            self.daily_halt = True
            self._queue_close(at, 'DAILY_LOSS_HALT')

    def _risk_reason(self, side, price, stop, facts):
        return entry_risk(side, price, stop, facts, self.equity,
                          slippage_ticks=self.slippage_ticks)['reason']

    def _fill(self, event):
        b, f, order = event.bar, event.facts, self.pending
        start = b.bar_end-timedelta(minutes=1)
        if not order or b.physical_contract != order.contract or start <= order.at:
            return
        buy = order.side == (1 if order.action == 'OPEN' else -1)
        raw = b.open + self.slippage_ticks*f.tick_size*(1 if buy else -1)
        price = (raw/f.tick_size).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*f.tick_size
        blocked = ('ZERO_VOLUME' if b.volume <= 0 else
                   'LIMIT_BLOCKED' if (buy and (b.open >= f.limit_up or price > f.limit_up))
                   or (not buy and (b.open <= f.limit_down or price < f.limit_down)) else
                   'NONPOSITIVE_FILL' if price <= 0 else None)
        if blocked:
            if not self.decisions or (self.decisions[-1]['reason'], self.decisions[-1]['action']) != (blocked, 'UNFILLED'):
                self._record(b.bar_end, 'UNFILLED', blocked, contract=order.contract)
            return
        if order.action == 'OPEN':
            reason = ('DAILY_LOSS_HALT' if self.daily_halt else
                      self._risk_reason(order.side, price, order.stop, f))
            if reason:
                self._record(start, 'REJECT', reason, contract=order.contract)
                self.pending = None
                return
            fee = f.fees.amount('open', price, f.multiplier)
            self.position = Position(order.side, order.contract, price, b.trading_day,
                                     start, order.stop, f.multiplier, fee)
            self.cash -= fee
        else:
            p = self.position
            if p is None or p.contract != order.contract or p.multiplier != f.multiplier:
                raise ValueError('JM_CLOSE_IDENTITY_CONFLICT')
            fee = f.fees.amount('close_today' if b.trading_day == p.entry_day else 'close', price, f.multiplier)
            gross = (price-p.entry_price)*p.side*p.multiplier
            self.cash += gross-fee
            self.trades.append(wire({'contract': p.contract, 'side': p.side, 'qty': 1,
                'entry_at': p.entry_at, 'exit_at': start, 'entry_price': p.entry_price,
                'exit_price': price, 'gross_pnl': gross, 'fees': fee+p.open_fee,
                'net_pnl': gross-fee-p.open_fee, 'reason': order.reason, 'status': 'CLOSED'}))
            self.position = None
            self.last_flat_at = start
        self.total_fees += fee
        self.fills.append(wire({'id': digest([len(self.fills), start, order.contract]),
            'action': order.action, 'side': order.side, 'qty': 1, 'contract': order.contract,
            'decision_at': order.at, 'fill_at': start, 'recorded_at': b.bar_end,
            'trading_day': b.trading_day, 'price': price, 'fee': fee,
            'execution_bar_open': b.open, 'tick_size': f.tick_size,
            'limit_up': f.limit_up, 'limit_down': f.limit_down, 'volume': b.volume,
            'multiplier': f.multiplier, 'facts_id': f.source_id, 'reason': order.reason,
            'causes': order.causes}))
        self.pending = None
        self.last_mark, self.last_facts = b.open, f
        self._halt_check(b.bar_end)

    def apply(self, event: Event):
        with localcontext(Context(prec=28)):
            self._apply(event)

    def _apply(self, event):
        b = event.bar
        if not b.observation_eligible:
            raise ValueError('JM_PREVIEW_NOT_TRADABLE')
        if self.status == 'ROLLOVER_INTERRUPTED' and event.kind != '1m':
            return
        identity = digest([event.kind, b.source_identity])
        content = digest(asdict(event))
        if identity in self.seen:
            if self.seen[identity] != content:
                raise ValueError('JM_EVENT_IDENTITY_CONFLICT')
            return
        clock = (b.confirmed_at.astimezone(UTC).isoformat(), RANK[event.kind])
        if self.last_clock is not None and clock <= tuple(self.last_clock):
            raise ValueError('JM_EVENT_ORDER_INVALID')
        if event.kind != '1m' and (self.owner != b.physical_contract or self.day != b.trading_day):
            raise ValueError('JM_FRAME_WITHOUT_EXECUTION_CONTEXT')
        if event.kind == '1m' and (b.low < event.facts.limit_down or b.high > event.facts.limit_up):
            raise ValueError('JM_BAR_OUTSIDE_EXCHANGE_LIMITS')
        if (event.kind == '1m' and self.position and b.physical_contract == self.position.contract
                and self.position.multiplier != event.facts.multiplier):
            raise ValueError('JM_MULTIPLIER_CHANGED')
        self.seen[identity], self.last_clock = content, clock
        if event.kind == '1m':
            if self.owner is not None and b.physical_contract != self.owner and self.status == 'ACTIVE':
                self.status = 'ROLLOVER_INTERRUPTED'
                self._queue_close(b.bar_end, 'ROLLOVER_INTERRUPTED')
                self._record(b.bar_end, 'INTERRUPT', self.status, old_contract=self.owner,
                             new_contract=b.physical_contract)
                return
            if self.status == 'ROLLOVER_INTERRUPTED' and (not self.position or b.physical_contract != self.position.contract):
                return
            if b.trading_day != self.day:
                self.reconcile()
                self.day_start_equity = self.equity
                if not self.position and not self.pending:
                    self.daily_halt = False
                self.day = b.trading_day
            self.owner = b.physical_contract
            if self.position and self.position.multiplier != event.facts.multiplier:
                raise ValueError('JM_MULTIPLIER_CHANGED')
            self._fill(event)
            self.last_mark, self.last_facts = b.close, event.facts
            if self.position:
                ratio = event.facts.long_margin_ratio if self.position.side == 1 else event.facts.short_margin_ratio
                margin = max(b.close, event.facts.prev_settlement)*self.position.multiplier*ratio
                if margin > self.equity:
                    self.daily_halt = True
                    self._queue_close(b.bar_end, 'MARGIN_HALT')
            self.peak = max(self.peak, self.equity)
            if self.peak > 0:
                self.max_drawdown = max(self.max_drawdown, (self.peak-self.equity)/self.peak*100)
            return
        if self.status != 'ACTIVE':
            return
        self._halt_check(b.bar_end)
        if event.kind == '1d':
            if self.pending and self.pending.action == 'OPEN' and b.bar_end > self.pending.at:
                self._record(b.bar_end, 'CANCEL', 'DAILY_ENTRY_EXPIRED', contract=self.pending.contract)
                self.pending = None
            if event.ema is None:
                return
            if self.position:
                p = self.position
                stop = self._stop(event.ema, p.side, self.last_facts.tick_size)
                p.stop = max(p.stop, stop) if p.side == 1 else min(p.stop, stop)
                if (self.last_mark-p.stop)*p.side <= 0:
                    self._queue_close(b.bar_end, 'PROTECTIVE_STOP')
                if (b.close-event.ema)*p.side < 0:
                    self._queue_close(b.bar_end, 'EMA_EXIT')
            elif self.pending is None and event.cross:
                if self.daily_halt:
                    self._record(b.bar_end, 'REJECT', 'DAILY_LOSS_HALT')
                elif self.last_flat_at is None or b.bar_end > self.last_flat_at:
                    stop = self._stop(event.ema, event.cross, self.last_facts.tick_size)
                    price = b.close+event.cross*self.slippage_ticks*self.last_facts.tick_size
                    reason = self._risk_reason(event.cross, price, stop, self.last_facts)
                    if reason:
                        self._record(b.bar_end, 'REJECT', reason)
                    else:
                        self.pending = Pending('OPEN', event.cross, b.physical_contract, b.bar_end,
                                               'DAILY_CROSS', stop, ['DAILY_CROSS'])
                        self._record(b.bar_end, 'OPEN_INTENT', 'DAILY_CROSS', side=event.cross, stop=stop)
        elif self.position and (b.close-self.position.stop)*self.position.side <= 0:
            self._queue_close(b.bar_end, 'PROTECTIVE_STOP')
        self.curve.append(wire({'at': b.bar_end, 'equity': self.equity, 'cash': self.cash,
                                'qty': self.position.side if self.position else 0}))

    def reconcile(self):
        with localcontext(Context(prec=28)):
            self._reconcile()

    def _reconcile(self):
        if self.status not in ('ACTIVE', 'ROLLOVER_INTERRUPTED'):
            raise ValueError('JM_ACCOUNT_STATUS_INVALID')
        if self.pending and (self.pending.action not in ('OPEN', 'CLOSE')
                or self.pending.side not in (-1, 1) or not self.pending.stop.is_finite()
                or self.pending.stop <= 0 or (self.pending.action == 'CLOSE') != bool(self.position)):
            raise ValueError('JM_PENDING_STATE_INVALID')
        if self.position and (self.position.side not in (-1, 1) or not self.position.stop.is_finite()
                              or self.position.stop <= 0):
            raise ValueError('JM_POSITION_STATE_INVALID')
        cash, side, contract, entry, multiplier, fees = D('100000'), 0, None, D(0), D(0), D(0)
        for fill in self.fills:
            fee, price = D(fill['fee']), D(fill['price'])
            if (fill['qty'] != 1 or fill['side'] not in (-1, 1) or fill['action'] not in ('OPEN', 'CLOSE')
                    or not fee.is_finite() or fee < 0 or not price.is_finite() or price <= 0):
                raise ValueError('JM_FILL_STATE_INVALID')
            fees += fee
            cash -= fee
            if fill['action'] == 'OPEN':
                if side or fill['qty'] != 1:
                    raise ValueError('JM_REPLAY_OVERPOSITION')
                side, contract, entry, multiplier = fill['side'], fill['contract'], price, D(fill['multiplier'])
            else:
                if not side or side != fill['side'] or contract != fill['contract']:
                    raise ValueError('JM_REPLAY_CLOSE_CONFLICT')
                cash += (price-entry)*side*multiplier
                side, contract = 0, None
        p = self.position
        if (cash != self.cash or fees != self.total_fees or side != (p.side if p else 0)
                or contract != (p.contract if p else None)
                or p is not None and (p.entry_price != entry or p.multiplier != multiplier)):
            raise ValueError('JM_ACCOUNT_RECONCILIATION_FAILED')

    def checkpoint(self):
        self.reconcile()
        body = wire({k: asdict(v) if isinstance(v, (Position, Pending, ExecutionFacts)) else v
                     for k, v in self.__dict__.items()})
        return {'versions': dict(VERSIONS), 'state': body, 'hash': digest(body)}

    @classmethod
    def restore(cls, checkpoint):
        if checkpoint['versions'] != VERSIONS or digest(checkpoint['state']) != checkpoint['hash']:
            raise ValueError('JM_CHECKPOINT_INVALID')
        s = json.loads(json.dumps(checkpoint['state']))
        obj = cls()
        if set(s) != set(obj.__dict__):
            raise ValueError('JM_CHECKPOINT_SCHEMA_INVALID')
        for name in ('cash', 'total_fees', 'day_start_equity', 'peak', 'max_drawdown'):
            s[name] = D(s[name])
        s['last_mark'] = D(s['last_mark']) if s['last_mark'] is not None else None
        s['day'] = date.fromisoformat(s['day']) if s['day'] else None
        s['last_flat_at'] = datetime.fromisoformat(s['last_flat_at']) if s['last_flat_at'] else None
        if s['position']:
            p = s['position']
            for key in ('entry_price', 'stop', 'multiplier', 'open_fee'):
                p[key] = D(p[key])
            p['entry_day'], p['entry_at'] = date.fromisoformat(p['entry_day']), datetime.fromisoformat(p['entry_at'])
            s['position'] = Position(**p)
        if s['pending']:
            p = s['pending']
            p['stop'], p['at'] = D(p['stop']), datetime.fromisoformat(p['at'])
            s['pending'] = Pending(**p)
        if s['last_facts']:
            f = s['last_facts']
            f['fees'] = FeeSchedule(**{k: v if k == 'source_id' else D(v) for k, v in f['fees'].items()})
            f['trading_day'] = date.fromisoformat(f['trading_day'])
            for key in ('tick_size', 'multiplier', 'prev_settlement', 'long_margin_ratio', 'short_margin_ratio', 'limit_up', 'limit_down'):
                f[key] = D(f[key])
            s['last_facts'] = ExecutionFacts(**f)
        obj.__dict__.update(s)
        obj.reconcile()
        return obj

    def result(self):
        with localcontext(Context(prec=28)):
            return self._result()

    def _result(self):
        self.reconcile()
        interrupted = self.status == 'ROLLOVER_INTERRUPTED'
        status = self.status if interrupted else 'PENDING_UNFILLED' if self.pending else 'OPEN' if self.position else 'COMPLETED'
        return wire({'versions': dict(VERSIONS), 'summary': {'status': status,
            'cash': self.cash, 'equity': None if interrupted else self.equity,
            'last_known_equity': self.equity, 'total_fees': self.total_fees,
            'net_return_pct': None if interrupted else (self.equity/D('100000')-1)*100,
            'max_drawdown_pct': self.max_drawdown, 'ending_qty': self.position.side if self.position else 0,
            'closed_trades': len(self.trades), 'annual_eligible': False},
            'position': asdict(self.position) if self.position else None,
            'pending': asdict(self.pending) if self.pending else None,
            'decisions': self.decisions, 'fills': self.fills, 'trades': self.trades, 'equity_curve': self.curve,
            'auto_order': False, 'oos_status': 'OOS_NOT_PROVEN', 'continuous_paper': False})

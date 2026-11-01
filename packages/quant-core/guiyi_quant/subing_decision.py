"""Offline SuBing decision journal. Explicit acknowledgements are not broker fills.

The caller supplies completed, continuous MDS observations and verified Session,
financial and admission facts. This module performs no I/O or PnL calculation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import re

from .indicators.subing_conditions import EntryWindow, observe_entry

VERSION = 'subing_jm30_decision_v3'


def _time(value):
    if not isinstance(value, str):
        raise ValueError('TIME_INVALID')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('TIME_INVALID')
    return result


def _number(value, *, nullable=False, positive=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError('DECIMAL_STRING_REQUIRED')
    result = Decimal(value)
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError('DECIMAL_INVALID')
    return result


def _flag(value, *, nullable=False):
    if type(value) is bool or (nullable and value is None):
        return value
    raise ValueError('BOOLEAN_REQUIRED')


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError('EVENT_FIELDS_INVALID')


def _wire(value):
    if isinstance(value, (datetime, date, Decimal)):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    if isinstance(value, dict):
        return {k: _wire(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(v) for v in value]
    return value


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


class DecisionModel:
    def __init__(self, contract: str, run_id: str):
        if not isinstance(contract, str) or not re.fullmatch(r'JM[0-9]{4}', contract):
            raise ValueError('CONTRACT_INVALID')
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('RUN_INVALID')
        self.contract, self.run_id = contract, run_id
        self.layers = []
        self.pending = None
        self.clear_reasons = []
        self.exit_layers = []
        self.cooldown = 0
        self.cooldown_ended_at = None
        self.round_started_at = None
        self.pullback = None
        self.reset_after = None
        self.day = None
        self.day_halted = False
        self.halted_day = None
        self.day_reconciled = False
        self.last_at = None
        self.last_observation = None
        self.window = EntryWindow(contract)
        self.technical_ready = False
        self.sequence = 0
        self.events, self.results, self.fingerprints = [], {}, {}

    def state(self):
        return _wire(dict(contract=self.contract, run_id=self.run_id, version=VERSION,
            layers=self.layers, quantity=len(self.layers), pending=self.pending,
            clear_reasons=self.clear_reasons, exit_layers=self.exit_layers,
            cooldown=self.cooldown, cooldown_ended_at=self.cooldown_ended_at,
            round_started_at=self.round_started_at, pullback=self.pullback,
            reset_after=self.reset_after, trading_day=self.day,
            day_halted=self.day_halted, day_reconciled=self.day_reconciled,
            last_at=self.last_at, last_observation=self.last_observation, technical_ready=self.technical_ready,
            entry_window=dict(source_end=self.window.source_end, age=self.window.age)))

    def apply(self, event):
        if type(event) is not dict or not isinstance(event.get('event_id'), str) or not event['event_id']:
            raise ValueError('EVENT_ID_REQUIRED')
        fingerprint = _digest(event)
        identity = event['event_id']
        if identity in self.fingerprints:
            if self.fingerprints[identity] != fingerprint:
                raise ValueError('EVENT_ID_CONFLICT')
            return deepcopy(self.results[identity])
        # Journals are append-only after successful transition; copying them per
        # minute made historical replay quadratic. Only transactional state is copied.
        journal_keys = ('events', 'results', 'fingerprints')
        journals = {key: self.__dict__[key] for key in journal_keys}
        backup = deepcopy({key: value for key, value in self.__dict__.items() if key not in journal_keys})
        try:
            at = _time(event.get('at'))
            if event.get('contract') != self.contract:
                raise ValueError('CONTRACT_CHANGED')
            if self.last_at is not None and at < self.last_at:
                raise ValueError('EVENT_OUT_OF_ORDER')
            before = self.state()
            actions = self._observe(event, at) if event.get('kind') == 'observe' else self._ack(event, at)
            self.last_at = at
            result = dict(event_id=identity, before=before, facts=deepcopy(event), actions=_wire(actions), after=self.state())
            self.events.append(deepcopy(event))
            self.fingerprints[identity] = fingerprint
            self.results[identity] = deepcopy(result)
            return result
        except Exception:
            self.__dict__ = {**backup, **journals}
            raise

    def _intent(self, at, kind, targets, reasons):
        self.sequence += 1
        self.pending = dict(decision_id=f'{self.run_id}:{self.sequence}', kind=kind,
            at=at, layer_ids=list(targets), reasons=list(reasons), cancel_requested=False)
        return deepcopy(self.pending)

    def _observe(self, e, at):
        _fields(e, 'event_id kind at contract trading_day close daily_direction daily_at day_end_window admission round_loss day_loss remaining_net reconciled m30')
        if e['kind'] != 'observe' or (self.last_observation is not None and at <= self.last_observation):
            raise ValueError('OBSERVATION_TIME_INVALID')
        day = date.fromisoformat(e['trading_day'])
        if self.day is not None and day < self.day:
            raise ValueError('TRADING_DAY_REVERSED')
        close = _number(e['close'], positive=True)
        remaining_net = _number(e['remaining_net'], nullable=True)
        for key in ('day_end_window', 'reconciled'):
            _flag(e[key])
        for key in ('admission', 'round_loss', 'day_loss'):
            _flag(e[key], nullable=True)
        if e['daily_direction'] not in ('UP', 'NEUTRAL', 'DOWN', 'UNKNOWN'):
            raise ValueError('DAILY_DIRECTION_INVALID')
        if e['daily_at'] is not None and _time(e['daily_at']) >= at:
            raise ValueError('DAILY_NOT_STRICT_BEFORE')
        if e['daily_direction'] != 'UNKNOWN' and e['daily_at'] is None:
            raise ValueError('DAILY_SOURCE_MISSING')
        m = e['m30']
        if m is not None:
            _fields(m, 'near_zero_golden minute_angle above_ema volume_effective below_previous_low high_death below_ema qualified_pullback pullback_high pullback_invalidated')
            for key in ('near_zero_golden', 'above_ema', 'volume_effective', 'below_previous_low', 'high_death', 'below_ema', 'qualified_pullback'):
                _flag(m[key], nullable=True)
            _flag(m['pullback_invalidated'])
            angle = _number(m['minute_angle'], nullable=True)
            high = _number(m['pullback_high'], nullable=True, positive=True)
            if m['qualified_pullback'] is True and high is None:
                raise ValueError('PULLBACK_HIGH_MISSING')
        if self.day != day:
            self.day = day
            self.day_reconciled = e['reconciled']
            if self.day_reconciled and self.halted_day != day:
                self.day_halted = False
        elif not self.day_reconciled and e['reconciled']:
            self.day_reconciled = True
            if self.halted_day != day:
                self.day_halted = False
        self.last_observation = at
        if e['day_loss'] is True:
            self.day_halted = True
            self.halted_day = day
        reasons = []
        if e['day_loss'] is True or self.day_halted:
            reasons.append('DAY_LOSS')
        if e['round_loss'] is True:
            reasons.append('ROUND_LOSS')
        if m and m['below_ema'] is True:
            reasons.append('EMA_CLEAR')
        if self.layers and e['day_end_window'] and remaining_net is not None and remaining_net <= 0:
            reasons.append('DAY_END_NONPOSITIVE')
        if reasons and (self.layers or self.pending):
            self.clear_reasons = list(dict.fromkeys(self.clear_reasons + reasons))
            self.pullback = None
        entry = None
        was_cooling = self.cooldown > 0
        if m:
            self.technical_ready = angle is not None and all(m[key] is not None for key in ('near_zero_golden', 'above_ema', 'volume_effective', 'below_previous_low', 'high_death', 'below_ema', 'qualified_pullback'))
            self.window, entry = observe_entry(self.window, contract=self.contract, bar_end=at,
                near_zero_golden=m['near_zero_golden'], daily_direction=e['daily_direction'],
                minute_angle=angle, above_ema=m['above_ema'], volume_effective=m['volume_effective'])
            if was_cooling:
                if self.reset_after is not None and at > self.reset_after:
                    self.cooldown -= 1
                self.window = EntryWindow(self.contract, at)
                if not self.cooldown:
                    self.cooldown_ended_at = at
            if m['pullback_invalidated'] or not self.technical_ready:
                self.pullback = None
        protected = [layer['layer_id'] for layer in self.layers if layer['kind'] == 'ADD' and at > layer['at'] and close < layer['price']]
        if self.clear_reasons:
            self.exit_layers = [layer['layer_id'] for layer in self.layers]
        else:
            self.exit_layers = list(dict.fromkeys(self.exit_layers + protected))
            remaining = [layer for layer in self.layers if layer['layer_id'] not in self.exit_layers]
            reductions = (int(m['below_previous_low'] is True) + int(m['high_death'] is True)) if m else 0
            count = min(reductions, max(0, len(remaining) - 1))
            if count:
                self.exit_layers += [layer['layer_id'] for layer in reversed(remaining[-count:])]
        exit_now = bool(self.exit_layers or self.clear_reasons)
        reduction_trigger = bool(m and (m['below_previous_low'] is True or m['high_death'] is True))
        if protected or reduction_trigger:
            self.pullback = None
            self.reset_after = at
        # Breakout is a completed 1m close, never the phase-two 30m high flag.
        breakout = self.pullback is not None and at > self.pullback['at'] and close > self.pullback['high']
        if breakout:
            self.pullback = None
        actions = []
        if self.pending:
            if self.pending['kind'] == 'CLOSE' and self.clear_reasons and (
                    set(self.pending['layer_ids']) != set(self.exit_layers)
                    or self.pending['reasons'] != self.clear_reasons):
                # Offline intent replacement, not a broker cancel acknowledgement.
                # A fresh identity/time preserves the original request and makes
                # new targets executable only strictly after this observation.
                superseded = self.pending['decision_id']
                replacement = self._intent(at, 'CLOSE', self.exit_layers, self.clear_reasons)
                replacement['supersedes_decision_id'] = superseded
                actions.append(replacement)
            if self.pending['kind'] in ('OPEN', 'ADD') and (exit_now or (self.pending['kind'] == 'ADD' and reduction_trigger) or e['day_end_window'] or e['daily_direction'] not in ('UP', 'NEUTRAL') or not e['reconciled'] or not self.technical_ready or e['admission'] is not True or e['round_loss'] is not False or e['day_loss'] is not False):
                if not self.pending['cancel_requested']:
                    self.pending['cancel_requested'] = True
                    actions.append(dict(kind='CANCEL', decision_id=self.pending['decision_id'], reason='OPENING_NO_LONGER_ALLOWED'))
            return actions
        if self.exit_layers:
            actions.append(self._intent(at, 'CLOSE', self.exit_layers,
                self.clear_reasons or (['ADD_PROTECTION'] if protected else []) + (['ORDINARY_REDUCTION'] if m else []) or ['EXIT_OBLIGATION']))
            return actions
        if self.clear_reasons and not self.layers:
            self.clear_reasons = []
        blocked = []
        if not self.technical_ready:
            blocked.append('TECHNICAL_FACTS_UNKNOWN')
        if not self.day_reconciled or not e['reconciled']:
            blocked.append('RECONCILIATION_REQUIRED')
        if self.day_halted:
            blocked.append('DAY_HALTED')
        if e['day_end_window']:
            blocked.append('DAY_END_NO_OPEN')
        if e['daily_direction'] not in ('UP', 'NEUTRAL'):
            blocked.append('DAILY_NOT_ALLOWED')
        if e['admission'] is not True or e['round_loss'] is not False or e['day_loss'] is not False:
            blocked.append('ADMISSION_OR_RISK_NOT_PROVEN')
        if was_cooling or self.cooldown:
            blocked.append('COOLDOWN')
        if entry and entry['met'] is True and not self.layers:
            source = _time(entry['window']['source_end'].isoformat())
            if self.cooldown_ended_at is not None and source <= self.cooldown_ended_at:
                blocked.append('OLD_GOLDEN')
            if blocked:
                actions.append(dict(kind='REJECT', opportunity='OPEN', reasons=blocked))
            else:
                actions.append(self._intent(at, 'OPEN', [], ['ENTRY_MET']))
        elif breakout:
            if len(self.layers) >= 3:
                blocked.append('MAX_THREE_LAYERS')
            if not self.layers:
                blocked.append('NO_POSITION')
            if exit_now:
                blocked.append('EXIT_PRIORITY')
            if blocked:
                actions.append(dict(kind='REJECT', opportunity='ADD', reasons=blocked))
            else:
                actions.append(self._intent(at, 'ADD', [], ['PULLBACK_BREAKOUT']))
        if m and self.layers and not exit_now and not reduction_trigger and self.technical_ready and m['qualified_pullback'] is True:
            threshold = self.reset_after or self.round_started_at
            if threshold is not None and at > threshold:
                self.pullback = dict(at=at, high=high)
        return actions

    def _ack(self, e, at):
        _fields(e, 'event_id kind at contract decision_id status price layer_ids')
        if e['kind'] != 'ack' or e['status'] not in ('FILLED', 'CANCELLED'):
            raise ValueError('ACK_INVALID')
        if not self.pending or e['decision_id'] != self.pending['decision_id'] or at <= self.pending['at']:
            raise ValueError('ACK_IDENTITY_OR_TIME_INVALID')
        if type(e['layer_ids']) is not list or any(not isinstance(x, str) for x in e['layer_ids']) or len(set(e['layer_ids'])) != len(e['layer_ids']):
            raise ValueError('ACK_TARGETS_INVALID')
        price = _number(e['price'], nullable=e['status'] == 'CANCELLED', positive=True)
        if e['status'] == 'CANCELLED':
            if e['layer_ids'] or e['price'] is not None:
                raise ValueError('CANCEL_HAS_FILL')
            self.pending = None
            if not self.layers:
                self.clear_reasons = []
            return [dict(kind='ACK_CANCELLED', decision_id=e['decision_id'])]
        kind = self.pending['kind']
        if kind in ('OPEN', 'ADD'):
            if e['layer_ids'] or len(self.layers) >= 3 or (kind == 'OPEN' and self.layers) or (kind == 'ADD' and not self.layers):
                raise ValueError('ACK_POSITION_INVALID')
            self.layers.append(dict(layer_id=e['decision_id'], kind=kind, price=price, at=at))
            if kind == 'OPEN':
                self.round_started_at = at
                self.reset_after = at
                self.pullback = None
            self.pending = None
        else:
            if not e['layer_ids'] or not set(e['layer_ids']) <= set(self.pending['layer_ids']):
                raise ValueError('ACK_TARGETS_INVALID')
            self.layers = [layer for layer in self.layers if layer['layer_id'] not in e['layer_ids']]
            self.exit_layers = [x for x in self.exit_layers if x not in e['layer_ids']]
            self.pending['layer_ids'] = [x for x in self.pending['layer_ids'] if x not in e['layer_ids']]
            if not self.pending['layer_ids']:
                self.pending = None
            self.pullback = None
            self.reset_after = at
            if not self.layers:
                self.cooldown = 10
                self.clear_reasons = []
                self.exit_layers = []
                self.window = EntryWindow(self.contract, self.window.last_end)
                self.round_started_at = None
        return [dict(kind='ACK_FILLED', decision_id=e['decision_id'], layer_ids=e['layer_ids'], price=price)]

    def checkpoint(self):
        payload = dict(version=VERSION, contract=self.contract, run_id=self.run_id, events=deepcopy(self.events))
        return {**payload, 'sha256': _digest(payload)}

    @classmethod
    def restore(cls, checkpoint):
        _fields(checkpoint, 'version contract run_id events sha256')
        payload = {k: v for k, v in checkpoint.items() if k != 'sha256'}
        if checkpoint['version'] != VERSION or _digest(payload) != checkpoint['sha256'] or type(checkpoint['events']) is not list:
            raise ValueError('CHECKPOINT_INVALID')
        model = cls(checkpoint['contract'], checkpoint['run_id'])
        for event in checkpoint['events']:
            model.apply(event)
        return model

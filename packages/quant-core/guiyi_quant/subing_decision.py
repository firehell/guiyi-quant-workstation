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
from types import MappingProxyType

from .indicators.subing_conditions import EntryWindow, observe_entry

VERSION = 'subing_jm30_decision_v6'
RESEARCH_VERSION = VERSION + '_parameter_stability_v1'
# Fixed one-at-a-time scenarios. Values are (window age, stop points, target R).
RESEARCH_PROFILES = MappingProxyType({
    'window4': (4, Decimal('13'), Decimal('1')),
    'window6': (6, Decimal('13'), Decimal('1')),
    'stop11': (5, Decimal('11'), Decimal('1')),
    'stop15': (5, Decimal('15'), Decimal('1')),
    'target0_8': (5, Decimal('13'), Decimal('0.8')),
    'target1_2': (5, Decimal('13'), Decimal('1.2')),
})


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


SHORT_FIELDS = 'near_zero_death low_golden above_previous_high high qualified_rebound rebound_low rebound_invalidated'


def direction_sign(side):
    if side not in ('LONG', 'SHORT'):
        raise ValueError('SIDE_INVALID')
    return Decimal(1 if side == 'LONG' else -1)


def candidate_side(frame):
    return 'SHORT' if frame and frame['minute_angle'] is not None and Decimal(frame['minute_angle']) < 0 else 'LONG'


def directional_frame(frame, side):
    """Shared policy view: positive angle/above/breakout mean favorable to side.

    Wire facts remain explicitly named for their actual market direction. The
    long-named internal keys below express the mirrored policy, never wire prices.
    """
    if frame is None or side == 'LONG':
        return frame
    return dict(frame, near_zero_golden=frame['near_zero_death'],
        minute_angle=None if frame['minute_angle'] is None else str(-Decimal(frame['minute_angle'])),
        above_ema=frame['below_ema'], below_ema=frame['above_ema'],
        below_previous_low=frame['above_previous_high'], high_death=frame['low_golden'],
        qualified_pullback=frame['qualified_rebound'], pullback_high=frame['rebound_low'],
        pullback_invalidated=frame['rebound_invalidated'], low=frame['high'])


def daily_allows(direction, side):
    return direction in (('UP', 'NEUTRAL') if side == 'LONG' else ('DOWN', 'NEUTRAL'))


class DecisionModel:
    def __init__(self, contract: str, run_id: str, *, research_profile: str | None = None):
        if not isinstance(contract, str) or not re.fullmatch(r'JM[0-9]{4}', contract):
            raise ValueError('CONTRACT_INVALID')
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('RUN_INVALID')
        if research_profile is not None and (type(research_profile) is not str or research_profile not in RESEARCH_PROFILES):
            raise ValueError('DECISION_RESEARCH_PROFILE_INVALID')
        self.research_profile = research_profile
        self.window_age, self.stop_buffer, self.target_r = RESEARCH_PROFILES.get(research_profile, (5, Decimal('13'), Decimal('1')))
        self.version = RESEARCH_VERSION if research_profile is not None else VERSION
        self.profit_reason = 'PROFIT_1R' if self.target_r == 1 else 'PROFIT_' + str(self.target_r).replace('.', '_') + 'R'
        self.contract, self.run_id = contract, run_id
        self.layers = []
        self.pending = None
        self.clear_reasons = []
        self.exit_layers = []
        self.side = None
        self.last_flat_at = None
        self.latest_frame = None
        self.latest_frame_at = None
        self.round_started_at = None
        self.pullback = None
        self.initial_stop = None
        self.entry_volume_tier = None
        self.risk_distance = None
        self.profit_target = None
        self.completed_m30 = 0
        self.fast_deadline = None
        self.profit_taken = False
        self.profit_targets = []
        self.reset_after = None
        self.day = None
        self.day_halted = False
        self.halted_day = None
        self.day_reconciled = False
        self.last_at = None
        self.last_observation = None
        self.windows = {side: EntryWindow(contract) for side in ('LONG', 'SHORT')}
        self.technical_ready = False
        self.sequence = 0
        self.events, self.results, self.fingerprints = [], {}, {}

    def _research_fields(self):
        return {'research_profile': self.research_profile} if self.research_profile is not None else {}

    def state(self):
        return _wire(dict(contract=self.contract, run_id=self.run_id, version=self.version, **self._research_fields(),
            layers=self.layers, quantity=len(self.layers), pending=self.pending,
            clear_reasons=self.clear_reasons, exit_layers=self.exit_layers,
            side=self.side, last_flat_at=self.last_flat_at, latest_frame=self.latest_frame, latest_frame_at=self.latest_frame_at,
            round_started_at=self.round_started_at, pullback=self.pullback,
            initial_stop=self.initial_stop, entry_volume_tier=self.entry_volume_tier, risk_distance=self.risk_distance, profit_target=self.profit_target,
            completed_m30=self.completed_m30, fast_deadline=self.fast_deadline,
            profit_taken=self.profit_taken, profit_targets=self.profit_targets,
            reset_after=self.reset_after, trading_day=self.day,
            day_halted=self.day_halted, day_reconciled=self.day_reconciled,
            last_at=self.last_at, last_observation=self.last_observation, technical_ready=self.technical_ready,
            entry_windows={side: dict(source_end=w.source_end, age=w.age) for side, w in self.windows.items()}))

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

    def _intent(self, at, kind, targets, reasons, side=None):
        self.sequence += 1
        self.pending = dict(decision_id=f'{self.run_id}:{self.sequence}', kind=kind,
            at=at, side=side or self.side, layer_ids=list(targets), reasons=list(reasons), cancel_requested=False)
        return deepcopy(self.pending)

    def _observe(self, e, at):
        _fields(e, 'event_id kind at contract trading_day close daily_direction daily_at day_end_window admission round_loss day_loss remaining_net base_net layer_nets reconciled m30')
        if e['kind'] != 'observe' or (self.last_observation is not None and at <= self.last_observation):
            raise ValueError('OBSERVATION_TIME_INVALID')
        day = date.fromisoformat(e['trading_day'])
        if self.day is not None and day < self.day:
            raise ValueError('TRADING_DAY_REVERSED')
        close = _number(e['close'], positive=True)
        remaining_net = _number(e['remaining_net'], nullable=True)
        base_net = _number(e['base_net'], nullable=True)
        if type(e['layer_nets']) is not dict or any(not isinstance(k, str) for k in e['layer_nets']):
            raise ValueError('LAYER_NETS_INVALID')
        layer_nets = {k: _number(v, nullable=True) for k, v in e['layer_nets'].items()}
        if not set(layer_nets) <= {layer['layer_id'] for layer in self.layers}:
            raise ValueError('LAYER_NETS_IDENTITY')
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
        raw = e['m30']
        m = raw
        if m is not None:
            _fields(m, 'near_zero_golden minute_angle above_ema volume_effective volume_tier below_previous_low high_death below_ema qualified_pullback pullback_high pullback_invalidated ema21 low ' + SHORT_FIELDS)
            for key in ('near_zero_golden', 'above_ema', 'volume_effective', 'below_previous_low', 'high_death', 'below_ema', 'qualified_pullback'):
                _flag(m[key], nullable=True)
            for key in ('near_zero_death', 'low_golden', 'above_previous_high', 'qualified_rebound'):
                _flag(m[key], nullable=True)
            if m['volume_tier'] not in (None, 'NOT_EXPANDED', 'ZERO_BASELINE', 'TIER_1', 'TIER_2', 'TIER_3'):
                raise ValueError('VOLUME_TIER_INVALID')
            _flag(m['rebound_invalidated'])
            _number(m['high'], nullable=True, positive=True)
            rebound_low = _number(m['rebound_low'], nullable=True, positive=True)
            if m['qualified_rebound'] is True and rebound_low is None:
                raise ValueError('REBOUND_LOW_MISSING')
            _flag(m['pullback_invalidated'])
            _number(m['ema21'], nullable=True, positive=True)
            _number(m['low'], nullable=True, positive=True)
            _number(m['minute_angle'], nullable=True)
            high = _number(m['pullback_high'], nullable=True, positive=True)
            if m['qualified_pullback'] is True and high is None:
                raise ValueError('PULLBACK_HIGH_MISSING')
        if raw is not None:
            self.latest_frame, self.latest_frame_at = deepcopy(raw), at
        side = self.side or (self.pending['side'] if self.pending else candidate_side(self.latest_frame))
        sign = direction_sign(side)
        m = directional_frame(raw, side)
        if m:
            _number(m['minute_angle'], nullable=True)
            high = _number(m['pullback_high'], nullable=True, positive=True)
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
        if self.layers and self.initial_stop is not None and sign * (close - self.initial_stop) <= 0:
            reasons.append('FIXED_STOP')
        if m and m['below_ema'] is True:
            reasons.append('EMA_CLEAR')
        if self.layers and e['day_end_window'] and remaining_net is not None and remaining_net <= 0:
            reasons.append('DAY_END_NONPOSITIVE')
        if reasons and (self.layers or self.pending):
            self.clear_reasons = list(dict.fromkeys(self.clear_reasons + reasons))
            self.pullback = None
        entry = None
        readiness = directional_frame(self.latest_frame, side)
        self.technical_ready = readiness is not None and readiness['minute_angle'] is not None and all(readiness[key] is not None for key in ('near_zero_golden', 'above_ema', 'volume_effective', 'below_previous_low', 'high_death', 'below_ema', 'qualified_pullback'))
        if m:
            if self.round_started_at is not None and at > self.round_started_at:
                self.completed_m30 += 1
                if self.completed_m30 == 3:
                    self.fast_deadline = at
            for entry_side in ('LONG', 'SHORT'):
                view = directional_frame(raw, entry_side)
                daily = e['daily_direction'] if entry_side == 'LONG' else {'UP': 'DOWN', 'DOWN': 'UP'}.get(e['daily_direction'], e['daily_direction'])
                self.windows[entry_side], candidate = observe_entry(self.windows[entry_side], contract=self.contract, bar_end=at,
                    near_zero_golden=view['near_zero_golden'], daily_direction=daily,
                    minute_angle=_number(view['minute_angle'], nullable=True), above_ema=view['above_ema'],
                    volume_effective=view['volume_effective'], max_age=self.window_age)
                if entry_side == side:
                    entry = candidate
            if m['pullback_invalidated'] or not self.technical_ready:
                self.pullback = None
        signal_frame = m
        profit_trigger = bool(self.layers and self.profit_target is not None and not self.profit_taken
            and at > self.round_started_at and sign * (close - self.profit_target) >= 0)
        if profit_trigger:
            self.profit_taken = True
            fast = self.completed_m30 < 3 or (self.fast_deadline is not None and at <= self.fast_deadline)
            eligible = [layer['layer_id'] for layer in reversed(self.layers) if layer['kind'] == 'ADD'
                and layer_nets.get(layer['layer_id']) is not None and layer_nets[layer['layer_id']] > 0]
            if self.entry_volume_tier == 'TIER_1':
                self.clear_reasons = list(dict.fromkeys(self.clear_reasons + [self.profit_reason + '_TIER1_CLEAR']))
                self.profit_targets = []
            else:
                self.profit_targets = eligible if fast else eligible[:1]
        protected = [layer['layer_id'] for layer in self.layers if layer['kind'] == 'ADD' and at > layer['at'] and sign * (close - layer['price']) < 0]
        if self.clear_reasons:
            self.exit_layers = [layer['layer_id'] for layer in self.layers]
        else:
            self.exit_layers = list(dict.fromkeys(self.exit_layers + protected))
            remaining = [layer for layer in self.layers if layer['layer_id'] not in self.exit_layers]
            reductions = (int(m['below_previous_low'] is True) + int(m['high_death'] is True)) if m else 0
            count = min(reductions, max(0, len(remaining) - 1))
            if count:
                self.exit_layers += [layer['layer_id'] for layer in reversed(remaining[-count:])]
            self.exit_layers = list(dict.fromkeys(self.exit_layers + self.profit_targets))
        exit_now = bool(self.exit_layers or self.clear_reasons)
        reduction_trigger = bool(m and (m['below_previous_low'] is True or m['high_death'] is True))
        if protected or reduction_trigger or profit_trigger:
            self.pullback = None
            self.reset_after = at
        # Breakout is a completed 1m close, never the phase-two 30m high flag.
        breakout_high = self.pullback['level'] if self.pullback is not None else None
        breakout = self.pullback is not None and at > self.pullback['at'] and sign * (close - self.pullback['level']) > 0
        if breakout:
            self.pullback = None
        actions = []
        if self.pending:
            if self.pending['kind'] == 'CLOSE' and (
                    not set(self.exit_layers) <= set(self.pending['layer_ids'])
                    or (self.clear_reasons and self.pending['reasons'] != self.clear_reasons)):
                # Offline intent replacement, not a broker cancel acknowledgement.
                # A fresh identity/time preserves the original request and makes
                # new targets executable only strictly after this observation.
                superseded = self.pending['decision_id']
                replacement = self._intent(at, 'CLOSE', self.exit_layers, self.clear_reasons or
                    list(dict.fromkeys(self.pending['reasons'] + ([self.profit_reason] if self.profit_targets else []) + (['ADD_PROTECTION'] if protected else []))))
                replacement['supersedes_decision_id'] = superseded
                actions.append(replacement)
            if self.pending['kind'] in ('OPEN', 'ADD') and (exit_now or (self.pending['kind'] == 'ADD' and (reduction_trigger or profit_trigger or base_net is None or base_net <= 0 or sign * (close - self.pending['breakout_level']) <= 0)) or e['day_end_window'] or not daily_allows(e['daily_direction'], side) or not e['reconciled'] or not self.technical_ready or e['admission'] is not True or e['round_loss'] is not False or e['day_loss'] is not False):
                if not self.pending['cancel_requested']:
                    self.pending['cancel_requested'] = True
                    actions.append(dict(kind='CANCEL', decision_id=self.pending['decision_id'], reason='OPENING_NO_LONGER_ALLOWED'))
            return actions
        if self.exit_layers:
            actions.append(self._intent(at, 'CLOSE', self.exit_layers,
                self.clear_reasons or (['ADD_PROTECTION'] if protected else []) + ([self.profit_reason] if self.profit_targets else []) + (['ORDINARY_REDUCTION'] if reduction_trigger else []) or ['EXIT_OBLIGATION']))
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
        if not daily_allows(e['daily_direction'], side):
            blocked.append('DAILY_NOT_ALLOWED')
        if e['admission'] is not True or e['round_loss'] is not False or e['day_loss'] is not False:
            blocked.append('ADMISSION_OR_RISK_NOT_PROVEN')
        if entry and entry['met'] is True and not self.layers:
            if self.last_flat_at is not None and at <= self.last_flat_at:
                blocked.append('SAME_OBSERVATION_AS_CLEAR')
            if signal_frame['volume_tier'] not in ('TIER_1', 'TIER_2', 'TIER_3'):
                blocked.append('ENTRY_VOLUME_TIER_NOT_PROVEN')
            ema = _number(signal_frame['ema21'], nullable=True, positive=True)
            extreme = _number(signal_frame['low'], nullable=True, positive=True)
            stop = ((min(ema, extreme) - self.stop_buffer) if side == 'LONG' else (max(ema, extreme) + self.stop_buffer)) if ema is not None and extreme is not None else None
            if stop is None or stop <= 0 or sign * (close - stop) <= 0:
                blocked.append('INITIAL_STOP_NOT_PROVEN')
            if blocked:
                actions.append(dict(kind='REJECT', opportunity='OPEN', side=side, reasons=blocked))
            else:
                action = self._intent(at, 'OPEN', [], ['ENTRY_MET'], side=side)
                self.pending['signal_at'] = self.latest_frame_at
                action['signal_at'] = self.latest_frame_at
                self.pending['entry_volume_tier'] = signal_frame['volume_tier']
                action['entry_volume_tier'] = signal_frame['volume_tier']
                self.pending['initial_stop'] = stop
                action['initial_stop'] = stop
                actions.append(action)
        elif breakout:
            if base_net is None or base_net <= 0:
                blocked.append('BASE_NET_NOT_POSITIVE')
            if profit_trigger:
                blocked.append('PROFIT_EXIT_PRIORITY')
            if len(self.layers) >= 3:
                blocked.append('MAX_THREE_LAYERS')
            if not self.layers:
                blocked.append('NO_POSITION')
            if exit_now:
                blocked.append('EXIT_PRIORITY')
            if blocked:
                actions.append(dict(kind='REJECT', opportunity='ADD', reasons=blocked))
            else:
                action = self._intent(at, 'ADD', [], ['PULLBACK_BREAKOUT'])
                self.pending['breakout_level'] = breakout_high
                action['breakout_level'] = breakout_high
                actions.append(action)
        if m and self.layers and not exit_now and not reduction_trigger and not profit_trigger and self.technical_ready and m['qualified_pullback'] is True:
            threshold = self.reset_after or self.round_started_at
            if threshold is not None and at > threshold:
                self.pullback = dict(at=at, level=high)
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
            sign = direction_sign(self.pending['side'])
            if kind == 'OPEN' and sign * (price - self.pending['initial_stop']) <= 0:
                raise ValueError('INITIAL_STOP_INVALID_AT_FILL')
            self.layers.append(dict(layer_id=e['decision_id'], kind=kind, side=self.pending['side'], price=price, at=at))
            if kind == 'OPEN':
                self.side = self.pending['side']
                self.initial_stop = self.pending['initial_stop']
                self.entry_volume_tier = self.pending['entry_volume_tier']
                self.risk_distance = sign * (price - self.initial_stop)
                self.profit_target = price + sign * self.risk_distance * self.target_r
                self.completed_m30 = 0
                self.fast_deadline = None
                self.profit_taken = False
                self.profit_targets = []
                self.round_started_at = at
                self.reset_after = at
                self.pullback = None
            self.pending = None
        else:
            if not e['layer_ids'] or not set(e['layer_ids']) <= set(self.pending['layer_ids']):
                raise ValueError('ACK_TARGETS_INVALID')
            self.layers = [layer for layer in self.layers if layer['layer_id'] not in e['layer_ids']]
            self.exit_layers = [x for x in self.exit_layers if x not in e['layer_ids']]
            self.profit_targets = [x for x in self.profit_targets if x not in e['layer_ids']]
            self.pending['layer_ids'] = [x for x in self.pending['layer_ids'] if x not in e['layer_ids']]
            if not self.pending['layer_ids']:
                self.pending = None
            self.pullback = None
            self.reset_after = at
            if not self.layers:
                self.side = None
                self.last_flat_at = at
                self.clear_reasons = []
                self.exit_layers = []
                self.windows = {side: EntryWindow(self.contract, w.last_end) for side, w in self.windows.items()}
                self.round_started_at = None
                self.initial_stop = self.risk_distance = self.profit_target = None
                self.entry_volume_tier = None
                self.completed_m30 = 0
                self.fast_deadline = None
                self.profit_taken = False
                self.profit_targets = []
        return [dict(kind='ACK_FILLED', decision_id=e['decision_id'], layer_ids=e['layer_ids'], price=price)]

    def checkpoint(self):
        payload = dict(version=self.version, contract=self.contract, run_id=self.run_id, events=deepcopy(self.events), **self._research_fields())
        return {**payload, 'sha256': _digest(payload)}

    @classmethod
    def restore(cls, checkpoint):
        extra = ' research_profile' if type(checkpoint) is dict and 'research_profile' in checkpoint else ''
        _fields(checkpoint, 'version contract run_id events sha256' + extra)
        payload = {k: v for k, v in checkpoint.items() if k != 'sha256'}
        expected_version = RESEARCH_VERSION if extra else VERSION
        if (extra and checkpoint['research_profile'] is None) or checkpoint['version'] != expected_version or _digest(payload) != checkpoint['sha256'] or type(checkpoint['events']) is not list:
            raise ValueError('CHECKPOINT_INVALID')
        model = cls(checkpoint['contract'], checkpoint['run_id'], research_profile=checkpoint.get('research_profile'))
        for event in checkpoint['events']:
            model.apply(event)
        return model

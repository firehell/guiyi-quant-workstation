"""Offline factual adapter for demand projection; no orders, fills, or net PnL.

Each event is delivered when information is available. next_open is a trusted
Session fact supplied at day end. Opening-price events based on completed 1m
bars are available only at that bar's end, not at the historical opening tick.
"""
from copy import deepcopy,copy
from datetime import datetime
from decimal import Decimal as D
import hashlib,json
from .subing_demand_policy import Facts,project
VERSION='subing_demand_observer_candidate_v1'

def stamp(s):
    t=datetime.fromisoformat(s)
    if t.tzinfo is None:raise ValueError('NAIVE_TIME')
    return t

def decimal(s,positive=False):
    if not isinstance(s,str):raise ValueError('DECIMAL_STRING_REQUIRED')
    v=D(s)
    if not v.is_finite() or (positive and v<=0):raise ValueError('INVALID_DECIMAL')
    return v

def gross(layers,mark,multiplier):
    m=decimal(mark,True);mult=decimal(multiplier,True);total=D(0);ids=set();sides=set()
    for l in layers:
        if l['id'] in ids or l['side'] not in ('LONG','SHORT') or type(l['quantity']) is not int or l['quantity']<=0:raise ValueError('LAYER_INVALID')
        ids.add(l['id']);sides.add(l['side'])
        total+=(1 if l['side']=='LONG' else -1)*(m-decimal(l['price'],True))*mult*l['quantity']
    if len(sides)>1:raise ValueError('MIXED_POSITION')
    return total

class Observer:
    def __init__(self,contract):
        self.contract=contract;self.position_id=None;self.streak=0;self.day=None
        self.waiting=None;self.exit_required=False;self.last_at=None;self.last_eod_day=None;self.seen={}

    def __deepcopy__(self,memo):
        # Cache entries are append-only and never mutated in place. Copy its
        # mapping, not every historical value, during model transaction backup.
        clone=copy(self);clone.waiting=deepcopy(self.waiting,memo);clone.seen=self.seen.copy()
        memo[id(self)]=clone;return clone

    def apply(self,event):
        # Atomic: validation or processing errors leave the old object unchanged.
        clone=copy(self);clone.waiting=deepcopy(self.waiting);clone.seen=self.seen.copy()
        result=clone._apply(deepcopy(event));self.__dict__=clone.__dict__;return result

    def _apply(self,e):
        wire=json.dumps(e,sort_keys=True,allow_nan=False,separators=(',',':'))
        digest=hashlib.sha256(wire.encode()).hexdigest();key=e['event_id']
        if not isinstance(key,str) or not key:raise ValueError('EVENT_ID_INVALID')
        if key in self.seen:
            old,result=self.seen[key]
            if digest!=old:raise ValueError('EVENT_ID_CONFLICT')
            return dict(deepcopy(result),duplicate=True)
        if e['contract']!=self.contract:raise ValueError('CONTRACT_CHANGED')
        at=stamp(e['observed_at']);price_at=stamp(e['price_at'])
        if price_at>at or (self.last_at and at<stamp(self.last_at)):raise ValueError('EVENT_TIME_INVALID')
        if e['kind'] not in ('BAR','DAY_END','NEXT_OPEN'):raise ValueError('EVENT_KIND_INVALID')
        if e.get('data_ready',True) is not True:raise ValueError('FACTS_UNAVAILABLE')
        if e['kind']!='NEXT_OPEN' and self.waiting and price_at>=stamp(self.waiting['open']):raise ValueError('OPEN_CHECK_MISSING')
        if e['regime'] not in ('RANGE','TREND_UP','TREND_DOWN','UNKNOWN'):raise ValueError('REGIME_INVALID')
        # Calendar order is supplied by authoritative trading-day/session facts.
        if self.day and e['trading_day']<self.day:raise ValueError('DAY_ORDER_INVALID')
        if self.day and e['trading_day']!=self.day and e['previous_trading_day']!=self.day:raise ValueError('DAY_GAP')
        if self.day and e['trading_day']!=self.day and self.last_eod_day!=self.day:raise ValueError('DAY_END_MISSING')
        amount=gross(e['layers'],e['mark'],e['multiplier'])
        if bool(e['layers'])!=bool(e['position_id']):raise ValueError('POSITION_ID_INVALID')
        if e['position_id']!=self.position_id:
            self.position_id=e['position_id'];self.streak=0;self.exit_required=False
        if e['regime']!='RANGE':self.streak=0
        phase='BAR_CLOSE';opening=False
        if e['kind']=='DAY_END':
            if price_at!=stamp(e['session_day_end']) or at<price_at:raise ValueError('NOT_DAY_END')
            if self.waiting and self.waiting['day']==e['trading_day']:raise ValueError('DUPLICATE_DAY_END')
            nxt=stamp(e['next_open'])
            if nxt<=at:raise ValueError('NEXT_OPEN_NOT_FUTURE')
            if self.day and e['previous_trading_day']!=self.day and e['trading_day']!=self.day: self.streak=0
            if e['layers'] and e['regime']=='RANGE' and amount<=0:self.streak+=1
            else:self.streak=0
            self.last_eod_day=e['trading_day']
            self.waiting={'day':e['trading_day'],'open':e['next_open'],'position_id':self.position_id}
            phase='DAY_END'
        elif e['kind']=='NEXT_OPEN':
            if not self.waiting or price_at!=stamp(self.waiting['open']):raise ValueError('UNEXPECTED_OPEN')
            if e['previous_trading_day']!=self.waiting['day']:raise ValueError('OPEN_DAY_LINK_INVALID')
            opening=e['position_id']==self.waiting['position_id'] and bool(e['layers'])
            self.waiting=None
            if opening:phase='NEXT_OPEN_AFTER_DAY_END'
        # Missing opening observation cannot be silently skipped.
        elif self.waiting and price_at>=stamp(self.waiting['open']):raise ValueError('OPEN_CHECK_MISSING')
        side=e['layers'][0]['side'] if e['layers'] else 'FLAT'
        d=project(Facts(side,e['regime'],phase=phase,pending_break=e.get('pending_break'),gross_remaining=amount,
                        nonpositive_range_days=self.streak,all_exit_required=self.exit_required or e.get('all_exit_required',False),
                        reduce_required=e.get('reduce_required',False),data_ready=e.get('data_ready',True),execution_ready=False))
        if d.kind in ('EXIT_REQUIRED','EXIT_OBLIGATION') and e['layers']:self.exit_required=True
        self.last_at=e['observed_at'];self.day=e['trading_day']
        result={'event_id':key,'observed_at':e['observed_at'],'price_at':e['price_at'],'phase':phase,
                'gross_remaining':str(amount),'nonpositive_range_days':self.streak,'demand':d.kind,'reason':d.reason,
                'execution':d.execution,'duplicate':False}
        self.seen[key]=(digest,deepcopy(result));return result

    def checkpoint(self):
        return json.loads(json.dumps({'version':VERSION,'state':self.__dict__},allow_nan=False))

    @classmethod
    def restore(cls,checkpoint):
        if checkpoint['version']!=VERSION:raise ValueError('CHECKPOINT_VERSION_INVALID')
        obj=cls(checkpoint['state']['contract']);obj.__dict__=deepcopy(checkpoint['state']);return obj

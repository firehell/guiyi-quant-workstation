"""Replayable observation pipeline: immutable warmup, then completed observations."""
from datetime import datetime,date,time
from decimal import Decimal as D
from zoneinfo import ZoneInfo
from app.market_data.domain import CanonicalBar
from app.market_data.new_subing_research import load_execution_facts
from guiyi_quant.new_subing import StrategyBar
from guiyi_quant.subing_decision import _wire
from .factors import Factors
from .account import ContinuousAccount,encode_execution

SH=ZoneInfo('Asia/Shanghai')

def bar(body):
    return CanonicalBar(**{k:datetime.fromisoformat(v) if k=='bar_end' else date.fromisoformat(v) if k=='trading_day' else D(v) if v is not None else None for k,v in body.items() if k in CanonicalBar.__dataclass_fields__})

class Pipeline:
    def __init__(self,identity):
        self.identity=identity;self.started=datetime.fromisoformat(identity['started_at']);self.factors={};self.products={};self.last={};self.chart={};self.account=None
        self.sequence=0;self.source_cursor=identity['cursor'];self.source_day=identity['source_day']
        for product,prepared in identity['prepared'].items():
            contract=prepared['contract'];f=Factors(contract);self.factors[product]=f;self.chart[product]=[]
            for freq in ('1d','30m','60m'):
                for raw in prepared['warmup'].get(freq,[]):f.step(freq,bar(raw))
            self.products[product]=dict(product=product,contract=contract,status=prepared['status'],execution_enabled=False,execution_facts='NOT_VERIFIED',
                parameter_status='JM_FIXED' if product=='jm' else 'RESEARCH_CANDIDATE_NOT_APPROVED',normalization_candidate=prepared.get('normalization_candidate'),warmup_errors=prepared['errors'])
        for payload in identity['bootstrap']:self._row(payload,identity['contexts'],None,self.started,bootstrap=True)

    def _row(self,payload,contexts,facts,now,bootstrap=False):
        product,freq=payload['channel'].split(':')[2:];body=payload['data'];b=bar(body);row=self.products[product];f=self.factors[product]
        key=(product,freq);previous=self.last.get(key)
        if previous and b.bar_end<=previous:raise ValueError('OBSERVATION_OUT_OF_ORDER')
        ctx=contexts[product]
        if freq in ('1m','30m','60m'):
            ends=[datetime.fromisoformat(x) for x in ctx['expected_'+freq]]
            lower=previous or datetime.fromisoformat(ctx['first_open'])
            expected=next((x for x in ends if x>lower),None)
            if b.bar_end!=expected:raise ValueError('OBSERVATION_GAP')
        elif freq not in ('30m','60m'):return
        self.last[key]=b.bar_end
        if body['contract']!=row['contract'] or ctx['contract']!=row['contract']:
            row['status']='ROLLOVER_WAIT';row['new_contract']=ctx['contract'];row['execution_enabled']=False
            if product=='jm' and self.account:self.account.halted='ROLLOVER_WAIT'
            return
        if freq=='1m':
            for required in ('30m','60m'):
                if b.bar_end.isoformat() in ctx['expected_'+required] and self.last.get((product,required))!=b.bar_end:raise ValueError('DERIVED_OBSERVATION_GAP')
        if freq!='1m':
            if f.trends[freq].last_end is None or b.bar_end>f.trends[freq].last_end:f.step(freq,b)
            if freq=='30m':
                self.chart[product].append(_wire(dict(at=b.bar_end,open=b.open,high=b.high,low=b.low,close=b.close,ema21=f.frame['ema21'],**(f.structure_point or {}))))
                self.chart[product]=self.chart[product][-128:]
            return
        row.update(observed_at=now.isoformat(),warmup_only=bootstrap,source_confirmed_at=payload['confirmed_at'],bar_end=b.bar_end.isoformat(),regime=f.frame['regime'] if f.frame else 'UNKNOWN',daily=f.daily[-1] if f.daily else None,hourly=f.hourly,structure=_wire(f.structure_point),close=str(b.close))
        if bootstrap or b.bar_end<=self.started:return
        row['status']='OBSERVING' if not row['warmup_errors'] else 'WARMUP_INCOMPLETE'
        if product!='jm':return
        if row['warmup_errors']:return
        if self.account and self.account.halted:
            self.account.hold_for_facts(b,f.frame if f.previous and f.previous.bar_end==b.bar_end else None,now,self.account.halted)
            row['status']=self.account.halted;row['execution_enabled']=False;return
        if not f.daily or date.fromisoformat(f.daily[-1]['time'][:10])<date.fromisoformat(ctx['previous']):
            row['status']='DAILY_FACTS_MISSING'
            if self.account:self.account.hold_for_facts(b,f.frame if f.previous and f.previous.bar_end==b.bar_end else None,now,'DAILY_FACTS_INTERRUPTED_REVIEW_REQUIRED')
            row['execution_enabled']=False;return
        if facts and datetime.fromisoformat(facts['captured_at'])>now:raise ValueError('EXECUTION_FACTS_NOT_YET_KNOWN')
        if not facts:
            row['status']='EXECUTION_FACTS_MISSING'
            if self.account:self.account.hold_for_facts(b,f.frame if f.previous and f.previous.bar_end==b.bar_end else None,now,'EXECUTION_FACTS_INTERRUPTED_REVIEW_REQUIRED')
            row['execution_enabled']=False;return
        if not self.account:self.account=ContinuousAccount(row['contract'],self.identity['run_id'],self.started)
        session=next(w for w in ctx['sessions'] if datetime.fromisoformat(w[0])<b.bar_end<=datetime.fromisoformat(w[1]))
        confirmed=datetime.fromisoformat(payload['confirmed_at'])
        sb=StrategyBar(product='jm',physical_contract=row['contract'],frequency='1m',source_identity=payload['observation_id'],confirmed_at=confirmed,
            session_open_at=datetime.fromisoformat(session[0]),session_close_at=datetime.fromisoformat(ctx['day_end']),**{k:v for k,v in vars_bar(b).items() if k!='turnover'})
        executions,_=load_execution_facts(facts,product='jm',bars=[sb]);x=executions[0]
        local=b.bar_end.astimezone(SH)
        technical=f.observation(b,local.date()==b.trading_day and local.time()>=time(14,50))
        structure=dict(f.structure_point or {},hourly=f.hourly,base_regime=f.frame['regime'] if f.frame else 'UNKNOWN')
        self.account.apply(dict(event_id=technical['event_id'],contract=row['contract'],execution=encode_execution(x),technical=technical,
            schedule={k:ctx[k] for k in ('previous','first_open','day_end','next_open')},expected_end=b.bar_end.isoformat(),observed_at=now.isoformat(),structure=_wire(structure)))
        row['execution_enabled']=True;row['execution_facts']='VERIFIED_CURRENT_DAY'

    def apply(self,event):
        from .store import digest
        before_fills=len(self.account.engine.fills) if self.account and self.account.engine else 0
        before_decisions=len(self.account.engine.model.chain) if self.account and self.account.engine else 0
        now=datetime.fromisoformat(event['observed_at'])
        for product,updates in event.get('daily_updates',{}).items():
            for raw in updates:self.factors[product].step('1d',bar(raw))
        for payload in event['observations']:
            self._row(payload,event['contexts'],event.get('facts'),now)
        self.source_cursor=event['cursor'];self.source_day=event['source_day'];self.sequence+=1
        fills=self.account.engine.fills[before_fills:] if self.account and self.account.engine else []
        decisions=self.account.engine.model.chain[before_decisions:] if self.account and self.account.engine else []
        self.last_outcome=_wire(dict(run_identity_hash=digest(self.identity),state_hash=digest(self.state()),model_fills=fills,model_decisions=decisions))
        if event.get('outcome') is not None and event['outcome']!=self.last_outcome:raise ValueError('MODEL_OUTCOME_REPLAY_CONFLICT')

    def state(self):
        return _wire(dict(run_id=self.identity['run_id'],started_at=self.identity['started_at'],status='OBSERVING',
            products=list(self.products.values()),account=self.account.state() if self.account else dict(status='WAIT_EXECUTION_FACTS_OR_FIRST_OBSERVATION',cash='100000',open_quantity=0),
            chart=self.chart['jm'],source_cursor=self.source_cursor,source_day=self.source_day,sequence=self.sequence,auto_order=False))

def vars_bar(b):
    from dataclasses import asdict
    return asdict(b)

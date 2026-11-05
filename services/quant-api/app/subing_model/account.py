"""Development account over the shared incremental execution engine."""
from dataclasses import asdict
from datetime import datetime,date
from decimal import Decimal as D
from copy import deepcopy
from guiyi_quant.subing_account import AccountEngine
from guiyi_quant.subing_demand_account_candidate import build_engine
from guiyi_quant.subing_decision import REGIME_PROFILE,_wire,_digest,directional_frame,technical_full_exit_reasons,technical_exit_targets
from guiyi_quant.new_subing import StrategyBar,ExecutionFacts,ExecutionBar
from guiyi_quant.paper import FeeSchedule

VERSION='subing_development_completed_close_v1'

def decode_execution(body):
    b=deepcopy(body['bar']);f=deepcopy(body['facts'])
    for k in ('bar_end','confirmed_at','session_open_at','session_close_at'):
        if b.get(k):b[k]=datetime.fromisoformat(b[k])
    b['trading_day']=date.fromisoformat(b['trading_day'])
    for k in ('open','high','low','close','volume','open_interest'):
        if b.get(k) is not None:b[k]=D(b[k])
    f['trading_day']=date.fromisoformat(f['trading_day']);fees=f.pop('fees')
    f['fees']=FeeSchedule(**{k:v if k=='source_id' else D(v) for k,v in fees.items()})
    for k in ('tick_size','multiplier','prev_settlement','long_margin_ratio','short_margin_ratio','limit_up','limit_down'):f[k]=D(f[k])
    return ExecutionBar(StrategyBar(**b),ExecutionFacts(**f))

class ContinuousAccount:
    def __init__(self,contract,run_id,started_at):
        self.contract=contract;self.run_id=run_id;self.started_at=started_at
        self.bars={};self.schedule={};self.structures={};self.seen={};self.engine=None;self.halted=None;self.protection_observation=None

    def apply(self,body):
        """Exact persisted observation input, including first processing/knowledge time."""
        identity=body['event_id'];digest=_digest(body)
        if identity in self.seen:
            if self.seen[identity]!=digest:raise ValueError('OBSERVATION_ID_CONFLICT')
            return False
        if self.halted:raise ValueError(self.halted)
        x=decode_execution(body['execution']);b=x.bar;at=datetime.fromisoformat(body['observed_at'])
        if at<self.started_at or b.bar_end<=self.started_at:raise ValueError('PRE_START_OBSERVATION')
        if body['contract']!=self.contract or b.physical_contract!=self.contract:
            self.halted='ROLLOVER_WAIT';raise ValueError('ROLLOVER_WAIT')
        if b.bar_end.isoformat()!=body['expected_end']:raise ValueError('OBSERVATION_GAP')
        day=b.trading_day.isoformat();cal=body['schedule']
        if day in self.schedule and self.schedule[day]!=cal:raise ValueError('SESSION_CHANGED')
        self.schedule[day]=cal;self.bars[b.bar_end]=x;self.structures[b.bar_end.isoformat()]=body['structure']
        if self.engine is None:
            _,Candidate,_=build_engine(self.bars,self.schedule,structures=self.structures)
            self.engine=AccountEngine(self.contract,'jm',x.facts.multiplier,self.run_id,
                regime_research_profile=REGIME_PROFILE,decision_factory=Candidate,live=True)
            if self.engine.model.regime!='UNKNOWN' and self.engine.model.regime_since is None:self.engine.model.regime_since=self.started_at
        try:self.engine.step(x,body['technical'],observed_at=at)
        except Exception:
            self.halted='INPUT_OR_ACCOUNT_FAILURE';raise
        self.seen[identity]=digest
        return True

    def hold_for_facts(self,b,frame,observed_at,reason):
        self.halted=reason
        if self.engine is None:return
        m=self.engine.model
        view=directional_frame(frame,m.side or 'LONG')
        required=technical_full_exit_reasons(m.layers,m.initial_stop,view,m.side or 'LONG',b.close)
        protected,targets=technical_exit_targets(m.layers,m.exit_layers,view,m.side or 'LONG',b.close,b.bar_end,m.add_protection)
        m.exit_layers=targets
        if required and m.layers:
            m.clear_reasons=list(dict.fromkeys(m.clear_reasons+required))
            m.exit_layers=[l['layer_id'] for l in m.layers]
            m.pullback=None
        if m.pending and m.pending['kind'] in ('OPEN','ADD'):m.pending['cancel_requested']=True
        self.protection_observation=_wire(dict(demand='EXIT_OBLIGATION' if m.clear_reasons else 'REDUCE_OBLIGATION' if m.exit_layers else 'HOLD_NO_ADD',required_reduction_layers=m.exit_layers,bar_end=b.bar_end,observed_at=observed_at,close=b.close,required_full_exit=m.clear_reasons,
            execution='WAIT_AUTHORITATIVE_FACTS_AND_REVIEW',valuation_status='LAST_KNOWN_VALUATION'))

    def state(self):
        if self.engine is None:return dict(version=VERSION,contract=self.contract,run_id=self.run_id,started_at=self.started_at.isoformat(),status=self.halted or 'WAIT_FIRST_OBSERVATION',cash='100000',open_quantity=0)
        result=self.engine.snapshot(include_journal=False)
        result.pop('decision_checkpoint',None);result.pop('trace',None)
        return dict(result,version=VERSION,started_at=self.started_at.isoformat(),observed_at=self.engine.last_observed_at.isoformat(),status=self.halted or 'OBSERVING',
            protection_observation=self.protection_observation,pending_knowledge_at=self.engine.pending_known_at.isoformat() if self.engine.pending_known_at else None,latest_decision=self.engine.model.chain[-1],decision_history=self.engine.model.chain[-100:],auto_order=False,execution_profile='next_completed_1m_close_slip1_actual_knowledge_v1')


def encode_execution(x):return _wire(asdict(x))

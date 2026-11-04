"""Isolated historical candidate; existing execution engine, candidate-owned fills.

Factory creates an isolated account module. No service module globals are changed.
The fixed v2 environment isolates demand-policy changes from structure research.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path
from guiyi_quant.subing_decision import DecisionModel,REGIME_PROFILE,_digest,_wire,directional_frame
from .subing_demand_observer import Observer
from guiyi_quant.indicators.subing_conditions import observe_entry,EntryWindow

VERSION='subing_demand_account_candidate_v2'
class _Chain(list):
    def __deepcopy__(self,memo):
        return _Chain(self)

EXIT_ONLY_VERSION='subing_demand_account_candidate_v1_exit_only'

def build_engine(executions,schedule,*,gate_first_entry=True,structures=None):
    version=('subing_unified_demand_candidate_v1' if structures is not None else VERSION) if gate_first_entry else EXIT_ONLY_VERSION
    bars=executions if isinstance(executions,dict) else {x.bar.bar_end:x for x in executions}
    context_hash=_digest(_wire({'schedule':schedule,'executions':[asdict(x) for x in bars.values()], **({'structures': structures} if structures is not None else {})}))
    class Candidate(DecisionModel):
        def __init__(self,contract,run_id,**kwargs):
            super().__init__(contract,run_id,**kwargs)
            self.version=version;self.observer=Observer(contract)
            self.chain=_Chain()
            self.structure_was_pending=False
            if structures:
                first=structures[min(structures)]
                if first and first.get('base_regime') in ('RANGE','TREND_UP','TREND_DOWN','UNKNOWN'):
                    self.regime=first['base_regime']

        @property
        def demands(self):
            return [deepcopy(value[1]) for value in self.observer.seen.values()]

        def _observe(self,e,at):
            x=bars[at];b=x.bar;cal=schedule[e['trading_day']]
            position_id=self.round_started_at.isoformat() if self.layers and self.round_started_at else None
            layers=[dict(id=l['layer_id'],side=l['side'],price=str(l['price']),quantity=1) for l in self.layers]
            def event(kind,mark,price_at,regime):
                return dict(event_id=kind+':'+e['event_id'],contract=self.contract,kind=kind,trading_day=e['trading_day'],previous_trading_day=cal['previous'],
                            observed_at=at.isoformat(),price_at=price_at.isoformat(),layers=layers,position_id=position_id,regime=regime,
                            mark=str(mark),multiplier=str(x.facts.multiplier),session_day_end=cal['day_end'],next_open=cal['next_open'])
            opening_review=None
            start=at-timedelta(minutes=1)
            # Fills already acknowledged by the execution engine are now known.
            # Opening mark is observed at completed minute end; new intent can
            # only fill strictly later through the unchanged execution engine.
            if self.observer.waiting and start.isoformat()==__import__('datetime').datetime.fromisoformat(cal['first_open']).isoformat():
                result=self.observer.apply(event('NEXT_OPEN',b.open,start,self.regime))
                opening_review=deepcopy(result)
                if result['demand']=='EXIT_REQUIRED':
                    self.clear_reasons=list(dict.fromkeys(self.clear_reasons+[result['reason']]))
            regime=e['m30']['regime'] if e['m30'] else self.regime
            kind='DAY_END' if at==__import__('datetime').datetime.fromisoformat(cal['day_end']) else 'BAR'
            result=self.observer.apply(event(kind,b.close,at,regime))
            if result['demand']=='EXIT_REQUIRED':
                self.clear_reasons=list(dict.fromkeys(self.clear_reasons+[result['reason']]))
            structure=structures.get(at.isoformat()) if structures is not None else None
            blocked=bool(structure and structure.get('phase')=='BREAK_PENDING')
            recovered=self.structure_was_pending and not blocked
            self.structure_was_pending=blocked
            adjusted=deepcopy(e)
            # Disable only the retired EOD PnL exit. Admission and execution's
            # original end-window check retain the ban on new exposure.
            if e['day_end_window']:
                adjusted['day_end_window']=False;adjusted['admission']=False
            if gate_first_entry and (regime in ('RANGE','UNKNOWN') or blocked):adjusted['admission']=False
            if blocked and self.pending and self.pending['kind'] in ('OPEN','ADD'):
                self.pending['cancel_requested']=True
            if blocked:
                self.pullback=None
            before_windows=deepcopy(self.windows)
            actions=super()._observe(adjusted,at)
            if blocked or recovered:self.pullback=None
            # Retain only an unexecuted opportunity blocked by this candidate's
            # environment gate. No paused clock, reused volume, or old round.
            eligible=(gate_first_entry and (regime in ('RANGE','UNKNOWN') or blocked) and e['m30'] is not None
                      and e['admission'] is True and e['round_loss'] is False and e['day_loss'] is False
                      and e['reconciled'] is True and not e['day_end_window']
                      and not self.layers and not self.pending and not self.clear_reasons
                      and (self.last_flat_at is None or at>self.last_flat_at))
            if eligible:
                for action in actions:
                    if action.get('kind')!='REJECT' or action.get('opportunity')!='OPEN':continue
                    if set(action.get('reasons',[]))!={'ADMISSION_OR_RISK_NOT_PROVEN'}:continue
                    side=action['side'];view=directional_frame(e['m30'],side)
                    daily=e['daily_direction'] if side=='LONG' else {'UP':'DOWN','DOWN':'UP'}.get(e['daily_direction'],e['daily_direction'])
                    _,opportunity=observe_entry(before_windows[side],contract=self.contract,bar_end=at,
                        near_zero_golden=view['near_zero_golden'],daily_direction=daily,
                        minute_angle=Decimal(view['minute_angle']) if view['minute_angle'] is not None else None,
                        above_ema=view['above_ema'],volume_effective=view['volume_effective'],max_age=self.window_age)
                    w=opportunity['window']
                    if opportunity['met'] is True and w['age'] is not None and w['age']<self.window_age:
                        self.windows[side]=EntryWindow(self.contract,at,w['source_end'],w['age'])
            if structures is not None:
                from .subing_demand_explanation import explain
                from .subing_demand_observer import gross
                phase='DAY_END' if kind=='DAY_END' else 'NEXT_OPEN_AFTER_DAY_END' if opening_review else 'BAR_CLOSE'
                explanation=explain(state=self.state(),regime=regime,phase=phase,
                    pending_break=structure.get('break_side') if blocked else None,
                    gross=gross(layers,str(b.close),str(x.facts.multiplier)),streak=self.observer.streak,
                    actions=actions,opening_review=opening_review)
                self.chain.append(_wire(dict(at=at,daily_direction=e['daily_direction'],daily_at=e['daily_at'],
                    regime=regime,structure=structure,conflict=bool(structure and structure.get('structure_direction') in ('UP','DOWN') and regime!='TREND_'+structure['structure_direction']),
                    **explanation, opening_review=opening_review,
                    conditions=dict(daily_direction=e['daily_direction'],environment_allows_new=regime not in ('RANGE','UNKNOWN') and not blocked,
                        risk_allows_new=e['admission'],frame=e['m30'] or self.latest_frame,entry_windows=self.state()['entry_windows']),
                    actions=actions,position=self.state(),gross_remaining=str(gross(layers,str(b.close),str(x.facts.multiplier))))))
            return actions

        def checkpoint(self):
            payload=dict(version=version,contract=self.contract,run_id=self.run_id,context_hash=context_hash,events=deepcopy(self.events))
            return dict(payload,sha256=_digest(payload))

        @classmethod
        def restore(cls,c):
            if c['version']!=version or c['context_hash']!=context_hash or _digest({k:v for k,v in c.items() if k!='sha256'})!=c['sha256']:raise ValueError('CHECKPOINT_INVALID')
            m=cls(c['contract'],c['run_id'],regime_research_profile=REGIME_PROFILE)
            for e in c['events']:m.apply(e)
            return m
    source=Path(__file__).with_name('subing_account.py')
    spec=importlib.util.spec_from_file_location('guiyi_quant._offline_demand_account',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.DecisionModel=Candidate
    return module,Candidate,context_hash

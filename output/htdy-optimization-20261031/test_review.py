"""Independent policy-wrapper boundary tests; no market or provider worker."""
import sys,json
from pathlib import Path
from types import SimpleNamespace as NS
from decimal import Decimal as D
from collections import Counter
sys.path.insert(0,str(Path(__file__).parent))
from experiment import CandidateReplay,Replay
from engine_base import iso,ts

def model(policy):
 m=object.__new__(CandidateReplay)
 m.policy=policy;m.t=101;m.feature_rows=[{'t':90,'contract':'TA','atr':'3','trend':'YELLOW'},{'t':100,'contract':'TA','atr':'99','trend':'BLUE'}];m.feature_times=[90,100]
 m.lock_contract=None;m.direction_lock=None;m.last_risk_t=None;m.risk_line=None;m.positions={};m.orders={};m.targets={};m.counts=Counter();m.consumed=set();m.close_reasons={};m.pending_build=None;m.fills=[]
 return m

def test_trend_rejection_still_passes_reverse_to_base(monkeypatch):
 m=model('trend_filter');m.positions['TA']=NS(side=1,contract='TA',entry_at=0);calls=[]
 monkeypatch.setattr(Replay,'on_signal',lambda self,sym,e:calls.append(('base',e['id'])))
 m.reject=lambda eid,*args:calls.append(('block_open',eid))
 m.on_signal('TA',{'id':'reverse','contract':'TA','result_codes':['sell'],'bar_end':iso(90)})
 assert calls==[('base','reverse'),('block_open','reverse')]

def test_feature_event_is_after_completed_bar_before_original_signal(monkeypatch):
 m=model('atr2');m.scheduled=False;m.d=NS(symbol='TA');events=[]
 def base_schedule(self):self.scheduled=True
 monkeypatch.setattr(Replay,'schedule',base_schedule)
 m.push=lambda *args:events.append(args)
 m.schedule();assert [(e[0],e[1]) for e in events]==[(91,1),(101,1)]
 m.schedule();assert len(events)==2

def test_atr_fill_freezes_pre_fill_value_and_not_next_bar(monkeypatch):
 m=model('atr2');m.t=100;m.orders['TA']=NS(number=1,opening=True);m.positions['TA']=NS(contract='TA',side=1,entry=D(120),entry_at=99);logged=[]
 def base_fill(self,*args):self.fills.append({'opening':True})
 monkeypatch.setattr(Replay,'on_fill',base_fill)
 m.store=NS(db=NS(execute=lambda *a:NS(fetchone=lambda:(json.dumps({'opening':True}),))))
 m.log=lambda *args,**kw:logged.append(kw)
 m.on_fill('TA',None)
 assert m.risk_line==D(114);assert logged[0]['feature_t']==90
 m.t=101;m.on_signal('TA',{'feature':{'t':100,'contract':'TA','close':'115','atr':'99'}})
 assert m.risk_line==D(114)

def test_fusion_samebar_holding_queues_build_after_clear():
 m=model('newow_dual');m.positions['TA']=NS(side=1,contract='TA',entry_at=0);calls=[];m.flatten=lambda *args:calls.append(args)
 m.on_signal('TA',{'feature':{'t':100,'contract':'TA','trend_action':'BUILD','osc_actions':['CLEAR']}})
 assert len(calls)==1 and calls[0][-1]=='NEWOW_CLEAR';assert m.pending_build['result_codes']==['buy']

def test_fusion_later_clear_cancels_old_build():
 m=model('newow_dual');m.pending_build={'id':'old'};m.flatten=lambda *args:None
 m.on_signal('TA',{'feature':{'t':100,'contract':'TA','trend_action':None,'osc_actions':['CLEAR']}})
 assert m.pending_build is None

def test_osc_exit_does_not_invent_short_exit():
 m=model('osc_exit');m.positions['TA']=NS(side=-1,contract='TA',entry_at=0);m.flatten=lambda *args:(_ for _ in ()).throw(AssertionError('unexpected exit'))
 m.on_signal('TA',{'feature':{'t':100,'contract':'TA','close':'100','osc_actions':['CLEAR']}})
 assert m.direction_lock is None

def test_real_reverse_target_survives_filter_and_blocks_only_open():
 m=model('trend_filter');m.positions['TA']=NS(side=1,contract='TA',entry_at=0);m.blocked_open=set();m.targets={};m.orders={};m.heap=[]
 m.d=NS(day=lambda *args:'1970-01-01',owner=lambda *args:'TA',meta={'TA':{'sessions':[]}})
 pushes=[];m.push=lambda *args:pushes.append(args);m.log=lambda *args,**kw:None
 m.on_signal('TA',{'id':'reverse','symbol':'TA','contract':'TA','result_codes':['sell'],'bar_end':iso(90)})
 assert m.targets['TA']['side']==-1
 assert 'reverse' in m.blocked_open
 assert pushes and pushes[0][3]=='try'

def test_candidate_checkpoint_preserves_exit_and_pending_state():
 import pickle
 m=model('atr2');m.by={'TA':D('12')};m.identity_hash='fixed';m.direction_lock=-1;m.lock_contract='TA';m.risk_line=D('104');m.last_risk_t=99;m.pending_build={'id':'pending','bar_end':iso(100)}
 saved={};m.store=NS(checkpoint=lambda state:saved.update(blob=pickle.dumps(state)),restore=lambda:pickle.loads(saved['blob']))
 m.checkpoint()
 fresh=model('atr2');fresh.identity_hash='fixed';fresh.store=m.store;fresh.restore()
 assert fresh.direction_lock==-1 and fresh.lock_contract=='TA' and fresh.risk_line==D('104') and fresh.last_risk_t==99
 assert fresh.pending_build==m.pending_build and fresh.by['TA']==D('12')

def test_candidate_restore_rejects_changed_identity():
 import pytest
 from engine_base import DataError
 m=model('atr2');m.identity_hash='new';m.store=NS(restore=lambda:{'identity_hash':'old'})
 with pytest.raises(DataError,match='CHECKPOINT_INPUT_CHANGED'):m.restore()

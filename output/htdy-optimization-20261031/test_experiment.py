import sys,json
from pathlib import Path
from decimal import Decimal as D
sys.path.insert(0,str(Path(__file__).parent))
from experiment import CandidateReplay
from engine_base import Replay as Base

def shell(policy):
 m=object.__new__(CandidateReplay);m.policy=policy;m.t=100;m.feature_rows=[{'t':90,'contract':'TA','atr':'3','trend':'YELLOW'}];m.feature_times=[90];m.direction_lock=None;m.lock_contract=None;m.last_risk_t=None;m.counts=__import__('collections').Counter();m.risk_line=None;m.positions={};m.consumed=set();return m

def test_latest_strict_before_contract():
 m=shell('atr2');assert m.latest('TA',90) is None;assert m.latest('TA',91)['atr']=='3';assert m.latest('MA',91) is None

def test_locked_direction_never_calls_original(monkeypatch):
 m=shell('atr2');m.direction_lock=1
 monkeypatch.setattr(Base,'on_signal',lambda *a:(_ for _ in ()).throw(AssertionError()))
 m.on_signal('TA',{'id':1,'contract':'TA','result_codes':['buy'],'bar_end':'2026-01-01T00:00:00Z'});assert m.counts['locked_signal']==1

def test_opposite_unlocks_but_samebar_cannot(monkeypatch):
 m=shell('atr2');m.direction_lock=1;m.last_risk_t=1767225600000000
 calls=[];monkeypatch.setattr(Base,'on_signal',lambda *a:calls.append(a));m.reject=lambda *a:None
 e={'id':1,'contract':'TA','result_codes':['sell'],'bar_end':'2026-01-01T00:00:00Z'}
 m.on_signal('TA',e);assert calls==[];assert m.direction_lock==1
 e['bar_end']='2026-01-01T01:00:00Z';m.on_signal('TA',e);assert len(calls)==1;assert m.direction_lock is None

def test_risk_trigger_uses_completed_close_and_no_refill():
 m=shell('atr2');m.positions={'TA':type('P',(),{'side':1,'contract':'TA','entry_at':0})()};m.risk_line=D(100);calls=[];m.flatten=lambda *a:calls.append(a)
 m.on_signal('TA',{'feature':{'t':99,'contract':'TA','close':'101'}});assert not calls
 m.on_signal('TA',{'feature':{'t':100,'contract':'TA','close':'99'}});assert calls[0][-1]=='ATR_RISK';assert m.direction_lock==1

def test_longflat_sell_flattens_without_short():
 m=shell('long_flat');calls=[];m.flatten=lambda *a:calls.append(a)
 m.on_signal('TA',{'id':4,'contract':'TA','result_codes':['sell'],'bar_end':'2026-01-01T00:00:00Z'});assert calls[0][-1]=='HTDY_SELL'

"""Research policies around unchanged captured execution model; never provider/Runtime."""
import sys,json,hashlib,bisect,argparse,gc
from pathlib import Path
from decimal import Decimal as D
R=Path(__file__).resolve().parent;OLD=R.parent/'htdy-ta-60m-70pct-20261031';sys.path.insert(0,str(OLD))
import bounded
from bounded import BoundedInputs
from replay import Replay
from spool import Store
from engine_base import ts,DataError
class CandidateReplay(Replay):
 def __init__(self,data,slip,store,policy,features):
  super().__init__(data,slip,store);self.policy=policy;self.name=f'{data.symbol}_{policy}_slip{slip}';self.feature_rows=features;self.feature_times=[r['t'] for r in features];self.direction_lock=None;self.lock_contract=None;self.risk_line=None;self.last_risk_t=None;self.close_reasons={};self.pending_build=None
 def latest(self,c,t):
  i=bisect.bisect_left(self.feature_times,t)-1
  return self.feature_rows[i] if i>=0 and self.feature_rows[i]['contract']==c else None
 def schedule(self):
  already=self.scheduled;super().schedule()
  if not already and self.policy!='original':
   for row in self.feature_rows:self.push(row['t']+1,1,self.d.symbol,'signal',{'feature':row})
 def flatten(self,sym,c,reason):
  self.cancel(sym,reason);self.targets[sym]={'side':0,'contract':c,'id':f'{reason}:{self.t}','reason':reason};self.push(self.t+1,3,sym,'try',None)
 def on_signal(self,sym,e):
  if 'feature' in e:
   f=e['feature'];p=self.positions.get(sym)
   if self.policy.startswith('newow_'):
    acts=([f['trend_action']] if self.policy=='newow_trend' else f['osc_actions'] if self.policy=='newow_oscillation' else f['osc_actions']+[f['trend_action']])
    if 'CLEAR' in acts and 'BUILD' not in acts:self.pending_build=None
    # Existing fusion processes CLEAR before BUILD; source prices never become Fill prices.
    if 'CLEAR' in acts and 'BUILD' in acts and p:
     self.pending_build={'id':f'{self.policy}:{self.t}:BUILD','symbol':sym,'contract':f['contract'],'bar_end':__import__('engine_base').iso(f['t']),'result_codes':['buy']}
     self.flatten(sym,f['contract'],'NEWOW_CLEAR');return
    for action in ['CLEAR','BUILD']:
     if action not in acts:continue
     if action=='CLEAR':self.flatten(sym,f['contract'],'NEWOW_CLEAR')
     else:
      event={'id':f'{self.policy}:{self.t}:BUILD','symbol':sym,'contract':f['contract'],'bar_end':__import__('engine_base').iso(f['t']),'result_codes':['buy']}
      super().on_signal(sym,event)
    return
   if p and p.contract==f['contract'] and f['t']>p.entry_at:
    reason=None
    if self.risk_line is not None and ((p.side==1 and D(f['close'])<=self.risk_line) or (p.side==-1 and D(f['close'])>=self.risk_line)):reason='ATR_RISK'
    if self.policy=='osc_exit' and p.side==1 and 'CLEAR' in f['osc_actions']:reason='OSC_CLEAR'
    if reason:self.direction_lock=p.side;self.lock_contract=p.contract;self.last_risk_t=f['t'];self.flatten(sym,p.contract,reason)
   return
  if self.policy.startswith('newow_'):return
  dirs=e['result_codes']
  if len(dirs)!=1:return super().on_signal(sym,e)
  side=1 if dirs[0]=='buy' else -1
  if self.lock_contract is not None and e['contract']!=self.lock_contract:self.direction_lock=None;self.lock_contract=None
  if self.direction_lock is not None:
   if side==self.direction_lock or ts(e['bar_end'])==self.last_risk_t:self.counts['locked_signal']+=1;return
   self.direction_lock=None
  f=self.latest(e['contract'],ts(e['bar_end'])+1)
  reject=False
  if self.policy in ['atr_matched','atr2','atr3'] and (not f or f['atr'] is None):reject=True
  if self.policy=='trend_filter' and (not f or f['trend']!=('YELLOW' if side==1 else 'BLUE')):reject=True
  if self.policy=='long_flat' and side==-1:
   self.consumed.add(e['id']);self.flatten(sym,e['contract'],'HTDY_SELL');return
  super().on_signal(sym,e)
  if reject:self.reject(e['id'],sym,'POLICY_ENTRY_REJECTED')
 def submit(self,sym):
  if self.pending_build and self.d.owner(sym,self.d.day(sym,self.t))!=self.pending_build['contract']:self.pending_build=None
  super().submit(sym)
  order=self.orders.get(sym)
  if order and not order.opening:self.close_reasons.setdefault(order.number,self.targets.get(sym,{}).get('reason'))
 def on_fill(self,sym,payload):
  order=self.orders.get(sym);before=len(self.fills);reason=self.targets.get(sym,{}).get('reason')
  if order and not order.opening:self.close_reasons.setdefault(order.number,reason)
  target=self.targets.get(sym)
  if order and not order.opening and target:self.targets[sym]={**target,'reason':self.close_reasons.get(order.number,reason)}
  super().on_fill(sym,payload)
  if target:self.targets[sym]=target
  if len(self.fills)>before:
   fill=json.loads(self.store.db.execute('select payload from fills order by seq desc limit 1').fetchone()[0])
   if not fill['opening']:
    self.risk_line=None
    if self.pending_build is not None and reason=='NEWOW_CLEAR' and self.t-ts(self.pending_build['bar_end'])<=180_000_000:
     build=self.pending_build;self.pending_build=None;super().on_signal(sym,build)
   elif self.policy in ['atr2','atr3']:
    p=self.positions[sym];f=self.latest(p.contract,self.t)
    if not f or f['atr'] is None:raise DataError('ATR_MISSING_AT_FILL')
    self.risk_line=p.entry-p.side*D(self.policy[-1])*D(f['atr']);self.log('FROZEN_ATR_RISK',atr=f['atr'],risk_line=str(self.risk_line),entry=str(p.entry),feature_t=f['t'])
 def save(self,dest):
  result=super().save(dest);return result

def run(symbol,policy,slip,data_root):
 bounded.R=Path(data_root);data=BoundedInputs(symbol);feature=json.loads((R/(symbol+'-features.json')).read_text());rows=feature['rows'];dest=R/'runs'/f'{symbol}_{policy}_slip{slip}';dest.parent.mkdir(exist_ok=True)
 if dest.exists() or (dest.parent/(dest.name+'.sqlite')).exists():raise DataError('EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY')
 store=Store(dest.parent/(dest.name+'.sqlite'));model=CandidateReplay(data,slip,store,policy,rows)
 h=hashlib.sha256()
 for source in sorted((Path(data_root)/symbol/'evidence').glob('*.json'))+[OLD/'replay.py',OLD/'engine_base.py',OLD/'bounded.py',OLD/'spool.py',Path(data_root)/symbol/'evidence/execution.sqlite',Path(data_root)/symbol/'evidence/facts.json',Path(data_root)/'common/public-fees.json',Path(data_root)/'common/margin_snapshot.csv']:
  with source.open('rb') as f:
   for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 input_digest=h.hexdigest()
 model.identity_hash=hashlib.sha256((Path(__file__).read_bytes()+json.dumps(feature,sort_keys=True).encode()+json.dumps(data.identity,sort_keys=True).encode()+str(policy).encode()+str(slip).encode()+input_digest.encode())).hexdigest()
 result=model.save(dest);print(json.dumps({k:result[k] for k in ['scenario','status','failure','period_end_equity','closed_trades','max_drawdown_pct','fees']},default=str),flush=True);store.close();data.db.close();data.trim()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--symbol',default='TA');p.add_argument('--policy',required=True);p.add_argument('--slip',type=int,required=True);p.add_argument('--data-root',default=str(OLD));a=p.parse_args();run(a.symbol,a.policy,a.slip,a.data_root)

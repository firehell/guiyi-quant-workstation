"""Fixed selection gate plus entry-signal aligned traceable trade differences."""
import json,csv
from pathlib import Path
from decimal import Decimal as D
R=Path(__file__).resolve().parent
POLICIES=['atr2','atr3','trend_filter','osc_exit']
def main():
 metrics=json.loads((R/'metrics.json').read_text());idx={m['scenario']:m for m in metrics};gates=[];diff=[];attribution=[]
 for sym in ['TA','MA']:
  for policy in POLICIES:
   base='atr_matched' if policy.startswith('atr') else 'original';checks=[]
   for slip in [1,2]:
    c=idx.get(f'{sym}_{policy}_slip{slip}');b=idx.get(f'{sym}_{base}_slip{slip}')
    if c is None or b is None:checks.append({'slip':slip,'status':'MISSING_RESULT'});continue
    criteria={'complete':c['status']==b['status']=='COMPLETED','n_ge_30':c['closed_trades']>=30,'mdd_lower':D(c['max_drawdown_pct'])<D(b['max_drawdown_pct']),'worst_improved':c['worst_closed_net'] is not None and b['worst_closed_net'] is not None and D(c['worst_closed_net'])>D(b['worst_closed_net']),'expectancy_not_lower':c['mean_closed_net'] is not None and b['mean_closed_net'] is not None and D(c['mean_closed_net'])>=D(b['mean_closed_net'])}
    checks.append({'slip':slip,'criteria':criteria,'pass':all(criteria.values())})
   gates.append({'symbol':sym,'policy':policy,'checks':checks,'pass':all(c.get('pass',False) for c in checks)})
 for m in metrics:
  root=R/'runs'/m['scenario'];ts=json.loads((root/'trades.json').read_text());sym=m['scenario'].split('_')[0];slip=m['scenario'].split('_')[-1];base=R/'runs'/f'{sym}_original_{slip}'/'trades.json';bs=json.loads(base.read_text()) if base.exists() else [];group={x['entry_signal']:x for x in bs};seen=set()
  for x in ts:
   b=group.get(x['entry_signal']);seen.add(x['entry_signal']);diff.append({'scenario':m['scenario'],'entry_signal':x['entry_signal'],'status':'MATCHED_ENTRY' if b else 'CANDIDATE_ONLY','candidate_entry':x['entry_at'],'candidate_exit':x['exit_at'],'candidate_net':x['net_pnl'],'baseline_net':b['net_pnl'] if b else None,'net_difference':str(D(x['net_pnl'])-D(b['net_pnl'])) if b else None,'exit_reason':x['exit_reason']})
  for b in bs:
   if b['entry_signal'] not in seen:diff.append({'scenario':m['scenario'],'entry_signal':b['entry_signal'],'status':'BASELINE_ONLY_OR_CANDIDATE_OPEN','baseline_net':b['net_pnl']})
  for group,v in m['closed_direction_year'].items():attribution.append({'scenario':m['scenario'],'exit_utc_calendar_year_side':group,**v})
 for name,rs in [('trade-differences.csv',diff),('year-direction-attribution.csv',attribution)]:
  with (R/name).open('w') as f:
   w=csv.DictWriter(f,fieldnames=sorted({k for r in rs for k in r}));w.writeheader();w.writerows(rs)
 ds={}
 for x in diff:
  g=ds.setdefault(x['scenario'],{'matched':0,'delta':D(0),'baseline_winner_to_candidate_loss':0,'baseline_loser_improved':0,'baseline_only':0})
  if x['status']=='MATCHED_ENTRY':
   g['matched']+=1;g['delta']+=D(x['net_difference']);g['baseline_winner_to_candidate_loss']+=D(x['baseline_net'])>0 and D(x['candidate_net'])<0;g['baseline_loser_improved']+=D(x['baseline_net'])<0 and D(x['net_difference'])>0
  elif x['status'].startswith('BASELINE_ONLY'):g['baseline_only']+=1
 (R/'trade-difference-summary.json').write_text(json.dumps(ds,default=str,indent=2))
 (R/'gate.json').write_text(json.dumps(gates,indent=2));print(json.dumps(gates,indent=2))
if __name__=='__main__':main()

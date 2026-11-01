"""Read persisted curves row-by-row; independently value from original entry."""
import argparse,csv,json,sqlite3
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
import sys
R=Path(__file__).resolve().parent
OLD=R.parent/'htdy-ta-60m-70pct-20261031'
sys.path.insert(0,str(OLD))
import bounded
from bounded import BoundedInputs
from engine_base import ts

def main(symbol):
 bounded.R=OLD if symbol.upper()=='TA' else R/'ma_data'
 root=R/'runs';summaries=[json.loads(p.read_text()) for p in sorted(root.glob(symbol.upper()+'_*/summary.json'))];checks=[];years=[]
 for s in summaries:
  if s['scenario']=='TA_original_slip1' and (R/'baseline-final/runs/TA_original_slip1/summary.json').exists():s=json.loads((R/'baseline-final/runs/TA_original_slip1/summary.json').read_text())
  data=BoundedInputs(symbol);path=(R/'baseline-final/runs' if s['scenario']=='TA_original_slip1' and (R/'baseline-final/runs/TA_original_slip1.sqlite').exists() else root)/(s['scenario']+'.sqlite');store=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);store.execute('pragma cache_size=-4096');pos={};gross=D(0);fees=D(0);closed=[];fills=[json.loads(x[0]) for x in store.execute('select payload from fills order by seq')];index=0;points=0;yearmap={};peak=D(100000);maxdd=D(0);previous_equity=D(100000)
  for raw in store.execute('select payload from curve order by seq'):
   row=json.loads(raw[0])
   while index<row['fill_count']:
    f=fills[index];index+=1;c=f['contract'];p=D(f['price']);fee=D(f['fee']);at=ts(f['at']);assert at>ts(f['created_at']);assert p<=D(f['order_limit']) if f['side']>0 else p>=D(f['order_limit'])
    if f['model']=='MINUTE_PROXY':assert at==ts(f['interval_end']) and ts(f['interval_start'])>ts(f['created_at'])
    if f['opening']:
     assert not pos;assert data.fee(c,data.day(symbol.upper(),at),p,True)==fee;pos[c]=f|{'entry_day':data.day(symbol.upper(),at)}
    else:
     old=pos.pop(c);assert f['side']==-old['side'];assert data.fee(c,data.day(symbol.upper(),at),p,False,old['entry_day'])==fee;pnl=(p-D(old['price']))*old['side']*data.multiplier(c);gross+=pnl;closed.append(pnl-D(old['fee'])-fee)
    fees+=fee
   t=ts(row['at']);floating=D(0);margin=D(0)
   for c,f in pos.items():
    mark=data.price(c,t,True)[0];floating+=(mark-D(f['price']))*f['side']*data.multiplier(c);margin+=mark*data.multiplier(c)*data.rate(c,f['side'],data.day(symbol.upper(),t))
   eq=D(100000)+gross-fees+floating;assert abs(eq-D(row['equity']))<D('0.00000001'),(s['scenario'],row['at'],'EQUITY');assert abs(margin-D(row['used_margin']))<D('0.00000001');assert abs(eq-margin-D(row['reserved_margin'])-D(row['frozen_fees'])-D(row['available']))<D('0.00000001');points+=1;peak=max(peak,eq);maxdd=max(maxdd,(peak-eq)/peak)
   year=int(data.day(symbol.upper(),t)[:4]);yearmap.setdefault(year,{'first':str(previous_equity),'last':str(eq),'points':0});yearmap[year]['last']=str(eq);yearmap[year]['points']+=1;previous_equity=eq
  assert index==len(fills);assert fees==D(s['fees']);assert len(closed)==s['closed_trades'];assert sum(v>0 for v in closed)==s['wins'];assert abs(sum(closed,D(0))-D(s['closed_net_pnl']))<D('0.00000001');assert D(s['max_drawdown_pct'])+D('0.000001')>=maxdd*100
  last=ts(s['last_trustworthy']['at']);floating=sum(((data.price(c,last,True)[0]-D(f['price']))*f['side']*data.multiplier(c) for c,f in pos.items()),D(0));assert abs(D(100000)+gross-fees+floating-D(s['last_trustworthy']['equity']))<D('0.00000001')
  wins=sum((v for v in closed if v>0),D(0));loss=-sum((v for v in closed if v<0),D(0));result={'scenario':s['scenario'],'points':points,'equity_margin_fees':'PASS','fill_limits_timing':'PASS','closed_wins':'PASS','closed_positive_net_sum':str(wins),'closed_negative_net_abs_sum':str(loss),'profit_factor':str(wins/loss) if loss else None,'payoff_ratio':str((wins/sum(v>0 for v in closed))/(loss/sum(v<0 for v in closed))) if wins and loss else None,'open_mtm_from_entry':str(floating),'open_entry_fees':str(sum((D(f['fee']) for f in pos.values()),D(0)))};checks.append(result)
  for year,values in yearmap.items():years.append({'scenario':s['scenario'],'year':year,**values,'return_pct':str((D(values['last'])/D(values['first'])-1)*100),'calendar_year_completeness':'NOT_ASSESSED','note':'trading-year grouping; start is previous valuation equity, not a forced close or new account'})
  store.close();data.trim();data.db.close();print(s['scenario'],points,'PASS',flush=True)
 (R/(symbol.upper()+'-valuation-verification.json')).write_text(json.dumps(checks,indent=2))
 with (R/(symbol.upper()+'-annual-valuation.csv')).open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(years[0]) if years else ['scenario','year']);w.writeheader();w.writerows(years)
 metrics=[]
 for s in summaries:
  if s['scenario']=='TA_original_slip1' and (R/'baseline-final/runs/TA_original_slip1/summary.json').exists():s=json.loads((R/'baseline-final/runs/TA_original_slip1/summary.json').read_text())
  v=next(x for x in checks if x['scenario']==s['scenario']);metrics.append({k:s[k] for k in ['scenario','status','period_end_equity','period_return_pct','verified_prefix_return_pct','closed_trades','wins','win_rate','fees','slippage_cost','max_drawdown_pct','margin_peak','minimum_available','max_positions','closed_net_pnl']}|{'verified_until':s['last_trustworthy']['at'],'prefix_equity':s['last_trustworthy']['equity'],'failure':s['failure'],'open_positions':len(s['open_positions']),'funds_rejected':s['counts'].get('FUNDS_REJECTED',0),'profit_factor':v['profit_factor'],'payoff_ratio':v['payoff_ratio'],'open_mtm':v['open_mtm_from_entry']})
 (R/(symbol.upper()+'-valuation-metrics.json')).write_text(json.dumps(metrics,ensure_ascii=False,indent=2));(R/(symbol.upper()+'-valuation-complete.json')).write_text(json.dumps({'symbol':symbol.upper(),'simulation_statuses':[s['status'] for s in summaries],'verified':True,'note':'terminal result may be data-insufficient or funding-failed, not full history completion'},indent=2))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--symbol',required=True);args=a.parse_args();main(args.symbol)

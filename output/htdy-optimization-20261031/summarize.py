"""Independent exported-ledger verification and study metrics."""
import json,hashlib,sqlite3,csv
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime
R=Path(__file__).resolve().parent
def main():
 rows=[]
 for p in sorted((R/'runs').glob('*/summary.json')):
  if p.parent.name=='TA_original_slip1' and (R/'baseline-final/runs/TA_original_slip1/summary.json').exists():p=R/'baseline-final/runs/TA_original_slip1/summary.json'
  s=json.loads(p.read_text());root=p.parent;t=json.loads((root/'trades.json').read_text());fills=json.loads((root/'fills.json').read_text());complete=json.loads((root/'complete.json').read_text())
  for name,digest in complete['files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
  for f in fills:
   assert datetime.fromisoformat(f['at'])>datetime.fromisoformat(f['created_at'])
   assert (datetime.fromisoformat(f['at'])-datetime.fromisoformat(f['created_at'])).total_seconds()<180
   assert D(f['price'])<=D(f['order_limit']) if f['side']==1 else D(f['price'])>=D(f['order_limit'])
  vals=[D(x['net_pnl']) for x in t];net=sum(vals,D(0));assert net==D(s['closed_net_pnl']);assert sum(D(x['fee']) for x in fills)==D(s['fees']);assert sum(x>0 for x in vals)==s['wins']
  groups={}
  for x in t:
   k=f"{x['exit_at'][:4]}:{'long' if x['side']==1 else 'short'}";g=groups.setdefault(k,{'n':0,'wins':0,'net':D(0)});g['n']+=1;g['wins']+=D(x['net_pnl'])>0;g['net']+=D(x['net_pnl'])
  curve_path=Path(json.loads((root/'curve-location.json').read_text())['database']);db=sqlite3.connect('file:'+str(curve_path)+'?mode=ro',uri=True);peak=D(100000);dd=D(0);last=None
  for (payload,) in db.execute('select payload from curve order by seq'):
   point=json.loads(payload);equity=D(point['equity']);assert equity==D(point['cash'])+D(point['floating']);peak=max(peak,equity);dd=max(dd,(peak-equity)/peak);last=point
  db.close();assert last is not None
  # Engine also observes event nodes; their peak may exceed recorded minute/finish peaks.
  assert dd*100<=D(s['max_drawdown_pct'])+D('0.000000001')
  if s['status']=='COMPLETED':assert D(last['equity'])==D(s['period_end_equity'])
  row={**s,'worst_closed_net':str(min(vals)) if vals else None,'mean_closed_net':str(net/len(vals)) if vals else None,'profit_factor':str(sum((v for v in vals if v>0),D(0))/-sum((v for v in vals if v<0),D(0))) if any(v<0 for v in vals) else None,'closed_direction_year':groups,'closed_attribution_year_basis':'UTC exit calendar year; annual-valuation.csv uses authoritative trading-year','ledger_verification':'PASS'};rows.append(row)
 cols=['scenario','status','period_end_equity','period_return_pct','closed_trades','wins','win_rate','closed_net_pnl','fees','slippage_cost','max_drawdown_pct','worst_closed_net','mean_closed_net','profit_factor']
 with (R/'metrics.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows({k:r[k] for k in cols} for r in rows)
 (R/'metrics.json').write_text(json.dumps(rows,default=str,ensure_ascii=False,indent=2));print('Verified',len(rows),'scenarios')
if __name__=='__main__':main()

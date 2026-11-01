"""Read-only independent verification of the frozen PTA research artifacts."""
import hashlib,json
from pathlib import Path
from decimal import Decimal as D
from collections import defaultdict
from datetime import datetime
ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'htdy-ta-60m-70pct-20261031'
def verify(folder):
 receipt=json.loads((folder/'complete.json').read_text())
 for name,digest in receipt['files'].items():
  assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest,(folder,name)
 s=json.loads((folder/'summary.json').read_text()); trades=json.loads((folder/'trades.json').read_text());fills=json.loads((folder/'fills.json').read_text())
 net=sum((D(t['net_pnl']) for t in trades),D(0));fees=sum((D(f['fee']) for f in fills),D(0))
 assert net==D(s['closed_net_pnl']);assert fees==D(s['fees']);assert len(trades)==s['closed_trades']
 for f in fills:assert datetime.fromisoformat(f['at'])>datetime.fromisoformat(f['created_at'])
 groups=defaultdict(list)
 for t in trades:groups[t['exit_at'][:4],t['side']].append(t)
 def metrics(ts):
  vs=[D(t['net_pnl']) for t in ts]; wins=[v for v in vs if v>0];loss=[v for v in vs if v<0]
  hours=[D(str((datetime.fromisoformat(t['exit_at'])-datetime.fromisoformat(t['entry_at'])).total_seconds()))/3600 for t in ts]
  return dict(n=len(vs),wins=len(wins),net=sum(vs,D(0)),expectancy=sum(vs,D(0))/len(vs) if vs else None,worst=min(vs) if vs else None,mean_win=sum(wins,D(0))/len(wins) if wins else None,mean_loss=sum(loss,D(0))/len(loss) if loss else None,mean_calendar_holding_hours=sum(hours,D(0))/len(hours) if hours else None)
 return dict(status='PASS',identity=receipt['input_hash'],equity=s['period_end_equity'],fees=fees,metrics=metrics(trades),by_exit_year_side={str(k):metrics(v) for k,v in groups.items()},worst_five=sorted(trades,key=lambda t:D(t['net_pnl']))[:5],open_positions=s['open_positions'])
if __name__=='__main__':
 result={str(slip):verify(OLD/'TA/results'/f'TA_htdy60m_slip{slip}') for slip in [1,2]}
 bridge=json.loads((OLD/'diagnosis/bridge.json').read_text())
 for kind in ['original_events_flat','historical_signals_flat']:verify(OLD/'diagnosis'/kind)
 result['monthly_bridge']=bridge
 (ROOT/'baseline-audit.json').write_text(json.dumps(result,ensure_ascii=False,default=str,indent=2))
 print('PASS: original hashes, closed PnL, fee totals and strict fill timing; two baseline and two monthly runs')

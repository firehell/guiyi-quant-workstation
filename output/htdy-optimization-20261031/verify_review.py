"""Independent bounded aggregate audit of completed research groups (no market access)."""
import json,hashlib
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime
ROOT=Path(__file__).resolve().parent

def verify(folder):
 receipt=json.loads((folder/'complete.json').read_text())
 for name,digest in receipt['files'].items():assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest,(folder,name)
 s=json.loads((folder/'summary.json').read_text());trades=json.loads((folder/'trades.json').read_text());fills=json.loads((folder/'fills.json').read_text())
 assert len(trades)==s['closed_trades'];assert sum(D(t['net_pnl'])>0 for t in trades)==s['wins'];net=sum((D(t['net_pnl']) for t in trades),D(0));assert net==D(s['closed_net_pnl'])
 assert sum((D(f['fee']) for f in fills),D(0))==D(s['fees'])
 for t in trades:
  assert datetime.fromisoformat(t['entry_at'])<datetime.fromisoformat(t['exit_at'])
  assert D(t['gross_pnl'])-D(t['entry_fee'])-D(t['exit_fee'])==D(t['net_pnl'])
 for f in fills:
  assert datetime.fromisoformat(f['created_at'])<datetime.fromisoformat(f['at'])
  assert D(f['price'])<=D(f['order_limit']) if f['side']>0 else D(f['price'])>=D(f['order_limit'])
 if s['status']=='COMPLETED':assert s['last_trustworthy']['at']==s['cutoff']
 return dict(status='PASS',scenario=s['scenario'],run_status=s['status'],closed_trades=len(trades),fills=len(fills),equity=s['period_end_equity'],net=net)
if __name__=='__main__':
 result=[verify(p.parent) for p in sorted((ROOT/'runs').glob('*/complete.json'))]
 (ROOT/'independent-verification.json').write_text(json.dumps(result,default=str,indent=2))
 print('PASS',len(result),'complete artifact groups',sum(x['closed_trades'] for x in result),'closed trades',sum(x['fills'] for x in result),'fills')

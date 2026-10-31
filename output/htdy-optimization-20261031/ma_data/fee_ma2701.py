"""Supplement exactly four null MA2701 fee fields on 2026-10-26."""
import json,os
from pathlib import Path
R=Path(__file__).resolve().parent;E=R/'MA/evidence';OUT=E/'supplement-fee-MA2701-20261026'
FIELDS=['commission_type','open_commission','close_commission','close_commission_today']
def dump(p,v):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,indent=2,default=str,allow_nan=False));os.replace(t,p)
def main():
 if OUT.exists():raise ValueError('EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY')
 facts=json.loads((E/'facts.json').read_text());rows=[r for r in facts['MA2701']['parameters'] if str(r['trading_date'])[:10]=='2026-10-26'];assert len(rows)==1 and all(rows[0].get(k) is None for k in FIELDS)
 OUT.mkdir();dump(OUT/'missing-before.json',rows[0]);journal=OUT/'requests.jsonl';calls=0
 def log(state):
  with journal.open('a') as f:f.write(json.dumps({'state':state,'contract':'MA2701','day':'2026-10-26','fields':FIELDS})+'\n');f.flush();os.fsync(f.fileno())
 try:
  from app.private_settings import load_private_execution_settings
  from app.market_data.rqdata_adapter import RQDataClient
  settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env');api=RQDataClient(settings=settings).api
  q=api.user.get_quota();remaining=int(q['bytes_limit'])-int(q['bytes_used']);dump(OUT/'quota.json',{'remaining':remaining,'reserve':128*1024**2});assert remaining>=128*1024**2
  log('request_started');calls=1
  df=api.futures.get_trading_parameters('MA2701',start_date='2026-10-26',end_date='2026-10-26',fields=FIELDS)
  log('request_completed')
  if df is None or df.empty:raise ValueError('EMPTY_FEE_FACT')
  raw=df.reset_index().to_dict(orient='records');dump(OUT/'raw.json',raw);assert len(raw)==1 and str(raw[0]['trading_date'])[:10]=='2026-10-26' and raw[0]['order_book_id']=='MA2701'
  if any(raw[0].get(k) is None for k in FIELDS):raise ValueError('FEE_FIELD_MISSING')
  from decimal import Decimal as D
  assert raw[0]['commission_type'] in ('by_volume','by_money') and all(D(str(raw[0][k])).is_finite() and D(str(raw[0][k]))>=0 for k in FIELDS[1:])
  if os.environ.get('TASK_STOP_FILE') and Path(os.environ['TASK_STOP_FILE']).exists():raise ValueError('RESOURCE_STOP')
  rows[0].update({k:raw[0][k] for k in FIELDS});dump(E/'facts.json',facts);result={'status':'VERIFIED_AND_IMPORTED','calls':calls,'contract':'MA2701','day':'2026-10-26','fields':FIELDS}
 except Exception as ex:result={'status':'DATA_INSUFFICIENT','calls':calls,'reason':str(ex) if isinstance(ex,ValueError) else type(ex).__name__}
 dump(OUT/'result.json',result);print(json.dumps(result))
 if result['status']!='VERIFIED_AND_IMPORTED':raise SystemExit(2)
if __name__=='__main__':main()

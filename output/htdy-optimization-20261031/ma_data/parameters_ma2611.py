"""One bounded, nonretrying MA2611 execution-fact attempt, research only."""
import hashlib,json,math,os
from pathlib import Path
from datetime import datetime,UTC
from app.private_settings import load_private_execution_settings
from app.market_data.rqdata_adapter import RQDataClient
from scripts.research.new_subing_execution_facts import instrument_payload
R=Path(__file__).resolve().parent;E=R/'MA/evidence';OUT=E/'supplement-parameters-MA2611';C='MA2611'
def dump(p,v):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,indent=2,default=str,allow_nan=False));os.replace(t,p)
def main():
 if OUT.exists():raise ValueError('EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY')
 OUT.mkdir();spans=json.loads((E/'spans.json').read_text());days=spans[C]['days'];facts=json.loads((E/'facts.json').read_text());assert C not in facts
 dump(OUT/'missing-before.json',{'contract':C,'days':days,'facts_absent':True,'old_facts_sha256':hashlib.sha256((E/'facts.json').read_bytes()).hexdigest()})
 journal=OUT/'requests.jsonl';calls=0
 def log(**v):
  with journal.open('a') as f:f.write(json.dumps(v,default=str)+'\n');f.flush();os.fsync(f.fileno())
 try:
  settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env');api=RQDataClient(settings=settings).api;q=api.user.get_quota();remaining=int(q['bytes_limit'])-int(q['bytes_used']);dump(OUT/'quota.json',{'remaining':remaining,'reserve':128*1024**2});assert remaining>=128*1024**2
  def fetch(kind,fn):
   nonlocal calls
   if os.environ.get('TASK_STOP_FILE') and Path(os.environ['TASK_STOP_FILE']).exists():raise ValueError('RESOURCE_STOP')
   log(kind=kind,state='request_started',contract=C,start=days[0],end=days[-1]);calls+=1;v=fn();log(kind=kind,state='request_completed');return v
  f={'instrument':instrument_payload(fetch('instrument',lambda:api.instruments(C)),C)}
  dump(OUT/'instrument.json',f['instrument'])
  for kind,fields in [('parameters',['long_margin_ratio','short_margin_ratio','commission_type','open_commission','close_commission','close_commission_today','min_order_quantity']),('daily',['settlement','prev_settlement']),('limits',['limit_up','limit_down'])]:
   if kind=='parameters':fn=lambda:api.futures.get_trading_parameters(C,start_date=days[0],end_date=days[-1],fields=fields)
   elif kind=='daily':fn=lambda:api.futures.get_exchange_daily(C,start_date=days[0],end_date=days[-1],fields=fields)
   else:fn=lambda:api.get_price(C,start_date=days[0],end_date=days[-1],frequency='1d',fields=fields,adjust_type='none',expect_df=True)
   df=fetch(kind,fn)
   if df is None or df.empty:raise ValueError('EMPTY_EXECUTION_FACTS')
   records=df.reset_index().to_dict(orient='records')
   for row in records:
    for k,v in row.items():
     if isinstance(v,float) and not math.isfinite(v):raise ValueError('NONFINITE_EXECUTION_FACT')
   dump(OUT/(kind+'.json'),records)
   selected=[r for r in records if str(r.get('trading_date',r.get('date')))[:10] in days]
   if sorted(str(r.get('trading_date',r.get('date')))[:10] for r in selected)!=days:raise ValueError('EXECUTION_FACT_DAY_MISSING_OR_DUPLICATE')
   if any(r.get(k) is None for r in selected for k in fields):raise ValueError('EXECUTION_FACT_FIELD_MISSING')
   f[kind]=selected
  facts[C]=f;dump(E/'facts.json',facts);result={'status':'VERIFIED_AND_IMPORTED','contract':C,'days':len(days),'provider_calls':calls}
 except Exception as ex:result={'status':'DATA_INSUFFICIENT','contract':C,'provider_calls':calls,'reason':str(ex) if isinstance(ex,ValueError) else type(ex).__name__}
 dump(OUT/'result.json',result);print(json.dumps(result))
 if result['status']!='VERIFIED_AND_IMPORTED':raise SystemExit(2)
if __name__=='__main__':main()

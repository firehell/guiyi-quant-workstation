"""Diagnostic-only A/B, exact same read-only transaction; no product source changes."""
import time,json,hashlib,datetime
from pathlib import Path
from collections import Counter
from sqlalchemy import text,event
from app.db.session import SessionLocal,engine
from app.market_data.composition import build_market_home_projection
from app.market_data.catalog import MarketCatalog
OUT=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/market-home-latency-20260914')
orig=MarketCatalog.trading_days
calls=Counter(); count=[0]; cached={}; enabled=[False]
def track(self,symbol,start,end):
 key=(symbol,start,end);calls[key]+=1
 if enabled[0] and key in cached:return cached[key]
 result=orig(self,symbol,start,end)
 if enabled[0]:cached[key]=result
 return result
MarketCatalog.trading_days=track
def after(*args):count[0]+=1
event.listen(engine,'after_cursor_execute',after)
try:
 with SessionLocal() as session:
  session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
  session.execute(text("SET LOCAL statement_timeout='45s'"))
  results=[];hashes=[]
  for label in ['baseline','exact_calendar_reuse']:
   calls.clear();cached.clear();enabled[0]=label!='baseline';n=count[0]
   p=build_market_home_projection(session)
   t=time.perf_counter();r=p.read();elapsed=time.perf_counter()-t
   h=hashlib.sha256(r.model_dump_json().encode()).hexdigest();hashes.append(h)
   row={'mode':label,'seconds':elapsed,'sql_count':count[0]-n,'calendar_calls':sum(calls.values()),'unique_calendar_queries':len(calls),'duplicate_calendar_queries':sum(calls.values())-len(calls),'max_repeats':max(calls.values()),'participants':r.participant_count,'response_sha256':h}
   results.append(row);print(json.dumps(row),flush=True)
  output={'checked_at':datetime.datetime.now().astimezone().isoformat(),'transaction':'repeatable read/read only','same_response':hashes[0]==hashes[1],'runs':results}
  (OUT/'request-reuse.json').write_text(json.dumps(output,indent=2))
  session.rollback()
except Exception as exc:print(json.dumps({'error_type':type(exc).__name__}),flush=True);raise SystemExit(1)
finally:engine.dispose()

"""Isolated read-only profiling of exact Runtime Market Home compute; no provider/writer calls."""
import cProfile, pstats, time, json, datetime
from pathlib import Path
from collections import Counter
from sqlalchemy import event, text
from app.db.session import SessionLocal, engine
from app.market_data.composition import build_market_home_projection, canonical_root
from app.market_data.market_data_service import MarketDataService
from app.market_data.after_market import _market_home_projection_refresh_enabled
OUT=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/market-home-latency-20260914')
rows=[]; sql={'count':0,'seconds':0.0}; phases={}
def before(conn,cursor,statement,parameters,context,executemany): context._audit_start=time.perf_counter()
def after(conn,cursor,statement,parameters,context,executemany):
 sql['count']+=1;sql['seconds']+=time.perf_counter()-context._audit_start
event.listen(engine,'before_cursor_execute',before);event.listen(engine,'after_cursor_execute',after)
orig=MarketDataService.query_page
def query(self,request):
 t=time.perf_counter();n=sql['count'];d=sql['seconds'];row={'symbol':request.symbol,'frequency':request.frequency.value,'limit':request.limit}
 try:
  result=orig(self,request);row['bars']=len(result.bars);return result
 finally:
  row.update(seconds=time.perf_counter()-t,sql_count=sql['count']-n,sql_seconds=sql['seconds']-d);rows.append(row)
MarketDataService.query_page=query
try:
 with SessionLocal() as session:
  session.execute(text('SET TRANSACTION READ ONLY'))
  session.execute(text("SET LOCAL statement_timeout = '45s'"))
  t=time.perf_counter();projection=build_market_home_projection(session);phases['compose']=time.perf_counter()-t
  t=time.perf_counter();identity=projection.service.authority_identity();phases['identity']=time.perf_counter()-t
  t=time.perf_counter();cached=projection.store.load(identity);phases['projection_load']=time.perf_counter()-t
  meta={'checked_at':datetime.datetime.now().astimezone().isoformat(),'canonical_root':str(canonical_root()),'projection_exists':projection.store.path.exists(),'projection_hit':cached is not None,'natural_projection_enabled':_market_home_projection_refresh_enabled(),'target':str(identity.target_as_of),'read_only':session.execute(text('SHOW transaction_read_only')).scalar()}
  print(json.dumps({'preflight':meta,'phases':phases},ensure_ascii=False),flush=True)
  prof=cProfile.Profile();t=time.perf_counter();prof.enable();response=projection.read();prof.disable();phases['projection_read']=time.perf_counter()-t
  t=time.perf_counter();wire=response.model_dump_json();phases['serialize']=time.perf_counter()-t
  stats=pstats.Stats(prof)
  functions=[]
  for (filename,line,name),(primitive,calls,self_time,cumulative,callers) in stats.stats.items():
   functions.append({'file':filename,'line':line,'function':name,'calls':calls,'self_seconds':self_time,'cumulative_seconds':cumulative})
  functions.sort(key=lambda x:x['cumulative_seconds'],reverse=True)
  evidence={'meta':meta,'phases':phases,'sql':sql,'queries':rows,'response':{'status':response.status,'participants':response.participant_count,'bytes':len(wire.encode())},'profile':functions[:160]}
  (OUT/'profile.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
  print(json.dumps({'phases':phases,'sql':sql,'response':evidence['response'],'queries':len(rows),'slowest':sorted(rows,key=lambda x:x['seconds'],reverse=True)[:8]},ensure_ascii=False),flush=True)
  session.rollback()
except Exception as exc:
 print(json.dumps({'error_type':type(exc).__name__}),flush=True)
 raise SystemExit(1)
finally: engine.dispose()

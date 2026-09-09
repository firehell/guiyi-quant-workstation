from __future__ import annotations
import os,sys,json,plistlib,subprocess,re,hashlib
from pathlib import Path
from datetime import datetime,date,timedelta,UTC
from dataclasses import asdict
from zoneinfo import ZoneInfo

OUT=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/01a07f08-100c-7e63-a568-e88df19d2b3d/2026-09-09')
OUT.mkdir(parents=True,exist_ok=True)
SH=ZoneInfo('Asia/Shanghai')
NOW=datetime.now(UTC); TODAY=NOW.astimezone(SH).date(); MON=TODAY-timedelta(days=TODAY.weekday())
roots={}
for service in ['api','web','live','alert','after-market']:
 p=Path(f'/Users/zhangzhao/Library/LaunchAgents/com.guiyi.quant-{service}.plist')
 d=plistlib.loads(p.read_bytes()); roots[service]=d.get('EnvironmentVariables',{}).get('GUIYI_PROJECT_ROOT',d.get('WorkingDirectory'))
ROOT=Path(roots['alert']); assert all(v==str(ROOT) for v in roots.values()),'RUNTIME_ROOT_MISMATCH'
sys.path.insert(0,str(ROOT/'services/quant-api'))
from dotenv import load_dotenv
load_dotenv('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env',override=True)
assert os.environ.get('POSTGRES_PASSWORD'),'RUNTIME_AUTH_MISSING'
os.environ['REDIS_PASSWORD']=os.getenv('REDIS_PASSWORD') or os.environ['POSTGRES_PASSWORD']
if os.getenv('REDIS_URL','redis://127.0.0.1:6379/0')=='redis://127.0.0.1:6379/0':
 from urllib.parse import quote
 os.environ['REDIS_URL']='redis://:'+quote(os.environ['REDIS_PASSWORD'],safe='')+'@127.0.0.1:6379/0'
from sqlalchemy import select,event,func,or_
from sqlalchemy.orm import Session
from app.db.session import engine
from app.models import TradingCalendar,Instrument
from app.alerts.models import AlertEvent,AlertRule
from app.alerts.registry import get_alert_rule_definition
from app.alerts.notification import AlertNotificationMessage,format_alert_message
from app.market_data.composition import build_market_data_service,build_market_read_service
from app.market_data.domain import SeriesPageQuery,ContractTradingDayQuery
from app.market_data.product_taxonomy import load_product_taxonomy
from app.market_data.operational_universe import load_operational_products
from app.redis_connections import get_redis_connection
from app.alerts.composition import RedisAlertRuntimeStatusStore

def safe(exc):
 code=getattr(exc,'code',None)
 return code if isinstance(code,str) and re.fullmatch('[A-Z0-9_]+',code) else type(exc).__name__
def enc(x):
 if isinstance(x,(datetime,date)):return x.isoformat()
 return str(x)
def save(name,obj):
 (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,default=enc,indent=2))
@event.listens_for(engine,'before_cursor_execute')
def guard(conn,cursor,statement,parameters,context,executemany):
 assert statement.lstrip().split()[0].upper() in ('SELECT','SHOW'),'SQL_NOT_READONLY'

def main():
 source={'cutoff':NOW,'today':TODAY,'week_start':MON,'runtime_roots':roots,'runtime_head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()}
 conn=engine.connect().execution_options(isolation_level='REPEATABLE READ',postgresql_readonly=True)
 redis=get_redis_connection()
 try:
  with Session(bind=conn,autoflush=False) as s:
   operational=load_operational_products()
   exchanges=set(s.scalars(select(Instrument.exchange_code).where(Instrument.symbol.in_(operational))))
   calendars=list(s.scalars(select(TradingCalendar).where(TradingCalendar.trade_date==TODAY,TradingCalendar.exchange_code.in_(exchanges))))
   assert {c.exchange_code for c in calendars}==exchanges,'CALENDAR_MISSING'
   source['calendar']=[{'exchange':c.exchange_code,'day':c.trade_date,'is_trading_day':c.is_trading_day,'has_night_session':c.has_night_session} for c in calendars]
   if not any(c.is_trading_day for c in calendars):
    source['status']='NON_TRADING_DAY';save('source.json',source);print('NON_TRADING_DAY');return
   assert all(c.is_trading_day for c in calendars),'EXCHANGE_CALENDAR_CONFLICT'
   tax=load_product_taxonomy(); md=build_market_data_service(s); mr=build_market_read_service(s,redis=redis)
   start=datetime.combine(MON,datetime.min.time(),SH).astimezone(UTC)
   stmt=select(AlertEvent,AlertRule.rule_code).join(AlertRule,AlertRule.id==AlertEvent.rule_id).where(or_(AlertEvent.trading_day>=MON,AlertEvent.notification_attempted_at>=start),AlertEvent.detected_at<=NOW).order_by(AlertEvent.id)
   results=list(s.execute(stmt));source['events']=[]
   for e,rule in results:
    record={k:getattr(e,k) for k in ['id','symbol','contract','trading_day','frequency','bar_end','result_codes','detected_at','notification_attempted_at','created_at']}
    record['rule_code']=rule;record['product_name']=tax[e.symbol].name;record['strategy']=get_alert_rule_definition(rule).display_name
    record['content']=format_alert_message(AlertNotificationMessage(rule,e.symbol,tax[e.symbol].name,e.contract,e.frequency,e.bar_end,e.detected_at,tuple(e.result_codes)))
    source['events'].append(record)
   assert len({e['id'] for e in source['events']})==len(results)
   source['runtime_status']=RedisAlertRuntimeStatusStore(redis).read()
   save('source.json',source);print('EVENTS',len(results),'TODAY',sum(e['trading_day']==TODAY for e in source['events']),flush=True)
   market={};save('market.json',market)
   groups={ (e['symbol'],e['contract']) for e in source['events'] }
   for symbol,contract in sorted(groups):
    item={'symbol':symbol,'contract':contract,'bars':[],'errors':[],'expected':[]};market[contract]=item
    try:
     days=sorted({e['trading_day'] for e in source['events'] if e['contract']==contract and e['trading_day'] is not None})
     assert days,'EVENT_TRADING_DAY_MISSING';since=min(days)
     expected=md.expected_contract_replay_endpoints(symbol=symbol,contract=contract,frequency='1m',trading_day=TODAY,cutoff=NOW,since=since)
     item['expected']=[(t,d) for t,d in expected]
     history_days=sorted({d for t,d in expected if d<TODAY})
     bars=[]
     if history_days:
      try:bars.extend(md.query_contract_trading_days(ContractTradingDayQuery(symbol=symbol,contract=contract,frequency='1m',since=history_days[0],through=history_days[-1])).bars)
      except Exception as exc:item['errors'].append({'part':'historical','code':safe(exc)})
     identity=SeriesPageQuery('contract',symbol,'1m',limit=2000,contract=contract)
     first=mr.display_snapshot(identity,None,NOW);second=mr.display_snapshot(identity,None,NOW)
     assert first==second,'SNAPSHOT_CHANGED'
     item['snapshot_source']=first.source;item['snapshot_day']=first.trading_day;item['snapshot_contract']=first.contract
     if first.source!='none':
      assert first.contract==contract and first.trading_day==TODAY,'SNAPSHOT_IDENTITY_MISMATCH'
      bars.extend(first.bars)
     else:item['errors'].append({'part':'today','code':'POST_CLOSE_SNAPSHOT_UNAVAILABLE'})
     assert len({b.bar_end for b in bars})==len(bars),'DUPLICATE_BARS'
     bars.sort(key=lambda b:b.bar_end)
     exp=set(expected);actual={(b.bar_end,b.trading_day) for b in bars}
     assert not actual-exp,'EXTRA_OR_DAY_MISMATCH'
     item['missing_count']=len(exp-actual)
     item['bars']=[asdict(b) for b in bars]
     print(contract,len(bars),'missing',item['missing_count'],'errors',len(item['errors']),flush=True)
    except Exception as exc:item['errors'].append({'part':'contract','code':safe(exc)});print(contract,'ERROR',safe(exc),flush=True)
    save('market.json',market)
   source['control_count']=len(list(s.execute(stmt)))
   assert source['control_count']==len(results)
   save('source.json',source)
 finally:redis.close();conn.close();engine.dispose()
if __name__=='__main__':
 try:main()
 except Exception as exc:print('FAILED',safe(exc));sys.exit(1)

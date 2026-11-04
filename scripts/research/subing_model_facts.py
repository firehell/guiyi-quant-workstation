"""Single bounded JM current-day execution-fact capture, with no automatic retry."""
from pathlib import Path
from datetime import date,datetime,UTC
import argparse,json
from scripts.research.new_subing_execution_facts import instrument_payload,normalize_rows,merge_daily_rows,EXCHANGE_FIELDS,LIMIT_FIELDS,_write
from app.market_data.new_subing_research import payload_hash

FIELDS=['long_margin_ratio','short_margin_ratio','commission_type','open_commission','close_commission','close_commission_today']

def main():
    p=argparse.ArgumentParser();p.add_argument('--contract',required=True);p.add_argument('--day',type=date.fromisoformat,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if not a.contract.startswith('JM') or not a.contract[2:].isdigit():raise ValueError('CONTRACT_INVALID')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.private_settings import load_private_execution_settings
    from app.market_data.catalog import MarketCatalog
    settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    try:
        with Session(engine,autoflush=False) as s,readonly_transaction(s):
            maps=MarketCatalog(s,Path(settings['GUIYI_CANONICAL_DATA_ROOT'])).main_map('jm',a.day,a.day)
            if len(maps)!=1 or maps[0].contract!=a.contract:raise ValueError('OWNER_MAPPING_INVALID')
    finally:engine.dispose()
    a.out.mkdir(parents=True,exist_ok=False)
    plan=dict(contract=a.contract,day=str(a.day),max_calls=6,canonical_write=False,catalog_write=False,automatic_retry=False)
    _write(a.out/'plan.json',dict(plan,plan_hash=payload_hash(plan)))
    calls=0
    def call(name,fn):
        nonlocal calls
        calls+=1
        if calls>6:raise ValueError('CALL_BUDGET')
        with (a.out/'journal.jsonl').open('a') as f:f.write(json.dumps(dict(sequence=calls,method=name,status='STARTED',at=datetime.now(UTC).isoformat()))+'\n')
        result=fn()
        with (a.out/'journal.jsonl').open('a') as f:f.write(json.dumps(dict(sequence=calls,method=name,status='COMPLETED'))+'\n')
        return result
    from app.market_data.rqdata_adapter import RQDataClient
    api=call('init',lambda:RQDataClient(settings=settings).api)
    quota=call('quota',api.user.get_quota)
    if quota['bytes_limit']-quota['bytes_used']<1024*1024:raise ValueError('PROVIDER_BUDGET_INSUFFICIENT')
    ins=instrument_payload(call('instruments',lambda:api.instruments(a.contract)),a.contract)
    day=str(a.day)
    pars=normalize_rows(call('parameters',lambda:api.futures.get_trading_parameters(a.contract,start_date=day,end_date=day,fields=FIELDS)),a.contract,[day],FIELDS)
    daily=normalize_rows(call('exchange_daily',lambda:api.futures.get_exchange_daily(a.contract,start_date=day,end_date=day,fields=list(EXCHANGE_FIELDS))),a.contract,[day],list(EXCHANGE_FIELDS))
    limits=normalize_rows(call('daily_limits',lambda:api.get_price(a.contract,start_date=day,end_date=day,frequency='1d',fields=list(LIMIT_FIELDS),adjust_type='none',expect_df=True)),a.contract,[day],list(LIMIT_FIELDS))
    _write(a.out/'jm.json',dict(schema_version=1,source='rqdata',plan_hash=payload_hash(plan),captured_at=datetime.now(UTC).isoformat(),time_semantics='current_effective_execution_facts',contracts={a.contract:dict(start=day,end=day,instrument=ins,parameters=pars,daily=merge_daily_rows(daily,limits),field_sources=dict(prev_settlement='futures.get_exchange_daily',limit_up='get_price:1d:limit_up',limit_down='get_price:1d:limit_down'))}))
    print(json.dumps(dict(status='CAPTURED',contract=a.contract,day=day,calls=calls)))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='FACTS_UNAVAILABLE',error_type=type(exc).__name__,code=getattr(exc,'code',None))));raise SystemExit(2) from None

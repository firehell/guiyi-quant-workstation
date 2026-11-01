"""Exact MA exit-day research supplementation; original evidence remains immutable."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, shutil, sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
R=Path(__file__).resolve().parent
ROOT=R.parents[2]
SOURCE=ROOT/'output/htdy-eight-history-20261031/MA/evidence'
E=R/'MA/evidence'
HELPER=ROOT/'output/htdy-ta-60m-70pct-20261031/exit_quotes.py'
spec=importlib.util.spec_from_file_location('ma_exit_quote_validation',HELPER)
quotes=importlib.util.module_from_spec(spec);spec.loader.exec_module(quotes)
RESERVE=128*1024**2

def dump(p, value):
    temp=p.with_suffix(p.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str))
    os.replace(temp,p)

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def plan():
    with sqlite3.connect('file:'+str(SOURCE/'execution.sqlite')+'?mode=ro',uri=True) as db:
        jobs=[]
        for (payload,) in db.execute('select payload from execution_gaps order by t,c'):
            g=json.loads(payload);c=g['contract'];day=g['requested_since']
            if g['requested_through']!=day or not c.startswith('MA'):raise ValueError('UNBOUNDED_GAP')
            expected=[t for (t,) in db.execute('select t from expected where c=? and day=? order by t',(c,day))]
            if not expected:raise ValueError('EXPECTED_ENDPOINTS_MISSING')
            jobs.append({'contract':c,'day':day,'frequency':'1m','expected_rows':len(expected),'estimated_response_bytes':len(expected)*256})
    value={'symbol':'MA','jobs':jobs,'price_requests_max':len(jobs),'reserve_bytes':RESERVE,'max_estimated_price_bytes':sum(j['estimated_response_bytes'] for j in jobs),'source_execution_sha256':digest(SOURCE/'execution.sqlite'),'helper_sha256':digest(HELPER),'destination':str(E),'source_unchanged':True}
    dump(R/'plan.json',value)
    return value

def clone():
    p=plan()
    if E.exists():raise ValueError('DESTINATION_EXISTS_NO_OVERWRITE')
    E.parent.mkdir(exist_ok=True)
    shutil.copytree(SOURCE,E)
    shutil.copyfile(SOURCE/'execution-gaps.json',E/'original-execution-gaps.json')
    if digest(E/'execution.sqlite')!=p['source_execution_sha256']:raise ValueError('COPY_HASH_MISMATCH')
    print(json.dumps({'status':'CLONED','jobs':len(p['jobs'])}))

def refresh():
    with sqlite3.connect('file:'+str(E/'execution.sqlite')+'?mode=ro',uri=True) as db:
        gaps=[json.loads(x[0]) for x in db.execute('select payload from execution_gaps order by t,c')]
        missing=db.execute('select count(*) from expected e left join bars b on e.c=b.c and e.t=b.t where b.t is null').fetchone()[0]
    dump(E/'execution-gaps.json',gaps)
    values=[]
    for p in sorted(E.glob('exit-quotes*/*.json')) if E.exists() else []:values.append(json.loads(p.read_text()))
    result={'remaining_gap_days':len(gaps),'missing_expected_minutes':missing,'verified_jobs':sum(v['status']=='VERIFIED_AND_IMPORTED' for v in values),'quotes':values,'original_execution_unchanged':digest(SOURCE/'execution.sqlite')==json.loads((R/'plan.json').read_text())['source_execution_sha256']}
    dump(E/'supplement-summary.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='quotes'}))

def guard_attempt(out,key):
    if any((out/(key+s)).exists() for s in ('.json','.jsonl','.parquet')):raise ValueError('EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY')

def supplement(contract,day,attempt=1):
    p=json.loads((R/'plan.json').read_text())
    if not any(j['contract']==contract and j['day']==day for j in p['jobs']):raise ValueError('JOB_NOT_IN_PLAN')
    out=E/('exit-quotes' if attempt==1 else 'exit-quotes-attempt'+str(attempt));out.mkdir(exist_ok=True);key=contract+'-'+day
    for old in E.glob('exit-quotes*/'+key+'.jsonl'):
        if any(json.loads(line).get('state')=='request_started' for line in old.read_text().splitlines()):raise ValueError('PRIOR_PROVIDER_REQUEST_NO_AUTOMATIC_RETRY')
    guard_attempt(out,key)
    journal=out/(key+'.jsonl')
    def log(state,**kw):
        with journal.open('a') as f:
            f.write(json.dumps({'state':state,'at':str(datetime.now(UTC)),**kw})+'\n');f.flush();os.fsync(f.fileno())
    result={'contract':contract,'trading_day':day,'frequency':'1m','destination':'RESEARCH_ONLY_NOT_CANONICAL','api_calls_for_prices':0}
    db=sqlite3.connect(E/'execution.sqlite');db.execute('pragma cache_size=-8192')
    expected=[x[0] for x in db.execute('select t from expected where c=? and day=? order by t',(contract,day))]
    log('attempt_started')
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from app.private_settings import load_private_execution_settings
        from app.db.session import normalize_database_url
        from app.market_data.catalog import MarketCatalog
        from app.market_data.storage import CanonicalMonthlyStore
        from app.market_data.market_data_service import MarketDataService
        from app.market_data.domain import BarFrequency,ContractTradingDayQuery
        settings,_=load_private_execution_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
        engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'options':'-c default_transaction_read_only=on -c statement_timeout=30000'})
        try:
            with Session(engine) as session:
                root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);mds=MarketDataService(MarketCatalog(session,root),CanonicalMonthlyStore(root))
                try:
                    bars=mds.query_contract_trading_days(ContractTradingDayQuery('ma',contract,BarFrequency.M1,date.fromisoformat(day),date.fromisoformat(day))).bars
                    rows=quotes.validate([{'order_book_id':contract,'datetime':b.bar_end,**{k:getattr(b,k) for k in quotes.FIELDS}} for b in bars],contract,expected)
                    result['source']='MDS_CANONICAL_EXACT_DAY'
                except Exception as ex:
                    code=getattr(ex,'code',None)
                    if code not in ('DATASET_OR_PARTITION_MISSING','DATASET_NOT_FOUND','PARTITION_NOT_FOUND'):raise ValueError('LOCAL_MDS_UNAVAILABLE_'+str(code or type(ex).__name__)) from None
                    rows=None;result['local_reason']=code
        finally:engine.dispose()
        if rows is None:
            from app.market_data.rqdata_adapter import RQDataClient
            api=RQDataClient(settings=settings).api
            quota=api.user.get_quota();remaining=int(quota['bytes_limit'])-int(quota['bytes_used'])
            result['quota_remaining_before']=remaining
            if remaining<RESERVE+p['max_estimated_price_bytes']:raise ValueError('QUOTA_RESERVE')
            log('request_started',contract=contract,day=day);result['api_calls_for_prices']=1
            frame=api.get_price(contract,start_date=day,end_date=day,frequency='1m',fields=quotes.FIELDS,adjust_type='none',expect_df=True)
            log('request_completed')
            if frame is None or frame.empty:raise ValueError('EXIT_QUOTES_UNAVAILABLE')
            raw=out/(key+'.parquet');frame.to_parquet(raw);result['raw_sha256']=digest(raw)
            rows=quotes.validate(frame.reset_index().to_dict(orient='records'),contract,expected)
            result['source']='RQDATA_RESEARCH_EXIT_1M_NOT_CANONICAL'
        if os.environ.get('TASK_STOP_FILE') and Path(os.environ['TASK_STOP_FILE']).exists():raise ValueError('RESOURCE_STOP_BEFORE_LOCAL_COMMIT')
        with db:
            quotes.insert(db,contract,day,rows)
            if result['source']=='MDS_CANONICAL_EXACT_DAY':db.execute("update bars set source='MDS_CANONICAL_EXACT_DAY' where c=? and day=? and source='RQDATA_RESEARCH_EXIT_1M_NOT_CANONICAL'",(contract,day))
            db.execute("delete from execution_gaps where c=? and json_extract(payload,'$.requested_since')=?",(contract,day))
        result.update(status='VERIFIED_AND_IMPORTED',rows=len(rows));log('research_commit_verified',rows=len(rows))
    except Exception as ex:
        db.rollback();reason=str(ex) if isinstance(ex,ValueError) and str(ex).replace('_','').isalnum() else type(ex).__name__
        result.update(status='DATA_INSUFFICIENT',reason=reason);log('stopped',reason=reason)
    finally:
        db.close();dump(out/(key+'.json'),result);print(json.dumps(result))
    if result['status']!='VERIFIED_AND_IMPORTED':raise SystemExit(2)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('command',choices=['plan','clone','supplement','refresh']);a.add_argument('--contract');a.add_argument('--day');a.add_argument('--attempt',type=int,choices=[1,2],default=1);args=a.parse_args()
    if args.command=='plan':print(json.dumps(plan(),indent=2))
    elif args.command=='clone':clone()
    elif args.command=='refresh':refresh()
    else:supplement(args.contract,args.day,args.attempt)

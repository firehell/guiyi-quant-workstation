"""Explicit foreground development model worker; reads existing completed observations."""
from datetime import UTC,datetime,date,timedelta
from pathlib import Path
import argparse,json,os,time,hashlib
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.private_settings import load_private_readonly_settings
from app.market_data.catalog import MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.observation_stream import ObservationStream,ObservationEnvelope,_text,DAILY_LIMIT
from app.market_data.aggregation import expected_intraday_ends
from guiyi_quant.subing_decision import _wire
from .store import ModelStore
from .pipeline import Pipeline

ROOT=Path(__file__).resolve().parents[4]
ACTIVE=ROOT/'.run/subing-model-active.json'
HEARTBEAT=ROOT/'.run/subing-model-heartbeat.json'
DB_PATH=ROOT/'.run/subing-model-database.url'
PRODUCTS='jm lc rb sa fg ma ec v pr ta ur sh sc cj'.split()

def validate_warmup_boundary(through,previous,cutoff,started):
    if through<previous:raise ValueError('WARMUP_NOT_CURRENT')
    if cutoff>started:raise ValueError('FUTURE_WARMUP')


def atomic(path,value):
    path.parent.mkdir(exist_ok=True)
    tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(_wire(value),f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def settings_and_redis():
    from redis import Redis
    settings,_=load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    url=settings.get('REDIS_URL','redis://127.0.0.1:6379/0')
    if url=='redis://127.0.0.1:6379/0':
        password=settings.get('REDIS_PASSWORD') or settings.get('POSTGRES_PASSWORD')
        if not password:raise ValueError('REDIS_SETTINGS_UNAVAILABLE')
        url='redis://:'+password+'@127.0.0.1:6379/0'
    return settings,Redis.from_url(url,socket_timeout=5,socket_connect_timeout=5)

def contexts(m,cat,day):
    result={}
    for product in PRODUCTS:
        calendar=cat.calendar_days(product,day-timedelta(days=14),day+timedelta(days=14))
        days=[d for d,open_day in calendar if open_day];i=days.index(day)
        if i==0 or i+1>=len(days):raise ValueError('CALENDAR_INSUFFICIENT')
        meta=m.historical_metadata_evidence(symbol=product,since=days[i-1],through=days[i+1])
        maps=cat.main_map(product,day,day)
        if len(maps)!=1:raise ValueError('OWNER_MAPPING_MISSING')
        ws=m.session_windows(symbol=product,trading_day=day);nextws=m.session_windows(symbol=product,trading_day=days[i+1])
        result[product]=dict(contract=maps[0].contract,previous=str(days[i-1]),first_open=min(w.start for w in ws).isoformat(),
            day_end=max(w.end for w in ws).isoformat(),next_open=min(w.start for w in nextws).isoformat(),sessions=[[w.start.isoformat(),w.end.isoformat()] for w in ws],
            **{'expected_'+f:[e.isoformat() for e in expected_intraday_ends(tuple(ws),f)] for f in ('1m','30m','60m')})
        if meta!=m.historical_metadata_evidence(symbol=product,since=days[i-1],through=days[i+1]):raise ValueError('METADATA_CHANGED')
    return result

def read_rows(stream,day,after='0-0'):
    tail=stream.tail(day)
    if after!='0-0' and not stream.redis.xrange(stream.key(day),min=after,max=after,count=1):raise ValueError('OBSERVATION_CURSOR_EXPIRED')
    if tail==after:return [],tail
    rows=stream.redis.xrange(stream.key(day),min='('+after,max=tail,count=DAILY_LIMIT+1)
    if len(rows)>DAILY_LIMIT:raise ValueError('OBSERVATION_READ_BUDGET')
    selected=[]
    for identifier,fields in rows:
        raw=fields.get(b'envelope',fields.get('envelope'));e=ObservationEnvelope.from_json(raw,stream_id=_text(identifier))
        parts=e.channel.split(':')
        if len(parts)!=4 or parts[:2]!=['live','bar'] or parts[2] not in PRODUCTS or parts[3] not in ('1m','30m','60m'):continue
        index=stream.redis.hget(stream.identity_key(day),e.observation_id)
        if not index or json.loads(index)['payload']!=_text(raw) or json.loads(index)['id']!=e.stream_id:raise ValueError('OBSERVATION_PROVENANCE_INVALID')
        if e.trading_day!=day or e.data['trading_day']!=str(day) or e.observation_id!=f"{day}:{e.data['contract']}:{parts[3]}:{e.data['bar_end']}":raise ValueError('OBSERVATION_IDENTITY_INVALID')
        if not e.notification_eligible or not e.confirmed_at or e.confirmed_at<datetime.fromisoformat(e.data['bar_end']) or e.source_observed_at>e.confirmed_at:raise ValueError('OBSERVATION_NOT_CONFIRMED')
        selected.append(json.loads(_text(raw)))
    selected.sort(key=lambda e:(e['data']['bar_end'],{'60m':0,'30m':1,'1m':2}[e['channel'].split(':')[-1]],e['channel']))
    return selected,tail

def facts_for(index,day):
    if not index or not index.exists():return None
    registry=json.loads(index.read_text());entry=registry.get(str(day))
    if not entry:return None
    path=Path(entry['path'])
    if not path.is_absolute() or path.is_symlink():raise ValueError('FACTS_PATH_INVALID')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('FACTS_HASH_INVALID')
    return json.loads(raw)

def code_hashes():
    files=[*sorted((ROOT/'packages/quant-core/guiyi_quant').glob('subing*.py')),*sorted((ROOT/'packages/quant-core/guiyi_quant/indicators').glob('*.py')),*sorted((ROOT/'packages/quant-core/guiyi_quant/paper').glob('*.py')),*sorted((ROOT/'packages/quant-core/guiyi_quant/new_subing').glob('*.py')),*sorted(Path(__file__).parent.glob('*.py'))]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--start',action='store_true');parser.add_argument('--check-start',action='store_true');parser.add_argument('--prepared',type=Path);parser.add_argument('--facts-index',type=Path,default=ROOT/'.run/subing-model-facts-index.json');parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if DB_PATH.is_symlink():raise ValueError('DATABASE_PATH_INVALID')
    store=ModelStore(DB_PATH.read_text());settings,redis=settings_and_redis();stream=ObservationStream(redis,kind='completed')
    sql=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    owner=store.engine.connect()
    if not owner.scalar(text('SELECT pg_try_advisory_lock(183047231)')):raise ValueError('MODEL_WORKER_ALREADY_RUNNING')
    def context(day):
        with Session(sql,autoflush=False) as db,readonly_transaction(db,timeout_seconds=120):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);cat=MarketCatalog(db,root);return contexts(MarketDataService(cat,CanonicalMonthlyStore(root)),cat,day)
    def daily_inputs(pipe,day):
        from .market import prefix
        updates={};proofs={};errors={}
        with Session(sql,autoflush=False) as db,readonly_transaction(db,timeout_seconds=180):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);cat=MarketCatalog(db,root);m=MarketDataService(cat,CanonicalMonthlyStore(root))
            for product in PRODUCTS:
                through=date.fromisoformat(ctx[product]['previous']);f=pipe.factors[product]
                last=f.trends['1d'].last_end
                if last is not None and last.date()>=through:continue
                try:
                    bars,proof=prefix(m,product,pipe.products[product]['contract'],'1d',through)
                    updates[product]=[_wire(__import__('dataclasses').asdict(b)) for b in bars if last is None or b.bar_end>last]
                    proofs[product]=proof
                except Exception as exc:errors[product]=getattr(exc,'code',None) or type(exc).__name__
        return updates,proofs,errors
    def validate_prepared(prepared,started):
        from app.market_data.domain import BarFrequency
        from app.market_data.new_subing_research import payload_hash
        with Session(sql,autoflush=False) as db,readonly_transaction(db,timeout_seconds=180):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);cat=MarketCatalog(db,root);m=MarketDataService(cat,CanonicalMonthlyStore(root))
            for product,p in prepared.items():
                through=date.fromisoformat(p['through']);cutoff=max(w.end for w in m.session_windows(symbol=product,trading_day=through))
                validate_warmup_boundary(through,date.fromisoformat(ctx[product]['previous']),cutoff,started)
                for freq,proof in p['sources'].items():
                    if payload_hash(p['warmup'][freq])!=proof['hash']:raise ValueError('WARMUP_HASH_INVALID')
                    if _wire(m.contract_source_evidence(symbol=product,contract=p['contract'],frequency=BarFrequency(freq),before=cutoff))!=proof['source']:raise ValueError('WARMUP_SOURCE_CHANGED')
    try:
        if args.start or args.check_start:
            if ACTIVE.exists():raise ValueError('MODEL_ALREADY_INITIALIZED')
            if not args.prepared:raise ValueError('PREPARED_REQUIRED')
            day=max(stream.days());ctx=context(day)
            prepared={};readiness={r['product']:r for r in json.loads((args.prepared/'readiness.json').read_text())}
            for product in PRODUCTS:
                p=json.loads((args.prepared/(product+'.json')).read_text());p['normalization_candidate']=readiness[product]['normalization_candidate'];prepared[product]=p
            bootstrap,tail=read_rows(stream,day)
            started=datetime.now(UTC)
            if any(datetime.fromisoformat(e['data']['bar_end'])>started or datetime.fromisoformat(e['confirmed_at'])>started for e in bootstrap):raise ValueError('FUTURE_BOOTSTRAP_OBSERVATION')
            validate_prepared(prepared,started)
            run_id='subing-dev-'+started.strftime('%Y%m%dT%H%M%S')
            identity=dict(run_id=run_id,started_at=started.isoformat(),prepared=prepared,bootstrap=bootstrap,contexts=ctx,cursor=tail,source_day=str(day),code_hashes=code_hashes(),execution_profile='next_completed_1m_close_slip1_actual_knowledge_v1')
            pipe=Pipeline(identity)
            if args.check_start:
                print(json.dumps(dict(status='START_PREFLIGHT_PASSED',products=len(pipe.products),bootstrap_rows=len(bootstrap),source_day=str(day),model_orders=0)));return
            store.create(run_id,identity,pipe.state());store.load(run_id)
            atomic(ACTIVE,dict(run_id=run_id,started_at=started,auto_order=False))
        else:
            run_id=json.loads(ACTIVE.read_text())['run_id'];r,events=store.load(run_id);identity=r['identity']
            if identity['code_hashes']!=code_hashes():raise ValueError('MODEL_CODE_IDENTITY_CHANGED')
            pipe=Pipeline(identity)
            for event in events:pipe.apply(event)
            if pipe.state()!=r['state']:raise ValueError('MODEL_RESTART_PARITY_FAILED')
        day=date.fromisoformat(pipe.source_day);ctx=context(day)
        daily_day=None;daily_pending={};daily_proofs={};daily_errors={}
        while True:
            if identity['code_hashes']!=code_hashes():raise ValueError('MODEL_CODE_IDENTITY_CHANGED')
            latest=max(stream.days())
            if latest>day and stream.tail(day)==pipe.source_cursor:
                if any(pipe.last.get((s,'1m'))!=datetime.fromisoformat(ctx[s]['day_end']) for s in PRODUCTS):raise ValueError('DAY_END_OBSERVATION_MISSING')
                day=latest;ctx=context(day);pipe.source_cursor='0-0'
            if daily_day!=day:
                daily_pending,daily_proofs,daily_errors=daily_inputs(pipe,day);daily_day=day
            rows,tail=read_rows(stream,day,pipe.source_cursor)
            if rows or tail!=pipe.source_cursor or str(day)!=pipe.source_day:
                now=datetime.now(UTC)
                if any(datetime.fromisoformat(e['confirmed_at'])>now for e in rows):raise ValueError('FUTURE_OBSERVATION')
                payload=dict(event_id=str(day)+':'+tail,observed_at=now.isoformat(),observations=rows,contexts=ctx,facts=facts_for(args.facts_index,day),daily_updates=daily_pending,daily_sources=daily_proofs,daily_errors=daily_errors,cursor=tail,source_day=str(day))
                sequence=pipe.sequence;pipe.apply(payload);payload['outcome']=pipe.last_outcome;store.append(run_id,payload,pipe.state(),sequence)
                daily_pending={};daily_proofs={}
            atomic(HEARTBEAT,dict(run_id=run_id,status='RUNNING',at=datetime.now(UTC),source_day=str(day),sequence=pipe.sequence))
            if args.once:return
            time.sleep(2)
    finally:owner.close();sql.dispose();store.engine.dispose();redis.close()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
    except Exception as exc:
        code=getattr(exc,'code',None) or (str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() and str(exc).isupper() else type(exc).__name__.upper())
        atomic(HEARTBEAT,dict(status='STOPPED',code=code,at=datetime.now(UTC)))
        print(json.dumps(dict(status='MODEL_STOPPED',code=code)));raise SystemExit(2) from None

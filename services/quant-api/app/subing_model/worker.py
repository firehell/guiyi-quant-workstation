"""Explicit foreground development model worker; reads existing completed observations."""
from datetime import UTC,datetime,timedelta
from pathlib import Path
import json
import os
import hashlib
from app.private_settings import load_private_readonly_settings
from app.market_data.observation_stream import ObservationEnvelope,_text,DAILY_LIMIT
from app.market_data.aggregation import expected_intraday_ends
from guiyi_quant.subing_decision import _wire

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
    raise SystemExit("SUBING_INDEPENDENT_MODEL_RETIRED_USE_SUBING_PORTFOLIO_WORKER")

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
    except Exception as exc:
        code=getattr(exc,'code',None) or (str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() and str(exc).isupper() else type(exc).__name__.upper())
        atomic(HEARTBEAT,dict(status='STOPPED',code=code,at=datetime.now(UTC)))
        print(json.dumps(dict(status='MODEL_STOPPED',code=code)));raise SystemExit(2) from None

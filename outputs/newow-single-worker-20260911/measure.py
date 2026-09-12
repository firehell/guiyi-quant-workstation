"""Five bounded real-data HTTP runs; output contains only public data and timings."""
import concurrent.futures as futures
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import httpx2 as httpx

OUT = Path('.run/single-worker')
BASE = 'http://127.0.0.1:8011'
PATH = '/api/v1/market/newow/strategy-detail'
PARAMS = {'product':'au','strategy':'trend','frequency':'1d','as_of':'2026-09-08T07:00:00.000001Z'}
BARS = {'symbol':'au','series_kind':'actual_dominant','frequency':'1d','limit':100,'before':PARAMS['as_of']}
report = {'cutoff':PARAMS['as_of'],'product':'au','chart_limit':100,'history_limit':2,
          'performance_since':'2023-01-01','performance_through':'2026-09-08',
          'os_disk_cache_cleared':False,'workers':1,'rounds':[]}
samples = []

def get(client,path,params):
    start=time.monotonic()
    r=client.get(BASE+path,params=params)
    elapsed=time.monotonic()-start
    if r.status_code != 200:
        raise RuntimeError(f'HTTP_{r.status_code}:{r.json().get("detail",{}).get("code")}')
    return r.json(), elapsed

def stable(body):
    # Token/navigation IDs and read time vary, business results must not.
    if isinstance(body,dict):
        return {k:stable(v) for k,v in body.items() if k not in {'snapshot_token','next_older_window','read_at','query_started_at','query_finished_at','actual_read_at'}}
    if isinstance(body,list):return [stable(x) for x in body]
    return body

def probe(kind,stop,round_id,phase):
    with httpx.Client(timeout=10,trust_env=False) as c:
        while not stop.is_set():
            start=time.monotonic()
            try:
                body,elapsed=get(c,'/health' if kind=='health' else '/api/v1/market/bars/page',{} if kind=='health' else BARS)
                status='ok'
            except Exception as exc:
                elapsed=time.monotonic()-start;status=type(exc).__name__
            samples.append({'kind':kind,'round':round_id,'phase':phase,'start':start,'end':time.monotonic(),'seconds':elapsed,'status':status})
            stop.wait(.02)

for round_id in range(5):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1',8011))
    trace_path=OUT/f'trace-{round_id}.json'
    process=subprocess.Popen([sys.executable,str(OUT/'serve.py'),'api',str(trace_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+20
        while True:
            if process.poll() is not None: raise RuntimeError('API_START_FAILED')
            try:
                with socket.create_connection(('127.0.0.1',8011),timeout=.2):break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('API_START_TIMEOUT')
                time.sleep(.05)
        with ExitStack() as stack:
            clients=[stack.enter_context(httpx.Client(timeout=120,trust_env=False)) for _ in range(4)]
            cold,tc=get(clients[0],PATH,{**PARAMS,'chart_limit':100})
            warm,tw=get(clients[1],PATH,{**PARAMS,'chart_limit':100})
            assert stable(cold)==stable(warm)
            token=cold['meta']['snapshot_token'];assert token and warm['meta']['snapshot_token']==token
            params={**PARAMS,'snapshot_token':token}
            refp={**params,'section':'reference','performance_since':'2023-01-01','performance_through':'2026-09-08','history_limit':2}
            stop=threading.Event()
            threads=[threading.Thread(target=probe,args=(kind,stop,round_id,'idle')) for kind in ['health','bars']]
            for t in threads:t.start()
            time.sleep(1)
            stop.set()
            for t in threads:t.join()
            stop=threading.Event()
            threads=[threading.Thread(target=probe,args=(kind,stop,round_id,'load')) for kind in ['health','bars']]
            for t in threads:t.start()
            try:
                reference,tr=get(clients[1],PATH,refp)
                reference_warm,trw=get(clients[2],PATH,refp)
                assert stable(reference)==stable(reference_warm)
                comp,tcold=get(clients[2],PATH,{**params,'section':'comparator'})
                compw,tcompw=get(clients[3],PATH,{**params,'section':'comparator'})
                assert stable(comp)==stable(compw)
            finally:
                stop.set()
                for t in threads:t.join()
            rv=reference['reference']['value'];assert rv['next_before'] and len(rv['items'])==2
            assert (rv['performance_since'],rv['performance_through'])==('2023-01-01','2026-09-08')
            # Four concurrent connections, distinct operations sharing one token.
            operations=[(clients[0],{**params,'section':'auxiliary','component':'macd'}),
                        (clients[1],{**refp,'history_before':rv['next_before']}),
                        (clients[2],{**params,'chart_limit':100,'chart_older_window':cold['chart']['value']['next_older_window']}),
                        (clients[3],{**params,'from':'2026-08-01','through':'2026-09-08','chart_limit':10})]
            with futures.ThreadPoolExecutor(max_workers=4) as pool:
                results=list(pool.map(lambda op:get(op[0],PATH,op[1])[0],operations))
            for result in results:assert result['meta']['snapshot_token']==token
            refpage=results[1]['reference']['value'];assert refpage['summary']==rv['summary']
            assert {i['reference_trade_id'] for i in rv['items']}.isdisjoint(i['reference_trade_id'] for i in refpage['items'])
            assert results[2]['chart']['value']['chart_through'] < cold['chart']['value']['chart_from']
            loc=results[3]['chart']['value'];assert loc['next_before']
            page,_=get(clients[0],PATH,{**operations[3][1],'chart_before':loc['next_before']})
            assert page['meta']['snapshot_token']==token
            assert {b['bar_end'] for b in page['chart']['value']['bars']}.isdisjoint(b['bar_end'] for b in loc['bars'])
            if round_id:
                old=clients[0].get(BASE+PATH,params={**PARAMS,'snapshot_token':previous_token})
                assert old.status_code==409
            previous_token=token
            report['rounds'].append({'pid':process.pid,'cold_chart_s':tc,'warm_chart_s':tw,'cold_reference_s':tr,'warm_reference_s':trw,'cold_comparator_s':tcold,'warm_comparator_s':tcompw,'chart_input_sha256':cold['meta']['input_content_sha256'],'reference_input_sha256':rv['reference_input_sha256'],'reference_count':rv['summary']['closed_count'],'interleaved_connections':4,'chain_passed':True})
            print('round',round_id+1,'passed',flush=True)
    finally:
        process.send_signal(signal.SIGINT)
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait();raise RuntimeError('API_STOP_TIMEOUT')
    OUT.joinpath('progress.json').write_text(json.dumps(report,indent=2))
    OUT.joinpath('samples-progress.json').write_text(json.dumps(samples))

intervals=[]
for trace_path in OUT.glob('trace-[0-4].json'):
    intervals += [t for t in json.loads(trace_path.read_text()) if t['section'] in ['reference','comparator']]
for sample in samples:
    sample['heavy_overlap']=any(sample['start']<t['end'] and sample['end']>t['start'] for t in intervals)
report['latency']={}
for kind in ['health','bars']:
    for phase in ['idle','load']:
        chosen=[s for s in samples if s['kind']==kind and s['phase']==phase and (phase=='idle' or s['heavy_overlap'])]
        values=sorted(s['seconds'] for s in chosen)
        assert values
        report['latency'][kind+'_'+phase]={'count':len(values),'p95_s':values[math.ceil(.95*len(values))-1],'max_s':max(values),'errors':sum(s['status']!='ok' for s in chosen)}
report['passed']=all(report['latency'][kind+'_load']['count']>=100 and report['latency'][kind+'_load']['p95_s']<=budget and report['latency'][kind+'_load']['errors']==0 for kind,budget in [('health',1),('bars',3)])
OUT.joinpath('samples.json').write_text(json.dumps(samples))
OUT.joinpath('http-acceptance.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report['latency'],indent=2),flush=True)
assert report['passed']

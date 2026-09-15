import json,time,datetime,urllib.request,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
OUT=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/market-home-latency-20260914')
def get(path):
 t=time.perf_counter();r={'path':path,'checked_at':datetime.datetime.now().astimezone().isoformat()}
 try:
  with urllib.request.urlopen('http://127.0.0.1:8000'+path,timeout=60) as f:r.update(status=f.status,body=json.load(f))
 except urllib.error.HTTPError as e:r.update(status=e.code,body=json.load(e))
 except Exception as e:r.update(status='failed',error_type=type(e).__name__)
 r['seconds']=time.perf_counter()-t
 print(json.dumps({'path':path,'status':r['status'],'seconds':r['seconds']}),flush=True);return r
with ThreadPoolExecutor(max_workers=2) as pool:
 heavy=pool.submit(get,'/api/v1/market/research/home-overview')
 time.sleep(0.3)
 rows=[get('/health'),get('/api/v1/market/dominants'),heavy.result()]
(OUT/'http-current.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))

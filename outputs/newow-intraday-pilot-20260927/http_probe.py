import json, subprocess
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from time import monotonic
from pathlib import Path
params={'product':'rb','strategy':'trend','frequency':'1m','section':'reference','as_of':'2026-09-24T07:00:00.000001+00:00'}
rows=[]
for stage in ('base','fusion','fusion_page'):
    start=monotonic()
    try:
        with urlopen('http://127.0.0.1:8011/api/v1/market/newow/strategy-detail?'+urlencode(params),timeout=120) as response:
            result=json.load(response)
        value=result['reference']['value']
        row={'stage':stage,'status':'PASS','seconds':round(monotonic()-start,3),'snapshot':result['meta']['snapshot_token'],'curve_count':len(value.get('curve_trades',[])),'has_fusion':'fusion_comparison' in value}; rows.append(row); print(json.dumps(row),flush=True)
        if stage=='fusion':
            cursor=value['fusion_comparison']['next_cursor']
            print(json.dumps({'fusion_cursor_length':len(cursor) if cursor else 0}),flush=True)
            if cursor:params['fusion_before']=cursor
        if stage=='base':
            params.update(include_fusion='true',performance_since=value['performance_since'],performance_through=value['performance_through'])
            if result['meta']['snapshot_token']:params['snapshot_token']=result['meta']['snapshot_token']
    except HTTPError as error:
        body=json.load(error)
        print(json.dumps({'stage':stage,'status':error.code,'code':body.get('detail',{}).get('code'),'seconds':round(monotonic()-start,3)}),flush=True);break
    except Exception as error:
        print(json.dumps({'stage':stage,'status':'FAILED','code':type(error).__name__}),flush=True);break

Path('outputs/newow-intraday-pilot-20260927/http-readback-final.json').write_text(json.dumps({'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'cutoff':params['as_of'],'status':'PASS' if len(rows)==3 else 'FAILED','rows':rows},indent=2)+'\n')

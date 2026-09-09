import json,hashlib
from pathlib import Path
from datetime import datetime,timedelta
from decimal import Decimal as D
from collections import Counter,defaultdict
from bisect import bisect_right,bisect_left
from zoneinfo import ZoneInfo
P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/01a07f08-100c-7e63-a568-e88df19d2b3d/2026-09-09')
OLD=Path('/Users/zhangzhao/.codex/visualizations/2026/09/08/01a07f08-100c-7e63-a568-e88df19d2b3d/outputs/push-review-close/analysis.json')
source=json.loads((P/'source.json').read_text());market=json.loads((P/'market.json').read_text());prev=json.loads(OLD.read_text());old={r['id']:r for r in prev['records']};SH=ZoneInfo('Asia/Shanghai')
def dt(s):return datetime.fromisoformat(s)
def local(s):return dt(s).astimezone(SH).strftime('%Y-%m-%d %H:%M:%S') if s else None
formula=json.loads((P/'formula.json').read_text()) if (P/'formula.json').exists() else {}
delivery_evidence=json.loads((P/'delivery_evidence.json').read_text()) if (P/'delivery_evidence.json').exists() else {}
records=[];changes=[];new_mature=[]
for ev in source['events']:
 r=ev.copy();r['strategy']='苏冰' if ev['strategy']=='苏冰预警' else ev['strategy'];r['side']=1 if r['result_codes']==['buy'] else -1 if r['result_codes']==['sell'] else None
 r['direction']='多头' if r['side']==1 else '空头' if r['side']==-1 else '方向冲突'
 r['send_local']=local(r['notification_attempted_at']);r['send_date']=r['send_local'][:10] if r['send_local'] else None;r['signal_local']=local(r['bar_end'])
 r['lag_seconds']=(dt(r['notification_attempted_at'])-dt(r['bar_end'])).total_seconds() if r['notification_attempted_at'] else None
 r['cohort']='当日新增' if r['trading_day']==source['today'] else '此前已有' if r['id'] in old else '周初夜盘补入'
 r['sender_status']=old.get(r['id'],{}).get('sender_status','逐条结果未留存')
 status=source['runtime_status']
 if r['notification_attempted_at'] and status.get('last_provider_accepted_at') and dt(r['notification_attempted_at'])==dt(status['last_provider_accepted_at']):r['sender_status']='provider_accepted'
 if r['notification_attempted_at'] and status.get('last_notification_failure_at') and dt(r['notification_attempted_at'])==dt(status['last_notification_failure_at']):r['sender_status']='transport_failed'
 if str(r['id']) in delivery_evidence:
  evidence=delivery_evidence[str(r['id'])]
  assert r['contract']==evidence['contract'] and r['bar_end']==evidence['bar_end'],'DELIVERY_EVIDENCE_IDENTITY_MISMATCH'
  r['sender_status']=evidence['label']
 r['formula_status']=formula.get(str(r['id']),{}).get('status','前次复算一致，本次未重算' if r['id'] in old else '本次未复算')
 m=market[r['contract']];times=[dt(t) for t,d in m['expected']];bars={dt(b['bar_end']):b for b in m['bars']}
 signal=bars.get(dt(r['bar_end']));r['signal_close']=signal['close'] if signal else None
 anchor_i=bisect_right(times,dt(r['notification_attempted_at'])) if r['notification_attempted_at'] else len(times)
 anchor_t=times[anchor_i] if anchor_i<len(times) else None;anchor=bars.get(anchor_t)
 r['anchor_time']=anchor_t.isoformat() if anchor_t else None;r['anchor_local']=local(r['anchor_time']);r['anchor_close']=anchor['close'] if anchor else None
 for h in [15,30,60]:
  k=str(h);r['end_'+k]=r['close_'+k]=r['return_'+k]=r['hit_'+k]=r['signal_return_'+k]=None
  if not r['notification_attempted_at']:st='无发送尝试时间'
  elif r['side'] is None:st='方向冲突'
  elif not times:st='数据不足'
  elif anchor_i+h>=len(times):st='待观察'
  elif any(t not in bars for t in times[anchor_i:anchor_i+h+1]):st='数据不足'
  else:
   st='可评估';target=times[anchor_i+h];close=bars[target]['close'];ret=D(r['side'])*(D(close)/D(anchor['close'])-1)
   r['end_'+k]=target.isoformat();r['close_'+k]=close;r['return_'+k]=str(ret);r['hit_'+k]=int(ret>0)
  r['status_'+k]=st
  si=bisect_left(times,dt(r['bar_end']))
  if signal and si<len(times) and times[si]==dt(r['bar_end']) and si+h<len(times) and all(t in bars for t in times[si:si+h+1]) and r['side']:
   r['signal_return_'+k]=str(D(r['side'])*(D(bars[times[si+h]]['close'])/D(signal['close'])-1))
  if r['id'] in old:
   oldr=old[r['id']];oval=oldr['return_'+k];nval=r['return_'+k]
   if oval is None and nval is not None:new_mature.append({'id':r['id'],'horizon':h,'return':nval})
   elif oval is not None and (nval is None or D(oval)!=D(nval)):changes.append({'id':r['id'],'horizon':h,'previous':oval,'current':nval})
 r['mfe60']=r['mae60']=None
 if r['return_60'] is not None:
  future=[bars[t] for t in times[anchor_i+1:anchor_i+61]];base=D(anchor['close']);side=D(r['side'])
  favorable=[side*(D(b['high'] if side>0 else b['low'])/base-1) for b in future];adverse=[side*(D(b['low'] if side>0 else b['high'])/base-1) for b in future]
  r['mfe60']=str(max([D(0)]+favorable));r['mae60']=str(min([D(0)]+adverse))
 records.append(r)
assert set(old)<=set(r['id'] for r in records)
for r in records:
 if r['id'] in old:
  for k in ['contract','bar_end','trading_day','rule_code','frequency','result_codes','notification_attempted_at']:
   assert r[k]==old[r['id']][k],f'EVENT_FACT_CHANGED {r["id"]} {k}'
def summarize(key,rs):
 out={'key':key,'count':len(rs),'buy':sum(r['side']==1 for r in rs),'sell':sum(r['side']==-1 for r in rs),'formula_match':sum(r['formula_status']=='当前输入复算一致' for r in rs)}
 for h in [15,30,60]:
  k=str(h);v=[D(r['return_'+k]) for r in rs if r['return_'+k] is not None];n=len(v);win=sum(x>0 for x in v)
  out.update({'n'+k:n,'win'+k:win,'loss'+k:sum(x<0 for x in v),'flat'+k:sum(x==0 for x in v),'pending'+k:sum(r['status_'+k]=='待观察' for r in rs),'missing'+k:sum(r['status_'+k] not in ('待观察','可评估') for r in rs),'hit'+k:win/n if n else None,'avg'+k:float(sum(v)/n) if n else None})
 return out
def group(rs,key):
 g=defaultdict(list)
 for r in rs:g[key(r)].append(r)
 return [summarize(k,g[k]) for k in sorted(g)]
today=[r for r in records if r['trading_day']==source['today']]
a={'cutoff':source['cutoff'],'today':source['today'],'week_start':source['week_start'],'records':records,'total':summarize('本周累计',records),'today_total':summarize('当日',today),'strategy_summary':group(records,lambda r:f"{r['strategy']} {r['frequency']}"),'today_strategy_summary':group(today,lambda r:f"{r['strategy']} {r['frequency']}"),'product_summary':group(records,lambda r:f"{r['strategy']} {r['frequency']} {r['product_name']} {r['symbol'].upper()}"),'today_product_summary':group(today,lambda r:f"{r['strategy']} {r['frequency']} {r['product_name']} {r['symbol'].upper()}"),'day_summary':group(records,lambda r:f"{r['trading_day']} {r['strategy']} {r['frequency']}"),'direction_summary':group(records,lambda r:f"{r['strategy']} {r['frequency']} {r['direction']}"),'today_direction_summary':group(today,lambda r:f"{r['strategy']} {r['frequency']} {r['direction']}"),'cohort_summary':group(records,lambda r:f"{r['cohort']} {r['strategy']} {r['frequency']}"),'delivery_counts':dict(Counter(r['sender_status'] for r in records)),'formula_counts':dict(Counter(r['formula_status'] for r in records)),'unique_products':len({r['symbol'] for r in records}),'today_products':len({r['symbol'] for r in today}),'minute_count':sum(len(m['bars']) for m in market.values()),'new_mature':new_mature,'revisions':changes,'previous_pending_now':[r for r in records if r['id'] in old and old[r['id']]['return_60'] is None],'source_sha256':{f:hashlib.sha256((P/f).read_bytes()).hexdigest() for f in ['source.json','market.json']}}
(P/'analysis.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
for k in ['today_total','total','today_strategy_summary','today_direction_summary','strategy_summary','delivery_counts','formula_counts','revisions']:print(k,json.dumps(a[k],ensure_ascii=False))
print('new_mature',len(new_mature),'previouspending60',[(r['id'],r['return_60']) for r in a['previous_pending_now']])

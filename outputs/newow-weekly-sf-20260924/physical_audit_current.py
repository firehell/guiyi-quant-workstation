import sys,json,re,collections,subprocess
from pathlib import Path
from datetime import datetime,date
from decimal import Decimal
R=Path('/Volumes/扩展盘/guiyi-quant-workstation');P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-sf-20260924')
sys.path[:0]=[str(R/'services/quant-api'),str(R/'packages/quant-core')]
from dotenv import load_dotenv
load_dotenv(Path.home()/'Library/Application Support/GuiyiQuant/project.env',override=True)
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.market_data.domain import DatasetKey,DatasetKind,BarFrequency
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.rqdata_adapter import _aggregate_daily_rows
from app.market_data.newow.product_reader import _is_strict_no_trade_fact
BASE=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining10-20260924');old=json.loads((BASE/'readiness-full.json').read_text())
ps=('sf',);cut=datetime.fromisoformat(old['as_of']);targets={}
for d in old['dependencies']:
 if d['symbol'] in ps:
  k=(d['symbol'],d['contract']);targets[k]=max(d['through'],targets.get(k,''))
out=[];fields=('open','high','low','close','volume','turnover','open_interest')
def encodebar(b):return {k:str(getattr(b,k)) for k in fields}
try:
 with SessionLocal() as s,readonly_transaction(s,timeout_seconds=1800):
  rev=catalog_revision(s,ps,cut.date(),('1d','1w'));m=build_market_data_service(s)
  for i,((symbol,contract),through) in enumerate(targets.items()):
   row={'symbol':symbol,'contract':contract,'through':through,'issues':[]}
   try:
    we=m.expected_contract_replay_endpoints(symbol=symbol,contract=contract,frequency=BarFrequency.W1,trading_day=date.fromisoformat(through),cutoff=cut)
    owners=[o for z in old['dependencies'] if z['symbol']==symbol and z['contract']==contract for o in z['owners']]
    owned=[(e,d) for e,d in we if any(date.fromisoformat(o['since'])<=d<=date.fromisoformat(o['through']) for o in owners)]
    row['owners']=owners
    if not owned:row['status']='NO_OWNED_COMPLETED_WEEK';out.append(row);continue
    we=tuple((e,d) for e,d in we if e<=owned[-1][0])
    end,day=we[-1];de=m.expected_contract_replay_endpoints(symbol=symbol,contract=contract,frequency=BarFrequency.D1,trading_day=day,cutoff=end)
    daily=[];facts=[];weekly=[];lineage=[]
    for freq in [BarFrequency.D1,BarFrequency.W1]:
     key=DatasetKey(DatasetKind.CONTRACT,symbol,contract,freq)
     for part in m.catalog.all_partitions(key):
      expected=de if freq==BarFrequency.D1 else we
      if (part.year,part.month) not in {(d.year,d.month) for _,d in expected}:continue
      lineage.append({'frequency':freq.value,'year':part.year,'month':part.month,'file':part.file_path.name,'quality_sha256':part.source_quality_sha256})
      if freq==BarFrequency.D1:
       bars,qs=m.store.read_catalog_partition_quality(part);daily.extend(b for b in bars if b.bar_end<=end);facts.extend(q for q in qs if q.bar_end<=end)
      else:weekly.extend(b for b in m.store.read_catalog_partition(part) if b.bar_end<=end)
    actual={(b.bar_end,b.trading_day) for b in daily}|{(q.bar_end,q.trading_day) for q in facts}
    missing=[{'bar_end':str(e),'trading_day':str(d)} for e,d in de if (e,d) not in actual]
    row.update(daily_missing=missing,daily_bar_count=len(daily),quality_fact_count=len(facts),weekly_bar_count=len(weekly),lineage=lineage)
    wb={b.bar_end:b for b in weekly}
    for e,d in we:
     iso=d.isocalendar()[:2];ds=sorted([b for b in daily if b.trading_day.isocalendar()[:2]==iso],key=lambda b:b.trading_day);qs=[q for q in facts if q.trading_day.isocalendar()[:2]==iso];exp=[(a,b) for a,b in de if b.isocalendar()[:2]==iso];present={(b.bar_end,b.trading_day) for b in ds}|{(q.bar_end,q.trading_day) for q in qs};stored=wb.get(e)
     issue={'week_end':str(d),'stored_weekly':stored is not None,'pre_first_owner':d<min(date.fromisoformat(o['since']) for o in owners)}
     if set(exp)!=present:
      issue.update(kind='D1_ENDPOINT_GAP',missing_days=[str(b) for a,b in exp if (a,b) not in present])
     elif qs:
      issue.update(kind='QUALITY_FACT_WITH_STORED_W1' if stored else 'PROVEN_QUALITY_INTERRUPTION',stored_values=encodebar(stored) if stored else None,quality_facts=[{'day':str(q.trading_day),'classification':q.classification} for q in qs])
     else:
      values=tuple((b.trading_day,{k:getattr(b,k) for k in fields}) for b in ds);expected=_aggregate_daily_rows(values,bar_end=e)
      if stored is None:issue.update(kind='W1_MISSING_D1_COMPLETE',no_trade_days=[str(b.trading_day) for b in ds if _is_strict_no_trade_fact(b)],daily_count=len(ds),missing_week_type='ALL_NO_TRADE' if all(_is_strict_no_trade_fact(b) for b in ds) else 'MIXED_NO_TRADE' if any(_is_strict_no_trade_fact(b) for b in ds) else 'NORMAL')
      else:
       changed=[k for k in fields if getattr(stored,k)!=getattr(expected,k)]
       if not changed:continue
       nt=[str(b.trading_day) for b in ds if _is_strict_no_trade_fact(b)]
       oldvals={'open':ds[0].open,'high':max(b.high for b in ds),'low':min(b.low for b in ds),'close':ds[-1].close}
       isold=all(getattr(stored,k)==(oldvals[k] if k in oldvals else getattr(expected,k)) for k in fields)
       issue.update(kind='STRICT_NO_TRADE_AGGREGATION' if nt and isold else 'D1_W1_VALUE_CONFLICT',fields=changed,strict_no_trade_days=nt,stored=encodebar(stored),expected=encodebar(expected))
     row['issues'].append(issue)
    row['status']='SCANNED'
   except Exception as ex:
    code=getattr(ex,'code',None) or str(ex);row.update(status='SCAN_BLOCKED',error_type=type(ex).__name__,error_code=code if re.fullmatch('[A-Z][A-Z0-9_]{2,100}',str(code)) else 'REDACTED')
   out.append(row)
   if (i+1)%20==0:print(json.dumps({'scanned':i+1,'total':len(targets)}),flush=True)
  after=catalog_revision(s,ps,cut.date(),('1d','1w'))
 with SessionLocal() as s,readonly_transaction(s,timeout_seconds=60):fresh=catalog_revision(s,ps,cut.date(),('1d','1w'))
 result={'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=R).strip(),'as_of':str(cut),'products':ps,'scope':'contracts enumerated by 20260923 fixed-cutoff prior native audit, maximum owner through per contract','catalog_revision':rev,'revision_stable':rev==after==fresh,'readonly':True,'provider_requests':0,'writes':0,'contracts':out}
 (P/'physical-causes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
 print(json.dumps({'total':len(out),'statuses':dict(collections.Counter(x['status'] for x in out)),'stable':rev==after==fresh}),flush=True)
except Exception as ex:print(json.dumps({'error_type':type(ex).__name__}),flush=True);sys.exit(1)

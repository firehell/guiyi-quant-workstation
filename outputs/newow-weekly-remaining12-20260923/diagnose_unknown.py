import json,sys,re,os
from pathlib import Path
from datetime import datetime,date
ROOT=Path('/private/tmp/guiyi-w1-r12-audit-20260923/code');P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining12-20260923')
sys.path[:0]=[str(ROOT/'services/quant-api'),str(ROOT/'packages/quant-core')]
from dotenv import load_dotenv
load_dotenv(Path.home()/'Library/Application Support/GuiyiQuant/project.env',override=True)
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.domain import ResolvedContractSegment
from app.market_data.newow.product_reader import NewowProductReader
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.product_identity import InputQualityPolicy
r=json.loads((P/'readiness-full.json').read_text());asof=datetime.fromisoformat(r['as_of']);ps=tuple(r['audit_identity']['products']);out=[]
try:
 with SessionLocal() as s, readonly_transaction(s,timeout_seconds=600):
  rev=catalog_revision(s,ps,asof.date(),('1d','1w'))
  if rev!=r['audit_identity']['catalog_revision_before']:raise ValueError('REVISION_CHANGED')
  reader=NewowProductReader(build_market_data_service(s),coverage=DatabaseCoverageSource(s,ROOT/'data/universe/product_window_starts.csv',now=lambda:asof),active_products=ps,now=lambda:asof,input_quality_policy=InputQualityPolicy.WEEKLY_V2)
  seen=set()
  for d in r['dependencies']:
   if d['status']!='UNKNOWN':continue
   key=(d['symbol'],d['contract'],d['through'])
   if key in seen:continue
   seen.add(key);o=d['owners'][0];row={'symbol':d['symbol'],'contract':d['contract'],'through':d['through'],'owner':o}
   try:row['result']=reader.check_dependency(d['symbol'],ProductFrequency.WEEKLY,ResolvedContractSegment(d['contract'],date.fromisoformat(o['since']),date.fromisoformat(o['through'])),datetime.fromisoformat(d['as_of']))
   except Exception as e:
    code=getattr(e,'code',None) or str(e)
    row['error_type']=type(e).__name__;row['error_code']=code if re.fullmatch('[A-Z][A-Z0-9_]{2,100}',str(code)) else 'REDACTED_NON_CODE_MESSAGE'
    tb=e.__traceback__;frames=[]
    while tb:
     frames.append({'file':Path(tb.tb_frame.f_code.co_filename).name,'function':tb.tb_frame.f_code.co_name,'line':tb.tb_lineno});tb=tb.tb_next
    row['code_frames']=frames
   out.append(row)
   print(json.dumps({k:v for k,v in row.items() if k!='code_frames'}),flush=True)
 result={'catalog_revision':rev,'rows':out,'readonly':True,'provider_requests':0,'writes':0}
 (P/'unknown-diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
except Exception as e:print(json.dumps({'error_type':type(e).__name__}));sys.exit(1)

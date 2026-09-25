import json,sys,re
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,date
ROOT=Path('/private/tmp/guiyi-w1-r12-audit-20260923/code');P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining12-20260923')
sys.path[:0]=[str(ROOT/'services/quant-api'),str(ROOT/'packages/quant-core')]
from dotenv import load_dotenv
load_dotenv(Path.home()/'Library/Application Support/GuiyiQuant/project.env',override=True)
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.historical_data_manager import ContractWarmupPlanner,ContractWarmupRequest
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.diagnostics import INTEGRITY_REASONS
r=json.loads((P/'readiness-full.json').read_text());v=json.loads((P/'v2-dependency-diagnosis.json').read_text());asof=datetime.fromisoformat(r['as_of']);ps=tuple(r['audit_identity']['products']);out=[];targets={}
for d in v['rows']:
 if d['original_status']=='UNKNOWN' and d.get('error_code')=='CONTRACT_REPLAY_COVERAGE_UNAVAILABLE':
  k=(d['symbol'],d['contract']);targets[k]=max(d['through'],targets.get(k,''))
try:
 with SessionLocal() as s, readonly_transaction(s,timeout_seconds=900):
  rev=catalog_revision(s,ps,asof.date(),('1d','1w'))
  if rev!=r['audit_identity']['catalog_revision_before']:raise ValueError('REVISION_CHANGED')
  m=build_market_data_service(s);planner=ContractWarmupPlanner(catalog=m.catalog,store=m.store,coverage=DatabaseCoverageSource(s,ROOT/'data/universe/product_window_starts.csv',now=lambda:asof))
  for (symbol,contract),through in targets.items():
   row={'symbol':symbol,'contract':contract,'through':through,'frequency':'1w','origin':'v2-supplement'}
   try:
    plan=asdict(planner.plan(ContractWarmupRequest(symbol=symbol,contract=contract,through=date.fromisoformat(through),frequency='1w')))
    row.update(plan);reasons={c for d in plan['scope_diagnostics'] for c in d['reason_codes']}
    row['status']='REVIEW_REQUIRED' if reasons & (INTEGRITY_REASONS|{'SOURCE_NONPOSITIVE_PRICE','WEEKLY_DAILY_VALUE_CONFLICT'}) else 'PROPOSED'
    row['scope_reason_codes']=sorted(reasons)
   except Exception as e:
    code=getattr(e,'code',None) or str(e);row.update(status='PLANNER_BLOCKED',error_type=type(e).__name__,error_code=code if re.fullmatch('[A-Z][A-Z0-9_]{2,100}',str(code)) else 'REDACTED_NON_CODE_MESSAGE')
   out.append(row)
  after=catalog_revision(s,ps,asof.date(),('1d','1w'))
 with SessionLocal() as s, readonly_transaction(s,timeout_seconds=60):fresh=catalog_revision(s,ps,asof.date(),('1d','1w'))
 result={'code_sha':r['audit_identity']['code_sha'],'catalog_revision':rev,'catalog_revision_stable':rev==after==fresh,'rows':out,'readonly':True,'provider_requests':0,'writes':0}
 (P/'supplemental-repair-plans.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n');print(json.dumps({'count':len(out),'stable':rev==after==fresh}),flush=True)
except Exception as e:print(json.dumps({'error_type':type(e).__name__}));sys.exit(1)

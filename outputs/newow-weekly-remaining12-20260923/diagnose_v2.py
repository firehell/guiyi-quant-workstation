import json,sys,re
from pathlib import Path
from datetime import datetime,date
ROOT=Path('/private/tmp/guiyi-w1-r12-audit-20260923/code');P=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining12-20260923')
sys.path[:0]=[str(ROOT/'services/quant-api'),str(ROOT/'packages/quant-core')]
from dotenv import load_dotenv
load_dotenv(Path.home()/'Library/Application Support/GuiyiQuant/project.env',override=True)
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.market_data.domain import BarFrequency
from app.market_data.weekly_quality import WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.newow.public_errors import public_product_error
r=json.loads((P/'readiness-full.json').read_text());asof=datetime.fromisoformat(r['as_of']);ps=tuple(r['audit_identity']['products']);out=[]
try:
 with SessionLocal() as s, readonly_transaction(s,timeout_seconds=900):
  rev=catalog_revision(s,ps,asof.date(),('1d','1w'))
  if rev!=r['audit_identity']['catalog_revision_before']:raise ValueError('REVISION_CHANGED')
  market=build_market_data_service(s);seen=set()
  for d in r['dependencies']:
   if d['status'] in ('DATA_READY','NOT_APPLICABLE'):continue
   key=(d['symbol'],d['contract'],d['through'])
   if key in seen:continue
   seen.add(key);o=d['owners'][0];row={'symbol':d['symbol'],'contract':d['contract'],'through':d['through'],'owner':o,'original_status':d['status']}
   try:
    expected=market.expected_contract_replay_endpoints(symbol=d['symbol'],contract=d['contract'],frequency=BarFrequency.W1,trading_day=date.fromisoformat(d['through']),cutoff=datetime.fromisoformat(d['as_of']))
    owned=[p for p in expected if date.fromisoformat(o['since'])<=p[1]<=date.fromisoformat(o['through'])]
    bars,gaps=market.query_contract_weekly_replay_quality(symbol=d['symbol'],contract=d['contract'],through=owned[-1][1],cutoff=owned[-1][0],classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
    actual={b.bar_end for b in bars}|{g.week_end for g in gaps};missing=sorted({e for e,_ in expected}-actual)
    row.update(status='V2_QUALITY_COVERED' if not missing else 'REPLAY_ENDPOINTS_MISSING',bar_count=len(bars),quality_gap_count=len(gaps),quality_gap_week_ends=[str(g.week_end) for g in gaps],missing_week_ends=[str(e) for e in missing])
   except Exception as e:
    code=getattr(e,'code',None) or str(e)
    row.update(status='BLOCKED',error_type=type(e).__name__,error_code=code if re.fullmatch('[A-Z][A-Z0-9_]{2,100}',str(code)) else 'REDACTED_NON_CODE_MESSAGE',public_error=public_product_error(e))
   out.append(row)
  after=catalog_revision(s,ps,asof.date(),('1d','1w'))
 result={'code_sha':r['audit_identity']['code_sha'],'catalog_revision':rev,'catalog_revision_stable':rev==after,'classification_version':WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2,'rows':out,'readonly':True,'provider_requests':0,'writes':0}
 (P/'v2-dependency-diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
 print(json.dumps({'completed':len(out),'stable':rev==after}),flush=True)
except Exception as e:print(json.dumps({'error_type':type(e).__name__}));sys.exit(1)

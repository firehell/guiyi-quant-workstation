import json, os, sys, hashlib, time
from pathlib import Path
from datetime import datetime, UTC
ROOT=Path('/Volumes/扩展盘/guiyi-quant-workstation')
OUT=Path('/Volumes/扩展盘/guiyi-quant-workstation/outputs/newow-weekly-remaining10-20260924')
sys.path[:0]=[str(ROOT/'services/quant-api'),str(ROOT/'packages/quant-core')]
from dotenv import load_dotenv
load_dotenv(Path.home()/'Library/Application Support/GuiyiQuant/project.env', override=True)
os.environ['PYTHONDONTWRITEBYTECODE']='1'
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service, canonical_root
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.newow.readiness_composition import build_newow_readiness
from app.market_data.newow.readiness import ReadinessRequest
from guiyi_quant.newow.product_contracts import ProductFrequency
PRODUCTS=('pf','pk','pl','pr','px','rs','sf','sh','sm','sr')
SHA='55454558629734aff0856d02692c1d4242500980'
def save(name,x):
    (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def main():
    from datetime import date
    started=datetime.now(UTC)
    ident={'code_sha':SHA,'products':PRODUCTS,'started_at':started.isoformat(),'readonly':True,'provider_requests':0,'writes':0,'canonical_root_sha256':hashlib.sha256(str(canonical_root().resolve()).encode()).hexdigest()}
    with SessionLocal() as session, readonly_transaction(session,timeout_seconds=3600):
        market=build_market_data_service(session)
        weeks={p:market.completed_calendar_week(symbol=p,week_monday=date(2026,9,14),as_of=started) for p in PRODUCTS}
        if any(v is None for v in weeks.values()) or len({str(v) for v in weeks.values()})!=1:
            save('cutoff-blocked.json',weeks);raise ValueError('COMPLETE_WEEK_NOT_COMMON')
        cutoff=next(iter(weeks.values()))[1]
        ident.update(complete_week=weeks,as_of=cutoff.isoformat())
        before=catalog_revision(session,PRODUCTS,cutoff.date(),('1d','1w'))
        ident['catalog_revision_before']=before
        save('audit-identity.json',ident)
        print(json.dumps({'phase':'audit_started','as_of':str(cutoff),'revision':before}),flush=True)
        report=build_newow_readiness(session,request=ReadinessRequest(products=PRODUCTS,as_of=cutoff,matrix=True,max_work=100000,timeout_seconds=3300,frequencies=(ProductFrequency.WEEKLY,),candidate_weekly=True))
        ident['catalog_revision_after']=catalog_revision(session,PRODUCTS,cutoff.date(),('1d','1w'))
        ident['catalog_revision_stable']=before==ident['catalog_revision_after']
        report['audit_identity']=ident
        save('readiness-full.json',report)
    with SessionLocal() as session, readonly_transaction(session,timeout_seconds=60):
        ident['catalog_revision_fresh_after']=catalog_revision(session,PRODUCTS,cutoff.date(),('1d','1w'))
    ident['fresh_revision_unchanged']=before==ident['catalog_revision_fresh_after']
    ident['finished_at']=datetime.now(UTC).isoformat()
    save('audit-identity.json',ident)
    print(json.dumps({'phase':'finished','status':report['status'],'budget_exhausted':report['budget_exhausted'],'fresh_revision_unchanged':ident['fresh_revision_unchanged']}),flush=True)
try:
    main()
except Exception as exc:
    save('runner-error.json',{'error_type':type(exc).__name__,'provider_requests':0,'writes':0})
    print(json.dumps({'status':'blocked','error_type':type(exc).__name__}),flush=True)
    sys.exit(1)

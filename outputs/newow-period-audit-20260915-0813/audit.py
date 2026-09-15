"""Native provider-free dependency checks; deliberately no repair planner/apply."""
from pathlib import Path
from datetime import datetime, UTC
from collections import Counter
import json, os, sys, time

ROOT = Path('/Volumes/扩展盘/guiyi-quant-workstation')
OUT = ROOT / 'outputs/newow-period-audit-20260915-0813'
sys.path[:0] = [str(ROOT), str(ROOT/'services/quant-api'), str(ROOT/'packages/quant-core')]

def main():
    from scripts.newow_weekly_recovery import load_private_execution_settings
    settings, identity = load_private_execution_settings(Path('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env'))
    os.environ['GUIYI_CANONICAL_DATA_ROOT'] = settings['GUIYI_CANONICAL_DATA_ROOT']
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.url import normalize_database_url
    from app.db.readonly import readonly_transaction
    from app.core.env import PROJECT_ROOT
    from app.market_data.composition import build_market_data_service
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.market_data.operational_universe import load_active_products, load_operational_products
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.readiness import ReadinessRequest, AuditBudget, NewowReadinessAudit
    from guiyi_quant.newow.product_contracts import ProductFrequency
    OUT.mkdir(exist_ok=False)
    as_of = datetime.now(UTC)
    symbols = load_operational_products()
    assert len(symbols) == len(set(symbols)) == 60
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), pool_pre_ping=True, connect_args={'connect_timeout':10})
    summary = {'as_of':as_of.isoformat(),'started_at':as_of.isoformat(),'identity':identity,'provider_requests':0,'writes':0,'repair_planning':False,'scope':'native chart/auxiliary/reference dependency checks; deferred explanation excluded','products':[]}
    started = time.monotonic()
    try:
        for symbol in symbols:
            with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=240):
                request = ReadinessRequest(products=(symbol,),as_of=as_of,matrix=False,max_work=10000,timeout_seconds=240,frequencies=(ProductFrequency.WEEKLY,ProductFrequency.DAILY,ProductFrequency.HOURLY))
                budget = AuditBudget(request,time.monotonic)
                market = build_market_data_service(session)
                coverage = DatabaseCoverageSource(session,PROJECT_ROOT/'data/universe/product_window_starts.csv',now=lambda:as_of)
                reader = NewowProductReader(market,coverage=coverage,active_products=load_active_products(),context_frequencies=(),now=lambda:as_of,cancelled=budget.expired)
                report = NewowReadinessAudit(reader=reader,plan=None,budget=budget).run(request)
            (OUT/f'{symbol}.json').write_text(json.dumps(report,ensure_ascii=False,default=str))
            item={'symbol':symbol,'periods':{},'elapsed_seconds':round(time.monotonic()-started,2)}
            for freq in ('1w','1d','60m'):
                deps=[d for d in report['dependencies'] if d['frequency']==freq]
                enums=[d for d in report['enumerations'] if d['frequency']==freq and d['section']!='explanation']
                bad=[d for d in deps if d['status'] not in ('DATA_READY','NOT_APPLICABLE')]
                enums_ok=len(enums)==3 and all(d['status']=='ENUMERATED' for d in enums)
                item['periods'][freq]={'input_complete':bool(deps) and not bad and enums_ok and not report['budget_exhausted'],'dependency_count':len(deps),'enumeration_complete':enums_ok,'budget_exhausted':report['budget_exhausted'],'failed_dependencies':len(bad),'affected_contracts':sorted({d['contract'] for d in bad}),'reasons':dict(Counter(d.get('reason') or d['status'] for d in bad))}
            summary['products'].append(item)
            (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
            print(json.dumps(item,ensure_ascii=False),flush=True)
    finally:
        engine.dispose()
        summary['finished_at']=datetime.now(UTC).isoformat()
        (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if len(summary['products'])==60 else 2

if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__,'code':'READONLY_AUDIT_FAILED'}),flush=True)
        sys.exit(1)

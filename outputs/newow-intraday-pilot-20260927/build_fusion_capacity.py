import os, json, resource, argparse
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from time import monotonic
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from scripts.newow_weekly_recovery import load_private_readonly_settings
from app.db.session import normalize_database_url
from app.db.base import Base
from app.market_data.composition import build_market_data_service, build_database_coverage_source, canonical_root
from app.market_data.catalog import MarketCatalog
from app.market_data.newow.product_reader import NewowProductReader
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.planning import HistoricalReferencePlanner, HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget, plan_to_dict
from app.reference_trading.service import HistoricalReferenceService
from app.reference_trading.models import REFERENCE_TABLES
from app.reference_trading.query import HistoricalReferenceQuery
from app.reference_trading.newow_fusion import SavedFusionSources
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductStrategy, ProductFrequency
from guiyi_quant.newow.product_identity import REFERENCE_MODEL_VERSION, futures_adaptation_version
from guiyi_quant.reference_trading import StreamIdentity
from contextlib import contextmanager
parser=argparse.ArgumentParser(); parser.add_argument('--frequency', choices=('1m','15m','30m','60m'), required=True); args=parser.parse_args()
settings,config=load_private_readonly_settings(Path('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env')); os.environ.update(settings)
engine=create_engine(normalize_database_url(settings['DATABASE_URL']))
schema='newow_intraday_pilot_20260927'
cutoff=datetime.fromisoformat('2026-09-24T07:00:00.000001+00:00')
root=Path('outputs/newow-intraday-pilot-20260927'); frequency=args.frequency; prefix='fusion-'+frequency
try:
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS "newow_intraday_pilot_20260927"')
    scoped=engine.execution_options(schema_translate_map={None:schema})
    Base.metadata.create_all(scoped,tables=[Base.metadata.tables[name] for name in REFERENCE_TABLES])
    factory=sessionmaker(scoped,expire_on_commit=False)
    repository=ReferenceRepository(factory)
    with Session(engine) as session:
        catalog=MarketCatalog(session,canonical_root())
        @contextmanager
        def guard():
            lease=catalog.acquire_maintenance_lock()
            if lease is None: raise ValueError('SOURCE_BUSY')
            try: yield
            finally: lease.release()
        newow=NewowProductReader(build_market_data_service(session),coverage=build_database_coverage_source(session),active_products=('rb',),now=lambda:cutoff)
        reader=MarketDataHistoricalInputReader(newow_reader=newow,subing_service=None,read_guard=guard,pin_verified_inputs=True,compact_intraday_inputs=True,fusion_sources=SavedFusionSources(factory))
        identity=build_fusion_stream_identity('rb',frequency)
        streams=[HistoricalStreamRequest(identity,date(2023,1,1),date(2026,9,24),cutoff)]
        request=HistoricalReferenceRequest('build',tuple(streams),WorkBudget(2,4_000_000,900,16_000_000_000),batch_size=256)
        started=monotonic(); plan=HistoricalReferencePlanner(reader,repository=repository).plan(request)
        (root/f'{prefix}-build-plan.json').write_text(json.dumps(plan_to_dict(plan),indent=2,default=str)+'\n')
        print(json.dumps({'stage':'planned','frequency':frequency,'plan_seconds':round(monotonic()-started,3),'counts':[item.input_count for item in plan.streams]}),flush=True)
        def after_batch(stage,context):
            token=context.get('resume_token')
            if token:
                target=root/f'{prefix}-resume.json'; temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(asdict(token),indent=2)+'\n');temporary.replace(target)
        service=HistoricalReferenceService(repository,reader,after_batch=after_batch)
        built_at=monotonic(); report=service.execute(plan,plan.plan_hash)
        result={'schema':'intraday_reference_build_capacity_v1','frequency':frequency,'config_identity':config,'isolated_schema':schema,'plan_hash':plan.plan_hash,'plan_seconds':round(built_at-started,3),'build_seconds':round(monotonic()-built_at,3),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'report':asdict(report),'queries':[]}
        query=HistoricalReferenceQuery(factory)
        for stream_report in report.streams:
            if stream_report.status!='completed': continue
            began=monotonic();page=query.trades(stream_report.stream_id,since=date(2025,9,25),through=date(2026,9,24),cutoff=cutoff,limit=200)
            page_seconds=monotonic()-began
            began=monotonic();summary=query.summary(stream_report.stream_id,since=date(2025,9,25),through=date(2026,9,24),cutoff=cutoff,snapshot_token=page['snapshot'])
            result['queries'].append({'stream_id':stream_report.stream_id,'page_seconds':round(page_seconds,3),'summary_seconds':round(monotonic()-began,3),'page_items':len(page['items']),'has_more':page['next_cursor'] is not None,'summary':summary})
        (root/f'{prefix}-build-capacity.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
        print(json.dumps({'stage':report.status,'frequency':frequency,'build_seconds':result['build_seconds'],'peak_rss_bytes':result['peak_rss_bytes'],'reasons':[item.reason for item in report.streams]}),flush=True)
        if report.status!='completed': raise SystemExit(2)
except Exception as error:
    print(json.dumps({'status':'FAILED','code':getattr(error,'code',type(error).__name__)}),flush=True);raise SystemExit(1)

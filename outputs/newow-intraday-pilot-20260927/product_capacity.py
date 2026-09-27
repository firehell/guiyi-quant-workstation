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
from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
from app.reference_trading.persisted_newow import PersistedNewowReference
scoped=engine.execution_options(schema_translate_map={None:schema});factory=sessionmaker(scoped,expire_on_commit=False)
try:
    with Session(engine) as session:
        market=build_market_data_service(session);coverage=build_database_coverage_source(session)
        def reader_factory(context,cancelled):
            return NewowProductReader(market,coverage=coverage,active_products=('rb',),context_frequencies=context,cancelled=cancelled,now=lambda:cutoff)
        service=NewowProductService(reader_factory,persisted_reference=PersistedNewowReference(factory).section)
        result=[]
        for section in ('chart','reference'):
            request=ProductServiceQuery(product='rb',strategy='trend',frequency=frequency,section=section,as_of=cutoff,chart_limit=500,history_limit=200 if section=='reference' else 50,performance_since=date(2025,9,25) if section=='reference' else None,performance_through=date(2026,9,24) if section=='reference' else None)
            began=monotonic();value=service.query(request);elapsed=monotonic()-began
            print(json.dumps({'section':section,'seconds':round(elapsed,3),'status':'PASS'}),flush=True)
            result.append({'section':section,'seconds':round(elapsed,3),'status':'PASS'})
        (root/f'{frequency}-product-capacity.json').write_text(json.dumps(result,indent=2)+'\n')
except Exception as error:
    print(json.dumps({'status':'FAILED','code':getattr(error,'code',str(error) if str(error).replace('_','').isupper() and len(str(error))<100 else type(error).__name__)}),flush=True);raise SystemExit(1)

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
from app.reference_trading.newow_fusion import PersistedFusionComparison
from app.schemas.market_newow_product import FusionComparisonOut
scoped=engine.execution_options(schema_translate_map={None:schema})
factory=sessionmaker(scoped,expire_on_commit=False)
try:
    with Session(engine) as session:
        reader=NewowProductReader(build_market_data_service(session),coverage=build_database_coverage_source(session),active_products=('rb',),now=lambda:cutoff)
        query=PersistedFusionComparison(factory)
        for name in ('summary','trades','presentation_facts','complete_trades'):
            original=getattr(query._query,name)
            def measured(*values,_method=original,_name=name,**options):
                began=monotonic();print(json.dumps({'stage':_name,'state':'begin'}),flush=True)
                result=_method(*values,**options)
                print(json.dumps({'stage':_name,'state':'end','seconds':round(monotonic()-began,3)}),flush=True);return result
            setattr(query._query,name,measured)
        started=monotonic()
        result=query.comparison(product='rb',frequency=frequency,since=date(2023,1,1),through=date(2026,9,24),cutoff=cutoff,reader=reader)
        FusionComparisonOut.model_validate(result)
        elapsed=monotonic()-started
        rows=list(result['items']); cursor=result['next_cursor']; seen={item['reference_trade_id'] for item in rows}
        pages=1
        if cursor:
            second=query.comparison(product='rb',frequency=frequency,since=date(2023,1,1),through=date(2026,9,24),cutoff=cutoff,reader=reader,cursor=cursor)
            if result['reference_revision']!=second['reference_revision'] or result['curve']!=second['curve']: raise ValueError('FUSION_PAGE_SNAPSHOT_CONFLICT')
            if seen.intersection(item['reference_trade_id'] for item in second['items']): raise ValueError('FUSION_PAGE_DUPLICATION')
            pages+=1
        from decimal import Decimal
        from decimal import localcontext
        with localcontext() as decimal_context:
            decimal_context.prec=60
            total=sum((Decimal(item['reference_return_pct']) for item in result['curve']),Decimal(0))
        print(json.dumps({'check':'curve_summary','curve_count':len(result['curve']),'closed_count':result['summary']['closed_count'],'sum':str(total),'expected':result['summary']['sum_return_percentage_points']}),flush=True)
        if len(result['curve'])!=result['summary']['closed_count'] or total!=Decimal(result['summary']['sum_return_percentage_points']): raise ValueError('FUSION_CURVE_SUMMARY_CONFLICT')
        evidence={'status':'PASS','frequency':frequency,'read_seconds':round(elapsed,3),'curve_count':len(result['curve']),'groups':result['groups'],'record_count':len(rows),'pages_verified':pages,'has_more':bool(cursor),'reference_revision':result['reference_revision'],'record_since':result['record_since'],'input_sha256':result['reference_input_sha256']}
        (root/f'{prefix}-query-readback.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence),flush=True)
except Exception as error:
    print(json.dumps({'status':'FAILED','sqlstate':getattr(getattr(error,'orig',None),'sqlstate',None) or getattr(getattr(error,'orig',None),'pgcode',None),'code':getattr(error,'code',str(error) if str(error).replace('_','').isupper() and len(str(error))<100 else type(error).__name__)}),flush=True);raise SystemExit(1)

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
settings,config=load_private_readonly_settings(Path('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env')); os.environ.update(settings)
engine=create_engine(normalize_database_url(settings['DATABASE_URL']))
schema='newow_intraday_pilot_20260927'
cutoff=datetime.fromisoformat('2026-09-24T07:00:00.000001+00:00')

from app.preview import create_preview_app
from app.api import market_newow
import uvicorn
os.environ['GUIYI_CANDIDATE_PREVIEW']='1'
os.environ['GUIYI_PREVIEW_AS_OF']=cutoff.isoformat()
os.environ['GUIYI_PREVIEW_CANDIDATE_ORIGIN']='http://127.0.0.1:8011'
os.environ['GUIYI_INTRADAY_PREVIEW_PRODUCT']='rb'
os.environ['REFERENCE_TRADING_READER_MODE']='persisted'
scoped=engine.execution_options(schema_translate_map={None:schema})
market_newow.SessionLocal=sessionmaker(scoped,expire_on_commit=False)
app=create_preview_app(enabled=True,as_of=cutoff.isoformat(),session_factory=sessionmaker(engine,expire_on_commit=False))
uvicorn.run(app,host='127.0.0.1',port=8011,log_level='warning',access_log=False)

import os,json
from datetime import date
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from scripts.newow_weekly_recovery import load_private_readonly_settings
from app.db.session import normalize_database_url
from app.db.readonly import readonly_transaction
from app.market_data.composition import build_market_data_service
from app.market_data.domain import ActualDominantTradingDayQuery,BarFrequency
from app.market_data.aggregation import aggregate_from_1m,expected_intraday_ends
settings,config=load_private_readonly_settings(Path('/Users/zhangzhao/Library/Application Support/GuiyiQuant/project.env'));os.environ.update(settings)
engine=create_engine(normalize_database_url(settings['DATABASE_URL']))

from app.market_data.composition import build_database_coverage_source
with Session(engine) as session, readonly_transaction(session):
    market=build_market_data_service(session)
    fact=market.catalog.contract_fact('pd','PD2612')
    floor=build_database_coverage_source(session).product_start('pd')
    print(json.dumps({'pd_contract_listed':fact.listed_date.isoformat(),'pd_maintained_start':floor.isoformat()}))

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
day=date(2025,11,27); rows=[]
try:
    with Session(engine) as session,readonly_transaction(session,timeout_seconds=300):
        market=build_market_data_service(session)
        for product in ('pd',):
            sessions=market.session_windows(symbol=product,trading_day=day)
            source=market.query_actual_dominant_trading_days(ActualDominantTradingDayQuery(product,BarFrequency.M1,day,day))
            for frequency in ('1m','15m','30m','60m'):
                expected=expected_intraday_ends(sessions,frequency)
                result=source if frequency=='1m' else market.query_actual_dominant_trading_days(ActualDominantTradingDayQuery(product,BarFrequency(frequency),day,day))
                actual=result.bars
                same_ends=tuple(bar.bar_end for bar in actual)==expected
                rebuilt=source.bars if frequency=='1m' else aggregate_from_1m(source.bars,target_frequency=frequency,sessions=sessions)
                parity=rebuilt==actual
                row={'product':product,'frequency':frequency,'day':day.isoformat(),'bar_count':len(actual),'expected_count':len(expected),'session_endpoint_parity':same_ends,'canonical_1m_aggregate_parity':parity,'physical_contracts':[owner.contract for owner in result.resolved_contract_segments],'sessions':[[item.start.isoformat(),item.end.isoformat()] for item in sessions],'first_bar_end':actual[0].bar_end.isoformat() if actual else None,'last_bar_end':actual[-1].bar_end.isoformat() if actual else None,'status':'PASS' if same_ends and parity else 'FAILED'}
                rows.append(row);print(json.dumps({k:row[k] for k in ('product','frequency','bar_count','status')}),flush=True)
    Path('outputs/newow-intraday-pilot-20260927/boundary-listing-readback.json').write_text(json.dumps({'schema':'intraday_boundary_readback_v1','config_identity':config,'rows':rows},indent=2,default=str)+'\n')
    if any(row['status']!='PASS' for row in rows):raise SystemExit(2)
except Exception as error:
    print(json.dumps({'status':'FAILED','code':getattr(error,'code',type(error).__name__)}),flush=True);raise SystemExit(1)

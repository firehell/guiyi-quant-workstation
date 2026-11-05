"""Read-only MDS snapshot for a bounded demand-adapter check. No downloads."""
from pathlib import Path
from datetime import date
from dataclasses import asdict
import json

ROOT=Path(__file__).resolve().parents[2]
def main():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.private_settings import load_private_readonly_settings
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.market_data.domain import BarFrequency,ContractTradingDayQuery
    from app.market_data.new_subing_research import validate_series,payload_hash
    from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
    settings,_=load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    start,end=date(2025,11,17),date(2025,11,24);contract='JM2601'
    try:
        with Session(engine,autoflush=False) as session,readonly_transaction(session,timeout_seconds=120):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT']);m=MarketDataService(MarketCatalog(session,root),CanonicalMonthlyStore(root))
            owners=ActualDominantResearchSegmentLoader(m).owner_segments(symbol='jm',since=start,through=end)
            if not owners or any(x.contract!=contract for x in owners):raise ValueError('OWNER_CONFLICT')
            meta=m.historical_metadata_evidence(symbol='jm',since=date(2025,11,14),through=date(2025,11,28))
            days=[date.fromisoformat(x[0]) for x in meta['calendar'] if x[1]]
            periods={d:tuple(m.session_windows(symbol='jm',trading_day=d)) for d in days}
            cutoff=max(w.end for w in periods[end]);freq=BarFrequency.M1
            proof=m.contract_source_evidence(symbol='jm',contract=contract,frequency=freq,before=cutoff)
            expected=m.expected_contract_replay_endpoints(symbol='jm',contract=contract,frequency=freq,trading_day=end,cutoff=cutoff,since=start)
            result=m.query_contract_trading_days(ContractTradingDayQuery('jm',contract,freq,start,end))
            validate_series(result,product='jm',contract=contract,frequency=freq,expected=expected)
            if proof!=m.contract_source_evidence(symbol='jm',contract=contract,frequency=freq,before=cutoff):raise ValueError('SOURCE_CHANGED')
            if meta!=m.historical_metadata_evidence(symbol='jm',since=date(2025,11,14),through=date(2025,11,28)):raise ValueError('METADATA_CHANGED')
            schedule={d.isoformat():dict(previous=days[i-1].isoformat(),first_open=min(w.start for w in periods[d]),day_end=max(w.end for w in periods[d]),next_open=min(w.start for w in periods[days[i+1]])) for i,d in enumerate(days) if start<=d<=end}
            bars=[asdict(b) for b in result.bars]
            output=dict(contract=contract,bars=bars,schedule=schedule,source=proof,metadata=meta,bars_hash=payload_hash(bars))
    finally:engine.dispose()
    out=ROOT/'output/subing-demand-adapter-20261104';out.mkdir(exist_ok=True)
    (out/'market.json').write_text(json.dumps(output,default=str,ensure_ascii=False)+'\n')
    print(json.dumps(dict(status='READ_ONLY_VALIDATED',bars=len(bars),days=len(schedule),contract=contract)))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Do not print infrastructure exception strings or private settings.
        print(json.dumps({'status':'SNAPSHOT_FAILED','error_type':type(exc).__name__}));raise SystemExit(2) from None

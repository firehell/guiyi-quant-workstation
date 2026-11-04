"""Bounded read-only input load and candidate-owned account feedback comparison."""
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
import json,hashlib,argparse
CODE_ROOT=Path(__file__).resolve().parents[2]
CODE_PATHS=[*sorted((CODE_ROOT/'packages/quant-core/guiyi_quant').glob('subing*.py')),Path(__file__).resolve(),CODE_ROOT/'scripts/research/subing_account.py',CODE_ROOT/'scripts/research/subing_trend.py']
CODE_HASHES={str(p.relative_to(CODE_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE_PATHS}
from guiyi_quant.subing_demand_account_candidate import build_engine,VERSION
from subing_account import load
from guiyi_quant import subing_account as baseline_engine
from guiyi_quant.subing_decision import REGIME_PROFILE
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since',type=date.fromisoformat,default=date(2025,11,17))
    parser.add_argument('--through',type=date.fromisoformat,default=date(2025,11,24))
    parser.add_argument('--contract',default='JM2601')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.since>args.through:raise ValueError('WINDOW_INVALID')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.private_settings import load_private_readonly_settings
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    facts_path=ROOT/'output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json'
    facts_bytes=facts_path.read_bytes();facts=json.loads(facts_bytes)
    settings,_=load_private_readonly_settings(Path.home()/'Library/Application Support/GuiyiQuant/project.env')
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    try:
        with Session(engine,autoflush=False) as session,readonly_transaction(session,timeout_seconds=180):
            root=Path(settings['GUIYI_CANONICAL_DATA_ROOT'])
            market=MarketDataService(MarketCatalog(session,root),CanonicalMonthlyStore(root))
            segments,evidence=load(market,facts,args.since,args.through,include_range=True)
            assert len(segments)==1 and segments[0]['contract']==args.contract
            meta=market.historical_metadata_evidence(symbol='jm',since=args.since-timedelta(days=14),through=args.through+timedelta(days=14))
            days=[date.fromisoformat(x[0]) for x in meta['calendar'] if x[1]]
            periods={d:market.session_windows(symbol='jm',trading_day=d) for d in days}
            schedule={str(d):dict(previous=str(days[i-1]),first_open=min(w.start for w in periods[d]).isoformat(),day_end=max(w.end for w in periods[d]).isoformat(),next_open=min(w.start for w in periods[days[i+1]]).isoformat()) for i,d in enumerate(days) if args.since<=d<=args.through}
            assert meta==market.historical_metadata_evidence(symbol='jm',since=args.since-timedelta(days=14),through=args.through+timedelta(days=14))
            for day,cal in schedule.items():
                ws=market.session_windows(symbol='jm',trading_day=date.fromisoformat(day))
                assert min(w.start for w in ws).isoformat()==__import__('datetime').datetime.fromisoformat(cal['first_open']).isoformat()
                assert max(w.end for w in ws).isoformat()==__import__('datetime').datetime.fromisoformat(cal['day_end']).isoformat()
    finally:engine.dispose()
    assert facts_path.read_bytes()==facts_bytes
    s=segments[0]
    from scripts.research.subing_trend import load as load_factors
    from guiyi_quant.subing_recent_structure import State,Bar,step
    from decimal import Decimal
    from datetime import datetime
    # Reload through the same authoritative loader, including physical warmup.
    engine=create_engine(normalize_database_url(settings['DATABASE_URL']),connect_args={'connect_timeout':5})
    try:
        with Session(engine,autoflush=False) as session,readonly_transaction(session,timeout_seconds=180):
            market=MarketDataService(MarketCatalog(session,root),CanonicalMonthlyStore(root))
            factors=load_factors(market,args.since,args.through,include_joint=True,include_range=True)
            if factors['input_hash']!=evidence['factors_input_hash']:raise ValueError('FACTOR_SOURCE_CHANGED')
            from app.market_data.domain import BarFrequency,ContractTradingDayQuery
            from app.market_data.new_subing_research import validate_series
            from guiyi_quant.indicators.subing_trend import initial_state,step as trend_step
            cutoff=max(x.bar.bar_end for x in s['executions'])
            hourly_source=market.contract_source_evidence(symbol='jm',contract=args.contract,frequency=BarFrequency.H1,before=cutoff)
            expected=market.expected_contract_replay_endpoints(symbol='jm',contract=args.contract,frequency=BarFrequency.H1,trading_day=args.through,cutoff=cutoff)
            if not expected:raise ValueError('HOURLY_INPUT_EMPTY')
            hourly=market.query_contract_trading_days(ContractTradingDayQuery('jm',args.contract,BarFrequency.H1,expected[0][1],args.through))
            validate_series(hourly,product='jm',contract=args.contract,frequency=BarFrequency.H1,expected=expected)
            hstate=initial_state(args.contract,'60m');hour_points={}
            for b in hourly.bars:
                hstate,hpoint=trend_step(hstate,contract=args.contract,frequency='60m',bar_end=b.bar_end,high=float(b.high),low=float(b.low),close=float(b.close))
                hour_points[b.bar_end.isoformat()]=dict(at=b.bar_end.isoformat(),direction=hpoint.direction)
            if hourly_source!=market.contract_source_evidence(symbol='jm',contract=args.contract,frequency=BarFrequency.H1,before=cutoff):raise ValueError('HOURLY_SOURCE_CHANGED')
    finally:engine.dispose()
    state=State(args.contract);points={};chart=[]
    for row in factors['rows']:
        if row['contract']!=args.contract or row['frequency']!='30m':continue
        at=datetime.fromisoformat(row['time'])
        state,point=step(state,Bar(at,*(Decimal(str(row[k])) for k in ('high','low','close'))),contract=args.contract)
        point=json.loads(json.dumps(point,default=str))
        point['base_regime']=row['range_factor']['regime']
        points[row['time']]=point
        chart.append(dict(at=row['time'],close=str(row['close']),**point))
    first=s['executions'][0].bar.bar_end.isoformat()
    prior_points=[v for k,v in points.items() if k<first]
    prior_hours=[v for k,v in hour_points.items() if k<first]
    structures={};latest=prior_points[-1] if prior_points else None;hour_latest=prior_hours[-1] if prior_hours else None
    for x in s['executions']:
        at=x.bar.bar_end.isoformat()
        if at in points:latest=points[at]
        if at in hour_points:hour_latest=hour_points[at]
        structures[at]=dict(latest or {},hourly=hour_latest)
    module,Candidate,context=build_engine(s['executions'],schedule,structures=structures)
    old_module,OldCandidate,_=build_engine(s['executions'],schedule)
    results={};model_version='subing_unified_demand_candidate_v1'
    for name,eng in [('baseline',baseline_engine),('previous_candidate',old_module),('candidate',module)]:
        run_id=f'demand-feedback:{args.contract}:{args.since}:{args.through}:{name}:{context[:12]}'
        result=eng.replay(s['executions'],s['observations'],run_id=run_id,execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
        if name!='baseline':
            Current=Candidate if name=='candidate' else OldCandidate
            result['execution_engine_version']=result['version'];result['version']=model_version if name=='candidate' else VERSION
            model=Current.restore(result['decision_checkpoint']);assert model.state()==result['decision_state']
            # A mid-journal restart must reproduce all later acknowledgements,
            # not just the final state or observed demands.
            events=result['decision_checkpoint']['events'];cut=len(events)//2
            head=Current(args.contract,run_id,regime_research_profile=REGIME_PROFILE)
            for e in events[:cut]:head.apply(e)
            resumed=Current.restore(head.checkpoint())
            for e in events[cut:]:assert resumed.apply(e)==model.results[e['event_id']]
            assert resumed.observer.checkpoint()==model.observer.checkpoint()
            result['demand_observations']=model.demands
            if name=='candidate':chain=model.chain
            assert all(__import__('datetime').datetime.fromisoformat(f['fill_at'])>__import__('datetime').datetime.fromisoformat(f['decision_at']) for f in result['fills'])
        results[name]=result
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    record=dict(kind='SEEN_BOUNDED_CANDIDATE_ACCOUNT_REPLAY',context_hash=context,evidence=evidence,facts_sha256=hashlib.sha256(facts_bytes).hexdigest(),results=results)
    (out/'replay.json').write_text(json.dumps(record,default=str,ensure_ascii=False)+'\n')
    summary={k:dict(summary=v['summary'],fills=len(v['fills']),exit_reasons=dict(Counter(reason for f in v['fills'] if f['action']=='CLOSE' for reason in f['reasons']))) for k,v in results.items()}
    summary['verification']=dict(candidate_decision_restore=True,candidate_observer_restore=True,strict_later_fills=True)
    (out/'summary.json').write_text(json.dumps(summary,default=str,ensure_ascii=False,indent=2)+'\n')
    packet=dict(version=model_version,product='jm',contract=args.contract,since=str(args.since),through=str(args.through),
        context_hash=context,input_snapshot_hash=evidence['factors_input_hash'],execution_facts_hash=record['facts_sha256'],
        mode='HISTORICAL_CANDIDATE',oos_status='NOT_PROVEN',initial_cash='100000',summary=summary,
        chart=chart,chain=chain,fills=results['candidate']['fills'])
    if CODE_HASHES!={str(p.relative_to(CODE_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE_PATHS}:raise ValueError('SOURCE_CODE_CHANGED')
    packet['code_hashes']=CODE_HASHES
    packet['hourly_source']=hourly_source
    raw=json.dumps(packet,default=str,ensure_ascii=False,separators=(',',':')).encode()
    key=hashlib.sha256(raw).hexdigest();(out/(key+'.json')).write_bytes(raw)
    (out/'index.json').write_text(json.dumps([dict(id=key,sha256=key,contract=args.contract,since=str(args.since),through=str(args.through))]))
    print(json.dumps(summary,default=str,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='REPLAY_FAILED',error_type=type(exc).__name__)));raise SystemExit(2) from None

"""Bounded read-only input load and candidate-owned account feedback comparison."""
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
import json,hashlib,argparse
from subing_demand_account_candidate import build_engine,VERSION,EXIT_ONLY_VERSION
from subing_account import load
from guiyi_quant import subing_account as baseline_engine
from guiyi_quant.subing_decision import REGIME_PROFILE
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since',type=date.fromisoformat,default=date(2025,11,17))
    parser.add_argument('--through',type=date.fromisoformat,default=date(2025,11,24))
    parser.add_argument('--contract',default='JM2601')
    parser.add_argument('--output',type=Path,default=ROOT/'output/subing-demand-account-20261104')
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
    s=segments[0];module,Candidate,context=build_engine(s['executions'],schedule)
    exit_module,ExitCandidate,exit_context=build_engine(s['executions'],schedule,gate_first_entry=False)
    results={}
    for name,eng in [('baseline',baseline_engine),('candidate',module),('exit_only',exit_module)]:
        run_id=f'demand-feedback:{args.contract}:{args.since}:{args.through}:{name}:{context[:12]}'
        result=eng.replay(s['executions'],s['observations'],run_id=run_id,execution_model='theoretical_open',regime_research_profile=REGIME_PROFILE)
        if name!='baseline':
            Current=Candidate if name=='candidate' else ExitCandidate
            result['execution_engine_version']=result['version'];result['version']=VERSION if name=='candidate' else EXIT_ONLY_VERSION
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
            assert all(__import__('datetime').datetime.fromisoformat(f['fill_at'])>__import__('datetime').datetime.fromisoformat(f['decision_at']) for f in result['fills'])
        results[name]=result
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    record=dict(kind='SEEN_BOUNDED_CANDIDATE_ACCOUNT_REPLAY',context_hash=context,evidence=evidence,facts_sha256=hashlib.sha256(facts_bytes).hexdigest(),results=results)
    (out/'replay.json').write_text(json.dumps(record,default=str,ensure_ascii=False)+'\n')
    summary={k:dict(summary=v['summary'],fills=len(v['fills']),exit_reasons=dict(Counter(reason for f in v['fills'] if f['action']=='CLOSE' for reason in f['reasons']))) for k,v in results.items()}
    summary['verification']=dict(candidate_decision_restore=True,candidate_observer_restore=True,strict_later_fills=True)
    (out/'summary.json').write_text(json.dumps(summary,default=str,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,default=str,ensure_ascii=False))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(status='REPLAY_FAILED',error_type=type(exc).__name__)));raise SystemExit(2) from None

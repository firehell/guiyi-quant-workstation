"""Timing-only observer on immutable baseline fills, NOT a candidate account PnL replay."""
from pathlib import Path
from datetime import datetime,timedelta
from bisect import bisect_right,bisect_left
from collections import Counter
import hashlib,json
from subing_demand_observer import Observer

ROOT=Path(__file__).resolve().parents[2]
def dt(s):return datetime.fromisoformat(s)

def main():
    out=ROOT/'output/subing-demand-adapter-20261104'
    market_path=out/'market.json';baseline_path=ROOT/'output/subing-regime-add-20261103-001/JM2601-candidate-slip1.json'
    envpath=ROOT/'output/subing-regime-add-20261103-001/JM2601-environment.json'
    factpath=ROOT/'output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json'
    market=json.loads(market_path.read_text());baseline=json.loads(baseline_path.read_text())['result']
    expected=next(x['result_sha256'] for x in json.loads((baseline_path.parent/'summary.json').read_text()) if x['contract']=='JM2601' and x['variant']=='candidate' and x['slip']==1)
    assert hashlib.sha256(baseline_path.read_bytes()).hexdigest()==expected
    instrument=json.loads(factpath.read_text())['contracts']['JM2601']['instrument']
    assert instrument['order_book_id']=='JM2601';multiplier=instrument['contract_multiplier']
    env=sorted([r for r in json.loads(envpath.read_text()) if r['frequency']=='30m'],key=lambda r:dt(r['time']))
    envtimes=[dt(r['time']) for r in env]
    fills=sorted(baseline['fills'],key=lambda f:dt(f['fill_at']));layers={};idx=0;position_id=None
    def position_before(t):
        nonlocal idx,position_id
        # Strictly earlier archived model fills only. No next-minute price/fill
        # at this completed-bar boundary can leak into the position snapshot.
        while idx<len(fills) and dt(fills[idx]['fill_at'])<t:
            f=fills[idx];assert f['contract']=='JM2601'
            assert f['quantity']==len(f['layer_ids'])
            if f['action'] in ('OPEN','ADD'):
                if not layers:position_id=f['decision_id']
                for key in f['layer_ids']:
                    assert key not in layers
                    layers[key]=dict(id=key,side=f['side'],price=f['price'],quantity=1)
            else:
                assert f['action'] in ('CLOSE','REDUCE')
                for key in f['layer_ids']:del layers[key]
                if not layers:position_id=None
            idx+=1
        return list(layers.values()),position_id
    def regime_at(t,strict=False):
        i=(bisect_left(envtimes,t) if strict else bisect_right(envtimes,t))-1
        if i<0:return 'UNKNOWN'
        return env[i]['range_factor']['regime']
    events=[];opening_checks=0
    for b in market['bars']:
        at=dt(b['bar_end']);start=at-timedelta(minutes=1);day=b['trading_day'];cal=market['schedule'][day]
        if start==dt(cal['first_open']) and events:
            ls,pid=position_before(start)
            events.append(dict(event_id='open:'+start.isoformat(),contract='JM2601',kind='NEXT_OPEN',trading_day=day,previous_trading_day=cal['previous'],observed_at=at.isoformat(),price_at=start.isoformat(),layers=ls,position_id=pid,regime=regime_at(start,True),mark=b['open'],multiplier=multiplier))
            opening_checks+=1
        ls,pid=position_before(at)
        events.append(dict(event_id='bar:'+at.isoformat(),contract='JM2601',kind='DAY_END' if at==dt(cal['day_end']) else 'BAR',trading_day=day,previous_trading_day=cal['previous'],observed_at=at.isoformat(),price_at=at.isoformat(),layers=ls,position_id=pid,regime=regime_at(at),mark=b['close'],multiplier=multiplier,session_day_end=cal['day_end'],next_open=cal['next_open']))
    # Checkpoints span an actual day-end and the next opening, including the
    # weekend trading-day relationship. Replayed demands cannot change fills.
    observer=Observer('JM2601');outputs=[];restored=None;restart_index=next(i+1 for i,e in enumerate(events) if e['kind']=='DAY_END')
    for i,e in enumerate(events):
        outputs.append(observer.apply(e))
        if i+1==restart_index:restored=Observer.restore(observer.checkpoint())
        elif i+1>restart_index:assert restored.apply(e)==outputs[-1]
    assert restored.checkpoint()==observer.checkpoint()
    # Exact redelivery must return a duplicate, never change live checkpoint.
    before=observer.checkpoint()
    for e in events[::100]:assert observer.apply(e)['duplicate']
    assert observer.checkpoint()==before
    interesting=[dict(result=p,regime=e['regime'],quantity=sum(x['quantity'] for x in e['layers'])) for e,p in zip(events,outputs) if e['kind'] in ('DAY_END','NEXT_OPEN')]
    summary=dict(kind='TIMING_OBSERVER_ON_FIXED_BASELINE_POSITIONS',environment_source='archived v2, not a promoted recent-structure classifier',
                 bars=len(market['bars']),events=len(events),opening_checks=opening_checks,day_ends=sum(e['kind']=='DAY_END' for e in events),
                 counts=dict(Counter(p['demand'] for p in outputs)),restart_parity=True,duplicate_parity=True,
                 sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (market_path,baseline_path,envpath,factpath)},
                 limitation='Opening marks are observed at completed 1m end; no same-open fill. Baseline fills unchanged, no new candidate account return. Existing technical-exit obligations are not imported here; only timing contribution is observed.',checks=interesting)
    (out/'observer-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
    (out/'observer-results.json').write_text(json.dumps(outputs,ensure_ascii=False,indent=2)+'\n')
    (out/'observer-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='sources'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()

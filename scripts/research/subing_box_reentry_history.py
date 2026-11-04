"""Fixed spike replay on archived physical prefixes, evaluated only on previously seen account spans."""
from collections import Counter
from datetime import datetime
from decimal import Decimal as D
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from guiyi_quant.indicators import subing_range, subing_trend
from subing_box_reentry import State, step, VERSION

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ('JM2501','JM2505','JM2509','JM2601','JM2605','JM2609','JM2701')


def main(replace_on_new_seed=False):
    source = ROOT/'output/regime-learning-20261102-final/jm-30m.jsonl.gz'
    data = {c: [] for c in CONTRACTS}
    # Labels and test partitions are deliberately not used as evaluation targets.
    with gzip.open(source,'rt') as f:
        for line in f:
            r=json.loads(line)
            if r['contract'] in data:
                data[r['contract']].append({k:r[k] for k in ('contract','time','high','low','close','baseline','trend_direction')})
    cards=json.loads((ROOT/'output/subing-demand-review-20261103-final/cards.json').read_text())['cards']
    cases={(c['contract'],c['at']):c['id'] for c in cards if c.get('at')}
    summaries=[]; traces=[]; case_results=[]; hashes={str(source.relative_to(ROOT)):hashlib.sha256(source.read_bytes()).hexdigest()}
    for contract, rows in data.items():
        archive=ROOT/f'output/subing-regime-add-20261103-001/{contract}-environment.json'
        hashes[str(archive.relative_to(ROOT))]=hashlib.sha256(archive.read_bytes()).hexdigest()
        env={datetime.fromisoformat(r['time']):r['range_factor'] for r in json.loads(archive.read_text()) if r['frequency']=='30m'}
        cutoff=max(env)
        rows=[r for r in rows if datetime.fromisoformat(r['time'])<=cutoff]
        assert len({r['time'] for r in rows})==len(rows)
        assert set(env).issubset({datetime.fromisoformat(r['time']) for r in rows})
        trend=subing_trend.initial_state(contract,'30m'); box=subing_range.initial_state(contract,'30m'); s=State()
        counts=Counter(); max_age=0; first_width=None; seed_index=None; max_width_multiple=D(0); reentries=0; overlaps=0; trend_bars=0
        for i,r in enumerate(rows):
            at=datetime.fromisoformat(r['time']); common=dict(contract=contract,frequency='30m',bar_end=at)
            trend,tp=subing_trend.step(trend,**common,high=r['high'],low=r['low'],close=r['close'])
            prices={k:D(str(r[k])) for k in ('high','low','close')}
            box,rp=subing_range.step(box,**common,**prices,atr=D(str(tp.atr14)) if tp.atr14 else None,trend_direction=tp.direction)
            assert (rp.regime,tp.direction)==(r['baseline'],r['trend_direction']), (contract,r['time'],'BASELINE_PARITY_FAILED')
            seed=(rp.box.lower,rp.box.upper) if rp.box and rp.phase in ('RANGE_ACTIVE','RANGE_EXPANDING') else None
            if replace_on_new_seed and seed is not None and rp.box.confirmed_at == at:
                s=State(last_at=s.last_at,contract=s.contract)
            s,phase=step(s,at=at,contract=contract,**prices,seed=seed,valid=rp.regime!='UNKNOWN')
            if phase=='RANGE_SEEDED':seed_index=i;first_width=s.upper-s.lower
            if s.lower is None:seed_index=None;first_width=None
            if at not in env:continue
            assert env[at]['regime']==rp.regime,(contract,r['time'],'ARCHIVE_REGIME_MISMATCH')
            counts[phase]+=1
            age=i-seed_index if seed_index is not None else None
            multiple=(s.upper-s.lower)/first_width if first_width else None
            if age is not None:max_age=max(max_age,age)
            if multiple is not None:max_width_multiple=max(max_width_multiple,multiple)
            reentries+=phase=='REENTERED_RANGE'
            base_trend=rp.regime in ('TREND_UP','TREND_DOWN')
            trend_bars+=base_trend
            # This is disagreement, NOT an error rate or known truth.
            inside=s.lower is not None and s.lower<=prices['close']<=s.upper
            overlaps+=bool(base_trend and inside)
            point=dict(contract=contract,time=r['time'],baseline=rp.regime,phase=phase,lower=s.lower,upper=s.upper,age_bars=age,width_multiple=multiple,close=prices['close'])
            traces.append(point)
            if (contract,r['time']) in cases:case_results.append(dict(case=cases[(contract,r['time'])],**point))
        summaries.append(dict(contract=contract,prefix_bars=len(rows),evaluated_bars=sum(counts.values()),phase_counts=dict(counts),max_box_age_bars=max_age,max_width_multiple=max_width_multiple,reentries=reentries,v2_trend_bars=trend_bars,v2_trend_inside_candidate_box=overlaps))
    output=ROOT/('output/subing-box-reentry-new-seed-20261104' if replace_on_new_seed else 'output/subing-box-reentry-history-20261104');output.mkdir(exist_ok=True)
    result=dict(version=VERSION+ ('_new_seed_v1' if replace_on_new_seed else ''),sources=hashes,scope='Frozen archived physical prefixes; evaluation limited to seven previously seen account spans; no label/test scoring, no execution',summaries=summaries,cases=case_results)
    (output/'result.json').write_text(json.dumps(result,default=str,ensure_ascii=False,indent=2)+'\n')
    (output/'trace.jsonl').write_text(''.join(json.dumps(x,default=str)+'\n' for x in traces))
    print(json.dumps(result,default=str,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--replace-on-new-seed',action='store_true')
    main(parser.parse_args().replace_on_new_seed)

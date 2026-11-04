"""Replay a fixed research structure rule; never uses future labels or price selection."""
from pathlib import Path
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal as D
import gzip,hashlib,json
from subing_recent_structure import Bar, State, step, VERSION
ROOT=Path(__file__).resolve().parents[2]
CONTRACTS=('JM2501','JM2505','JM2509','JM2601','JM2605','JM2609','JM2701')

def main():
    src=ROOT/'output/regime-learning-20261102-final/jm-30m.jsonl.gz'
    envdir=ROOT/'output/subing-regime-add-20261103-001'
    env={c:{r['time'] for r in json.loads((envdir/f'{c}-environment.json').read_text()) if r['frequency']=='30m'} for c in CONTRACTS}
    cutoffs={c:max(v) for c,v in env.items()}
    rows={c:[] for c in CONTRACTS}
    with gzip.open(src,'rt') as f:
        for line in f:
            r=json.loads(line)
            if r['contract'] in rows and r['time']<=cutoffs[r['contract']]:
                rows[r['contract']].append({k:r[k] for k in ('contract','time','open','high','low','close','baseline')})
    cards=[c for c in json.loads((ROOT/'output/subing-demand-review-20261103-final/cards.json').read_text())['cards'] if c.get('at')]
    cards += [dict(id=c['id'],contract=c['selection']['contract'],at=c['selection']['time']) for c in json.loads((ROOT/'output/subing-box-lifecycle-cases-20261104/cases.json').read_text())]
    cases={(c['contract'],c['at']):c['id'] for c in cards}
    traces=[];summaries=[];examples=[]
    for contract,bs in rows.items():
        assert len({b['time'] for b in bs})==len(bs)
        assert env[contract].issubset({b['time'] for b in bs})
        s=State(contract);counts=Counter();max_age=0;prev=[]
        for b in bs:
            at=datetime.fromisoformat(b['time']);s,p=step(s,Bar(at,*(D(str(b[k])) for k in ('high','low','close'))),contract=contract)
            prev.append(b)
            if b['time'] in env[contract]:
                counts[p['phase']]+=1
                # Bar-count age, not elapsed wall-clock hours through session gaps.
                age=sum(datetime.fromisoformat(x['time'])>s.boundary_at for x in prev) if s.boundary_at else None
                max_age=max(max_age,age or 0)
                traces.append(dict(contract=contract,time=b['time'],close=b['close'],baseline=b['baseline'],age=age,**p))
            if (contract,b['time']) in cases:
                examples.append(dict(id=cases[(contract,b['time'])],contract=contract,at=b['time'],point=p,pivots=[asdict(x) for x in s.pivots],bars=prev[-128:]))
        summaries.append(dict(contract=contract,prefix_bars=len(bs),evaluated_bars=sum(counts.values()),counts=dict(counts),max_boundary_age_bars=max_age))
    out=ROOT/'output/subing-recent-structure-20261104';out.mkdir(exist_ok=True)
    record=dict(version=VERSION,source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),scope='Archived prefix only, seen spans; not MDS coverage verification, labels or execution',summaries=summaries,cases=examples)
    (out/'result.json').write_text(json.dumps(record,default=str,ensure_ascii=False,indent=2)+'\n')
    (out/'trace.jsonl').write_text(''.join(json.dumps(t,default=str)+'\n' for t in traces))
    print(json.dumps(dict(summaries=summaries,cases=[dict(id=c['id'],point=c['point']) for c in examples]),default=str,indent=2))

if __name__=='__main__':main()

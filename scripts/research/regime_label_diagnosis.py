"""Evaluate one frozen structural-label hypothesis on the 90 development cards.

Never a parameter search, holdout evaluation, training or active promotion.
"""
import argparse
from collections import Counter,defaultdict
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import gzip
import json
from pathlib import Path

from app.market_data.new_subing_research import payload_hash
from guiyi_quant.indicators.atr import initial_atr_state, step_atr
from scripts.research import regime_structural_labels as candidate
from scripts.research.regime_review import validate_review


def tally(rows,field):
    counts=Counter(agreement=0,conflict=0,abstained=0,owner_uncertain=0)
    for row in rows:
        label=row[field]
        if row['owner_answer']=='UNCERTAIN':
            counts['owner_uncertain']+=1
        elif label==row['owner_answer']:
            counts['agreement']+=1
        elif label in ('DISPUTED','UNKNOWN'):
            counts['abstained']+=1
        else:
            counts['conflict']+=1
    return dict(counts)


def run(dataset,answers,output):
    snapshot=json.loads((dataset/'snapshot.json').read_text())
    identity=payload_hash(snapshot)
    run_info=json.loads((dataset/'run.json').read_text())
    if identity!=run_info['dataset_id'] or run_info['status']!='WAIT_LABEL_REVIEW':
        raise ValueError('DIAGNOSIS_DATASET_INVALID')
    key=json.loads((dataset/'review-key.json').read_text())
    if key['dataset_id']!=identity:
        raise ValueError('DIAGNOSIS_KEY_INVALID')
    review=validate_review(key,json.loads(answers.read_text()),snapshot['label_version'])
    if review['reviewed']!=90 or review['remaining']!=0:
        raise ValueError('DIAGNOSIS_REVIEW_INCOMPLETE')
    text=(dataset/'index.html').read_text()
    public=json.loads(text.split('const DATA=',1)[1].split(';\nconst $=',1)[0])
    if public['dataset_id']!=identity:
        raise ValueError('DIAGNOSIS_PAGE_INVALID')
    samples={s['id']:s for s in public['samples']}
    if set(samples)!={r['id'] for r in review['rows']}:
        raise ValueError('DIAGNOSIS_SAMPLES_INVALID')
    groups=defaultdict(list)
    for r in review['rows']:
        sample=samples[r['id']]
        if any(b['day']>=snapshot['splits']['test_from'] for b in sample['bars']):
            raise ValueError('DIAGNOSIS_HOLDOUT_FORBIDDEN')
        groups[(r['symbol'],r['frequency'])].append(r)
    artifacts={r['file']:r['sha256'] for r in snapshot['rows']}
    code_hash=sha256(Path(candidate.__file__).read_bytes()).hexdigest()
    results=[]
    for (symbol,frequency),rows in groups.items():
        filename=f'{symbol}-{frequency}.jsonl.gz'
        source=dataset/filename
        if source.resolve().parent!=dataset.resolve() or sha256(source.read_bytes()).hexdigest()!=artifacts[filename]:
            raise ValueError('DIAGNOSIS_ROWS_CHANGED')
        needed={(samples[r['id']]['contract'],samples[r['id']]['bars'][-1]['time']):r for r in rows}
        cutoffs={contract:max(time for c,time in needed if c==contract) for contract,_ in needed}
        found={}
        state=None
        segment=None
        with gzip.open(source,'rt') as stream:
            for line in stream:
                bar=json.loads(line)
                contract=bar['contract']
                if contract not in cutoffs or bar['time']>cutoffs[contract]:
                    continue
                if bar['day']>=snapshot['splits']['test_from']:
                    raise ValueError('DIAGNOSIS_HOLDOUT_FORBIDDEN')
                if segment!=bar['segment']:
                    state=candidate.initial_state(contract,frequency)
                    segment=bar['segment']
                    atr_state=initial_atr_state(14,smoothing_policy='wilder_sma_seed')
                atr_state,atr_point=step_atr(atr_state,high=bar['high'],low=bar['low'],close=bar['close'],bar_end=bar['time'])
                atr=atr_point.value if atr_point.ready else None
                state,point=candidate.step(state,contract=contract,frequency=frequency,
                    time=datetime.fromisoformat(bar['time']),high=bar['high'],low=bar['low'],close=bar['close'],atr=atr)
                query=(contract,bar['time'])
                if query in needed and bar['owned']:
                    row=needed[query]
                    final_bar=samples[row['id']]['bars'][-1]
                    if any(bar[k]!=final_bar[k] for k in ('time','day','open','high','low','close')):
                        raise ValueError('DIAGNOSIS_BAR_MISMATCH')
                    found[query]={**row,'contract':contract,'time':bar['time'],'candidate':point.regime,
                        'candidate_point':asdict(point),'display_factor_v2':bar['baseline']}
                    if set(found)==set(needed):
                        break
        if set(found)!=set(needed):
            raise ValueError('DIAGNOSIS_ENDPOINT_MISSING')
        results.extend(found.values())
    if code_hash!=sha256(Path(candidate.__file__).read_bytes()).hexdigest():
        raise ValueError('DIAGNOSIS_CODE_CHANGED')
    baseline=tally(results,'reference')
    trial=tally(results,'candidate')
    passes=(trial['agreement']>=baseline['agreement'] and trial['conflict']<=baseline['conflict']
            and trial['abstained']<=baseline['abstained'])
    report=dict(dataset_id=identity,owner_answers_sha256=sha256(answers.read_bytes()).hexdigest(),
        role='DEVELOPMENT_DIAGNOSIS_NOT_OOS',candidate_version=candidate.VERSION,candidate_code_sha256=code_hash,
        reference=baseline,candidate=trial,display_factor_v2=tally(results,'display_factor_v2'),
        decision='NEEDS_INDEPENDENT_VALIDATION' if passes else 'REJECTED_FOR_BULK_LABELING',
        acceptance='All three development counts must be non-worse; passing is not independent validation.',
        by_frequency={f:{'reference':tally([r for r in results if r['frequency']==f],'reference'),
                         'candidate':tally([r for r in results if r['frequency']==f],'candidate')} for f in ('1d','30m','60m')},
        rows=sorted(results,key=lambda r:r['id']),training_started=False,runtime_changed=False)
    with output.open('x') as handle:
        json.dump(report,handle,ensure_ascii=False,default=lambda v:v.isoformat(),indent=2)
    print(json.dumps({k:report[k] for k in ('reference','candidate','decision')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--answers',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        run(args.dataset,args.answers,args.output)
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error_type':type(exc).__name__}))
        raise SystemExit(2) from None

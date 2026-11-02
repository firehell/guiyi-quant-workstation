"""One predeclared development-only label trial against both manual rounds."""
import argparse
from collections import defaultdict
from datetime import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path

from app.market_data.new_subing_research import payload_hash
from guiyi_quant.indicators import atr as atr_kernel
from guiyi_quant.indicators.atr import initial_atr_state, step_atr
from scripts.research import regime_learning_core
from scripts.research import regime_path_candidate as candidate
from scripts.research.regime_calibration import content_hash
from scripts.research.regime_label_diagnosis import tally
from scripts.research.regime_review import validate_review


def run(root, output):
    dataset = root/'regime-learning-20261102-final'
    snapshot = json.loads((dataset/'snapshot.json').read_text())
    source_run = json.loads((dataset/'run.json').read_text())
    if payload_hash(snapshot) != source_run['dataset_id'] or source_run['status'] != 'WAIT_LABEL_REVIEW':
        raise ValueError('SOURCE_IDENTITY_CHANGED')
    dependencies = [Path(__file__), Path(candidate.__file__), Path(atr_kernel.__file__), Path(regime_learning_core.__file__)]
    dependency_hashes = {str(p):sha256(p.read_bytes()).hexdigest() for p in dependencies}
    answer_paths = [root/'regime-owner-review-20261102-81d9376e/owner-answers.json', root/'regime-owner-calibration-20261102-2f72105c/owner-answers.json']
    answer_hashes = {str(p):sha256(p.read_bytes()).hexdigest() for p in answer_paths}
    output.mkdir(parents=True, exist_ok=False)
    code = sha256(Path(candidate.__file__).read_bytes()).hexdigest()
    protocol = dict(version=candidate.VERSION, policy=candidate.POLICY, code_hash=code,
        role='DEVELOPMENT_NOT_OOS', trials=1, source_dataset_id=source_run['dataset_id'],
        dependency_hashes=dependency_hashes, answer_hashes=answer_hashes,
        acceptance='Combined and each round: conflicts no greater, agreements no fewer, abstentions no greater than original reference. Passing only permits further validation.',
        training=False, sealed_evaluation=False)
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2))
    groups = defaultdict(list)
    round_inputs = [('original90', dataset, root/'regime-owner-review-20261102-81d9376e/owner-answers.json'),
                    ('new24', root/'regime-calibration-20261102-final', root/'regime-owner-calibration-20261102-2f72105c/owner-answers.json')]
    for name, folder, answers in round_inputs:
        run_info = json.loads((folder/'run.json').read_text())
        key = json.loads((folder/'review-key.json').read_text())
        public = json.loads((folder/'index.html').read_text().split('const DATA=',1)[1].split(';\nconst $=',1)[0])
        if run_info['dataset_id'] != key['dataset_id'] or key['dataset_id'] != public['dataset_id']:
            raise ValueError('ROUND_IDENTITY_CHANGED')
        if name == 'new24':
            spec = json.loads((folder/'calibration.json').read_text())
            if payload_hash(spec) != key['dataset_id'] or content_hash(public['samples']) != spec['public_content_hash']:
                raise ValueError('CALIBRATION_CONTENT_CHANGED')
        review = validate_review(key, json.loads(answers.read_text()), run_info['label_version'])
        if review['remaining'] or review['reviewed'] != (90 if name == 'original90' else 24):
            raise ValueError('REVIEW_INCOMPLETE')
        cards = {s['id']:s for s in public['samples']}
        for row in review['rows']:
            s = cards[row['id']]
            if any(b['day'] >= snapshot['splits']['test_from'] for b in s['bars']):
                raise ValueError('SEALED_FORBIDDEN')
            groups[(row['symbol'], row['frequency'])].append(dict(row, round=name, card=s))
    results, transitions = [], []
    artifacts = {(r['symbol'], r['frequency']):r for r in snapshot['rows']}
    for identity, targets in groups.items():
        source = dataset/artifacts[identity]['file']
        if source.resolve().parent != dataset.resolve() or sha256(source.read_bytes()).hexdigest() != artifacts[identity]['sha256']:
            raise ValueError('SOURCE_CHANGED')
        needed = {(r['card']['contract'],r['card']['bars'][-1]['time']):r for r in targets}
        cutoffs = {c:max(t for cc,t in needed if cc==c) for c,_ in needed}
        segment, found, recent, previous = None, set(), [], None
        with gzip.open(source, 'rt') as stream:
            for line in stream:
                b = json.loads(line)
                if b['contract'] not in cutoffs or b['time'] > cutoffs[b['contract']]:
                    continue
                if b['day'] >= snapshot['splits']['test_from']:
                    raise ValueError('SEALED_FORBIDDEN')
                if b['segment'] != segment:
                    segment, recent, previous = b['segment'], [], None
                    state = candidate.initial_state(b['contract'], b['frequency'])
                    atr_state = initial_atr_state(14, smoothing_policy='wilder_sma_seed')
                atr_state, ap = step_atr(atr_state, high=b['high'], low=b['low'], close=b['close'], bar_end=b['time'])
                state, point = candidate.step(state, contract=b['contract'], frequency=b['frequency'], time=datetime.fromisoformat(b['time']), close=b['close'], atr=ap.value if ap.ready else None)
                recent = (*recent, {k:b[k] for k in ('time','day','open','high','low','close')})[-64:]
                if b['owned'] and point['label'] != 'UNKNOWN':
                    transitions.append(dict(frequency=b['frequency'], candidate_change=previous is not None and previous[0]!=point['label'], reference_change=previous is not None and previous[1]!=point['reference']))
                    previous = (point['label'],point['reference'])
                query = (b['contract'],b['time'])
                if b['owned'] and query in needed:
                    row = needed[query]
                    if list(recent) != row['card']['bars'] or b['reference']['label'] != row['reference']:
                        raise ValueError('CARD_CONTENT_CHANGED')
                    results.append({k:v for k,v in row.items() if k!='card'} | dict(candidate=point['label'], facts=point, time=b['time'], contract=b['contract']))
                    found.add(query)
                    if found == set(needed):
                        break
        if found != set(needed):
            raise ValueError('ENDPOINT_MISSING')
    if any(sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in dependency_hashes.items()):
        raise ValueError('CODE_CHANGED')
    if any(sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in answer_hashes.items()):
        raise ValueError('ANSWERS_CHANGED')
    def comparison(rows):
        ref, trial = tally(rows,'reference'), tally(rows,'candidate')
        passed = trial['agreement']>=ref['agreement'] and trial['conflict']<=ref['conflict'] and trial['abstained']<=ref['abstained']
        return dict(reference=ref,candidate=trial,passes=passed)
    total = comparison(results)
    rounds = {n:comparison([r for r in results if r['round']==n]) for n,_,_ in round_inputs}
    report = dict(protocol=protocol, combined=total, rounds=rounds,
        by_frequency={f:comparison([r for r in results if r['frequency']==f]) for f in ('1d','30m','60m')},
        decision='NEEDS_FURTHER_VALIDATION' if total['passes'] and all(r['passes'] for r in rounds.values()) else 'REJECTED_FOR_BULK_LABELING',
        diagnostic_switches=dict(scope='owned development prefixes of sampled contracts only; includes DISPUTED; not whole-market rate',bars=len(transitions),candidate=sum(x['candidate_change'] for x in transitions),reference=sum(x['reference_change'] for x in transitions)),
        rows=results, training_started=False)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:report[k] for k in ('combined','rounds','decision','diagnostic_switches')}))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('output'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    run(args.root,args.output)

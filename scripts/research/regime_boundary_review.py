"""Four already-seen cases: elicit confirmation timing, never unseen accuracy."""
from collections import deque
import gzip
from hashlib import sha256
import json
from pathlib import Path

from app.market_data.new_subing_research import payload_hash
from guiyi_quant.indicators.ema import initial_ema_state, step_ema

VERSION = 'owner_range_boundary_v2'
IDS = ('005aa269549cd1b10a20','0005402032473ce7025d','0003e99d8385fab4cb20','004a13c4b435e9530971')


def validate(public, answer):
    if answer.get('dataset_id') != public['dataset_id'] or answer.get('label_version') != VERSION:
        raise ValueError('BOUNDARY_IDENTITY_INVALID')
    allowed = {s['id'] for s in public['samples']}
    answers = answer.get('answers')
    if not isinstance(answers, dict) or not set(answers) <= allowed:
        raise ValueError('BOUNDARY_ANSWERS_INVALID')
    complete = 0
    for events in answers.values():
        if not isinstance(events, list) or len(events) > 25:
            raise ValueError('BOUNDARY_EVENTS_INVALID')
        for i, event in enumerate(events):
            if not isinstance(event, dict) or event.get('cut') != 40+i or event.get('choice') not in ('not_yet','range','uncertain'):
                raise ValueError('BOUNDARY_EVENT_INVALID')
        complete += len(events) == 25
    return dict(reviewed=complete, remaining=len(allowed)-complete, training_permitted=False)


def build(root, output):
    source=root/'regime-learning-20261102-final'
    snapshot=json.loads((source/'snapshot.json').read_text())
    run=json.loads((source/'run.json').read_text())
    if payload_hash(snapshot)!=run['dataset_id']:
        raise ValueError('BOUNDARY_SOURCE_CHANGED')
    old=json.loads((source/'index.html').read_text().split('const DATA=',1)[1].split(';\nconst $=',1)[0])
    if old['dataset_id']!=run['dataset_id']:
        raise ValueError('BOUNDARY_PAGE_CHANGED')
    samples=[]
    for sid in IDS:
        s=next(s for s in old['samples'] if s['id']==sid)
        entry=next(e for e in snapshot['rows'] if (e['symbol'],e['frequency'])==(s['symbol'],s['frequency']))
        file=source/entry['file']
        if file.resolve().parent!=source.resolve() or sha256(file.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('BOUNDARY_FILE_CHANGED')
        segment=None
        found=False
        with gzip.open(file,'rt') as stream:
            for line in stream:
                b=json.loads(line)
                if b['contract']!=s['contract'] or b['time']>s['bars'][-1]['time']:
                    continue
                if b['day']>=snapshot['splits']['test_from']:
                    raise ValueError('BOUNDARY_SEALED_FORBIDDEN')
                if b['segment']!=segment:
                    segment=b['segment']
                    ema=initial_ema_state(21)
                    values=deque(maxlen=64)
                    bars=deque(maxlen=64)
                ema,p=step_ema(ema,b['close'],bar_end=b['time'])
                values.append(p.value if p.ready and p.valid else None)
                bars.append({k:b[k] for k in ('time','day','open','high','low','close')})
                if b['owned'] and b['time']==s['bars'][-1]['time']:
                    if list(bars)!=s['bars']:
                        raise ValueError('BOUNDARY_CARD_CHANGED')
                    samples.append(dict(s,ema21=list(values)))
                    found=True
                    break
        if not found:
            raise ValueError('BOUNDARY_CARD_MISSING')
    template=Path(__file__).with_suffix('.html').read_text()
    payload=dict(label_version=VERSION, source_dataset_id=run['dataset_id'], samples=samples,
                 role='SEEN_DEVELOPMENT_SEMANTICS_NOT_OOS',start=40,
                 template_hash=sha256(template.encode()).hexdigest())
    identity=payload_hash(payload)
    public=dict(payload,dataset_id=identity)
    output.mkdir(parents=True,exist_ok=False)
    (output/'index.html').write_text(template.replace('__DATA__',json.dumps(public,ensure_ascii=False).replace('<','\\u003c')))
    (output/'run.json').write_text(json.dumps(dict(status='WAIT_LABEL_REVIEW',dataset_id=identity,label_version=VERSION,training_permitted=False),indent=2))
    (output/'boundary.json').write_text(json.dumps(public,ensure_ascii=False,indent=2))
    print(json.dumps(dict(dataset_id=identity,samples=len(samples))))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('output'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    build(args.root,args.output)

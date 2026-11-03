"""Seen development-only lifecycle attribution; no training, test or promotion."""
import gzip
import json
from hashlib import sha256
from pathlib import Path
from collections import Counter
from guiyi_quant.indicators.ema import initial_ema_state, step_ema
from guiyi_quant.indicators.subing_range import direction_transition
from app.market_data.new_subing_research import payload_hash
from scripts.research.regime_trend_review import validate


def run(root,output):
    source=root/'regime-learning-20261102-final'
    snapshot=json.loads((source/'snapshot.json').read_text())
    if payload_hash(snapshot)!=json.loads((source/'run.json').read_text())['dataset_id']:raise ValueError('SOURCE_CHANGED')
    rounds=[('seen4','regime-trend-lifecycle-20261102','regime-trend-owner-20261103-eb733ddf'),('fresh6','regime-trend-fresh-20261103','regime-trend-fresh-owner-20261103-69a56196')]
    queries={};cardmeta={};answer_hashes={}
    for roundname,folder,archive in rounds:
        public=json.loads((root/folder/'boundary.json').read_text()); raw=(root/archive/'owner-answers.json').read_bytes();answer=json.loads(raw);validate(public,answer);answer_hashes[roundname]=sha256(raw).hexdigest()
        for sample in public['samples']:
            cid=roundname+':'+sample['id'];cardmeta[cid]=dict(round=roundname,symbol=sample['symbol'],frequency=sample['frequency'])
            for event in answer['answers'][sample['id']]:
                bar=sample['bars'][event['cut']-1];key=(sample['symbol'],sample['frequency'],sample['contract'],bar['time'])
                if key in queries:raise ValueError('DUPLICATE_EVENT')
                choice=event['choice'];owner='TREND_UP' if choice.startswith('up_') else 'TREND_DOWN' if choice.startswith('down_') else 'RANGE' if choice=='ended' else 'UNKNOWN'
                queries[key]=dict(card=cid,cut=event['cut'],choice=choice,owner=owner,expected_bar=bar)
    timing=[(d,n) for d in (1,2,3) for n in (2,3,4)]
    events=[]
    for entry in snapshot['rows']:
        if not any(k[:2]==(entry['symbol'],entry['frequency']) for k in queries):continue
        path=source/entry['file']
        if path.resolve().parent!=source.resolve() or sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('INPUT_CHANGED')
        segment=None
        with gzip.open(path,'rt') as stream:
            for line in stream:
                b=json.loads(line)
                if b['day']>=snapshot['splits']['test_from']:continue
                if b['segment']!=segment:
                    segment=b['segment'];states=[(None,0,None,0) for _ in timing];emas={n:initial_ema_state(n) for n in (10,21,60)};prev60=None;carry={n:('RANGE',0) for n in (1,2,3)}
                vals={}
                for n in emas:
                    emas[n],point=step_ema(emas[n],b['close'],bar_end=b['time']);vals[n]=point.value if point.ready and point.valid else None
                ready=b['baseline']!='UNKNOWN'
                states=[direction_transition(*st,b['trend_direction'],direction_bars=d,neutral_bars=n) for st,(d,n) in zip(states,timing)] if ready else [(None,0,None,0) for _ in timing]
                preds={f'timing_{d}_{n}':('TREND_'+st[2] if st[2] else 'RANGE') if ready else 'UNKNOWN' for st,(d,n) in zip(states,timing)}
                if preds['timing_2_3']!=b['baseline']:raise ValueError('V2_PARITY')
                for confirmation in carry:
                    side,fail=carry[confirmation];base=b['baseline']
                    if not ready or any(v is None for v in vals.values()) or prev60 is None:side,fail=base,0
                    else:
                        sign=1 if side=='TREND_UP' else -1 if side=='TREND_DOWN' else 0
                        support=sign and sign*(vals[21]-vals[60])>0 and sign*(vals[60]-prev60)>0
                        broken=sign and sign*(b['close']-vals[21])<0 and sign*(vals[10]-vals[21])<0
                        fail=fail+1 if broken else 0
                        if not support or fail>=confirmation:side,fail=base,0
                    carry[confirmation]=(side,fail);preds[f'slow_carry_{confirmation}']=side
                prev60=vals[60]
                key=(b['symbol'],b['frequency'],b['contract'],b['time'])
                if b['owned'] and key in queries:
                    q=queries[key]
                    if {k:b[k] for k in q['expected_bar']}!=q['expected_bar']:raise ValueError('BAR_MISMATCH')
                    events.append(dict(**{k:v for k,v in q.items() if k!='expected_bar'},time=b['time'],close=b['close'],emas=vals,trend_direction=b['trend_direction'],v2=b['baseline'],predictions=preds))
    if len(events)!=len(queries):raise ValueError('COVERAGE_MISSING')
    cards=[]
    for cid,meta in cardmeta.items():
        es=sorted([e for e in events if e['card']==cid],key=lambda e:e['cut']);scores={}
        for name in es[0]['predictions']:
            scores[name]=dict(agreement=sum(e['predictions'][name]==e['owner'] for e in es),false_keep=sum(e['owner']=='RANGE' and e['predictions'][name] in ('TREND_UP','TREND_DOWN') for e in es),missed_trend=sum(e['owner'] in ('TREND_UP','TREND_DOWN') and e['predictions'][name]!=e['owner'] for e in es),switches=sum(a['predictions'][name]!=b['predictions'][name] for a,b in zip(es,es[1:])))
        cards.append(dict(card=cid,**meta,scores=scores,confusion=dict(Counter(e['owner']+' -> '+e['v2'] for e in es))))
    aggregate={n:{metric:sum(c['scores'][n][metric] for c in cards) for metric in ('agreement','false_keep','missed_trend','switches')} for n in events[0]['predictions']}
    output.mkdir(exist_ok=False,parents=True)
    result=dict(role='SEEN_DEVELOPMENT_DIAGNOSIS_NOT_OOS',source=payload_hash(snapshot),answer_hashes=answer_hashes,sealed_test_evaluated=False,training_permitted=False,cards=cards,aggregate=aggregate,events=events,limitations=['250 correlated events from 10 paths; all used for development','Timing and carry rules are diagnostic hypotheses, not promoted formulas','No execution or profit evaluated','No health classifier trained'])
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(aggregate,indent=2))
    print('M60',json.dumps([c for c in cards if c['symbol']=='m'],ensure_ascii=False))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('output'));p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.root,a.output)

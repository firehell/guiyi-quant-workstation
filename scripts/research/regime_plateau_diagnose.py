"""Three fixed causal plateau probes on seen cards, not trained/promoted models."""
import json
from pathlib import Path
from collections import Counter
from scripts.research.regime_trend_review import validate


def run(root):
    rounds=[('regime-trend-lifecycle-20261102','regime-trend-owner-20261103-eb733ddf'),('regime-trend-fresh-20261103','regime-trend-fresh-owner-20261103-69a56196')]
    rows=[]
    for folder,archive in rounds:
        public=json.loads((root/folder/'boundary.json').read_text());a=json.loads((root/archive/'owner-answers.json').read_text());validate(public,a)
        for s in public['samples']:
            for e in a['answers'][s['id']]:
                end=e['cut']-1;b=s['bars'][:end+1];emas=s['emas'];sign=1 if emas['21'][end]>emas['60'][end] and emas['60'][end]>emas['60'][end-3] else -1 if emas['21'][end]<emas['60'][end] and emas['60'][end]<emas['60'][end-3] else 0
                atr=sum(max(b[i]['high']-b[i]['low'],abs(b[i]['high']-b[i-1]['close']),abs(b[i]['low']-b[i-1]['close'])) for i in range(len(b)-14,len(b)))/14
                owner='UP' if e['choice'].startswith('up_') else 'DOWN' if e['choice'].startswith('down_') else 'RANGE'
                predictions={};features={}
                for n in (6,10,14):
                    progress=sign*(b[-1]['close']-b[-1-n]['close'])/atr if atr>0 else None
                    # Close displacement proxy intentionally tests limitation: may confuse pullback and plateau.
                    prediction=('UP' if sign>0 else 'DOWN') if sign and progress is not None and progress>.5 else 'RANGE'
                    predictions[str(n)]=prediction;features[str(n)]=progress
                rows.append(dict(symbol=s['symbol'],frequency=s['frequency'],cut=e['cut'],owner=owner,choice=e['choice'],predictions=predictions,progress_atr=features))
    scores={}
    for n in ('6','10','14'):
        scores[n]=dict(agreement=sum(r['owner']==r['predictions'][n] for r in rows),false_keep=sum(r['owner']=='RANGE' and r['predictions'][n]!='RANGE' for r in rows),missed_trend=sum(r['owner']!='RANGE' and r['predictions'][n]!=r['owner'] for r in rows),m60_agreement=sum(r['symbol']=='m' and r['owner']==r['predictions'][n] for r in rows))
    result=dict(role='SEEN_CARD_DIAGNOSTIC_NOT_OOS',scores=scores,rows=rows,training_permitted=False,thresholds='fixed n=6/10/14, close progress >0.5 mean true range14; research proxy, not established owner rules',limitations=['No smoothing or health model','Net displacement is not a full consolidation definition','No trading evaluation; no promotion'])
    path=root/'regime-lifecycle-diagnosis-20261103/plateau-probes.json'
    if path.exists():raise ValueError('OUTPUT_EXISTS')
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(scores,indent=2))

if __name__=='__main__':run(Path('output'))
